"""La vista de inventario refleja existencias actuales y bloquea reversiones."""

import os
import unittest
from uuid import uuid4

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from dragontech_manager.app import create_main_window
from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.ui.inventory import InventoryWorkspacePage, ProductDetailDialog
from dragontech_manager.ui.theme import apply_theme


class InventoryRefreshUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.version = migrate(self.connection)
        self.window = create_main_window(
            self.connection, database_path=":memory:", schema_version=self.version
        )
        self.addCleanup(self.window.close)
        self.inventory = self.window.inventory_service
        self.product = self.inventory.create_product(
            sku="UI-REV-1", name="Producto visible", unit_cost_cop=1_000,
            suggested_price_cop=2_000,
        )
        self.inventory.adjust_stock(
            self.product["id"], 5, unit_cost_cop=1_000, reason="Carga inicial", idempotency_key=uuid4().hex)

    def _row_for_sku(self, page) -> int:
        for row in range(page.products.table.rowCount()):
            if page.products.table.item(row, 0).text() == "UI-REV-1":
                return row
        self.fail("El producto no aparece en la tabla de inventario")

    def _sale(self, quantity: int = 2) -> dict:
        customer = self.window.customer_service.create_customer("Cliente UI")
        return self.window.sales_service.create_sale(
            customer["id"],
            [{"description": "Producto visible", "quantity": quantity,
              "unit_price_cop": 2_000, "product_id": self.product["id"]}],
            idempotency_key=f"ui-refresh-{quantity}",
        )

    def test_navigation_refreshes_stock_after_a_sale(self) -> None:
        self.window._navigate("inventory")
        page = self.window.pages["inventory"]
        self.assertIsInstance(page, InventoryWorkspacePage)
        row = self._row_for_sku(page)
        self.assertEqual(page.products.table.item(row, 5).text(), "5")

        self._sale(quantity=2)
        # Sin refrescar, la tabla conserva el dato anterior.
        self.assertEqual(page.products.table.item(row, 5).text(), "5")

        self.window._navigate("dashboard")
        self.window._navigate("inventory")
        refreshed = self._row_for_sku(page)
        self.assertEqual(page.products.table.item(refreshed, 5).text(), "3")

    def test_explicit_refresh_updates_stock_and_totals(self) -> None:
        self.window._navigate("inventory")
        page = self.window.pages["inventory"]
        self.inventory.adjust_stock(
            self.product["id"], 4, unit_cost_cop=1_000, reason="Entrada posterior", idempotency_key=uuid4().hex)
        page.refresh()
        row = self._row_for_sku(page)
        self.assertEqual(page.products.table.item(row, 5).text(), "9")

    def test_reverse_button_is_disabled_for_sale_movements(self) -> None:
        self._sale(quantity=1)
        self.window._navigate("inventory")
        page = self.window.pages["inventory"]
        dialog = ProductDetailDialog(self.inventory, self.product["id"], page)
        self.addCleanup(dialog.close)

        sale_row = next(
            row for row in range(dialog.table.rowCount())
            if dialog.table.item(row, 0).text() == "Salida por venta"
        )
        dialog.table.selectRow(sale_row)
        dialog._sync_reverse()
        self.assertFalse(dialog.reverse_button.isEnabled())
        self.assertIn("venta", dialog.reverse_button.toolTip())

    def test_reverse_button_stays_enabled_for_manual_adjustments(self) -> None:
        movement = self.inventory.adjust_stock(
            self.product["id"], 1, unit_cost_cop=1_000, reason="Ajuste corregible", idempotency_key=uuid4().hex)
        self.window._navigate("inventory")
        page = self.window.pages["inventory"]
        dialog = ProductDetailDialog(self.inventory, self.product["id"], page)
        self.addCleanup(dialog.close)

        adjustment_row = next(
            row for row in range(dialog.table.rowCount())
            if dialog.table.item(row, 0).text() == "Ajuste"
        )
        dialog.table.selectRow(adjustment_row)
        dialog._sync_reverse()
        self.assertTrue(dialog.reverse_button.isEnabled())
        self.assertNotIn("proviene de", dialog.reverse_button.toolTip())
        self.assertIsNotNone(movement["id"])


if __name__ == "__main__":
    unittest.main()
