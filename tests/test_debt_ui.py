"""Humo de la UI del directorio de actores y de la deuda de una venta."""

import os
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.actors import ActorService
from dragontech_manager.services.debt import DebtService
from dragontech_manager.services.returns import ReturnsService
from dragontech_manager.ui.actors import ActorEditDialog, ActorsDialog
from dragontech_manager.ui.compensations import FormDialog
from dragontech_manager.ui.debt import DebtDialog
from dragontech_manager.ui.sales import SaleDetailsDialog
from dragontech_manager.ui.theme import apply_theme
from tests.test_returns import make_world


class DebtUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.c = open_database(":memory:")
        self.addCleanup(self.c.close)
        migrate(self.c)
        _inv, self.sales, customer, mouse = make_world(self.c)
        self.sale = self.sales.create_sale(customer["id"], [
            {"description": "Servicio", "quantity": 1, "unit_price_cop": 100_000}], idempotency_key="ui-debt")

    def test_actor_directory_dialog_creates_and_toggles(self) -> None:
        service = ActorService(self.c)
        dialog = ActorsDialog(service)
        values = {"name": "Olga", "role": "propietario", "document": None, "can_authorize": True,
                  "limit_cop": 1_000_000, "notes": "", "active": True}
        with patch.object(ActorEditDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
                patch.object(ActorEditDialog, "values", return_value=values):
            dialog._new()
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog.table.selectRow(0)
        dialog._toggle()
        self.assertEqual(service.list_actors(), [])  # inactivo: no aparece en selectores
        self.assertEqual(len(service.list_actors(active_only=False)), 1)

    def test_operations_ask_for_the_directory_when_empty(self) -> None:
        details = SaleDetailsDialog(self.sales, self.sale["id"])
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as asked:
            self.assertIsNone(details._actor_lists())
        asked.assert_called_once()

    def test_debt_dialog_forgives_and_shows_history(self) -> None:
        actors = ActorService(self.c)
        cashier = actors.create_actor("Ana", "cajero")["id"]
        boss = actors.create_actor("Olga", "propietario", can_authorize=True, limit_cop=10_000_000)["id"]
        service = DebtService(self.c)
        dialog = DebtDialog(service, self.sale["id"], service.methods.list_methods("cliente"))
        self.assertTrue(dialog.buttons["forgive"].isEnabled())
        form = {"amount": "40000", "reason": "Cortesía", "executor": cashier, "authorizer": boss,
                "ref": "DOC-1", "medium": "documento_firmado"}
        with patch.object(FormDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
                patch.object(FormDialog, "values", return_value=form):
            dialog._extinguish("condonacion")
        self.assertTrue(dialog.changed)
        self.assertEqual(service.liquidation(self.sale["id"])["deuda_pendiente_cop"], 60_000)
        self.assertEqual(dialog.extinctions.rowCount(), 1)
        self.assertGreaterEqual(dialog.history.rowCount(), 2)  # venta + condonación
        dialog.extinctions.selectRow(0)
        annul = dict(form, amount="40000")
        with patch.object(FormDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
                patch.object(FormDialog, "values", return_value=annul):
            dialog._annul()
        self.assertEqual(service.liquidation(self.sale["id"])["deuda_pendiente_cop"], 100_000)

        details = SaleDetailsDialog(self.sales, self.sale["id"])
        self.assertTrue(details.debt_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
