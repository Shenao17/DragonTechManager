"""Entregas del día, arqueo de caja y guarda de cancelación comercial (Fase 1, pendientes bloque 2)."""

import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from dragontech_manager.business_date import business_date_from_utc
from dragontech_manager.services._common import timestamp_and_business_year
from dragontech_manager.services.cash import CashReportService
from dragontech_manager.services.errors import ValidationError
from dragontech_manager.ui.cancel_sale import CancelSaleDialog
from dragontech_manager.ui.cash import CashDialog
from dragontech_manager.ui.theme import apply_theme
from tests.test_debt_actors import auth
from tests.test_delivery_corrections import CorrectionBase

PAST = "2026-10-30T15:00:00Z"


class CashReportTests(CorrectionBase):
    def setUp(self) -> None:
        super().setUp()
        self.cash = CashReportService(self.c)
        self.today = business_date_from_utc(timestamp_and_business_year()[0])

    def test_effective_date_and_registration_date_are_reported_separately(self) -> None:
        cid = self.refund(30_000, "a", method="Efectivo", deliver=False)
        self.comp.confirm_delivery(cid, registered_by=self.a["cajero"], idempotency_key="d", occurred_at_utc=PAST)
        today = self.cash.deliveries_of_day(self.today)
        past = self.cash.deliveries_of_day("2026-10-30")
        self.assertEqual([(r["criterio"], r["importe_cop"]) for r in today["por_criterio"]], [("fecha_registro", 30_000)])
        self.assertEqual([(r["criterio"], r["importe_cop"]) for r in past["por_criterio"]], [("fecha_efectiva", 30_000)])
        self.assertEqual([e["importe_cop"] for e in past["entregas"]], [30_000])
        self.assertEqual(today["entregas"], [])  # el listado del día usa la fecha efectiva

    def test_corrections_move_the_delivery_and_released_deliveries_do_not_count(self) -> None:
        cid = self.refund(30_000, "a", method="Efectivo")
        self.assertEqual(self.cash.arqueo(self.today)["entregado_efectivo_cop"], 30_000)
        self.corr(cid, idempotency_key="c", occurred_at_utc=PAST, medium="transferencia", external_reference="TRX-9",
                  receiver="Cliente Uno")
        self.assertEqual(self.cash.arqueo(self.today)["entregado_efectivo_cop"], 0)
        past = self.cash.arqueo("2026-10-30")
        self.assertEqual((past["entregado_efectivo_cop"], past["entregado_otros_medios_cop"]), (0, 30_000))
        delivery = self.cash.deliveries_of_day("2026-10-30")["entregas"][0]
        self.assertEqual((delivery["medio"], delivery["referencia_externa"], delivery["receptor"]),
                         ("transferencia", "TRX-9", "Cliente Uno"))
        self.investigate(cid)
        self.release(cid)
        self.assertEqual(self.cash.deliveries_of_day("2026-10-30")["entregas"], [])
        self.assertEqual(self.cash.arqueo("2026-10-30")["entregado_otros_medios_cop"], 0)

    def test_arqueo_figures_pending_annulled_and_counted_difference(self) -> None:
        self.refund(20_000, "a", method="Efectivo")
        self.refund(20_000, "b", method="Efectivo", deliver=False)
        annulled = self.refund(10_000, "c", method="Efectivo", deliver=False)
        self.comp.annul(annulled, reason="Error", registered_by=self.a["cajero"], authorizer=self.a["super"],
                        authorization_ref="A", idempotency_key="an")
        self.refund(5_000, "d", method="Transferencia", deliver=False)
        report = self.cash.arqueo(self.today)
        self.assertEqual((report["entregado_efectivo_cop"], report["comprometido_efectivo_cop"],
                          report["pendiente_efectivo_cop"], report["anulado_efectivo_cop"]),
                         (20_000, 50_000, 20_000, 10_000))  # la transferencia no cuenta como efectivo
        self.assertEqual(self.cash.arqueo(self.today, counted_cash_cop=18_000)["diferencia_cop"], -2_000)
        self.assertEqual(self.cash.arqueo(self.today, counted_cash_cop=20_000)["diferencia_cop"], 0)
        self.assertEqual(self.cash.arqueo(self.today)["diferencia_cop"], None)
        empty = self.cash.arqueo("2020-01-01")
        self.assertEqual((empty["entregado_efectivo_cop"], empty["pendiente_efectivo_cop"]), (0, 0))
        for bad in ({"day": "01/11/2026"}, {"counted_cash_cop": -1}, {"counted_cash_cop": 1.5}, {"counted_cash_cop": True}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.cash.arqueo(**{"day": self.today, **bad})

    def test_dialog_shows_figures_and_computes_the_difference_without_saving(self) -> None:
        QApplication.instance() or QApplication([])
        apply_theme(QApplication.instance())
        self.refund(20_000, "a", method="Efectivo")
        dialog = CashDialog(self.cash)
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog.counted.setText("15000")
        self.assertIn("Falta", dialog.difference.text())
        dialog.counted.setText("20000")
        self.assertIn("Cuadra", dialog.difference.text())
        dialog.day.setText("mañana")
        dialog._render()
        self.assertTrue(dialog.error.text())
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE '%conteo%'").fetchone()[0], 0)


class CancellationGuardTests(CorrectionBase):
    def test_sale_not_fully_returned_is_never_closed_as_cancelled(self) -> None:  # Informe3 §1.10 #11
        sale = self.new_sale("g1", paid=100_000)
        self.return_lines(sale, "g1-r", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 2}])  # queda 1 mouse + servicio
        status = self.returns.cancellation_status(sale["id"])
        self.assertFalse(status["cerrada"])
        self.assertEqual(status["unidades_pendientes"], 2)
        self.assertTrue(any("sin devolver" in b for b in status["bloqueos"]))
        self.assertEqual(status["venta"]["estado_comercial"], "abierta")

    def test_retained_value_must_be_charged_forgiven_or_written_off_but_still_is_not_a_cancellation(self) -> None:
        sale = self.new_sale("g2")
        status = self.returns.cancellation_status(sale["id"])
        self.assertEqual(status["venta"]["importe_neto_cop"], 100_000)  # el cargo es todo lo retenido
        self.debt.forgive(sale["id"], 100_000, reason="Cortesía", idempotency_key="f", **auth(self.a, "dueno"))
        status = self.returns.cancellation_status(sale["id"])
        self.assertEqual((status["cerrada"], status["venta"]["estado_comercial"]), (False, "abierta"))  # condonar no es devolver

    def test_full_return_closes_only_after_compensation_is_delivered(self) -> None:
        sale = self.new_sale("g3", paid=100_000)
        self.return_lines(sale, "g3-r", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 3},
                                         {"sale_line_id": sale["lineas"][1]["id"], "quantity": 1}])
        status = self.returns.cancellation_status(sale["id"])
        self.assertFalse(status["cerrada"])
        self.assertTrue(any("en exceso" in b for b in status["bloqueos"]))
        cid = self.comp.commit(sale["id"], refund_cop=100_000, method="Efectivo", reason="x", executor=self.a["cajero"],
                               authorizer=self.a["super"], authorization_ref="A", idempotency_key="g3-c")["compensaciones"][0]["id"]
        self.assertTrue(any("sin entregar" in b for b in self.returns.cancellation_status(sale["id"])["bloqueos"]))
        self.comp.confirm_delivery(cid, registered_by=self.a["cajero"], idempotency_key="g3-d")
        status = self.returns.cancellation_status(sale["id"])
        self.assertEqual((status["cerrada"], status["bloqueos"], status["venta"]["estado_comercial"]),
                         (True, [], "cancelada_liquidada"))

    def test_assistant_dialog_reflects_the_status_and_runs_existing_steps(self) -> None:
        QApplication.instance() or QApplication([])
        apply_theme(QApplication.instance())
        sale = self.new_sale("g4")
        calls = []
        dialog = CancelSaleDialog(lambda: self.returns.cancellation_status(sale["id"]),
                                  {"return": lambda: calls.append("return"), "compensate": lambda: calls.append("compensate"),
                                   "debt": lambda: calls.append("debt")})
        self.assertIn("sin devolver", dialog.summary.text())
        self.assertTrue(dialog.buttons["return"].isEnabled())
        self.assertFalse(dialog.buttons["compensate"].isEnabled())
        dialog.buttons["debt"].click()
        self.assertEqual(calls, ["debt"])


if __name__ == "__main__":
    unittest.main()
