"""Persistencia parametrizada de ventas y pagos de clientes."""

import sqlite3

from ._rows import row_dict, rows_dict


class SalesRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_sale(self, *, code: str, customer_id: int, proposal_id: int | None,
                    sale_date: str, notes: str, created_utc: str,
                    idempotency_key: str, request_hash: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO ventas
               (codigo, cliente_id, cotizacion_id, fecha_venta, estado, notas,
                creado_en_utc, clave_idempotencia, huella_solicitud)
               VALUES (?, ?, ?, ?, 'abierta', ?, ?, ?, ?) RETURNING *""",
            (code, customer_id, proposal_id, sale_date, notes, created_utc,
             idempotency_key, request_hash),
        ).fetchone())

    def add_line(self, sale_id: int, line: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO venta_detalles
               (venta_id, descripcion, cantidad, precio_unitario_cop,
                costo_unitario_historico_cop, producto_id, cotizacion_detalle_id)
               VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *""",
            (sale_id, line["description"], line["quantity"], line["unit_price_cop"],
             line.get("historical_cost_cop"), line.get("product_id"),
             line.get("proposal_line_id")),
        ).fetchone())

    def get_sale(self, sale_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            """SELECT v.*, c.nombre AS cliente_nombre, b.importe_acordado_cop,
                      b.pagado_neto_cop, b.saldo_pendiente_cop,
                      b.estado_cobro
               FROM ventas v JOIN clientes c ON c.id = v.cliente_id
               JOIN v_saldos_ventas b ON b.venta_id = v.id WHERE v.id = ?""",
            (sale_id,),
        ).fetchone())

    def get_by_idempotency_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM ventas WHERE clave_idempotencia = ?", (key,)
        ).fetchone())

    def get_by_proposal(self, proposal_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM ventas WHERE cotizacion_id = ?", (proposal_id,)
        ).fetchone())

    def lines(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT d.*, p.sku AS producto_sku FROM venta_detalles d
               LEFT JOIN productos p ON p.id = d.producto_id
               WHERE d.venta_id = ? ORDER BY d.id""", (sale_id,)
        ).fetchall())

    def payments(self, sale_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT p.*,
                      EXISTS (SELECT 1 FROM pagos_clientes r WHERE r.reversa_pago_id = p.id) AS reversado
               FROM pagos_clientes p WHERE p.venta_id = ?
               ORDER BY p.registrado_en_utc, p.id""", (sale_id,)
        ).fetchall())

    def list_sales(self, *, search: str | None, state: str | None,
                   date_from: str | None, date_to: str | None,
                   limit: int, offset: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT v.id, v.codigo, v.fecha_venta, v.cliente_id,
                      c.nombre AS cliente_nombre, v.estado, b.importe_acordado_cop,
                      b.pagado_neto_cop, b.saldo_pendiente_cop,
                      b.estado_cobro
               FROM ventas v JOIN clientes c ON c.id = v.cliente_id
               JOIN v_saldos_ventas b ON b.venta_id = v.id
               WHERE (? IS NULL OR b.estado_cobro = ?)
                 AND (? IS NULL OR v.codigo LIKE '%' || ? || '%' COLLATE NOCASE
                      OR c.nombre LIKE '%' || ? || '%' COLLATE NOCASE)
                 AND (? IS NULL OR v.fecha_venta >= ?)
                 AND (? IS NULL OR v.fecha_venta <= ?)
               ORDER BY v.fecha_venta DESC, v.id DESC LIMIT ? OFFSET ?""",
            (state, state, search, search, search, date_from, date_from,
             date_to, date_to, limit, offset),
        ).fetchall())

    def create_payment(self, *, sale_id: int, amount_cop: int, method: str, method_id: int,
                       reference: str, timestamp_utc: str, business_date: str,
                       idempotency_key: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO pagos_clientes
               (venta_id, importe_cop, tipo, metodo, metodo_pago_id, referencia,
                registrado_en_utc, fecha_negocio, clave_idempotencia)
               VALUES (?, ?, 'recibo', ?, ?, ?, ?, ?, ?) RETURNING *""",
            (sale_id, amount_cop, method, method_id, reference, timestamp_utc,
             business_date, idempotency_key),
        ).fetchone())

    def get_payment(self, payment_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM pagos_clientes WHERE id = ?", (payment_id,)
        ).fetchone())

    def get_payment_by_key(self, key: str) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM pagos_clientes WHERE clave_idempotencia = ?", (key,)
        ).fetchone())

    def payment_reversed(self, payment_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM pagos_clientes WHERE reversa_pago_id = ?", (payment_id,)
        ).fetchone() is not None

    def reverse_payment(self, original: dict, *, reason: str, timestamp_utc: str,
                        business_date: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO pagos_clientes
               (venta_id, importe_cop, tipo, metodo, metodo_pago_id, referencia,
                registrado_en_utc, fecha_negocio, reversa_pago_id, motivo)
               VALUES (?, ?, 'reversion', ?, ?, ?, ?, ?, ?, ?) RETURNING *""",
            (original["venta_id"], original["importe_cop"], original["metodo"],
             original["metodo_pago_id"], original["referencia"], timestamp_utc,
             business_date, original["id"], reason),
        ).fetchone())
