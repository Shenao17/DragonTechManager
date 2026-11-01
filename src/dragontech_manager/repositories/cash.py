"""Consultas de los reportes de entregas y arqueo de caja."""

import sqlite3

from ._rows import row_dict, rows_dict


class CashRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def deliveries_by_criterion(self, day: str) -> list[dict]:
        return rows_dict(self.connection.execute(
            "SELECT * FROM v_entregas_del_dia WHERE fecha = ? ORDER BY criterio, medio", (day,)).fetchall())

    def effective_deliveries(self, day: str) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT * FROM v_entregas_efectivas
               WHERE liberada = 0 AND date(ocurrido_efectivo_utc, '-5 hours') = ?
               ORDER BY ocurrido_efectivo_utc, evento_id""", (day,)).fetchall())

    def arqueo(self, day: str) -> dict | None:
        return row_dict(self.connection.execute("SELECT * FROM v_arqueo_caja WHERE fecha = ?", (day,)).fetchone())
