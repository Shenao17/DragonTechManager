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
            """SELECT o.*, c.nombre AS cliente_nombre, e.codigo AS equipo_codigo,
                      e.tipo AS equipo_tipo,
                      o.importe_inicial_cop + COALESCE((
                          SELECT SUM(s.importe_propuesto_cop)
                          FROM servicios_adicionales s
                          JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
                          WHERE s.orden_id = o.id AND d.decision = 'aprobado'
                            AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                                        WHERE d2.servicio_adicional_id = s.id
                                        ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
                      ), 0) AS importe_acordado_cop
               FROM ordenes_servicio o
               JOIN clientes c ON c.id = o.cliente_id
               JOIN equipos e ON e.id = o.equipo_id
               WHERE (? IS NULL OR o.estado = ?)
                 AND (? IS NULL OR o.cliente_id = ?)
                 AND (? IS NULL OR o.equipo_id = ?)
               ORDER BY o.recibido_en_utc DESC, o.id DESC LIMIT ? OFFSET ?""",
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
