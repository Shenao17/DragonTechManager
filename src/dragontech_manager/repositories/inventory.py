"""Persistencia de productos, proveedores y movimientos de inventario."""

import sqlite3

from ._rows import row_dict, rows_dict


class InventoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_product(self, values: dict, created_utc: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO productos
               (sku, nombre, descripcion, categoria, costo_actual_cop, precio_actual_cop,
                activo, umbral_reposicion, creado_en_utc)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?) RETURNING *""",
            (values["sku"], values["name"], values["description"], values["category"],
             values["unit_cost_cop"], values["suggested_price_cop"],
             values["minimum_stock"], created_utc),
        ).fetchone())

    def get_product(self, product_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            """SELECT p.*, e.existencia, e.reservado, e.disponible
               FROM productos p JOIN v_existencias e ON e.producto_id = p.id
               WHERE p.id = ?""", (product_id,)
        ).fetchone())

    def update_product(self, product_id: int, values: dict) -> dict | None:
        self.connection.execute(
            """UPDATE productos SET sku=?, nombre=?, descripcion=?, categoria=?,
               costo_actual_cop=?, precio_actual_cop=?, umbral_reposicion=?, activo=?
               WHERE id=?""",
            (values["sku"], values["name"], values["description"], values["category"],
             values["unit_cost_cop"], values["suggested_price_cop"],
             values["minimum_stock"], int(values["active"]), product_id),
        )
        return self.get_product(product_id)

    def list_products(self, *, search: str | None, stock_filter: str,
                      active: bool | None, limit: int, offset: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT p.*, e.existencia, e.reservado, e.disponible
               FROM productos p JOIN v_existencias e ON e.producto_id = p.id
               WHERE (? IS NULL OR p.sku LIKE '%' || ? || '%' COLLATE NOCASE
                      OR p.nombre LIKE '%' || ? || '%' COLLATE NOCASE
                      OR p.descripcion LIKE '%' || ? || '%' COLLATE NOCASE
                      OR p.categoria LIKE '%' || ? || '%' COLLATE NOCASE)
                 AND (? IS NULL OR p.activo = ?)
                 AND (? = 'todos'
                      OR (? = 'agotado' AND e.existencia = 0)
                      OR (? = 'bajo' AND p.umbral_reposicion IS NOT NULL
                          AND e.existencia <= p.umbral_reposicion)
                      OR (? = 'disponible' AND e.existencia > 0))
               ORDER BY p.nombre COLLATE NOCASE, p.id LIMIT ? OFFSET ?""",
            (search, search, search, search, search, active, int(active) if active is not None else None,
             stock_filter, stock_filter, stock_filter, stock_filter, limit, offset),
        ).fetchall()
        return rows_dict(rows)

    def list_movements(self, product_id: int, *, limit: int = 100, offset: int = 0) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT m.*, cd.compra_id, c.referencia AS compra_referencia,
                      p.nombre AS producto_nombre,
                      v.codigo AS venta_codigo, o.codigo AS orden_codigo,
                      a.codigo AS armado_codigo
               FROM movimientos_inventario m
               LEFT JOIN compra_detalles cd ON cd.id = m.compra_detalle_id
               LEFT JOIN compras c ON c.id = cd.compra_id
               LEFT JOIN venta_detalles vd ON vd.id = m.venta_detalle_id
               LEFT JOIN ventas v ON v.id = vd.venta_id
               LEFT JOIN orden_repuestos ore ON ore.id = m.orden_repuesto_id
               LEFT JOIN ordenes_servicio o ON o.id = ore.orden_id
               LEFT JOIN armado_componentes ac ON ac.id = m.armado_componente_id
               LEFT JOIN armados_pc a ON a.id = ac.armado_id
               JOIN productos p ON p.id = m.producto_id
               WHERE m.producto_id = ? ORDER BY m.creado_en_utc DESC, m.id DESC LIMIT ? OFFSET ?""",
            (product_id, limit, offset),
        ).fetchall())

    def stock_summary(self) -> dict[str, int]:
        row = self.connection.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(CASE WHEN e.existencia = 0 THEN 1 ELSE 0 END), 0) AS agotados,
                      COALESCE(SUM(CASE WHEN p.umbral_reposicion IS NOT NULL
                            AND e.existencia > 0 AND e.existencia <= p.umbral_reposicion
                            THEN 1 ELSE 0 END), 0) AS bajos
               FROM productos p JOIN v_existencias e ON e.producto_id = p.id
               WHERE p.activo = 1"""
        ).fetchone()
        return dict(row)

    def stock_and_reserved(self, product_id: int) -> tuple[int, int] | None:
        row = self.connection.execute(
            "SELECT existencia, reservado FROM v_existencias WHERE producto_id = ?", (product_id,)
        ).fetchone()
        return (row["existencia"], row["reservado"]) if row else None

    def add_movement(self, *, product_id: int, delta: int, cost_cop: int,
                     kind: str, created_utc: str, reason: str,
                     purchase_line_id: int | None = None,
                     sale_line_id: int | None = None,
                     reverses_movement_id: int | None = None) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                compra_detalle_id, venta_detalle_id, reversa_movimiento_id, creado_en_utc, motivo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *""",
            (product_id, delta, cost_cop, kind, purchase_line_id,
             sale_line_id, reverses_movement_id, created_utc, reason),
        ).fetchone())

    def reserve_sale_line(self, *, product_id: int, sale_line_id: int,
                          quantity: int, timestamp_utc: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO reservas_inventario
               (producto_id, venta_detalle_id, cantidad, estado, creada_en_utc, actualizada_en_utc)
               VALUES (?, ?, ?, 'reservada', ?, ?) RETURNING *""",
            (product_id, sale_line_id, quantity, timestamp_utc, timestamp_utc),
        ).fetchone())

    def get_movement(self, movement_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM movimientos_inventario WHERE id = ?", (movement_id,)
        ).fetchone())

    def movement_reversal_exists(self, movement_id: int) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM movimientos_inventario WHERE reversa_movimiento_id = ?", (movement_id,)
        ).fetchone() is not None

    def create_supplier(self, values: dict, created_utc: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO proveedores
               (nombre, identificacion_fiscal, telefono, correo, direccion, notas, creado_en_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *""",
            (values["name"], values["tax_id"], values["phone"], values["email"],
             values["address"], values["notes"], created_utc),
        ).fetchone())

    def get_supplier(self, supplier_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM proveedores WHERE id = ?", (supplier_id,)
        ).fetchone())

    def update_supplier(self, supplier_id: int, values: dict) -> dict | None:
        self.connection.execute(
            """UPDATE proveedores SET nombre=?, identificacion_fiscal=?, telefono=?,
               correo=?, direccion=?, notas=?, activo=? WHERE id=?""",
            (values["name"], values["tax_id"], values["phone"], values["email"],
             values["address"], values["notes"], int(values["active"]), supplier_id),
        )
        return self.get_supplier(supplier_id)

    def list_suppliers(self, *, search: str | None, active: bool | None,
                       limit: int, offset: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT * FROM proveedores
               WHERE (? IS NULL OR nombre LIKE '%' || ? || '%' COLLATE NOCASE
                      OR identificacion_fiscal LIKE '%' || ? || '%'
                      OR telefono LIKE '%' || ? || '%' OR correo LIKE '%' || ? || '%' COLLATE NOCASE)
                 AND (? IS NULL OR activo = ?)
               ORDER BY nombre COLLATE NOCASE, id LIMIT ? OFFSET ?""",
            (search, search, search, search, search, active, int(active) if active is not None else None,
             limit, offset),
        ).fetchall())

    def supplier_tax_id_exists(self, tax_id: str, *, except_id: int | None = None) -> bool:
        return self.connection.execute(
            """SELECT 1 FROM proveedores WHERE identificacion_fiscal = ?
               AND (? IS NULL OR id <> ?) LIMIT 1""", (tax_id, except_id, except_id)
        ).fetchone() is not None
