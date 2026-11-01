"""Persistencia de compras, detalles, saldos y pagos a proveedores."""

import sqlite3

from ._rows import row_dict, rows_dict


class ProcurementRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_purchase(self, *, supplier_id: int, reference: str, purchase_date: str,
                        notes: str, created_utc: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO compras
               (proveedor_id, referencia, fecha_compra, estado, notas, creado_en_utc)
               VALUES (?, ?, ?, 'borrador', ?, ?) RETURNING *""",
            (supplier_id, reference, purchase_date, notes, created_utc),
        ).fetchone())

    def add_purchase_line(self, purchase_id: int, line: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO compra_detalles
               (compra_id, producto_id, cantidad, costo_unitario_historico_cop, descripcion_historica)
               VALUES (?, ?, ?, ?, ?) RETURNING *""",
            (purchase_id, line["product_id"], line["quantity"], line["unit_cost_cop"], line["description"]),
        ).fetchone())

    def get_purchase(self, purchase_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            """SELECT c.*, p.nombre AS proveedor_nombre, s.importe_compra_cop,
                      s.pagado_neto_cop, s.saldo_pendiente_cop
               FROM compras c JOIN proveedores p ON p.id = c.proveedor_id
               JOIN v_saldos_compras s ON s.compra_id = c.id WHERE c.id = ?""",
            (purchase_id,),
        ).fetchone())

    def purchase_lines(self, purchase_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT d.*, p.sku, p.nombre AS producto_nombre
               FROM compra_detalles d JOIN productos p ON p.id = d.producto_id
               WHERE d.compra_id = ? ORDER BY d.id""", (purchase_id,)
        ).fetchall())

    def update_purchase(self, purchase_id: int, *, supplier_id: int,
                        reference: str, purchase_date: str, notes: str) -> None:
        self.connection.execute(
            """UPDATE compras SET proveedor_id=?, referencia=?, fecha_compra=?, notas=?
               WHERE id=?""", (supplier_id, reference, purchase_date, notes, purchase_id)
        )
        self.connection.execute("DELETE FROM compra_detalles WHERE compra_id=?", (purchase_id,))

    def set_purchase_state(self, purchase_id: int, state: str, *, received_on: str | None = None) -> None:
        self.connection.execute(
            "UPDATE compras SET estado=?, fecha_recepcion=? WHERE id=?",
            (state, received_on, purchase_id),
        )

    def list_purchases(self, *, search: str | None, state: str | None,
                       limit: int, offset: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT c.id, c.proveedor_id, p.nombre AS proveedor_nombre, c.referencia,
                      c.fecha_compra, c.fecha_recepcion, c.estado,
                      s.importe_compra_cop, s.pagado_neto_cop, s.saldo_pendiente_cop
               FROM compras c JOIN proveedores p ON p.id = c.proveedor_id
               JOIN v_saldos_compras s ON s.compra_id = c.id
               WHERE (? IS NULL OR c.estado = ?)
                 AND (? IS NULL OR c.referencia LIKE '%' || ? || '%' COLLATE NOCASE
                      OR p.nombre LIKE '%' || ? || '%' COLLATE NOCASE
                      OR CAST(c.id AS TEXT) LIKE '%' || ? || '%')
               ORDER BY c.fecha_compra DESC, c.id DESC LIMIT ? OFFSET ?""",
            (state, state, search, search, search, search, limit, offset),
        ).fetchall())

    def add_supplier_payment(self, *, purchase_id: int, amount_cop: int, method: str,
                             method_id: int, reference: str, timestamp_utc: str,
                             business_date: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO pagos_proveedores
               (compra_id, importe_cop, tipo, metodo, metodo_pago_id, referencia,
                registrado_en_utc, fecha_negocio)
               VALUES (?, ?, 'pago', ?, ?, ?, ?, ?) RETURNING *""",
            (purchase_id, amount_cop, method, method_id, reference, timestamp_utc,
             business_date),
        ).fetchone())

    def get_supplier_payment(self, payment_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM pagos_proveedores WHERE id=?", (payment_id,)
        ).fetchone())

    def payment_reversal_exists(self, payment_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM pagos_proveedores WHERE reversa_pago_id=?", (payment_id,)
        ).fetchone() is not None

    def reverse_supplier_payment(self, original: dict, *, reason: str, timestamp_utc: str,
                                 business_date: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO pagos_proveedores
               (compra_id, importe_cop, tipo, metodo, metodo_pago_id, referencia,
                registrado_en_utc, fecha_negocio, reversa_pago_id, motivo)
               VALUES (?, ?, 'reversion', ?, ?, ?, ?, ?, ?, ?) RETURNING *""",
            (original["compra_id"], original["importe_cop"], original["metodo"],
             original["metodo_pago_id"], original["referencia"], timestamp_utc,
             business_date, original["id"], reason),
        ).fetchone())

    def list_supplier_payments(self, purchase_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT * FROM pagos_proveedores WHERE compra_id = ?
               ORDER BY registrado_en_utc, id""", (purchase_id,)
        ).fetchall())

    def purchase_has_payment_history(self, purchase_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM pagos_proveedores WHERE compra_id=? LIMIT 1", (purchase_id,)
        ).fetchone() is not None

    def list_supplier_purchases(self, supplier_id: int, *, limit: int = 100) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT c.id, c.referencia, c.fecha_compra, c.fecha_recepcion, c.estado,
                      s.importe_compra_cop, s.pagado_neto_cop, s.saldo_pendiente_cop
               FROM compras c JOIN v_saldos_compras s ON s.compra_id = c.id
               WHERE c.proveedor_id = ? ORDER BY c.fecha_compra DESC, c.id DESC LIMIT ?""",
            (supplier_id, limit),
        ).fetchall())
