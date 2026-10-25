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

    def get_detail(self, order_id: int) -> dict | None:
        row = self.connection.execute(
            """SELECT o.*, c.nombre AS cliente_solicitante_nombre,
                      c.telefono AS cliente_telefono, c.whatsapp AS cliente_whatsapp,
                      e.codigo AS equipo_codigo, e.tipo AS equipo_tipo,
                      e.marca AS equipo_marca, e.modelo AS equipo_modelo,
                      e.serial AS equipo_serial, propietario.nombre AS propietario_nombre,
                      o.importe_inicial_cop + COALESCE((
                          SELECT SUM(s.importe_propuesto_cop)
                          FROM servicios_adicionales s
                          WHERE s.orden_id = o.id AND (
                              SELECT d.decision FROM decisiones_adicional d
                              WHERE d.servicio_adicional_id = s.id
                              ORDER BY d.decidido_en_utc DESC, d.id DESC LIMIT 1
                          ) = 'aprobado'
                      ), 0) AS importe_acordado_cop
               FROM ordenes_servicio o
               JOIN clientes c ON c.id = o.cliente_id
               JOIN equipos e ON e.id = o.equipo_id
               JOIN clientes propietario ON propietario.id = e.cliente_id
               WHERE o.id = ?""",
            (order_id,),
        ).fetchone()
        return row_dict(row)

    def status_history(self, order_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT estado_anterior, estado_nuevo, cambiado_en_utc, motivo
               FROM historial_estados_orden
               WHERE orden_id = ? ORDER BY cambiado_en_utc, id""",
            (order_id,),
        ).fetchall()
        return rows_dict(rows)

    def has_pending_additional_decisions(self, order_id: int) -> bool:
        row = self.connection.execute(
            """SELECT EXISTS (
                   SELECT 1 FROM servicios_adicionales s
                   WHERE s.orden_id = ? AND NOT EXISTS (
                       SELECT 1 FROM decisiones_adicional d
                       WHERE d.servicio_adicional_id = s.id
                   )
               )""",
            (order_id,),
        ).fetchone()
        return bool(row[0])

    def list_additional_services(self, order_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT s.id, s.orden_id, s.descripcion, s.importe_propuesto_cop,
                      s.propuesto_en_utc, d.decision, d.decidido_en_utc, d.evidencia,
                      CASE WHEN d.decision IS NULL THEN 'pendiente' ELSE d.decision END AS estado
               FROM servicios_adicionales s
               LEFT JOIN decisiones_adicional d ON d.id = (
                   SELECT d2.id FROM decisiones_adicional d2
                   WHERE d2.servicio_adicional_id = s.id
                   ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1
               )
               WHERE s.orden_id = ?
               ORDER BY s.propuesto_en_utc, s.id""",
            (order_id,),
        ).fetchall()
        return rows_dict(rows)

    def additional_service(self, additional_id: int) -> dict | None:
        return row_dict(
            self.connection.execute(
                "SELECT * FROM servicios_adicionales WHERE id = ?", (additional_id,)
            ).fetchone()
        )

    def additional_decision_history(self, additional_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT decision, decidido_en_utc, evidencia
               FROM decisiones_adicional WHERE servicio_adicional_id = ?
               ORDER BY decidido_en_utc, id""",
            (additional_id,),
        ).fetchall()
        return rows_dict(rows)

    def has_pending_duplicate_proposal(
        self, order_id: int, description: str, amount_cop: int
    ) -> bool:
        row = self.connection.execute(
            """SELECT EXISTS (
                   SELECT 1 FROM servicios_adicionales s
                   WHERE s.orden_id = ? AND s.descripcion = ? COLLATE NOCASE
                     AND s.importe_propuesto_cop = ?
                     AND NOT EXISTS (
                         SELECT 1 FROM decisiones_adicional d
                         WHERE d.servicio_adicional_id = s.id
                     )
               )""",
            (order_id, description, amount_cop),
        ).fetchone()
        return bool(row[0])

    def create_additional_service(
        self, order_id: int, description: str, amount_cop: int, timestamp_utc: str
    ) -> dict:
        row = self.connection.execute(
            """INSERT INTO servicios_adicionales
               (orden_id, descripcion, importe_propuesto_cop, propuesto_en_utc)
               VALUES (?, ?, ?, ?) RETURNING *""",
            (order_id, description, amount_cop, timestamp_utc),
        ).fetchone()
        return row_dict(row)

    def add_additional_decision(
        self,
        additional_id: int,
        decision: str,
        timestamp_utc: str,
        evidence: str,
    ) -> None:
        self.connection.execute(
            """INSERT INTO decisiones_adicional
               (servicio_adicional_id, decision, decidido_en_utc, evidencia)
               VALUES (?, ?, ?, ?)""",
            (additional_id, decision, timestamp_utc, evidence),
        )

    def update_technical_details(
        self,
        order_id: int,
        *,
        diagnosis: str,
        work_performed: str,
        tests_performed: str,
        technician: str,
        timestamp_utc: str,
    ) -> dict | None:
        row = self.connection.execute(
            """UPDATE ordenes_servicio
               SET diagnostico = ?, trabajo_realizado = ?, pruebas_realizadas = ?,
                   tecnico = ?, actualizado_en_utc = ?
               WHERE id = ? RETURNING *""",
            (diagnosis, work_performed, tests_performed, technician, timestamp_utc, order_id),
        ).fetchone()
        return row_dict(row)

    def update_status(
        self,
        order_id: int,
        *,
        previous_state: str,
        new_state: str,
        timestamp_utc: str,
        delivery_date: str | None,
    ) -> dict | None:
        row = self.connection.execute(
            """UPDATE ordenes_servicio
               SET estado = ?, fecha_entrega = COALESCE(?, fecha_entrega), actualizado_en_utc = ?
               WHERE id = ? AND estado = ? RETURNING *""",
            (new_state, delivery_date, timestamp_utc, order_id, previous_state),
        ).fetchone()
        return row_dict(row)

    def add_status_event(
        self,
        order_id: int,
        *,
        previous_state: str | None,
        new_state: str,
        timestamp_utc: str,
        reason: str,
    ) -> None:
        self.connection.execute(
            """INSERT INTO historial_estados_orden
               (orden_id, estado_anterior, estado_nuevo, cambiado_en_utc, motivo)
               VALUES (?, ?, ?, ?, ?)""",
            (order_id, previous_state, new_state, timestamp_utc, reason),
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
