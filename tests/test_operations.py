"""Solicitudes de operación persistentes e idempotencia persistente de pagos de cliente (Informe2 §3.9)."""

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services import operation_retry
from dragontech_manager.services.errors import ConflictError, DataIntegrityError, ValidationError
from dragontech_manager.services.operations import OperationRegistry
from dragontech_manager.services.sales import SalesService
from tests.test_debt_actors import Base, auth, make_actors
from tests.test_returns import make_world


def count(c, table, where="1=1"):
    return c.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


class PersistentRequestTests(Base):
    def setUp(self) -> None:
        super().setUp()
        self.registry = OperationRegistry(self.c)

    def intent(self, key):
        row = self.c.execute("SELECT * FROM solicitudes_operacion WHERE clave_idempotencia = ?", (key,)).fetchone()
        return dict(row) if row else None

    def test_payment_intent_is_completed_in_the_same_transaction_and_replays_without_duplicates(self) -> None:
        sale = self.new_sale("p")
        first = self.sales.register_payment(sale["id"], 10_000, method="Efectivo", idempotency_key="pay-1")
        row = self.intent("pay-1")
        self.assertEqual((row["estado"], row["tipo_operacion"], row["entidad_tipo"], row["entidad_id"]),
                         ("completada", "pago_venta", "pago_cliente", first["pago"]["id"]))
        self.assertEqual(len(first["pago"]["huella_solicitud"]), 64)
        again = self.sales.register_payment(sale["id"], 10_000, method="Efectivo", idempotency_key="pay-1")
        self.assertTrue(again["repetido"])
        self.assertEqual(count(self.c, "pagos_clientes", "venta_id = %d" % sale["id"]), 1)
        self.assertEqual(count(self.c, "solicitudes_operacion", "tipo_operacion = 'pago_venta'"), 1)

    def test_same_key_other_content_conflicts_with_zero_writes(self) -> None:
        sale = self.new_sale("c")
        self.sales.register_payment(sale["id"], 10_000, method="Efectivo", idempotency_key="k")
        for amount, method in ((11_000, "Efectivo"), (10_000, "Tarjeta")):
            with self.assertRaises(ConflictError):
                self.sales.register_payment(sale["id"], amount, method=method, idempotency_key="k")
        self.assertEqual(count(self.c, "pagos_clientes", "venta_id = %d" % sale["id"]), 1)
        self.assertEqual(count(self.c, "solicitudes_operacion", "clave_idempotencia = 'k'"), 1)

    def test_legacy_payment_without_fingerprint_still_replays_by_fields(self) -> None:
        sale = self.new_sale("l")
        self.c.execute("""INSERT INTO pagos_clientes (venta_id, importe_cop, tipo, metodo, metodo_pago_id, registrado_en_utc,
                          fecha_negocio, clave_idempotencia) VALUES (?, 7000, 'recibo', 'Efectivo', 1,
                          '2026-10-30T12:00:00Z', '2026-10-30', 'legacy-key')""", (sale["id"],))
        again = self.sales.register_payment(sale["id"], 7_000, method="Efectivo", idempotency_key="legacy-key")
        self.assertTrue(again["repetido"])
        with self.assertRaises(ConflictError):
            self.sales.register_payment(sale["id"], 8_000, method="Efectivo", idempotency_key="legacy-key")
        with self.assertRaises(sqlite3.IntegrityError):  # huella sin clave
            self.c.execute("""INSERT INTO pagos_clientes (venta_id, importe_cop, tipo, metodo, metodo_pago_id, registrado_en_utc,
                              fecha_negocio, huella_solicitud) VALUES (?, 1, 'recibo', 'Efectivo', 1,
                              '2026-10-30T12:00:00Z', '2026-10-30', ?)""", (sale["id"], "0" * 64))

    def test_failure_inside_the_transaction_rolls_back_everything_and_leaves_a_retryable_pending_request(self) -> None:
        sale = self.new_sale("r")
        self.c.execute("""CREATE TRIGGER falla_prueba AFTER INSERT ON cancelacion_venta_lineas
                          BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END""")
        before = (count(self.c, "cancelaciones_venta"), count(self.c, "movimientos_inventario"))
        with self.assertRaises(DataIntegrityError):
            self.return_lines(sale, "ret-1", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 2}])
        self.assertEqual((count(self.c, "cancelaciones_venta"), count(self.c, "movimientos_inventario")), before)
        row = self.intent("ret-1")
        self.assertEqual(row["estado"], "pendiente")
        self.assertTrue(row["detalle"].startswith("Rechazada: "))
        self.assertEqual(self.registry.pending()[0]["clave_idempotencia"], "ret-1")
        self.c.execute("DROP TRIGGER falla_prueba")
        outcome = operation_retry.retry(self.c, "ret-1")  # tras «reiniciar»: misma clave y carga guardada
        self.assertTrue(outcome["reintentada"])
        self.assertEqual((self.intent("ret-1")["estado"], count(self.c, "cancelaciones_venta")), ("completada", 1))
        self.assertEqual(self.registry.pending(), [])
        with self.assertRaises(ValidationError):  # una completada ya no se reintenta
            operation_retry.retry(self.c, "ret-1")

    def test_each_financial_operation_can_be_retried_after_a_forced_failure(self) -> None:
        a = self.a
        sale = self.new_sale("m", paid=100_000)
        self.return_lines(sale, "m-ret", [{"sale_line_id": sale["lineas"][0]["id"], "quantity": 2}])  # D = 60.000
        cases = [
            ("compensaciones_cancelacion", "comp", lambda: self.comp.commit(
                sale["id"], refund_cop=20_000, credit_cop=40_000, method="Efectivo", customer_consent=True, reason="x",
                executor=a["cajero"], authorizer=a["super"], authorization_ref="A", idempotency_key="comp"),
             "compensacion_venta"),
        ]
        for table, key, call, operation in cases:
            with self.subTest(operation=operation):
                self.c.execute(f"CREATE TRIGGER falla_prueba BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'fallo'); END")
                with self.assertRaises(DataIntegrityError):
                    call()
                self.assertEqual(self.intent(key)["estado"], "pendiente")
                self.c.execute("DROP TRIGGER falla_prueba")
                operation_retry.retry(self.c, key)
                self.assertEqual(self.intent(key)["estado"], "completada")
                self.assertEqual(count(self.c, "compensaciones_cancelacion"), 2)  # reembolso + crédito, una sola vez
        # evento de entrega
        refund = [c for c in self.comp.list_for_sale(sale["id"]) if c["tipo"] == "reembolso"][0]
        self.c.execute("CREATE TRIGGER falla_prueba BEFORE INSERT ON eventos_compensacion BEGIN SELECT RAISE(ABORT, 'fallo'); END")
        with self.assertRaises(DataIntegrityError):
            self.comp.confirm_delivery(refund["id"], registered_by=a["cajero"], idempotency_key="deliv")
        self.c.execute("DROP TRIGGER falla_prueba")
        operation_retry.retry(self.c, "deliv")
        self.assertEqual(count(self.c, "eventos_compensacion", "tipo = 'entregada'"), 1)
        # crédito, pago y condonación
        nxt = self.new_sale("n")
        self.c.execute("CREATE TRIGGER falla_prueba BEFORE INSERT ON movimientos_saldo_favor WHEN NEW.tipo = 'utilizacion' BEGIN SELECT RAISE(ABORT, 'fallo'); END")
        from dragontech_manager.services.credit import CreditService
        with self.assertRaises(DataIntegrityError):
            CreditService(self.c).apply_to_sale(nxt["id"], 30_000, reason="x", registered_by=a["cajero"], idempotency_key="cr")
        self.c.execute("DROP TRIGGER falla_prueba")
        operation_retry.retry(self.c, "cr")
        self.assertEqual(count(self.c, "movimientos_saldo_favor", "tipo = 'utilizacion'"), 1)
        self.c.execute("CREATE TRIGGER falla_prueba BEFORE INSERT ON pagos_clientes WHEN NEW.clave_idempotencia = 'pg' BEGIN SELECT RAISE(ABORT, 'fallo'); END")
        with self.assertRaises(DataIntegrityError):
            self.sales.register_payment(nxt["id"], 20_000, method="Efectivo", idempotency_key="pg")
        self.c.execute("DROP TRIGGER falla_prueba")
        operation_retry.retry(self.c, "pg")
        self.assertEqual(count(self.c, "pagos_clientes", "clave_idempotencia = 'pg'"), 1)
        debt_sale = self.indebted_sale("dd")
        self.c.execute("CREATE TRIGGER falla_prueba BEFORE INSERT ON extinciones_deuda_venta BEGIN SELECT RAISE(ABORT, 'fallo'); END")
        with self.assertRaises(DataIntegrityError):
            self.debt.forgive(debt_sale["id"], 30_000, reason="x", idempotency_key="fg", **auth(a))
        self.c.execute("DROP TRIGGER falla_prueba")
        operation_retry.retry(self.c, "fg")
        self.assertEqual(self.liq(debt_sale)["deuda_pendiente_cop"], 0)

    def test_abandon_rules_and_state_machine(self) -> None:
        self.c.execute("""CREATE TRIGGER falla_prueba BEFORE INSERT ON pagos_clientes BEGIN SELECT RAISE(ABORT, 'fallo'); END""")
        sale = self.new_sale("ab")
        with self.assertRaises(DataIntegrityError):
            self.sales.register_payment(sale["id"], 5_000, method="Efectivo", idempotency_key="ab-1")
        self.c.execute("DROP TRIGGER falla_prueba")
        with self.assertRaises(ValidationError):
            self.registry.abandon("ab-1", " ")
        self.registry.abandon("ab-1", "El cliente se retiró")
        self.assertEqual(self.intent("ab-1")["estado"], "abandonada")
        with self.assertRaises(ConflictError):  # clave retirada
            self.sales.register_payment(sale["id"], 5_000, method="Efectivo", idempotency_key="ab-1")
        with self.assertRaises(ConflictError):
            self.registry.abandon("ab-1", "otra vez")
        done = self.sales.register_payment(sale["id"], 5_000, method="Efectivo", idempotency_key="ab-2")
        with self.assertRaises(ConflictError):  # completada no se abandona
            self.registry.abandon("ab-2", "x")
        for sql in ("UPDATE solicitudes_operacion SET estado = 'pendiente' WHERE clave_idempotencia = 'ab-2'",
                    "UPDATE solicitudes_operacion SET huella_solicitud = '%s' WHERE clave_idempotencia = 'ab-1'" % ("1" * 64),
                    "DELETE FROM solicitudes_operacion"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.c.execute(sql)
        self.assertEqual(done["pago"]["huella_solicitud"], self.intent("ab-2")["huella_solicitud"])

    def test_reconcile_marks_pending_requests_whose_entity_already_exists(self) -> None:
        sale = self.new_sale("rc")
        # estado imposible por atomicidad, sembrado a mano: intención pendiente con la entidad ya creada
        self.c.execute("""INSERT INTO pagos_clientes (venta_id, importe_cop, tipo, metodo, metodo_pago_id, registrado_en_utc,
                          fecha_negocio, clave_idempotencia) VALUES (?, 3000, 'recibo', 'Efectivo', 1,
                          '2026-10-30T12:00:00Z', '2026-10-30', 'rc-1')""", (sale["id"],))
        for key in ("rc-1", "rc-2"):
            self.c.execute("""INSERT INTO solicitudes_operacion (clave_idempotencia, tipo_operacion, huella_solicitud, estado,
                              solicitado_por, creada_en_utc) VALUES (?, 'pago_venta', ?, 'pendiente', 'x', '2026-10-31T12:00:00Z')""",
                           (key, "0" * 64))
        self.assertEqual(self.registry.reconcile(), 1)
        self.assertEqual((self.intent("rc-1")["estado"], self.intent("rc-1")["entidad_tipo"]), ("completada", "pago_cliente"))
        self.assertEqual(self.intent("rc-2")["estado"], "pendiente")  # sin entidad: sigue pendiente
        with self.assertRaises(ConflictError):  # otra huella sobre una solicitud existente
            self.registry.begin("rc-2", "pago_venta", "1" * 64, "x", {}, "")


class PersistentRequestConcurrencyTests(unittest.TestCase):
    def test_parallel_same_key_payments_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "db.sqlite3")
            setup = open_database(path)
            migrate(setup)
            inventory, sales, customer, mouse = make_world(setup)
            sale = sales.create_sale(customer["id"], [{"description": "S", "quantity": 1, "unit_price_cop": 100_000}],
                                     idempotency_key="cs")
            setup.close()
            results, barrier = [], threading.Barrier(6)

            def worker(index):
                connection = open_database(path)
                barrier.wait()
                try:
                    amount = 40_000 if index < 4 else 41_000  # 2 hilos con otra huella usando la misma clave
                    results.append(SalesService(connection).register_payment(
                        sale["id"], amount, method="Efectivo", idempotency_key="race"))
                except Exception as error:  # noqa: BLE001
                    results.append(error)
                finally:
                    connection.close()
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for t in threads: t.start()
            for t in threads: t.join()
            check = open_database(path)
            self.addCleanup(check.close)
            self.assertEqual(count(check, "pagos_clientes", "clave_idempotencia = 'race'"), 1)
            self.assertEqual(count(check, "solicitudes_operacion", "clave_idempotencia = 'race'"), 1)
            self.assertEqual(check.execute("SELECT estado FROM solicitudes_operacion WHERE clave_idempotencia = 'race'").fetchone()[0], "completada")
            winner = check.execute("SELECT importe_cop FROM pagos_clientes WHERE clave_idempotencia = 'race'").fetchone()[0]
            self.assertEqual(sum(1 for r in results if isinstance(r, dict)), 6 - sum(1 for r in results if isinstance(r, ConflictError)))
            self.assertEqual(sum(1 for r in results if isinstance(r, ConflictError)), 2 if winner == 40_000 else 4)


if __name__ == "__main__":
    unittest.main()
