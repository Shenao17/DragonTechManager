"""Persistencia de compensaciones, eventos de entrega y ledger de saldo a favor."""

import sqlite3

from ._rows import row_dict, rows_dict


class CompensationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def position(self, sale_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM v_ventas_posicion WHERE venta_id = ?", (sale_id,)).fetchone())

    def by_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM compensaciones_cancelacion WHERE clave_idempotencia = ?", (key,)).fetchone())

    def get(self, compensation_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            """SELECT c.*, e.estado, e.en_investigacion, e.liberada, m.familia AS metodo_familia, m.nombre AS metodo_nombre
               FROM compensaciones_cancelacion c
               JOIN v_compensaciones_estado e ON e.compensacion_id = c.id
               LEFT JOIN metodos_pago m ON m.id = c.metodo_pago_id WHERE c.id = ?""",
            (compensation_id,)).fetchone())

    def create(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO compensaciones_cancelacion
               (venta_id, cancelacion_id, tipo, importe_cop, metodo_pago_id, motivo,
                responsable_ejecucion, autorizador, autorizado_en_utc, referencia_autorizacion,
                consentimiento_cliente, fecha_negocio, registrado_en_utc, clave_idempotencia,
                huella_solicitud, ejecutor_id, autorizador_id, origen_identidad)
               VALUES (:venta_id, :cancelacion_id, :tipo, :importe_cop, :metodo_pago_id, :motivo,
                       :responsable_ejecucion, :autorizador, :autorizado_en_utc,
                       :referencia_autorizacion, :consentimiento_cliente, :fecha_negocio,
                       :registrado_en_utc, :clave_idempotencia, :huella_solicitud, :ejecutor_id,
                       :autorizador_id, :origen_identidad) RETURNING *""",
            values).fetchone())

    def list_for_sale(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT c.*, e.estado, e.en_investigacion, e.liberada, m.nombre AS metodo_nombre, m.familia AS metodo_familia,
                      (SELECT x.voucher_codigo FROM eventos_compensacion x
                       WHERE x.compensacion_id = c.id AND x.tipo = 'preparada') AS voucher_codigo
               FROM compensaciones_cancelacion c
               JOIN v_compensaciones_estado e ON e.compensacion_id = c.id
               LEFT JOIN metodos_pago m ON m.id = c.metodo_pago_id
               WHERE c.venta_id = ? ORDER BY c.id""", (sale_id,)).fetchall())

    def pending(self) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM v_compensaciones_pendientes ORDER BY comprometida_en_utc, compensacion_id").fetchall())

    def event_by_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM eventos_compensacion WHERE clave_idempotencia = ?", (key,)).fetchone())

    def events(self, compensation_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM eventos_compensacion WHERE compensacion_id = ? ORDER BY id",
            (compensation_id,)).fetchall())

    def event_of_type(self, compensation_id: int, kind: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM eventos_compensacion WHERE compensacion_id = ? AND tipo = ?",
            (compensation_id, kind)).fetchone())

    def add_event(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO eventos_compensacion
               (compensacion_id, tipo, ocurrido_en_utc, registrado_en_utc, registrado_por,
                autorizador, referencia_autorizacion, voucher_codigo, medio, referencia_externa,
                importe_cop, motivo, clave_idempotencia, huella_solicitud,
                registrado_por_id, autorizador_id, origen_identidad, correccion_tipo,
                ocurrido_corregido_en_utc, receptor, evidencia)
               VALUES (:compensacion_id, :tipo, :ocurrido_en_utc, :registrado_en_utc,
                       :registrado_por, :autorizador, :referencia_autorizacion, :voucher_codigo,
                       :medio, :referencia_externa, :importe_cop, :motivo, :clave_idempotencia,
                       :huella_solicitud, :registrado_por_id, :autorizador_id, :origen_identidad,
                       :correccion_tipo, :ocurrido_corregido_en_utc, :receptor, :evidencia)
               RETURNING *""", {"registrado_por_id": None, "autorizador_id": None, "origen_identidad": None,
                                "correccion_tipo": None, "ocurrido_corregido_en_utc": None, "receptor": None,
                                "evidencia": "", **values}).fetchone())

    # --- saldo a favor ---
    def balance(self, customer_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM v_saldos_favor WHERE cliente_id = ?", (customer_id,)).fetchone())

    def ledger_by_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM movimientos_saldo_favor WHERE clave_idempotencia = ?", (key,)).fetchone())

    def ledger(self, customer_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM movimientos_saldo_favor WHERE cliente_id = ? ORDER BY id",
            (customer_id,)).fetchall())

    def apply_to_sale(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO movimientos_saldo_favor
               (cliente_id, tipo, importe_cop, origen_tipo, origen_id, venta_id, fecha_negocio,
                registrado_en_utc, motivo, registrado_por, clave_idempotencia, huella_solicitud,
                registrado_por_id, origen_identidad)
               VALUES (:cliente_id, 'utilizacion', :importe_cop, 'venta', :venta_id, :venta_id,
                       :fecha_negocio, :registrado_en_utc, :motivo, :registrado_por,
                       :clave_idempotencia, :huella_solicitud, :registrado_por_id,
                       :origen_identidad) RETURNING *""", values).fetchone())
