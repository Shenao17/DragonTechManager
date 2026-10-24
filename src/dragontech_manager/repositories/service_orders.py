"""Persistencia y consultas de órdenes de servicio."""

import sqlite3

from ._rows import row_dict, rows_dict


class ServiceOrderRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        *,
        code: str,
        customer_id: int,
        equipment_id: int,
        received_at_utc: str,
        problem_reported: str,
        initial_amount_cop: int,
        diagnosis: str,
        technician: str,
        status: str,
    ) -> dict:
        row = self.connection.execute(
            """INSERT INTO ordenes_servicio
               (codigo, cliente_id, equipo_id, recibido_en_utc, problema_reportado,
                importe_inicial_cop, diagnostico, tecnico, estado,
                creado_en_utc, actualizado_en_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *""",
            (
                code,
                customer_id,
                equipment_id,
                received_at_utc,
                problem_reported,
                initial_amount_cop,
                diagnosis,
                technician,
                status,
                received_at_utc,
                received_at_utc,
            ),
        ).fetchone()
        return row_dict(row)

    def get(self, order_id: int) -> dict | None:
        return row_dict(
            self.connection.execute(
                "SELECT * FROM ordenes_servicio WHERE id = ?", (order_id,)
            ).fetchone()
        )

    def list_orders(
        self,
        *,
        state: str | None,
        customer_id: int | None,
        equipment_id: int | None,
        limit: int,
        offset: int,
    ) -> list[dict]:
        rows = self.connection.execute(
            """SELECT * FROM ordenes_servicio
               WHERE (? IS NULL OR estado = ?)
                 AND (? IS NULL OR cliente_id = ?)
                 AND (? IS NULL OR equipo_id = ?)
               ORDER BY recibido_en_utc DESC, id DESC LIMIT ? OFFSET ?""",
            (
                state,
                state,
                customer_id,
                customer_id,
                equipment_id,
                equipment_id,
                limit,
                offset,
            ),
        ).fetchall()
        return rows_dict(rows)

    def history_for_equipment(self, equipment_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT * FROM ordenes_servicio WHERE equipo_id = ?
               ORDER BY recibido_en_utc DESC, id DESC""",
            (equipment_id,),
        ).fetchall()
        return rows_dict(rows)
