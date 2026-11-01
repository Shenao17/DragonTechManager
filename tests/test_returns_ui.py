"""Humo de la UI de devoluciones y reversión clasificada de pagos."""

import os
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.returns import ReturnsService
from dragontech_manager.services.sales import SalesService
from dragontech_manager.ui.returns import PaymentReversalDialog, ReturnDialog
from dragontech_manager.ui.sales import SaleDetailsDialog
from dragontech_manager.ui.theme import apply_theme
from tests.test_returns import make_world


class ReturnsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.c = open_database(":memory:")
        self.addCleanup(self.c.close)
        migrate(self.c)
        inventory, self.sales, customer, mouse = make_world(self.c)
        self.sale = self.sales.create_sale(customer["id"], [
            {"description": "Mouse", "quantity": 2, "unit_price_cop": 30_000, "product_id": mouse["id"]}],
            idempotency_key="ui-sale")

    def test_return_dialog_payload_and_details_flow(self) -> None:
        lines = ReturnsService(self.c).returnable_lines(self.sale["id"])
        dialog = ReturnDialog(self.sale, lines)
        with self.assertRaises(ValueError):
            dialog.lines_payload()  # nada que devolver
        dialog.devolver[0].setValue(1)
        self.assertEqual(dialog.reintegrar[0].value(), 1)  # sigue lo devuelto
        dialog.reason.setText("Desiste"); dialog.requester.setText("Cliente"); dialog.executor.setText("Ana")
        values = dialog.values()
        self.assertEqual(values["lines"][0]["quantity"], 1)

        details = SaleDetailsDialog(self.sales, self.sale["id"])
        with patch.object(ReturnDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
                patch.object(ReturnDialog, "values", return_value=values), \
                patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            details._return()
        self.assertTrue(details.changed)
        self.assertEqual(self.sales.get_sale(self.sale["id"])["unidades_devueltas"], 1)
        self.assertEqual(details.sale["estado_devolucion"], "parcial")

    def test_payment_reversal_dialog_requires_motive_and_evidence(self) -> None:
        dialog = PaymentReversalDialog()
        dialog._validate()
        self.assertTrue(dialog.error.text())
        dialog.reason.setText("Duplicado"); dialog.evidence.setText("Extracto")
        self.assertEqual(dialog.values()["nature"], "correccion_registro_erroneo")


if __name__ == "__main__":
    unittest.main()
