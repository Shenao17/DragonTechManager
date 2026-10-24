"""Persistencia y consultas de clientes."""

import sqlite3

from ._rows import row_dict, rows_dict


class CustomerRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        *,
        name: str,
        phone: str | None,
        whatsapp: str | None,
        email: str | None,
        notes: str,
        timestamp_utc: str,
    ) -> dict:
        row = self.connection.execute(
            """INSERT INTO clientes
               (nombre, telefono, whatsapp, correo, notas, creado_en_utc, actualizado_en_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *""",
            (name, phone, whatsapp, email, notes, timestamp_utc, timestamp_utc),
        ).fetchone()
        return row_dict(row)

    def get(self, customer_id: int) -> dict | None:
        return row_dict(
            self.connection.execute(
                "SELECT * FROM clientes WHERE id = ?", (customer_id,)
            ).fetchone()
        )

    def list(self, *, search: str | None, limit: int, offset: int) -> list[dict]:
        rows = self.connection.execute(
            """SELECT * FROM clientes
               WHERE (? IS NULL OR nombre LIKE '%' || ? || '%' COLLATE NOCASE
                      OR telefono LIKE '%' || ? || '%' OR whatsapp LIKE '%' || ? || '%'
                      OR correo LIKE '%' || ? || '%')
               ORDER BY nombre COLLATE NOCASE, id LIMIT ? OFFSET ?""",
            (search, search, search, search, search, limit, offset),
        ).fetchall()
        return rows_dict(rows)
