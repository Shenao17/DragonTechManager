"""Regresión: al cambiar de producto, los campos derivados no conservan datos del anterior."""

import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from dragontech_manager.ui.procurement import PurchaseLineDialog
from dragontech_manager.ui.sales import SaleLineDialog
from dragontech_manager.ui.theme import apply_theme

HP = {"id": 1, "sku": "HP-INK", "nombre": "Tinta HP 664", "activo": 1,
      "precio_actual_cop": 45_000, "costo_actual_cop": 30_000}
SAMSUNG = {"id": 2, "sku": "SAM-24", "nombre": "Monitor Samsung 24", "activo": 1,
           "precio_actual_cop": 650_000, "costo_actual_cop": 500_000}
LG = {"id": 3, "sku": "LG-27", "nombre": "Monitor LG 27", "activo": 1,
      "precio_actual_cop": 900_000, "costo_actual_cop": 700_000}
PRODUCTS = [HP, SAMSUNG, LG]


def select(dialog, product):
    dialog.product.setCurrentIndex(dialog.product.findText(f"{product['sku']} · {product['nombre']}"))


class _Qt(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)


class SaleLineDialogTests(_Qt):
    def accepted(self, dialog):
        dialog._accept_line()
        return dialog.line

    def test_switching_products_replaces_description_and_price(self) -> None:
        dialog = SaleLineDialog(PRODUCTS)
        select(dialog, SAMSUNG)
        select(dialog, HP)
        self.assertEqual(dialog.description.toPlainText(), "Tinta HP 664")
        self.assertEqual(dialog.price.text(), "45000")
        self.assertEqual(self.accepted(dialog), {"description": "Tinta HP 664", "quantity": 1,
                                                  "unit_price_cop": 45_000, "product_id": 1})

    def test_several_switches_never_mix_data(self) -> None:
        dialog = SaleLineDialog(PRODUCTS)
        for product in (SAMSUNG, LG, HP, LG, SAMSUNG):
            select(dialog, product)
            line = self.accepted(dialog)
            self.assertEqual((line["product_id"], line["description"], line["unit_price_cop"]),
                             (product["id"], product["nombre"], product["precio_actual_cop"]))

    def test_clearing_selection_removes_previous_product_values(self) -> None:
        dialog = SaleLineDialog(PRODUCTS)
        select(dialog, LG)
        dialog.product.setCurrentIndex(0)  # «Concepto no inventariable»
        self.assertEqual((dialog.description.toPlainText(), dialog.price.text()), ("", ""))
        dialog._accept_line()
        self.assertIsNone(dialog.line)  # sin descripción no se guarda
        select(dialog, HP)
        self.assertEqual(self.accepted(dialog)["description"], "Tinta HP 664")

    def test_manual_edits_survive_until_the_product_changes(self) -> None:
        dialog = SaleLineDialog(PRODUCTS)
        select(dialog, SAMSUNG)
        dialog.description.setPlainText("Monitor Samsung 24 con garantía extendida")
        dialog.price.setText("700000")
        line = self.accepted(dialog)
        self.assertEqual((line["description"], line["unit_price_cop"], line["product_id"]),
                         ("Monitor Samsung 24 con garantía extendida", 700_000, 2))
        select(dialog, HP)  # lo editado pertenecía al producto anterior
        self.assertEqual((dialog.description.toPlainText(), dialog.price.text()), ("Tinta HP 664", "45000"))
        dialog.price.setText("40000")  # y lo nuevo vuelve a ser manual
        self.assertEqual(self.accepted(dialog)["unit_price_cop"], 40_000)

    def test_free_concept_keeps_manual_values(self) -> None:
        dialog = SaleLineDialog(PRODUCTS)
        dialog.description.setPlainText("Mano de obra")
        dialog.price.setText("80000")
        line = self.accepted(dialog)
        self.assertEqual((line["product_id"], line["description"], line["unit_price_cop"]), (None, "Mano de obra", 80_000))

    def test_editing_existing_line_keeps_its_snapshot_values(self) -> None:
        existing = {"product_id": 2, "description": "Descripción histórica", "quantity": 3, "unit_price_cop": 123_000}
        dialog = SaleLineDialog(PRODUCTS, line=existing)
        line = self.accepted(dialog)
        self.assertEqual((line["product_id"], line["description"], line["unit_price_cop"], line["quantity"]),
                         (2, "Descripción histórica", 123_000, 3))
        select(dialog, LG)
        self.assertEqual(self.accepted(dialog)["description"], "Monitor LG 27")

    def test_save_never_trusts_stale_widgets(self) -> None:
        dialog = SaleLineDialog(PRODUCTS)
        select(dialog, SAMSUNG)
        dialog.product.blockSignals(True)  # simula un cambio de selección sin señal
        select(dialog, LG)
        dialog.product.blockSignals(False)
        line = self.accepted(dialog)
        self.assertEqual((line["product_id"], line["description"], line["unit_price_cop"]), (3, "Monitor LG 27", 900_000))


class PurchaseLineDialogTests(_Qt):
    def accepted(self, dialog):
        dialog._accept_line()
        return dialog.line

    def test_switching_products_updates_cost_description_and_id(self) -> None:
        dialog = PurchaseLineDialog(PRODUCTS)
        for product in (LG, HP, SAMSUNG):
            select(dialog, product)
            line = self.accepted(dialog)
            self.assertEqual((line["product_id"], line["description"], line["unit_cost_cop"]),
                             (product["id"], product["nombre"], product["costo_actual_cop"]))

    def test_actual_purchase_cost_stays_editable_until_product_changes(self) -> None:
        dialog = PurchaseLineDialog(PRODUCTS)
        select(dialog, SAMSUNG)
        dialog.cost.setText("480000")
        self.assertEqual(self.accepted(dialog)["unit_cost_cop"], 480_000)
        select(dialog, LG)
        self.assertEqual(dialog.cost.text(), "700000")
        self.assertEqual(self.accepted(dialog)["unit_cost_cop"], 700_000)

    def test_editing_existing_line_preserves_historical_values(self) -> None:
        existing = {"product_id": 2, "quantity": 4, "unit_cost_cop": 455_000, "description": "Compra de abril"}
        dialog = PurchaseLineDialog(PRODUCTS, line=existing)
        line = self.accepted(dialog)
        self.assertEqual((line["product_id"], line["unit_cost_cop"], line["description"]), (2, 455_000, "Compra de abril"))

    def test_blank_description_falls_back_to_the_current_product(self) -> None:
        dialog = PurchaseLineDialog(PRODUCTS)
        select(dialog, HP)
        dialog.description.setPlainText("")
        self.assertEqual(self.accepted(dialog)["description"], "Tinta HP 664")


if __name__ == "__main__":
    unittest.main()
