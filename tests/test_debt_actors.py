"""Actores, extinción de deuda, recuperaciones y reversión real (Fase 1, Entrega 6)."""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.actors import ActorService
from dragontech_manager.services.compensations import CompensationService
from dragontech_manager.services.credit import CreditService
from dragontech_manager.services.debt import DebtService
from dragontech_manager.services.errors import ConflictError, DataIntegrityError, ValidationError
from dragontech_manager.services.returns import ReturnsService
from dragontech_manager.services.sales import SalesService
from tests.test_returns import WHO, make_world

REAL = dict(nature="reversion_financiera_real", source="banco", evidence="Aviso del banco")


def make_actors(connection):
    actors = ActorService(connection)
    return {
        "cajero": actors.create_actor("Ana Caja", "cajero")["id"],
        "super": actors.create_actor("Sergio Supervisor", "supervisor", can_authorize=True, limit_cop=5_000_000)["id"],
        "dueno": actors.create_actor("Olga Propietaria", "propietario", can_authorize=True, limit_cop=50_000_000)["id"],
        "chico": actors.create_actor("Cris Limitado", "supervisor", can_authorize=True, limit_cop=10_000)["id"],
        "sinlimite": actors.create_actor("Nora Sin Límite", "supervisor", can_authorize=True)["id"],
        "vendedor": actors.create_actor("Vera Vendedora", "vendedor")["id"],
    }


def auth(a, who="super", **extra):
    return dict(executor=a["cajero"], authorizer=a[who], authorization_ref="DOC-1",
                authorization_medium="documento_firmado", **extra)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.c = open_database(":memory:")
        self.addCleanup(self.c.close)
        migrate(self.c)
        self.inventory, self.sales, self.customer, self.mouse = make_world(self.c)
        self.a = make_actors(self.c)
        self.debt, self.comp, self.returns = DebtService(self.c), CompensationService(self.c), ReturnsService(self.c)

    def new_sale(self, key, paid=0):
        sale = self.sales.create_sale(self.customer["id"], [
            {"description": "Mouse", "quantity": 3, "unit_price_cop": 30_000, "product_id": self.mouse["id"]},
            {"description": "Configuración", "quantity": 1, "unit_price_cop": 10_000}], idempotency_key=key)
        if paid:
            self.sales.register_payment(sale["id"], paid, method="Efectivo", idempotency_key=f"{key}-pay")
        return sale

    def return_lines(self, sale, key, lines):
        return self.returns.register_return(sale["id"], lines, reason="Devolución", idempotency_key=key,
                                            requester="Cliente", requester_type="cliente", executor=self.a["cajero"],
                                            authorizer=self.a["super"], authorization_ref="AUT-RET")

    def indebted_sale(self, key="debt"):
        """Venta impaga de 100.000 devuelta por completo reconociendo solo 70.000: deuda 30.000."""
        sale = self.new_sale(key)
        self.return_lines(sale, f"{key}-r", [
            {"sale_line_id": sale["lineas"][0]["id"], "quantity": 3, "recognized_value_cop": 60_000,
             "value_adjustment_reason": "Daño"},
            {"sale_line_id": sale["lineas"][1]["id"], "quantity": 1}])
        return sale

    def liq(self, sale):
        return self.debt.liquidation(sale["id"])

    def check_history(self, sale):
        rows = self.debt.history(sale["id"])
        liq = self.liq(sale)
        self.assertEqual(sum(r["efecto_residuo_cop"] for r in rows), liq["residuo_liquidacion_cop"])
        self.assertEqual(sum(r["efecto_caja_cop"] for r in rows),
                         liq["pagado_neto_cop"] + liq["recuperado_cop"] - liq["reembolsos_entregados_cop"])


class ActorTests(Base):
    def test_directory_rules_and_snapshots(self) -> None:
        actors = ActorService(self.c)
        with self.assertRaises(Exception):
            actors.create_actor("ana caja", "cajero")  # nombre duplicado (sin distinguir mayúsculas)
        with self.assertRaises(ValidationError):
            actors.create_actor("Zoe", "astronauta")
        sale = self.new_sale("snap", paid=100_000)
        out = self.return_lines(sale, "snap-r", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 2}])
        header = out["devolucion"]
        self.assertEqual((header["origen_identidad"], header["ejecutor_id"], header["responsable_ejecucion"]),
                         ("directorio", self.a["cajero"], "Ana Caja"))
        actors.update_actor(self.a["cajero"], name="Ana Renombrada", role="cajero")
        self.assertEqual(self.returns.list_returns(sale["id"])[0]["responsable_ejecucion"], "Ana Caja")  # no se reescribe
        actors.set_active(self.a["cajero"], False)
        with self.assertRaises(ValidationError):
            self.return_lines(sale, "snap-r2", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 1}])
        self.assertEqual(len(actors.list_actors()), 5)
        self.assertEqual(len(actors.list_actors(active_only=False)), 6)
        with self.assertRaises(sqlite3.IntegrityError):
            self.c.execute("DELETE FROM actores")

    def test_legacy_text_stays_legacy_and_modes_do_not_mix(self) -> None:
        sale = self.new_sale("leg")
        out = self.returns.register_return(sale["id"], [{"sale_line_id": sale["lineas"][1]["id"], "quantity": 1}],
                                           reason="x", idempotency_key="leg-r", **WHO)
        self.assertEqual((out["devolucion"]["origen_identidad"], out["devolucion"]["ejecutor_id"]), ("legado", None))
        with self.assertRaises(ValidationError):
            self.returns.register_return(sale["id"], [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 1}],
                                         reason="x", idempotency_key="mix", requester="C", requester_type="cliente",
                                         executor=self.a["cajero"], authorizer="Texto libre", authorization_ref="A")

    def test_compensation_with_directory_actors_enforces_authorizer_and_limit(self) -> None:
        sale = self.new_sale("lim", paid=100_000)
        self.return_lines(sale, "lim-r", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 2}])
        base = dict(refund_cop=60_000, method="Efectivo", reason="x", authorization_ref="A1")
        for authorizer, error in ((self.a["cajero"], "permiso"), (self.a["chico"], "límite"), (self.a["sinlimite"], "límite")):
            with self.subTest(authorizer=authorizer), self.assertRaisesRegex(ValidationError, error):
                self.comp.commit(sale["id"], executor=self.a["cajero"], authorizer=authorizer,
                                 idempotency_key=f"k{authorizer}", **base)
        with self.assertRaisesRegex(ValidationError, "distinto"):
            self.comp.commit(sale["id"], executor=self.a["super"], authorizer=self.a["super"], idempotency_key="same", **base)
        out = self.comp.commit(sale["id"], executor=self.a["cajero"], authorizer=self.a["super"], idempotency_key="ok", **base)
        row = out["compensaciones"][0]
        self.assertEqual((row["ejecutor_id"], row["autorizador_id"], row["origen_identidad"]), (self.a["cajero"], self.a["super"], "directorio"))
        # la base de datos también protege una inserción directa con autorizador sin permiso o sin límite
        raw = """INSERT INTO compensaciones_cancelacion (venta_id, tipo, importe_cop, metodo_pago_id, motivo,
                 responsable_ejecucion, autorizador, autorizado_en_utc, referencia_autorizacion, fecha_negocio,
                 registrado_en_utc, clave_idempotencia, huella_solicitud, ejecutor_id, autorizador_id, origen_identidad)
                 VALUES (?, 'reembolso', 1, 1, 'x', 'a', 'b', '2026-10-31T12:00:00Z', 'r', '2026-10-31',
                 '2026-10-31T12:00:00Z', ?, ?, ?, ?, 'directorio')"""
        for key, authorizer in (("r1", self.a["vendedor"]), ("r2", self.a["sinlimite"]), ("r3", self.a["cajero"])):
            with self.subTest(key=key), self.assertRaises(sqlite3.IntegrityError):
                self.c.execute(raw, (sale["id"], key, "0" * 64, self.a["cajero"], authorizer))

    def test_payment_reversal_records_actors(self) -> None:
        sale = self.new_sale("rv", paid=10_000)
        pay = self.sales.get_sale(sale["id"])["pagos"][0]
        with self.assertRaisesRegex(ValidationError, "obligatorio"):
            self.sales.reverse_payment(pay["id"], reason="x", nature="correccion_registro_erroneo", source="operador",
                                       evidence="E", executor=self.a["cajero"])
        out = self.sales.reverse_payment(pay["id"], reason="Duplicado", nature="correccion_registro_erroneo",
                                         source="operador", evidence="Extracto", executor=self.a["cajero"],
                                         authorizer=self.a["super"])["pago"]
        self.assertEqual((out["ejecutor_id"], out["autorizador_id"], out["ejecutor_nombre"], out["autorizador_nombre"]),
                         (self.a["cajero"], self.a["super"], "Ana Caja", "Sergio Supervisor"))


class ExtinctionTests(Base):
    def test_forgive_exact_debt_leaves_cash_untouched_and_blocks_payment(self) -> None:
        sale = self.indebted_sale()
        liq = self.liq(sale)
        self.assertEqual((liq["deuda_pendiente_cop"], liq["saldo_pendiente_cop"], liq["estado_comercial"],
                          liq["estado_liquidacion"]), (30_000, 30_000, "cancelada_con_deuda", "pendiente_cobro"))
        out = self.debt.forgive(sale["id"], 30_000, reason="Cargo por daño", idempotency_key="f1", **auth(self.a))
        liq = out["liquidacion"]
        self.assertEqual((liq["deuda_pendiente_cop"], liq["condonado_cop"], liq["residuo_liquidacion_cop"],
                          liq["estado_comercial"], liq["estado_liquidacion"], liq["estado_cobro"], liq["pagado_neto_cop"]),
                         (0, 30_000, 0, "cancelada_liquidada", "condonada", "cancelada", 0))
        with self.assertRaises(ConflictError):  # venta cancelada y liquidada: ya no se cobra
            self.sales.register_payment(sale["id"], 1, method="Efectivo", idempotency_key="late")
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM pagos_clientes WHERE venta_id = ?", (sale["id"],)).fetchone()[0], 0)
        self.check_history(sale)

    def test_limits_r9_authorization_and_evidence(self) -> None:
        sale = self.indebted_sale()
        with self.assertRaises(ValidationError):  # R9: más que la deuda
            self.debt.forgive(sale["id"], 30_001, reason="x", idempotency_key="a", **auth(self.a))
        with self.assertRaisesRegex(ValidationError, "evidencia"):
            self.debt.write_off(sale["id"], 10_000, collection_evidence="", reason="x", idempotency_key="b", **auth(self.a))
        for who, error in (("vendedor", "permiso"), ("chico", "límite"), ("sinlimite", "límite")):
            with self.subTest(who=who), self.assertRaisesRegex(ValidationError, error):
                self.debt.forgive(sale["id"], 20_000, reason="x", idempotency_key=f"c{who}", **auth(self.a, who))
        with self.assertRaisesRegex(ValidationError, "distinto"):
            self.debt.forgive(sale["id"], 1, reason="x", idempotency_key="d", executor=self.a["super"],
                              authorizer=self.a["super"], authorization_ref="R", authorization_medium="presencial")
        with self.assertRaisesRegex(ValidationError, "directorio"):
            self.debt.forgive(sale["id"], 1, reason="x", idempotency_key="e", executor="Texto", authorizer="Otro",
                              authorization_ref="R", authorization_medium="presencial")
        with self.assertRaisesRegex(ValidationError, "medio"):
            self.debt.forgive(sale["id"], 1, reason="x", idempotency_key="f", executor=self.a["cajero"],
                              authorizer=self.a["super"], authorization_ref="R", authorization_medium="telepatia")
        written = self.debt.write_off(sale["id"], 30_000, collection_evidence="3 llamadas y 2 correos", reason="Incobrable",
                                      idempotency_key="g", **auth(self.a, "dueno"))
        self.assertEqual((written["liquidacion"]["castigado_cop"], written["liquidacion"]["estado_liquidacion"]), (30_000, "castigada"))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM extinciones_deuda_venta").fetchone()[0], 1)

    def test_partial_payment_then_forgive_remaining_and_no_overpayment_after(self) -> None:
        sale = self.indebted_sale()
        self.sales.register_payment(sale["id"], 10_000, method="Efectivo", idempotency_key="part")
        self.debt.forgive(sale["id"], 20_000, reason="Resto", idempotency_key="f", **auth(self.a))
        liq = self.liq(sale)
        self.assertEqual((liq["pagado_neto_cop"], liq["condonado_cop"], liq["deuda_pendiente_cop"], liq["residuo_liquidacion_cop"]),
                         (10_000, 20_000, 0, 0))
        with self.assertRaises(ConflictError):
            self.sales.register_payment(sale["id"], 1, method="Efectivo", idempotency_key="over")

    def test_pay_after_partial_forgiveness_cannot_push_q_above_debt(self) -> None:  # R9 también al pagar
        sale = self.indebted_sale()
        self.debt.forgive(sale["id"], 20_000, reason="Parcial", idempotency_key="f", **auth(self.a))
        with self.assertRaises(ValidationError):  # solo quedan 10.000 cobrables
            self.sales.register_payment(sale["id"], 10_001, method="Efectivo", idempotency_key="p1")
        self.sales.register_payment(sale["id"], 10_000, method="Efectivo", idempotency_key="p2")
        self.assertEqual(self.liq(sale)["deuda_pendiente_cop"], 0)

    def test_annulment_restores_debt_without_deleting_original(self) -> None:
        sale = self.indebted_sale()
        ext = self.debt.forgive(sale["id"], 30_000, reason="x", idempotency_key="f", **auth(self.a))["extincion"]
        with self.assertRaises(ValidationError):
            self.debt.annul_extinction(ext["id"], 30_001, reason="Error", idempotency_key="a0", **auth(self.a))
        out = self.debt.annul_extinction(ext["id"], 10_000, reason="Error de importe", idempotency_key="a1", **auth(self.a))
        self.assertEqual((out["liquidacion"]["deuda_pendiente_cop"], out["liquidacion"]["condonado_cop"]), (10_000, 20_000))
        self.assertEqual(self.c.execute("SELECT importe_cop FROM extinciones_deuda_venta").fetchone()[0], 30_000)
        self.assertTrue(self.debt.annul_extinction(ext["id"], 10_000, reason="Error de importe", idempotency_key="a1", **auth(self.a))["repetido"])
        self.debt.annul_extinction(ext["id"], 20_000, reason="Resto", idempotency_key="a2", **auth(self.a))
        with self.assertRaises(ValidationError):
            self.debt.annul_extinction(ext["id"], 1, reason="Más", idempotency_key="a3", **auth(self.a))
        self.assertEqual(self.liq(sale)["deuda_pendiente_cop"], 30_000)
        self.check_history(sale)
        for sql in ("UPDATE extinciones_deuda_venta SET motivo='x'", "DELETE FROM extinciones_deuda_venta",
                    "UPDATE anulaciones_extincion_deuda SET motivo='x'", "DELETE FROM anulaciones_extincion_deuda"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.c.execute(sql)

    def test_idempotent_retry_conflict_and_fake_payments_rejected(self) -> None:
        sale = self.indebted_sale()
        first = self.debt.forgive(sale["id"], 10_000, reason="x", idempotency_key="same", **auth(self.a))
        again = self.debt.forgive(sale["id"], 10_000, reason="x", idempotency_key="same", **auth(self.a))
        self.assertTrue(again["repetido"])
        self.assertEqual(first["extincion"]["id"], again["extincion"]["id"])
        with self.assertRaises(ConflictError):
            self.debt.forgive(sale["id"], 11_000, reason="x", idempotency_key="same", **auth(self.a))
        self.assertEqual(self.liq(sale)["condonado_cop"], 10_000)
        with self.assertRaises(sqlite3.IntegrityError):  # un «pago» negativo/ficticio no existe en el modelo
            self.c.execute("""INSERT INTO pagos_clientes (venta_id, importe_cop, tipo, metodo, registrado_en_utc)
                              VALUES (?, -10000, 'recibo', 'Efectivo', '2026-10-31T12:00:00Z')""", (sale["id"],))

    def test_unpaid_sale_without_return_can_be_forgiven_but_not_beyond_total(self) -> None:
        sale = self.new_sale("plain")
        with self.assertRaises(ValidationError):
            self.debt.forgive(sale["id"], 100_001, reason="x", idempotency_key="a", **auth(self.a, "dueno"))
        self.debt.forgive(sale["id"], 100_000, reason="Cortesía", idempotency_key="b", **auth(self.a, "dueno"))
        self.assertEqual(self.liq(sale)["estado_cobro"], "completada")


class ReversalAndRecoveryTests(Base):
    def paid_returned_sale(self, key="rev"):
        sale = self.new_sale(key, paid=100_000)
        self.return_lines(sale, f"{key}-r", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 2}])  # R = 60.000
        return sale

    def refund(self, sale, amount, key, deliver=True):
        out = self.comp.commit(sale["id"], refund_cop=amount, method="Efectivo", reason="x", executor=self.a["cajero"],
                               authorizer=self.a["super"], authorization_ref="A", idempotency_key=key)
        cid = out["compensaciones"][0]["id"]
        if deliver:
            self.comp.confirm_delivery(cid, registered_by=self.a["cajero"], idempotency_key=f"{key}-d")
        return cid

    def pay_id(self, sale):
        return self.sales.get_sale(sale["id"])["pagos"][0]["id"]

    def test_real_reversal_after_delivered_refund_becomes_recoverable_debt(self) -> None:
        sale = self.paid_returned_sale()
        self.refund(sale, 60_000, "r1")
        self.sales.reverse_payment(self.pay_id(sale), reason="Contracargo", **REAL)
        liq = self.liq(sale)
        # P = 0, T-R = 40.000, C_e = 60.000: N0 = 100.000; 40.000 cobrables como pago, 60.000 como recuperación H
        self.assertEqual((liq["deuda_bruta_cop"], liq["saldo_pendiente_cop"], liq["exceso_reembolsado_cop"],
                          liq["estado_cobro"]), (100_000, 40_000, 60_000, "abierta"))
        self.assertEqual(liq["deuda_pendiente_cop"], 100_000)
        with self.assertRaises(ValidationError):  # H no cubre lo que cabe en un pago normal
            self.debt.record_recovery(sale["id"], 60_001, method="Efectivo", reason="Cobro", idempotency_key="h0", **auth(self.a))
        rec = self.debt.record_recovery(sale["id"], 60_000, method="Transferencia", reference="TRX-9", reason="Cobro de contracargo",
                                        idempotency_key="h1", **auth(self.a))
        self.assertTrue(self.debt.record_recovery(sale["id"], 60_000, method="Transferencia", reference="TRX-9",
                                                  reason="Cobro de contracargo", idempotency_key="h1", **auth(self.a))["repetido"])
        self.assertEqual((rec["liquidacion"]["pagado_neto_cop"], rec["liquidacion"]["recuperado_cop"],
                          rec["liquidacion"]["deuda_pendiente_cop"]), (0, 60_000, 40_000))  # H no es un pago de venta
        self.sales.register_payment(sale["id"], 40_000, method="Efectivo", idempotency_key="rest")
        liq = self.liq(sale)
        self.assertEqual((liq["deuda_pendiente_cop"], liq["residuo_liquidacion_cop"], liq["estado_liquidacion"]), (0, 0, "liquidada"))
        self.check_history(sale)

    def test_unfunded_uncommitted_refund_is_annulled_but_prepared_one_is_kept_and_blocked(self) -> None:
        sale = self.paid_returned_sale()
        self.refund(sale, 20_000, "d1")                      # entregado
        pending = self.refund(sale, 20_000, "d2", deliver=False)   # comprometido
        prepared = self.refund(sale, 20_000, "d3", deliver=False)
        self.comp.prepare(prepared, registered_by=self.a["cajero"], idempotency_key="prep")
        self.sales.reverse_payment(self.pay_id(sale), reason="Contracargo", **REAL)
        states = {c["id"]: c["estado"] for c in self.comp.list_for_sale(sale["id"])}
        self.assertEqual(states[pending], "anulada")
        self.assertEqual(states[prepared], "preparada")  # nunca se auto-anula una entrega preparada
        event = [e for c in self.comp.list_for_sale(sale["id"]) if c["id"] == pending for e in c["eventos"]][0]
        self.assertEqual((event["origen_identidad"], event["registrado_por"]), ("sistema", "Sistema"))
        with self.assertRaises(DataIntegrityError):  # entrega no financiada bloqueada (R3)
            self.comp.confirm_delivery(prepared, registered_by=self.a["cajero"], idempotency_key="deliv")
        with self.assertRaises(ValidationError):
            self.refund(sale, 1, "d4")
        self.assertGreater(self.liq(sale)["compromisos_sin_respaldo_cop"], 0)
        self.assertEqual(len(self.sales.get_sale(sale["id"])["pagos"]), 2)  # el pago original sigue ahí

    def test_system_annulment_failure_rolls_back_the_reversal(self) -> None:
        sale = self.paid_returned_sale()
        self.refund(sale, 20_000, "e1", deliver=False)
        self.c.execute("""CREATE TRIGGER falla_sistema BEFORE INSERT ON eventos_compensacion
                          WHEN NEW.origen_identidad = 'sistema' BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END""")
        with self.assertRaises(Exception):
            self.sales.reverse_payment(self.pay_id(sale), reason="Contracargo", **REAL)
        self.assertEqual(len(self.sales.get_sale(sale["id"])["pagos"]), 1)  # sin reversión parcial
        self.assertFalse(self.c.in_transaction)

    def test_credit_use_and_forgiveness_share_the_same_payable_limit(self) -> None:
        sale = self.indebted_sale("cr")
        self.debt.forgive(sale["id"], 25_000, reason="x", idempotency_key="f", **auth(self.a))
        # saldo cobrable = 5.000: usar saldo a favor por más está bloqueado aunque el cliente tenga crédito
        other = self.paid_returned_sale("cr3")
        self.comp.commit(other["id"], credit_cop=60_000, customer_consent=True, reason="x", executor=self.a["cajero"],
                         authorizer=self.a["super"], authorization_ref="A", idempotency_key="g")
        with self.assertRaises(ValidationError):
            CreditService(self.c).apply_to_sale(sale["id"], 5_001, reason="x", registered_by=self.a["cajero"], idempotency_key="u1")
        out = CreditService(self.c).apply_to_sale(sale["id"], 5_000, reason="x", registered_by=self.a["cajero"], idempotency_key="u2")
        self.assertEqual(out["movimiento"]["registrado_por_id"], self.a["cajero"])
        self.assertEqual(self.liq(sale)["deuda_pendiente_cop"], 0)


class HistoryAndOrdersTests(Base):
    def test_history_sums_match_liquidation_across_a_full_story(self) -> None:
        sale = self.new_sale("story", paid=100_000)
        self.return_lines(sale, "story-r", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 2}])
        self.comp.commit(sale["id"], refund_cop=20_000, credit_cop=40_000, method="Efectivo", customer_consent=True,
                         reason="x", executor=self.a["cajero"], authorizer=self.a["super"], authorization_ref="A",
                         idempotency_key="story-c")
        refund = [c for c in self.comp.list_for_sale(sale["id"]) if c["tipo"] == "reembolso"][0]
        self.comp.confirm_delivery(refund["id"], registered_by=self.a["cajero"], idempotency_key="story-d")
        self.check_history(sale)
        self.assertEqual(self.liq(sale)["estado_liquidacion"], "liquidada")
        events = {r["evento"] for r in self.debt.history(sale["id"])}
        self.assertTrue({r["origen_identidad"] for r in self.debt.history(sale["id"])} <= {"sistema", "legado", "directorio"})
        self.assertTrue({"venta", "pago", "devolucion", "compromiso_reembolso", "entrega_reembolso", "credito_generado"} <= events)

    def test_portfolio_lists_only_pending_debt_and_orders_expose_credit_column(self) -> None:
        sale = self.indebted_sale("port")
        self.assertEqual([r["venta_id"] for r in self.debt.portfolio()], [sale["id"]])
        self.debt.forgive(sale["id"], 30_000, reason="x", idempotency_key="f", **auth(self.a))
        self.assertEqual(self.debt.portfolio(), [])
        cols = {r["name"] for r in self.c.execute("PRAGMA table_info(v_saldos_ordenes)")}
        self.assertIn("saldo_favor_aplicado_cop", cols)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM v_saldos_ordenes WHERE saldo_favor_aplicado_cop <> 0").fetchone()[0], 0)


class DebtConcurrencyTests(unittest.TestCase):
    def test_parallel_forgiveness_never_exceeds_debt_and_same_key_writes_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "db.sqlite3")
            setup = open_database(path)
            migrate(setup)
            inventory, sales, customer, mouse = make_world(setup)
            a = make_actors(setup)
            sale = sales.create_sale(customer["id"], [{"description": "Servicio", "quantity": 1, "unit_price_cop": 100_000}],
                                     idempotency_key="cs")
            setup.close()
            results, barrier = [], threading.Barrier(6)

            def worker(index):
                connection = open_database(path)
                barrier.wait()
                try:
                    # 3 hilos con claves distintas pidiendo 60.000 (solo uno cabe) y 3 con la misma clave
                    key, amount = (f"k{index}", 60_000) if index < 3 else ("same", 40_000)
                    results.append(DebtService(connection).forgive(
                        sale["id"], amount, reason="x", idempotency_key=key, **auth(a)))
                except Exception as error:  # noqa: BLE001
                    results.append(error)
                finally:
                    connection.close()
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for t in threads: t.start()
            for t in threads: t.join()
            check = open_database(path)
            self.addCleanup(check.close)
            total = check.execute("SELECT COALESCE(SUM(importe_cop), 0) FROM extinciones_deuda_venta").fetchone()[0]
            self.assertLessEqual(total, 100_000)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM extinciones_deuda_venta WHERE clave_idempotencia = 'same'").fetchone()[0], 1)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM extinciones_deuda_venta WHERE importe_cop = 60000").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
