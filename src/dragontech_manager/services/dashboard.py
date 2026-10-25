"""Consultas de aplicación para el panel principal."""

import sqlite3

from dragontech_manager.repositories.dashboard import DashboardRepository


class DashboardService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.repository = DashboardRepository(connection)

    def order_summary(self) -> dict[str, int]:
        return self.repository.order_summary()

    def recent_orders(self, limit: int = 8) -> list[dict]:
        return self.repository.recent_orders(limit)
