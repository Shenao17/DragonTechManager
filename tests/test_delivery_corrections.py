"""Corrección de entregas, investigación y reversión de reembolsos entregados (Fase 1, pendientes bloque 1)."""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services import operation_retry
from dragontech_manager.services.compensations import CompensationService
from dragontech_manager.services.errors import ConflictError, DataIntegrityError, ValidationError
from tests.test_debt_actors import REAL, Base, auth, make_actors
from tests.test_returns import make_world


class CorrectionBase(Base):
    def setUp(self) -> None:
        super().setUp()
        self.sale = self.new_sale("cor", paid=100_000)
        self.return_lines(self.sale, "cor-r", [{"sale_line_id": self.sale["lineas"][0]["id"], "quantity": 2}])  # D = 60.000
        self.sid = self.sale["id"]

    def refund(self, amount, key, method="Transferencia", deliver=True, ref=None):
        out = self.comp.commit(self.sid, refund_cop=amount, method=method, reason="x", executor=self.a["cajero"],
                               authorizer=self.a["super"], authorization_ref="A", idempotency_key=key)
        cid = out["compensaciones"][0]["id"]
        if deliver:
            self.comp.confirm_delivery(cid, registered_by=self.a["cajero"], idempotency_key=f"{key}-d",
                                       external_reference=ref or f"TRX-{key}")
        return cid

    def corr(self, cid, **kw):
        kw.setdefault("reason", "Dato mal digitado")
        return self.comp.correct_delivery_data(cid, registered_by=self.a["cajero"], authorizer=self.a["super"],
                                               authorization_ref="DOC-9", **kw)

    def investigate(self, cid, key="inv"):
        return self.comp.mark_under_investigation(cid, reason="El efectivo no salió", registered_by=self.a["cajero"],
                                                  idempotency_key=key)

    def release(self, cid, key="rel", **kw):
        return self.comp.report_delivery_not_occurred(
            cid, reason="No se entregó", evidence="Arqueo sin faltante y voucher sin firma", registered_by=self.a["cajero"],
            authorizer=self.a["super"], authorization_ref="DOC-10", idempotency_key=key, **kw)

    def pos(self):
        return self.comp.position(self.sid)


class DataCorrectionTests(CorrectionBase):
    def test_data_correction_changes_no_amounts_and_keeps_the_original_event(self) -> None:
        cid = self.refund(60_000, "a")
        before = self.pos()
        out = self.corr(cid, idempotency_key="c1", medium="tarjeta", external_reference="POS-77",
                        occurred_at_utc="2026-10-30T15:00:00Z", receiver="Cliente Uno")
        self.assertEqual(out["compensacion"]["estado"], "corregida")
        after = self.pos()
        self.assertEqual((after["c_comprometido"], after["c_entregado"], after["n0"], after["d"]),
                         (before["c_comprometido"], before["c_entregado"], before["n0"], before["d"]))
        events = self.comp.list_for_sale(self.sid)[0]["eventos"]
        self.assertEqual([e["tipo"] for e in events], ["entregada", "corregida"])
        self.assertEqual((events[0]["medio"], events[0]["referencia_externa"]), ("transferencia", "TRX-a"))  # intacto
        self.assertEqual((events[1]["correccion_tipo"], events[1]["medio"], events[1]["receptor"],
                          events[1]["autorizador"]), ("datos", "tarjeta", "Cliente Uno", "Sergio Supervisor"))
        self.assertTrue(self.corr(cid, idempotency_key="c1", medium="tarjeta", external_reference="POS-77",
                                  occurred_at_utc="2026-10-30T15:00:00Z", receiver="Cliente Uno")["repetido"])

    def test_validations(self) -> None:
        cid = self.refund(30_000, "a")
        other = self.refund(30_000, "b")
        with self.assertRaisesRegex(ValidationError, "al menos un dato"):
            self.corr(cid, idempotency_key="k1")
        with self.assertRaises(ValidationError):
            self.corr(cid, idempotency_key="k2", medium="cheque")
        with self.assertRaises(ValidationError):
            self.corr(cid, idempotency_key="k3", occurred_at_utc="ayer")
        with self.assertRaises(DataIntegrityError):  # fecha futura
            self.corr(cid, idempotency_key="k4", occurred_at_utc="2999-01-01T00:00:00Z")
        with self.assertRaises(DataIntegrityError):  # la referencia respalda otra entrega
            self.corr(other, idempotency_key="k5", external_reference="TRX-a")
        with self.assertRaisesRegex(ValidationError, "distinto"):
            self.comp.correct_delivery_data(cid, reason="x", registered_by=self.a["super"], authorizer=self.a["super"],
                                            authorization_ref="D", idempotency_key="k6", receiver="X")
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM eventos_compensacion WHERE tipo = 'corregida'").fetchone()[0], 0)


class InvestigationAndReleaseTests(CorrectionBase):
    def test_investigating_a_registered_delivery_blocks_new_refunds_without_changing_balances(self) -> None:
        cid = self.refund(30_000, "a")
        before = self.pos()
        out = self.investigate(cid)
        self.assertEqual((out["compensacion"]["estado"], out["compensacion"]["en_investigacion"]), ("entregada", 1))
        self.assertEqual((self.pos()["c_entregado"], self.pos()["n0"]), (before["c_entregado"], before["n0"]))
        self.assertEqual([r["compensacion_id"] for r in self.c.execute("SELECT * FROM v_investigaciones_compensacion")], [cid])
        self.assertEqual([p["compensacion_id"] for p in self.comp.pending_deliveries()], [cid])
        with self.assertRaises(ConflictError):
            self.investigate(cid, key="again")
        with self.assertRaises(DataIntegrityError):  # regla de oro
            self.refund(10_000, "b")

    def test_release_requires_an_open_investigation_and_evidence(self) -> None:
        cid = self.refund(30_000, "a")
        with self.assertRaisesRegex(ConflictError, "investigación"):
            self.release(cid)
        self.investigate(cid)
        with self.assertRaises(ValidationError):
            self.comp.report_delivery_not_occurred(cid, reason="x", evidence=" ", registered_by=self.a["cajero"],
                                                   authorizer=self.a["super"], authorization_ref="D", idempotency_key="e0")
        with self.assertRaisesRegex(ValidationError, "distinto"):
            self.comp.report_delivery_not_occurred(cid, reason="x", evidence="E", registered_by=self.a["super"],
                                                   authorizer=self.a["super"], authorization_ref="D", idempotency_key="e1")
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM eventos_compensacion WHERE tipo = 'corregida'").fetchone()[0], 0)

    def test_release_frees_the_commitment_reopens_the_overpayment_and_keeps_history(self) -> None:
        cid = self.refund(60_000, "a")
        self.assertEqual((self.pos()["c_comprometido"], self.pos()["c_entregado"]), (60_000, 60_000))
        self.investigate(cid)
        out = self.release(cid)
        self.assertEqual((out["compensacion"]["estado"], out["compensacion"]["liberada"]), ("anulada", 1))
        sale = out["venta"]
        self.assertEqual((sale["reembolsos_comprometidos_cop"], sale["reembolsos_entregados_cop"],
                          sale["sobrepago_pendiente_cop"], sale["pagado_neto_cop"]), (0, 0, 60_000, 100_000))
        events = [e["tipo"] for e in self.comp.list_for_sale(self.sid)[0]["eventos"]]
        self.assertEqual(events, ["entregada", "en_investigacion", "corregida"])  # la entrega original sigue
        self.assertTrue(self.release(cid)["repetido"])
        with self.assertRaises(Exception):  # no se libera dos veces ni se entrega otra vez
            self.release(cid, key="rel2")
        with self.assertRaises(ConflictError):
            self.comp.confirm_delivery(cid, registered_by=self.a["cajero"], idempotency_key="again", external_reference="TRX-z")
        self.refund(60_000, "b", ref="TRX-nuevo")  # se compensa con un compromiso nuevo
        self.assertEqual(self.pos()["c_entregado"], 60_000)

    def test_r13c_release_is_rejected_when_it_would_leave_forgiveness_above_the_debt(self) -> None:
        cid = self.refund(60_000, "a")
        pay = self.sales.get_sale(self.sid)["pagos"][0]["id"]
        self.sales.reverse_payment(pay, reason="Contracargo", **REAL)          # P = 0: N0 = 100.000
        ext = self.debt.forgive(self.sid, 100_000, reason="Incobrable", idempotency_key="f", **auth(self.a, "dueno"))["extincion"]
        self.investigate(cid)
        before = self.c.execute("SELECT COUNT(*) FROM eventos_compensacion WHERE tipo = 'corregida'").fetchone()[0]
        with self.assertRaisesRegex(DataIntegrityError, "condonaciones"):
            self.release(cid)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM eventos_compensacion WHERE tipo = 'corregida'").fetchone()[0], before)
        self.assertEqual(self.pos()["c_entregado"], 60_000)  # nada cambió
        self.debt.annul_extinction(ext["id"], 60_000, reason="Ajuste previo", idempotency_key="an", **auth(self.a, "dueno"))
        self.release(cid, key="rel-ok")                                       # ahora cabe: Q = 40.000 = N0 nuevo
        self.assertEqual(self.pos()["q"], 40_000)
        self.assertEqual(self.liq(self.sale)["deuda_pendiente_cop"], 0)

    def test_failed_release_is_atomic_and_retryable_after_restart(self) -> None:
        from dragontech_manager.services.operations import OperationRegistry
        cid = self.refund(30_000, "a")
        self.investigate(cid)
        self.c.execute("""CREATE TRIGGER falla_prueba BEFORE INSERT ON eventos_compensacion WHEN NEW.tipo = 'corregida'
                          BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END""")
        with self.assertRaises(DataIntegrityError):
            self.release(cid, key="rel-x")
        self.assertEqual(self.pos()["c_entregado"], 30_000)
        self.assertEqual([r["clave_idempotencia"] for r in OperationRegistry(self.c).pending()], ["rel-x"])
        self.c.execute("DROP TRIGGER falla_prueba")
        operation_retry.retry(self.c, "rel-x")
        self.assertEqual(self.pos()["c_entregado"], 0)
        self.assertEqual(OperationRegistry(self.c).pending(), [])

    def test_events_stay_immutable_and_credits_have_no_delivery_events(self) -> None:
        self.refund(30_000, "a")
        for sql in ("UPDATE eventos_compensacion SET motivo = 'x'", "DELETE FROM eventos_compensacion"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.c.execute(sql)
        credit = self.comp.commit(self.sid, credit_cop=10_000, customer_consent=True, reason="x", executor=self.a["cajero"],
                                  authorizer=self.a["super"], authorization_ref="A", idempotency_key="cr")["compensaciones"][0]
        with self.assertRaises(ConflictError):
            self.investigate(credit["id"], key="inv-credit")


class CorrectionConcurrencyTests(unittest.TestCase):
    def test_parallel_release_happens_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "db.sqlite3")
            setup = open_database(path)
            migrate(setup)
            inventory, sales, customer, mouse = make_world(setup)
            a = make_actors(setup)
            from dragontech_manager.services.returns import ReturnsService
            sale = sales.create_sale(customer["id"], [{"description": "S", "quantity": 2, "unit_price_cop": 50_000}], idempotency_key="s")
            sales.register_payment(sale["id"], 100_000, method="Efectivo", idempotency_key="p")
            ReturnsService(setup).register_return(sale["id"], [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 1}], reason="x",
                                                  requester="C", requester_type="cliente", executor=a["cajero"], idempotency_key="r")
            comp = CompensationService(setup)
            cid = comp.commit(sale["id"], refund_cop=50_000, method="Efectivo", reason="x", executor=a["cajero"], authorizer=a["super"],
                              authorization_ref="A", idempotency_key="c")["compensaciones"][0]["id"]
            comp.confirm_delivery(cid, registered_by=a["cajero"], idempotency_key="d")
            comp.mark_under_investigation(cid, reason="duda", registered_by=a["cajero"], idempotency_key="i")
            setup.close()
            results, barrier = [], threading.Barrier(5)

            def worker(index):
                connection = open_database(path)
                barrier.wait()
                try:
                    results.append(CompensationService(connection).report_delivery_not_occurred(
                        cid, reason="No salió", evidence="Arqueo", registered_by=a["cajero"], authorizer=a["super"],
                        authorization_ref="D", idempotency_key="rel" if index < 3 else f"rel-{index}"))
                except Exception as error:  # noqa: BLE001
                    results.append(error)
                finally:
                    connection.close()
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
            for t in threads: t.start()
            for t in threads: t.join()
            check = open_database(path)
            self.addCleanup(check.close)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM eventos_compensacion WHERE tipo = 'corregida'").fetchone()[0], 1)
            ok = [r for r in results if isinstance(r, dict)]
            # Gana un solo hilo. Si gana uno del grupo con la misma clave, sus dos hermanos reciben el original (3 éxitos);
            # si gana uno de clave propia, los demás fallan por la liberación ya hecha (1 éxito).
            self.assertEqual(sum(1 for r in ok if not r["repetido"]), 1)
            self.assertIn(len(ok), (1, 3))
            self.assertEqual(len({r["evento"]["id"] for r in ok}), 1)


if __name__ == "__main__":
    unittest.main()
