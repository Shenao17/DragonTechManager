"""Humo de la UI: panel de pendientes, correcciones de entrega y su indicador en la ventana."""

import os
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from dragontech_manager.app import create_main_window
from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.operations import OperationRegistry
from dragontech_manager.ui.compensations import CompensationsDialog, FormDialog
from dragontech_manager.ui.pending import PendingOperationsDialog, pending_count
from dragontech_manager.ui.theme import apply_theme
from tests.test_delivery_corrections import CorrectionBase


class PendingUiTests(CorrectionBase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_panel_lists_pending_deliveries_and_retries_or_abandons_requests(self) -> None:
        cid = self.refund(30_000, "a", deliver=False)
        self.c.execute("""CREATE TRIGGER falla_prueba BEFORE INSERT ON pagos_clientes BEGIN SELECT RAISE(ABORT, 'fallo'); END""")
        sale = self.new_sale("pend")
        for key in ("x1", "x2"):
            with self.assertRaises(Exception):
                self.sales.register_payment(sale["id"], 5_000 if key == "x1" else 6_000, method="Efectivo", idempotency_key=key)
        self.c.execute("DROP TRIGGER falla_prueba")
        self.assertEqual(pending_count(self.c), 3)
        dialog = PendingOperationsDialog(self.c)
        self.assertEqual((dialog.deliveries.rowCount(), dialog.requests.rowCount()), (1, 2))
        self.assertEqual(dialog.delivery_items[0]["compensacion_id"], cid)
        keys = [r["clave_idempotencia"] for r in dialog.request_items]
        with patch.object(QMessageBox, "information"):
            dialog.requests.selectRow(keys.index("x1"))
            dialog._retry()
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM pagos_clientes WHERE clave_idempotencia = 'x1'").fetchone()[0], 1)
        dialog.requests.selectRow(0)
        with patch.object(QInputDialog, "getText", return_value=("El cliente se fue", True)):
            dialog._abandon()
        self.assertEqual(OperationRegistry(self.c).pending(), [])
        self.assertEqual(pending_count(self.c), 1)  # solo queda la entrega: nunca se auto-anula

    def test_correction_and_release_dialogs_drive_the_services(self) -> None:
        self.refund(30_000, "a")
        panel = CompensationsDialog(self.comp, self.sid)
        panel.table.selectRow(0)
        self.assertTrue(panel.buttons["correct"].isEnabled())
        self.assertFalse(panel.buttons["not_occurred"].isEnabled())  # primero hay que investigar
        accept = patch.object(FormDialog, "exec", return_value=QDialog.DialogCode.Accepted)
        common = {"by": self.a["cajero"], "authorizer": self.a["super"], "ref": "DOC-1"}
        with accept, patch.object(FormDialog, "values", return_value={
                "medium": "", "reference": "TRX-nuevo", "occurred": "", "receiver": "Cliente", "reason": "Dato", **common}):
            panel._correct()
        panel.table.selectRow(0)
        with accept, patch.object(FormDialog, "values", return_value={"reason": "Duda", "by": self.a["cajero"]}):
            panel._investigate()
        panel.table.selectRow(0)
        self.assertTrue(panel.buttons["not_occurred"].isEnabled())
        self.assertFalse(panel.buttons["annul"].isEnabled())
        with accept, patch.object(FormDialog, "values", return_value={"reason": "No salió", "evidence": "Arqueo", **common}):
            panel._not_occurred()
        self.assertEqual(panel.items[0]["estado"], "anulada")
        self.assertIn("entrega no ocurrió", panel.table.item(0, 3).text())
        self.assertEqual(self.comp.position(self.sid)["c_entregado"], 0)

    def test_main_window_shows_the_pending_indicator_but_does_not_open_dialogs_by_itself(self) -> None:
        window = create_main_window(self.c, database_path=":memory:", schema_version=16)
        self.assertEqual(window.pending_button.text(), "Pendientes")
        self.refund(10_000, "z", deliver=False)
        with patch.object(PendingOperationsDialog, "exec", return_value=QDialog.DialogCode.Accepted) as opened:
            window.show_pending_operations_on_start()
        opened.assert_called_once()
        self.assertEqual(window.pending_button.text(), "Pendientes (1)")


if __name__ == "__main__":
    unittest.main()
