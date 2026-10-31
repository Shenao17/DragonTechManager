"""Traducción específica de errores de integridad de SQLite."""

import sqlite3
import unittest
from contextlib import closing

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.errors import (
    ConflictError,
    DataIntegrityError,
    ValidationError,
    translate_integrity_error,
)
from dragontech_manager.services.inventory import InventoryService

UTC = "2026-10-24T15:30:00Z"


class IntegrityErrorTranslationTests(unittest.TestCase):
    def test_unique_error_names_the_duplicated_field(self) -> None:
        translated = translate_integrity_error(
            sqlite3.IntegrityError("UNIQUE constraint failed: productos.sku")
        )
        self.assertIsInstance(translated, ConflictError)
        self.assertIn("código (SKU)", str(translated))

    def test_unique_error_lists_every_duplicated_field(self) -> None:
        translated = translate_integrity_error(
            sqlite3.IntegrityError(
                "UNIQUE constraint failed: ventas.codigo, ventas.cliente_id"
            )
        )
        self.assertIn("el código", str(translated))
        self.assertIn("el cliente", str(translated))

    def test_not_null_error_names_the_missing_field(self) -> None:
        translated = translate_integrity_error(
            sqlite3.IntegrityError("NOT NULL constraint failed: clientes.nombre")
        )
        self.assertIsInstance(translated, ValidationError)
        self.assertIn("el nombre", str(translated))
        self.assertIn("obligatorio", str(translated))

    def test_foreign_key_error_remains_understandable(self) -> None:
        translated = translate_integrity_error(
            sqlite3.IntegrityError("FOREIGN KEY constraint failed")
        )
        self.assertIsInstance(translated, DataIntegrityError)
        self.assertIn("referencia", str(translated))

    def test_check_error_identifies_the_field_when_it_is_known(self) -> None:
        translated = translate_integrity_error(
            sqlite3.IntegrityError("CHECK constraint failed: productos.sku")
        )
        self.assertIsInstance(translated, ValidationError)
        self.assertIn("código (SKU)", str(translated))

    def test_trigger_message_is_preserved_verbatim(self) -> None:
        translated = translate_integrity_error(
            sqlite3.IntegrityError("Los movimientos de inventario son inmutables")
        )
        self.assertIsInstance(translated, DataIntegrityError)
        self.assertEqual(str(translated), "Los movimientos de inventario son inmutables")

    def test_unknown_internal_message_is_not_leaked(self) -> None:
        translated = translate_integrity_error(
            sqlite3.IntegrityError("datatype mismatch")
        )
        self.assertNotIn("datatype", str(translated))
        self.assertIn("base rechazó", str(translated))

    def test_duplicate_sku_through_service_reports_the_field(self) -> None:
        with closing(open_database(":memory:")) as connection:
            migrate(connection)
            inventory = InventoryService(connection)
            inventory.create_product(sku="DUP-1", name="Producto original")
            with self.assertRaises(ConflictError) as captured:
                inventory.create_product(sku="DUP-1", name="Producto duplicado")
            self.assertIn("código (SKU)", str(captured.exception))

    def test_trigger_rule_through_service_keeps_the_business_message(self) -> None:
        with closing(open_database(":memory:")) as connection:
            migrate(connection)
            inventory = InventoryService(connection)
            product = inventory.create_product(sku="INM-1", name="Producto inmutable")
            movement = inventory.adjust_stock(
                product["id"], 1, unit_cost_cop=1000, reason="Conteo"
            )
            with self.assertRaises(sqlite3.IntegrityError) as captured:
                connection.execute(
                    "DELETE FROM movimientos_inventario WHERE id = ?", (movement["id"],)
                )
            translated = translate_integrity_error(captured.exception)
            self.assertIsInstance(translated, DataIntegrityError)
            self.assertEqual(
                str(translated), "No se borran movimientos de inventario"
            )


if __name__ == "__main__":
    unittest.main()
