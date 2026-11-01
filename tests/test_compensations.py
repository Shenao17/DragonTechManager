"""Saldo a favor y compensaciones de devoluciones (Fase 1, Entrega 5)."""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.compensations import CompensationService
from dragontech_manager.services.credit import CreditService
from dragontech_manager.services.errors import ConflictError, DataIntegrityError, ValidationError
from dragontech_manager.services.returns import ReturnsService
from dragontech_manager.services.sales import SalesService
from tests.test_returns import WHO, make_world

AUTH = dict(executor="Ana", authorizer="Supervisor", authorization_ref="AUT-1")


def build_world(connection):
    """Venta de 100.000 pagada y con 2 de 3 ratones devueltos (R = 60.000, D = 60.000)."""
    inventory, sales, customer, mouse = make_world(connection)
    sale = sales.create_sale(customer["id"], [
        {"description": "Mouse", "quantity": 3, "unit_price_cop": 30_000, "product_id": mouse["id"]},
        {"description": "Configuración", "quantity": 1, "unit_price_cop": 10_000}], idempotency_key="comp-sale")
    sales.register_payment(sale["id"], 100_000, method="Efectivo", idempotency_key="comp-pay")
    ReturnsService(connection).register_return(
        sale["id"], [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 2}], reason="Desiste",
        idempotency_key="comp-ret", **WHO)
    return sales, customer, sale


class CompensationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.c = open_database(":memory:")
        self.addCleanup(self.c.close)
        migrate(self.c)
        self.sales, self.customer, self.sale = build_world(self.c)
        self.comp = CompensationService(self.c)
        self.credit = CreditService(self.c)
        self.sid = self.sale["id"]

    def commit(self, key="k", **kw):
        kw.setdefault("reason", "Devolución")
        kw.setdefault("method", "Efectivo")
        return self.comp.commit(self.sid, idempotency_key=key, **{**AUTH, **kw})

    def view(self):
        return self.sales.get_sale(self.sid)

    # --- reembolso ---
    def test_full_refund_lifecycle_preserves_history(self) -> None:
        out = self.commit(refund_cop=60_000)
        comp = out["compensaciones"][0]
        self.assertEqual((comp["estado"], out["venta"]["estado_cobro"], out["venta"]["sobrepago_pendiente_cop"],
                          out["venta"]["reembolso_por_entregar_cop"]), ("comprometida", "reembolso_pendiente", 0, 60_000))
        prepared = self.comp.prepare(comp["id"], registered_by="Caja", idempotency_key="prep")
        self.assertEqual(prepared["compensacion"]["estado"], "preparada")
        voucher = prepared["evento"]["voucher_codigo"]
        again = self.comp.prepare(comp["id"], registered_by="Caja", idempotency_key="prep")
        self.assertTrue(again["repetido"])
        done = self.comp.confirm_delivery(comp["id"], registered_by="Caja", idempotency_key="deliv", external_reference="")
        self.assertEqual((done["evento"]["voucher_codigo"], done["compensacion"]["estado"]), (voucher, "entregada"))
        sale = done["venta"]
        self.assertEqual((sale["reembolsos_entregados_cop"], sale["reembolso_por_entregar_cop"], sale["estado_cobro"]),
                         (60_000, 0, "completada"))
        self.assertEqual([e["tipo"] for e in self.comp.list_for_sale(self.sid)[0]["eventos"]], ["preparada", "entregada"])
        self.assertEqual(len(sale["pagos"]), 1)  # el pago original no se toca
        self.assertEqual(self.credit.balance(self.customer["id"])["saldo_disponible_cop"], 0)

    def test_partial_refunds_one_delivery_at_a_time(self) -> None:
        first = self.commit("a", refund_cop=25_000)["compensaciones"][0]
        self.comp.prepare(first["id"], registered_by="Caja", idempotency_key="p1")
        with self.assertRaises(DataIntegrityError):  # regla de oro: entrega preparada en curso
            self.commit("b", refund_cop=35_000)
        self.comp.confirm_delivery(first["id"], registered_by="Caja", idempotency_key="d1")
        second = self.commit("b", refund_cop=35_000)["compensaciones"][0]
        self.assertEqual(self.view()["sobrepago_pendiente_cop"], 0)
        with self.assertRaises(ValidationError):  # tope agotado
            self.commit("c", refund_cop=1)
        self.comp.confirm_delivery(second["id"], registered_by="Caja", idempotency_key="d2")

    def test_limits_r2_r3_and_authorization(self) -> None:
        with self.assertRaises(ValidationError):
            self.commit("x1", refund_cop=60_001)
        with self.assertRaises(ValidationError):
            self.commit("x2", refund_cop=0, credit_cop=0)
        with self.assertRaises(ValidationError):  # autorizador = ejecutor
            self.commit("x3", refund_cop=1_000, authorizer="ana")
        with self.assertRaises(ValidationError):  # medio no válido
            self.commit("x4", refund_cop=1_000, method="Otro")
        with self.assertRaises(sqlite3.IntegrityError):  # R3 en base de datos (reembolso > P)
            self.c.execute("""INSERT INTO compensaciones_cancelacion (venta_id, tipo, importe_cop, metodo_pago_id, motivo,
                responsable_ejecucion, autorizador, autorizado_en_utc, referencia_autorizacion, fecha_negocio,
                registrado_en_utc, clave_idempotencia, huella_solicitud)
                VALUES (?, 'reembolso', 60001, 1, 'x', 'a', 'b', '2026-10-31T12:00:00Z', 'r', '2026-10-31',
                '2026-10-31T12:00:00Z', 'raw', ?)""", (self.sid, "0" * 64))

    def test_no_compensation_without_overpayment(self) -> None:  # escenario H: el cliente aún debe
        sales, customer = self.sales, self.customer
        other = sales.create_sale(customer["id"], [{"description": "Servicio", "quantity": 2, "unit_price_cop": 50_000}],
                                  idempotency_key="other")
        sales.register_payment(other["id"], 20_000, method="Efectivo", idempotency_key="o-pay")
        ReturnsService(self.c).register_return(other["id"], [{"sale_line_id": other["lineas"][0]["id"], "quantity": 1}],
                                               reason="x", idempotency_key="o-ret", **WHO)
        with self.assertRaises(ValidationError):
            self.comp.commit(other["id"], refund_cop=1, method="Efectivo", reason="x", idempotency_key="o-c", **AUTH)

    def test_delivery_is_single_and_idempotent(self) -> None:
        comp = self.commit(refund_cop=10_000)["compensaciones"][0]
        first = self.comp.confirm_delivery(comp["id"], registered_by="Caja", idempotency_key="d1")
        self.assertTrue(self.comp.confirm_delivery(comp["id"], registered_by="Caja", idempotency_key="d1")["repetido"])
        with self.assertRaises(ConflictError):  # misma clave, otro contenido
            self.comp.confirm_delivery(comp["id"], registered_by="Otro", idempotency_key="d1")
        with self.assertRaises(Exception):  # segunda entrega con otra clave
            self.comp.confirm_delivery(comp["id"], registered_by="Caja", idempotency_key="d2")
        self.assertEqual(len([e for e in self.comp.list_for_sale(self.sid)[0]["eventos"] if e["tipo"] == "entregada"]), 1)
        self.assertEqual(first["evento"]["importe_cop"], 10_000)

    def test_annul_releases_cap_but_never_after_delivery(self) -> None:
        comp = self.commit("a", refund_cop=60_000)["compensaciones"][0]
        with self.assertRaises(ValidationError):  # autorizador = quien registra
            self.comp.annul(comp["id"], reason="Error", registered_by="Caja", authorizer="caja",
                            authorization_ref="A", idempotency_key="an0")
        out = self.comp.annul(comp["id"], reason="Error de importe", registered_by="Caja",
                              authorizer="Supervisor", authorization_ref="A-9", idempotency_key="an1")
        self.assertEqual((out["compensacion"]["estado"], out["venta"]["sobrepago_pendiente_cop"]), ("anulada", 60_000))
        new = self.commit("b", refund_cop=60_000)["compensaciones"][0]
        self.comp.confirm_delivery(new["id"], registered_by="Caja", idempotency_key="d")
        with self.assertRaises(ConflictError):
            self.comp.annul(new["id"], reason="Tarde", registered_by="Caja", authorizer="Supervisor",
                            authorization_ref="A", idempotency_key="an2")

    def test_investigation_blocks_new_refunds_until_resolved(self) -> None:
        comp = self.commit("a", refund_cop=20_000)["compensaciones"][0]
        with self.assertRaises(ConflictError):  # solo se investiga lo preparado
            self.comp.mark_under_investigation(comp["id"], reason="Duda", registered_by="Caja", idempotency_key="i0")
        self.comp.prepare(comp["id"], registered_by="Caja", idempotency_key="p")
        self.comp.mark_under_investigation(comp["id"], reason="Efectivo faltante", registered_by="Caja", idempotency_key="i1")
        self.assertEqual(self.comp.pending_deliveries()[0]["estado"], "en_investigacion")
        with self.assertRaises(DataIntegrityError):
            self.commit("b", refund_cop=10_000)
        self.comp.confirm_delivery(comp["id"], registered_by="Caja", idempotency_key="d")  # se resuelve confirmando
        self.assertEqual(self.comp.pending_deliveries(), [])

    def test_external_reference_cannot_be_reused(self) -> None:
        a = self.commit("a", refund_cop=10_000, method="Transferencia")["compensaciones"][0]
        with self.assertRaises(DataIntegrityError):  # transferencia sin referencia
            self.comp.confirm_delivery(a["id"], registered_by="Caja", idempotency_key="d0")
        self.comp.confirm_delivery(a["id"], registered_by="Caja", idempotency_key="d1", external_reference="TRX-1")
        b = self.commit("b", refund_cop=10_000, method="Transferencia")["compensaciones"][0]
        with self.assertRaises(Exception):
            self.comp.confirm_delivery(b["id"], registered_by="Caja", idempotency_key="d2", external_reference="TRX-1")
        self.assertEqual(self.comp.list_for_sale(self.sid)[1]["estado"], "comprometida")

    # --- crédito y mixtas ---
    def test_credit_generation_balance_and_consent(self) -> None:
        with self.assertRaises(ValidationError):
            self.commit("c0", credit_cop=60_000)  # sin consentimiento: crédito sustituye efectivo
        out = self.commit("c1", credit_cop=60_000, customer_consent=True)
        self.assertEqual((out["venta"]["credito_generado_cop"], out["venta"]["sobrepago_pendiente_cop"]), (60_000, 0))
        balance = self.credit.balance(self.customer["id"])
        self.assertEqual((balance["generado_cop"], balance["utilizado_cop"], balance["saldo_disponible_cop"]), (60_000, 0, 60_000))
        ledger = self.credit.movements(self.customer["id"])
        self.assertEqual((len(ledger), ledger[0]["tipo"], ledger[0]["origen_tipo"]), (1, "generacion", "compensacion_venta"))
        self.assertTrue(self.commit("c1", credit_cop=60_000, customer_consent=True)["repetido"])
        self.assertEqual(len(self.credit.movements(self.customer["id"])), 1)  # nace una sola vez

    def test_mixed_compensation_is_atomic_and_idempotent(self) -> None:
        out = self.commit("m", refund_cop=20_000, credit_cop=40_000, customer_consent=True)
        self.assertEqual([c["tipo"] for c in out["compensaciones"]], ["reembolso", "credito"])
        self.assertEqual((out["venta"]["sobrepago_pendiente_cop"], self.credit.balance(self.customer["id"])["saldo_disponible_cop"]), (0, 40_000))
        replay = self.commit("m", refund_cop=20_000, credit_cop=40_000, customer_consent=True)
        self.assertTrue(replay["repetido"])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM compensaciones_cancelacion").fetchone()[0], 2)
        with self.assertRaises(ConflictError):
            self.commit("m", refund_cop=30_000, credit_cop=30_000, customer_consent=True)
        # escenario B/K: nunca más que D en conjunto
        with self.assertRaises(ValidationError):
            self.commit("m2", refund_cop=1, credit_cop=1, customer_consent=True)

    def test_mixed_failure_midway_leaves_nothing(self) -> None:
        self.c.execute("""CREATE TRIGGER falla_credito BEFORE INSERT ON movimientos_saldo_favor
                          BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END""")
        with self.assertRaises(Exception):
            self.commit("f", refund_cop=20_000, credit_cop=40_000, customer_consent=True)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM compensaciones_cancelacion").fetchone()[0], 0)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM movimientos_saldo_favor").fetchone()[0], 0)
        self.assertFalse(self.c.in_transaction)

    def test_apply_credit_to_future_sale_until_exhausted(self) -> None:
        self.commit("c", credit_cop=60_000, customer_consent=True)
        nxt = self.sales.create_sale(self.customer["id"], [{"description": "Cable", "quantity": 1, "unit_price_cop": 45_000}],
                                     idempotency_key="next")
        with self.assertRaises(ValidationError):  # más que el saldo pendiente de la venta
            self.credit.apply_to_sale(nxt["id"], 45_001, reason="x", registered_by="Ana", idempotency_key="u0")
        first = self.credit.apply_to_sale(nxt["id"], 40_000, reason="Anticipo", registered_by="Ana", idempotency_key="u1")
        self.assertEqual((first["saldo"]["saldo_disponible_cop"], first["venta"]["saldo_favor_aplicado_cop"],
                          first["venta"]["saldo_pendiente_cop"]), (20_000, 40_000, 5_000))
        self.assertTrue(self.credit.apply_to_sale(nxt["id"], 40_000, reason="Anticipo", registered_by="Ana",
                                                  idempotency_key="u1")["repetido"])  # doble clic
        with self.assertRaises(ConflictError):
            self.credit.apply_to_sale(nxt["id"], 41_000, reason="Anticipo", registered_by="Ana", idempotency_key="u1")
        self.assertEqual(self.credit.balance(self.customer["id"])["saldo_disponible_cop"], 20_000)
        last = self.credit.apply_to_sale(nxt["id"], 5_000, reason="Resto", registered_by="Ana", idempotency_key="u2")
        self.assertEqual((last["venta"]["estado_cobro"], last["saldo"]["saldo_disponible_cop"]), ("completada", 15_000))
        with self.assertRaises(ValidationError):  # venta ya cubierta
            self.credit.apply_to_sale(nxt["id"], 1, reason="x", registered_by="Ana", idempotency_key="u3")
        with self.assertRaises(ValidationError):  # R4: ya no admite pagos
            self.sales.register_payment(nxt["id"], 1, method="Efectivo", idempotency_key="p-late")
        # agotar el saldo en otra venta
        third = self.sales.create_sale(self.customer["id"], [{"description": "Otro", "quantity": 1, "unit_price_cop": 99_000}],
                                       idempotency_key="third")
        self.credit.apply_to_sale(third["id"], 15_000, reason="Resto", registered_by="Ana", idempotency_key="u4")
        self.assertEqual(self.credit.balance(self.customer["id"])["saldo_disponible_cop"], 0)
        with self.assertRaises(ValidationError):
            self.credit.apply_to_sale(third["id"], 1, reason="x", registered_by="Ana", idempotency_key="u5")

    def test_ledger_rejects_negative_balance_foreign_sale_and_edits(self) -> None:
        self.commit("c", credit_cop=10_000, customer_consent=True)
        event_comp = self.commit("e", refund_cop=5_000)["compensaciones"][0]
        self.comp.prepare(event_comp["id"], registered_by="Caja", idempotency_key="pe")
        other_customer = self.sales.connection.execute(
            "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('Otro', '2026-10-31T12:00:00Z', '2026-10-31T12:00:00Z') RETURNING id").fetchone()[0]
        raw = """INSERT INTO movimientos_saldo_favor (cliente_id, tipo, importe_cop, origen_tipo, origen_id, venta_id,
                 fecha_negocio, registrado_en_utc, motivo, registrado_por, clave_idempotencia, huella_solicitud)
                 VALUES (?, 'utilizacion', ?, 'venta', ?, ?, '2026-10-31', '2026-10-31T12:00:00Z', 'x', 'y', ?, ?)"""
        fp = "0" * 64
        nxt = self.sales.create_sale(self.customer["id"], [{"description": "C", "quantity": 1, "unit_price_cop": 50_000}], idempotency_key="n")
        with self.assertRaises(sqlite3.IntegrityError):  # saldo negativo
            self.c.execute(raw, (self.customer["id"], -10_001, nxt["id"], nxt["id"], "r1", fp))
        with self.assertRaises(sqlite3.IntegrityError):  # venta de otro cliente
            self.c.execute(raw, (other_customer, -1, nxt["id"], nxt["id"], "r2", fp))
        for sql in ("UPDATE movimientos_saldo_favor SET motivo='x'", "DELETE FROM movimientos_saldo_favor",
                    "UPDATE compensaciones_cancelacion SET motivo='x'", "DELETE FROM eventos_compensacion"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.c.execute(sql)

    # --- pagos y reversiones (R4, R6) ---
    def test_payment_correction_cannot_strand_commitments_but_real_reversal_is_recorded(self) -> None:
        comp = self.commit("a", refund_cop=60_000)["compensaciones"][0]
        pay = self.sale["pagos"][0] if self.sale.get("pagos") else self.view()["pagos"][0]
        with self.assertRaises(DataIntegrityError):  # R6: corregir el pago dejaría C > P
            self.sales.reverse_payment(pay["id"], reason="Duplicado", nature="correccion_registro_erroneo",
                                       source="operador", evidence="Extracto")
        self.comp.confirm_delivery(comp["id"], registered_by="Caja", idempotency_key="d")
        out = self.sales.reverse_payment(pay["id"], reason="Contracargo", nature="reversion_financiera_real",
                                         source="banco", evidence="Aviso del banco")
        sale = out["venta"]
        self.assertEqual((sale["pagado_neto_cop"], sale["reembolsos_entregados_cop"], sale["exceso_reembolsado_cop"]),
                         (0, 60_000, 60_000))
        self.assertEqual(len(sale["pagos"]), 2)
        with self.assertRaises(ValidationError):  # nuevas compensaciones bloqueadas
            self.commit("z", refund_cop=1)

    # --- equivalencia y compatibilidad ---
    def test_sales_without_returns_or_credit_keep_previous_balances(self) -> None:
        plain = self.sales.create_sale(self.customer["id"], [{"description": "Plano", "quantity": 2, "unit_price_cop": 5_000}],
                                       idempotency_key="plain")
        self.sales.register_payment(plain["id"], 4_000, method="Efectivo", idempotency_key="plain-pay")
        sale = self.sales.get_sale(plain["id"])
        self.assertEqual((sale["importe_acordado_cop"], sale["pagado_neto_cop"], sale["saldo_pendiente_cop"],
                          sale["sobrepago_pendiente_cop"], sale["estado_cobro"], sale["saldo_favor_aplicado_cop"]),
                         (10_000, 4_000, 6_000, 0, "parcial", 0))


class CompensationConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = str(Path(self.dir.name) / "db.sqlite3")
        setup = open_database(self.path)
        migrate(setup)
        _sales, customer, sale = build_world(setup)
        self.sid, self.customer_id = sale["id"], customer["id"]
        CompensationService(setup).commit(self.sid, credit_cop=60_000, reason="x", customer_consent=True,
                                          idempotency_key="seed", **AUTH)
        setup.close()

    def run_threads(self, count, target):
        results, barrier = [], threading.Barrier(count)

        def worker(index):
            connection = open_database(self.path)
            barrier.wait()
            try:
                results.append(target(connection, index))
            except Exception as error:  # noqa: BLE001 - se clasifica abajo
                results.append(error)
            finally:
                connection.close()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
        for t in threads: t.start()
        for t in threads: t.join()
        return results

    def test_parallel_credit_applications_never_overspend_balance(self) -> None:
        def apply(connection, index):
            sale = SalesService(connection).create_sale(
                self.customer_id, [{"description": "X", "quantity": 1, "unit_price_cop": 50_000}], idempotency_key=f"s{index}")
            return CreditService(connection).apply_to_sale(sale["id"], 40_000, reason="x", registered_by="Ana",
                                                           idempotency_key=f"app{index}")
        results = self.run_threads(4, apply)
        ok = [r for r in results if isinstance(r, dict)]
        self.assertEqual(len(ok), 1)  # 60.000 de saldo: cabe una sola aplicación de 40.000
        check = open_database(self.path)
        self.addCleanup(check.close)
        self.assertEqual(CreditService(check).balance(self.customer_id)["saldo_disponible_cop"], 20_000)

    def test_parallel_same_key_commits_once(self) -> None:
        def commit(connection, _index):
            # D ya está cubierto por el crédito sembrado: esta prueba usa una venta nueva
            return None
        # misma clave desde 5 conexiones sobre la misma compensación mixta nueva
        setup = open_database(self.path)
        sales = SalesService(setup)
        sale = sales.create_sale(self.customer_id, [{"description": "S", "quantity": 2, "unit_price_cop": 50_000}], idempotency_key="s2")
        sales.register_payment(sale["id"], 100_000, method="Efectivo", idempotency_key="s2pay")
        ReturnsService(setup).register_return(sale["id"], [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 1}],
                                              reason="x", idempotency_key="s2ret", **WHO)
        setup.close()

        def worker(connection, _index):
            return CompensationService(connection).commit(sale["id"], refund_cop=50_000, method="Efectivo", reason="x",
                                                           idempotency_key="race", **AUTH)
        results = self.run_threads(5, worker)
        self.assertTrue(all(isinstance(r, dict) for r in results), results)
        check = open_database(self.path)
        self.addCleanup(check.close)
        self.assertEqual(check.execute("SELECT COUNT(*) FROM compensaciones_cancelacion WHERE venta_id = ?", (sale["id"],)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
