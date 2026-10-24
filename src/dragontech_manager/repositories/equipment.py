"""Persistencia y consultas de equipos."""

import sqlite3

from ._rows import row_dict, rows_dict


class EquipmentRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        *,
        code: str,
        customer_id: int,
        equipment_type: str,
        brand: str,
        model: str,
        serial: str | None,
        specifications: str,
        accessories_received: str,
        physical_condition: str,
        timestamp_utc: str,
    ) -> dict:
        row = self.connection.execute(
            """INSERT INTO equipos
               (codigo, cliente_id, tipo, marca, modelo, serial, especificaciones,
                accesorios_recibidos, estado_fisico, creado_en_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *""",
            (
                code,
                customer_id,
                equipment_type,
                brand,
                model,
                serial,
                specifications,
                accessories_received,
                physical_condition,
                timestamp_utc,
            ),
        ).fetchone()
        return row_dict(row)

    def get(self, equipment_id: int) -> dict | None:
        return row_dict(
            self.connection.execute(
                """SELECT e.*, c.nombre AS cliente_nombre FROM equipos e
                   JOIN clientes c ON c.id = e.cliente_id WHERE e.id = ?""",
                (equipment_id,),
            ).fetchone()
        )

    def list_for_customer(self, customer_id: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT * FROM equipos WHERE cliente_id = ?
               ORDER BY creado_en_utc DESC, id DESC""",
            (customer_id,),
        ).fetchall()
        return rows_dict(rows)

    def list_all(self, *, search: str | None, limit: int, offset: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT e.*, c.nombre AS cliente_nombre
               FROM equipos e JOIN clientes c ON c.id = e.cliente_id
               WHERE (? IS NULL OR e.codigo LIKE '%' || ? || '%' COLLATE NOCASE
                      OR e.tipo LIKE '%' || ? || '%' COLLATE NOCASE
                      OR e.marca LIKE '%' || ? || '%' COLLATE NOCASE
                      OR e.modelo LIKE '%' || ? || '%' COLLATE NOCASE
                      OR COALESCE(e.serial, '') LIKE '%' || ? || '%' COLLATE NOCASE
                      OR c.nombre LIKE '%' || ? || '%' COLLATE NOCASE)
               ORDER BY e.creado_en_utc DESC, e.id DESC LIMIT ? OFFSET ?""",
            (search, search, search, search, search, search, search, limit, offset),
        ).fetchall()
        return rows_dict(rows)
