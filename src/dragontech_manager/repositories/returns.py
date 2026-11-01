"""Persistencia de devoluciones y cancelaciones de venta."""

import sqlite3

from ._rows import row_dict, rows_dict


class ReturnsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get_by_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM cancelaciones_venta WHERE clave_idempotencia = ?", (key,)
        ).fetchone())

    def get(self, return_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM cancelaciones_venta WHERE id = ?", (return_id,)
        ).fetchone())

    def create(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO cancelaciones_venta
               (venta_id, motivo, solicitante, solicitante_tipo, solicitado_en_utc,
                responsable_ejecucion, ejecutado_en_utc, autorizador, autorizado_en_utc,
                referencia_autorizacion, fecha_negocio, clave_idempotencia, huella_solicitud,
                solicitante_id, ejecutor_id, autorizador_id, origen_identidad)
               VALUES (:venta_id, :motivo, :solicitante, :solicitante_tipo, :solicitado_en_utc,
                       :responsable_ejecucion, :ejecutado_en_utc, :autorizador, :autorizado_en_utc,
                       :referencia_autorizacion, :fecha_negocio, :clave_idempotencia,
                       :huella_solicitud, :solicitante_id, :ejecutor_id, :autorizador_id,
                       :origen_identidad) RETURNING *""", values,
        ).fetchone())

    def add_line(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO cancelacion_venta_lineas
               (cancelacion_id, venta_detalle_id, cantidad_devuelta, cantidad_reintegrada,
                condicion_no_apta, motivo_no_reintegro, importe_reconocido_cop, motivo_ajuste_valor)
               VALUES (:cancelacion_id, :venta_detalle_id, :cantidad_devuelta, :cantidad_reintegrada,
                       :condicion_no_apta, :motivo_no_reintegro, :importe_reconocido_cop,
                       :motivo_ajuste_valor) RETURNING *""", values,
        ).fetchone())

    def lines_of(self, return_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT l.*, d.descripcion, d.precio_unitario_cop, d.producto_id
               FROM cancelacion_venta_lineas l JOIN venta_detalles d ON d.id = l.venta_detalle_id
               WHERE l.cancelacion_id = ? ORDER BY l.id""", (return_id,)
        ).fetchall())

    def list_for_sale(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM cancelaciones_venta WHERE venta_id = ? ORDER BY ejecutado_en_utc, id",
            (sale_id,)
        ).fetchall())

    def returnable_lines(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT d.id AS venta_detalle_id, d.descripcion, d.cantidad, d.precio_unitario_cop,
                      d.producto_id, d.costo_unitario_historico_cop,
                      COALESCE((SELECT SUM(l.cantidad_devuelta) FROM cancelacion_venta_lineas l
                                WHERE l.venta_detalle_id = d.id), 0) AS cantidad_devuelta,
                      d.cantidad - COALESCE((SELECT SUM(l.cantidad_devuelta)
                                             FROM cancelacion_venta_lineas l
                                             WHERE l.venta_detalle_id = d.id), 0) AS cantidad_disponible
               FROM venta_detalles d WHERE d.venta_id = ? ORDER BY d.id""", (sale_id,)
        ).fetchall())

    def lost_inventory(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM v_devoluciones_no_reintegradas WHERE venta_id = ? ORDER BY linea_id",
            (sale_id,)
        ).fetchall())
