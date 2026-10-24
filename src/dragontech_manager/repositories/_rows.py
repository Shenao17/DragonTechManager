"""Conversión consistente de filas SQLite a diccionarios simples."""

import sqlite3


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_dict(rows) -> list[dict]:
    return [dict(row) for row in rows]
