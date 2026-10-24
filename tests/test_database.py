"""Pruebas iniciales de las garantías de conexión SQLite."""

import sqlite3
import unittest
from contextlib import closing

from dragontech_manager.database.connection import open_database


class DatabaseConnectionTests(unittest.TestCase):
    def test_enables_foreign_keys_for_each_connection(self) -> None:
        with closing(open_database(":memory:")) as connection:
            enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(enabled, 1)

    def test_foreign_key_violation_is_rejected(self) -> None:
        with closing(open_database(":memory:")) as connection:
            connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO child (parent_id) VALUES (42)")

    def test_connection_returns_rows_by_column_name(self) -> None:
        with closing(open_database(":memory:")) as connection:
            row = connection.execute("SELECT 7 AS answer").fetchone()
            self.assertEqual(row["answer"], 7)


if __name__ == "__main__":
    unittest.main()
