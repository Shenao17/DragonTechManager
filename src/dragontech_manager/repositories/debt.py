"""Persistencia de extinciones de deuda, anulaciones y recuperaciones."""

import sqlite3

from ._rows import row_dict, rows_dict


class DebtRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def position(self, sale_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM v_ventas_posicion WHERE venta_id = ?", (sale_id,)).fetchone())

    def liquidation(self, sale_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM v_saldos_ventas WHERE venta_id = ?", (sale_id,)).fetchone())

    def extinction_by_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM extinciones_deuda_venta WHERE clave_idempotencia = ?", (key,)).fetchone())

    def extinction(self, extinction_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            """SELECT x.*, x.importe_cop - COALESCE((SELECT SUM(a.importe_anulado_cop)
                   FROM anulaciones_extincion_deuda a WHERE a.extincion_id = x.id), 0) AS importe_vigente_cop
               FROM extinciones_deuda_venta x WHERE x.id = ?""", (extinction_id,)).fetchone())

    def add_extinction(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO extinciones_deuda_venta
               (venta_id, cancelacion_id, tipo, importe_cop, motivo, evidencia_cobro, referencia_autorizacion,
                medio_autorizacion, autorizador_id, autorizador_nombre, autorizado_en_utc, ejecutor_id,
                ejecutor_nombre, fecha_negocio, registrado_en_utc, clave_idempotencia, huella_solicitud)
               VALUES (:venta_id, :cancelacion_id, :tipo, :importe_cop, :motivo, :evidencia_cobro,
                       :referencia_autorizacion, :medio_autorizacion, :autorizador_id, :autorizador_nombre,
                       :registrado_en_utc, :ejecutor_id, :ejecutor_nombre, :fecha_negocio, :registrado_en_utc,
                       :clave_idempotencia, :huella_solicitud) RETURNING *""", values).fetchone())

    def cancellation_by_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM anulaciones_extincion_deuda WHERE clave_idempotencia = ?", (key,)).fetchone())

    def add_cancellation(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO anulaciones_extincion_deuda
               (extincion_id, importe_anulado_cop, motivo, referencia_autorizacion, medio_autorizacion,
                autorizador_id, autorizador_nombre, ejecutor_id, ejecutor_nombre, fecha_negocio,
                anulada_en_utc, clave_idempotencia, huella_solicitud)
               VALUES (:extincion_id, :importe_anulado_cop, :motivo, :referencia_autorizacion,
                       :medio_autorizacion, :autorizador_id, :autorizador_nombre, :ejecutor_id,
                       :ejecutor_nombre, :fecha_negocio, :registrado_en_utc, :clave_idempotencia,
                       :huella_solicitud) RETURNING *""", values).fetchone())

    def recovery_by_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM recuperaciones_deuda_venta WHERE clave_idempotencia = ?", (key,)).fetchone())

    def add_recovery(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO recuperaciones_deuda_venta
               (venta_id, importe_cop, metodo_pago_id, referencia, motivo, referencia_autorizacion,
                medio_autorizacion, autorizador_id, autorizador_nombre, ejecutor_id, ejecutor_nombre,
                fecha_negocio, registrado_en_utc, clave_idempotencia, huella_solicitud)
               VALUES (:venta_id, :importe_cop, :metodo_pago_id, :referencia, :motivo,
                       :referencia_autorizacion, :medio_autorizacion, :autorizador_id, :autorizador_nombre,
                       :ejecutor_id, :ejecutor_nombre, :fecha_negocio, :registrado_en_utc,
                       :clave_idempotencia, :huella_solicitud) RETURNING *""", values).fetchone())

    def extinctions_for_sale(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT x.*, x.importe_cop - COALESCE((SELECT SUM(a.importe_anulado_cop)
                   FROM anulaciones_extincion_deuda a WHERE a.extincion_id = x.id), 0) AS importe_vigente_cop
               FROM extinciones_deuda_venta x WHERE x.venta_id = ? ORDER BY x.id""", (sale_id,)).fetchall())

    def recoveries_for_sale(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM recuperaciones_deuda_venta WHERE venta_id = ? ORDER BY id", (sale_id,)).fetchall())

    def history(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM v_historial_financiero_venta WHERE venta_id = ? ORDER BY instante_utc, evento, referencia_id",
            (sale_id,)).fetchall())

    def portfolio(self) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM v_cartera_ventas ORDER BY antiguedad_dias DESC, venta_id").fetchall())
