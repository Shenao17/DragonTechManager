"""Consultas de solo lectura para el panel principal."""

import sqlite3


class DashboardRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def order_summary(self) -> dict[str, int]:
        row = self.connection.execute(
            """SELECT
                   SUM(CASE WHEN estado IN ('recibida', 'diagnostico', 'espera_aprobacion') THEN 1 ELSE 0 END) AS pendientes,
                   SUM(CASE WHEN estado = 'en_proceso' THEN 1 ELSE 0 END) AS en_proceso,
                   SUM(CASE WHEN estado = 'lista' THEN 1 ELSE 0 END) AS listas,
                   SUM(CASE WHEN estado = 'entregada' THEN 1 ELSE 0 END) AS entregadas,
                   COUNT(*) AS total
               FROM ordenes_servicio"""
        ).fetchone()
        return {
            key: int(row[key] or 0)
            for key in ("pendientes", "en_proceso", "listas", "entregadas", "total")
        }
