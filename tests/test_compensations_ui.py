"""Humo de la UI de compensaciones, entrega de reembolsos y saldo a favor."""

import os
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.sales import SalesService
from dragontech_manager.ui.compensations import CompensationsDialog, FormDialog
from dragontech_manager.ui.sales import SaleDetailsDialog
from dragontech_manager.ui.theme import apply_theme
from tests.test_compensations import build_world


def fill(values):
    return patch.object(FormDialog, "values", return_value=values)


class CompensationsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.c = open_database(":memory:")
        self.addCleanup(self.c.close)
        migrate(self.c)
        self.sales, self.customer, self.sale = build_world(self.c)

    def test_compensate_deliver_and_apply_credit_flow(self) -> None:
        details = SaleDetailsDialog(self.sales, self.sale["id"])
        self.assertTrue(details.compensate_button.isEnabled())
        accept = patch.object(FormDialog, "exec", return_value=QDialog.DialogCode.Accepted)
        yes = patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes)
        mixed = {"refund": "20000", "credit": "40000", "method": 1, "consent": True, "reason": "Devolución",
                 "executor": "Ana", "authorizer": "Supervisor", "authorization_ref": "AUT-1"}
        with accept, yes, fill(mixed):
            details._compensate()
        self.assertEqual((details.sale["reembolso_por_entregar_cop"], details.sale["credito_generado_cop"],
                          details.sale["sobrepago_pendiente_cop"]), (20_000, 40_000, 0))
        self.assertFalse(details.compensate_button.isEnabled())

        panel = CompensationsDialog(details.compensation_service, self.sale["id"])
        refund_row = next(i for i, item in enumerate(panel.items) if item["tipo"] == "reembolso")
        panel.table.selectRow(refund_row)
        self.assertTrue(panel.buttons["prepare"].isEnabled())
        with accept, fill({"by": "Caja"}):
            panel._prepare()
        panel.table.selectRow(refund_row)
        with accept, fill({"medium": "efectivo", "reference": "", "by": "Caja"}):
            panel._deliver()
        self.assertEqual(panel.items[refund_row]["estado"], "entregada")
        self.assertTrue(panel.changed)

        nxt = SalesService(self.c).create_sale(self.customer["id"], [
            {"description": "Cable", "quantity": 1, "unit_price_cop": 30_000}], idempotency_key="ui-next")
        other = SaleDetailsDialog(self.sales, nxt["id"])
        with accept, fill({"amount": "30000", "reason": "Crédito", "by": "Ana"}):
            other._apply_credit()
        self.assertEqual((other.sale["saldo_favor_aplicado_cop"], other.sale["estado_cobro"]), (30_000, "completada"))


if __name__ == "__main__":
    unittest.main()
