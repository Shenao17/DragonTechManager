"""Consultas y persistencia de propuestas a clientes."""

import sqlite3

from ._rows import row_dict, rows_dict


class ProposalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(self, *, code: str, customer_id: int, created_utc: str,
               expires_on: str | None, notes: str, conditions: str) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO cotizaciones
               (codigo, cliente_id, creada_en_utc, vence_el, estado, notas, condiciones)
               VALUES (?, ?, ?, ?, 'borrador', ?, ?) RETURNING *""",
            (code, customer_id, created_utc, expires_on, notes, conditions),
        ).fetchone())

    def add_line(self, proposal_id: int, line: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO cotizacion_detalles
               (cotizacion_id, descripcion, cantidad, precio_unitario_cop,
                costo_unitario_historico_cop, producto_id)
               VALUES (?, ?, ?, ?, ?, ?) RETURNING *""",
            (proposal_id, line["description"], line["quantity"], line["unit_price_cop"],
             line.get("historical_cost_cop"), line.get("product_id")),
        ).fetchone())

    def get(self, proposal_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            """SELECT q.*, c.nombre AS cliente_nombre FROM cotizaciones q
               JOIN clientes c ON c.id = q.cliente_id WHERE q.id = ?""",
            (proposal_id,),
        ).fetchone())

    def lines(self, proposal_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM cotizacion_detalles WHERE cotizacion_id = ? ORDER BY id",
            (proposal_id,),
        ).fetchall())

    def update(self, proposal_id: int, *, customer_id: int, expires_on: str | None,
               notes: str, conditions: str) -> None:
        self.connection.execute(
            """UPDATE cotizaciones SET cliente_id = ?, vence_el = ?, notas = ?,
               condiciones = ? WHERE id = ?""",
            (customer_id, expires_on, notes, conditions, proposal_id),
        )
        self.connection.execute(
            "DELETE FROM cotizacion_detalles WHERE cotizacion_id = ?", (proposal_id,)
        )

    def transition(self, proposal_id: int, state: str) -> None:
        self.connection.execute(
            "UPDATE cotizaciones SET estado = ? WHERE id = ?", (state, proposal_id)
        )

    def append_history(self, proposal_id: int, *, event: str, previous: str | None,
                       new: str, detail: str, created_utc: str) -> None:
        self.connection.execute(
            """INSERT INTO historial_cotizaciones
               (cotizacion_id, evento, estado_anterior, estado_nuevo, detalle, creado_en_utc)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (proposal_id, event, previous, new, detail, created_utc),
        )

    def history(self, proposal_id: int) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT * FROM historial_cotizaciones
               WHERE cotizacion_id = ? ORDER BY creado_en_utc, id""", (proposal_id,)
        ).fetchall())

    def list(self, *, search: str | None, state: str | None,
             limit: int, offset: int) -> list[dict]:
        rows = rows_dict(self.connection.execute(
            """SELECT q.id, q.codigo, q.cliente_id, c.nombre AS cliente_nombre,
                      q.creada_en_utc, q.vence_el, q.estado
               FROM cotizaciones q JOIN clientes c ON c.id = q.cliente_id
               WHERE (? IS NULL OR q.estado = ?)
                 AND (? IS NULL OR q.codigo LIKE '%' || ? || '%' COLLATE NOCASE
                      OR c.nombre LIKE '%' || ? || '%' COLLATE NOCASE)
               ORDER BY q.creada_en_utc DESC, q.id DESC LIMIT ? OFFSET ?""",
            (state, state, search, search, search, limit, offset),
        ).fetchall())
        if not rows:
            return rows
        ids = [row["id"] for row in rows]
        marks = ",".join("?" for _ in ids)
        line_rows = self.connection.execute(
            f"SELECT cotizacion_id, cantidad, precio_unitario_cop FROM cotizacion_detalles WHERE cotizacion_id IN ({marks})",
            ids,
        ).fetchall()
        totals = {proposal_id: 0 for proposal_id in ids}
        for line in line_rows:
            totals[line["cotizacion_id"]] += line["cantidad"] * line["precio_unitario_cop"]
        for row in rows:
            row["total_cop"] = totals[row["id"]]
        return rows
