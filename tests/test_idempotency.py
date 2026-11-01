"""Idempotencia de pagos/reversiones de proveedor y ajustes/reversiones de inventario."""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services import idempotency
from dragontech_manager.services.errors import ConflictError, ValidationError
from dragontech_manager.services.inventory import InventoryService
from dragontech_manager.services.procurement import ProcurementService


def seed(connection):
    inventory = InventoryService(connection)
    procurement = ProcurementService(connection)
    supplier = inventory.create_supplier(name="Proveedor idempotente")
    product = inventory.create_product(sku="IDEM-1", name="Producto", unit_cost_cop=1000,
                                       suggested_price_cop=2000)
    purchase = procurement.create_purchase(supplier["id"], [{
        "product_id": product["id"], "quantity": 1, "unit_cost_cop": 100_000,
        "description": "Compra"}])
    procurement.transition_purchase(purchase["id"], "pendiente")
    return inventory, procurement, product, purchase


def count(connection, table):
    return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class IdempotencyHelperTests(unittest.TestCase):
    def test_key_validation_and_fingerprint_is_canonical(self) -> None:
        self.assertEqual(idempotency.validate_key("  abc "), "abc")
        for bad in (None, "", "   ", 5, "x" * 121):
            with self.assertRaises(ValidationError):
                idempotency.validate_key(bad)
        a = idempotency.fingerprint({"b": 1, "a": "ñ"})
        self.assertEqual(a, idempotency.fingerprint({"a": "ñ", "b": 1}))
        self.assertEqual(len(a), 64)
        self.assertNotEqual(a, idempotency.fingerprint({"a": "ñ", "b": 2}))

    def test_intent_key_is_stable_until_completed_or_payload_changes(self) -> None:
        intent = idempotency.IntentKey()
        first = intent.for_payload({"x": 1})
        self.assertEqual(first, intent.for_payload({"x": 1}))
        self.assertNotEqual(first, intent.for_payload({"x": 2}))
        stable = intent.for_payload({"x": 2})
        intent.complete()
        self.assertNotEqual(stable, intent.for_payload({"x": 2}))


class IdempotentOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.inventory, self.procurement, self.product, self.purchase = seed(self.connection)

    def test_supplier_payment_double_click_returns_original(self) -> None:
        args = (self.purchase["id"], 30_000)
        first = self.procurement.register_supplier_payment(*args, method="Efectivo", idempotency_key="k1")
        again = self.procurement.register_supplier_payment(*args, method="efectivo", idempotency_key="k1")
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(count(self.connection, "pagos_proveedores"), 1)
        self.assertEqual(len(first["huella_solicitud"]), 64)

    def test_supplier_payment_same_key_other_content_conflicts_without_writes(self) -> None:
        self.procurement.register_supplier_payment(
            self.purchase["id"], 30_000, method="Efectivo", idempotency_key="k1")
        for kwargs in ({"amount": 31_000, "method": "Efectivo"}, {"amount": 30_000, "method": "Transferencia"}):
            with self.assertRaises(ConflictError):
                self.procurement.register_supplier_payment(
                    self.purchase["id"], kwargs["amount"], method=kwargs["method"], idempotency_key="k1")
        self.assertEqual(count(self.connection, "pagos_proveedores"), 1)

    def test_distinct_keys_are_distinct_intentions_and_respect_balance(self) -> None:
        for key in ("a", "b"):
            self.procurement.register_supplier_payment(
                self.purchase["id"], 50_000, method="Efectivo", idempotency_key=key)
        with self.assertRaises(ValidationError):  # saldo agotado
            self.procurement.register_supplier_payment(
                self.purchase["id"], 1, method="Efectivo", idempotency_key="c")
        self.assertEqual(count(self.connection, "pagos_proveedores"), 2)

    def test_supplier_reversal_replay_and_conflict(self) -> None:
        pay = self.procurement.register_supplier_payment(
            self.purchase["id"], 30_000, method="Efectivo", idempotency_key="p")
        rev = self.procurement.reverse_supplier_payment(pay["id"], reason="Error", idempotency_key="r")
        again = self.procurement.reverse_supplier_payment(pay["id"], reason="Error", idempotency_key="r")
        self.assertEqual(rev["id"], again["id"])
        with self.assertRaises(ConflictError):
            self.procurement.reverse_supplier_payment(pay["id"], reason="Otro motivo", idempotency_key="r")
        with self.assertRaises(ConflictError):  # clave nueva sobre pago ya revertido
            self.procurement.reverse_supplier_payment(pay["id"], reason="Error", idempotency_key="r2")
        self.assertEqual(count(self.connection, "pagos_proveedores"), 2)

    def test_stock_adjustment_and_reversal_are_idempotent(self) -> None:
        kw = dict(unit_cost_cop=500, reason="Conteo")
        first = self.inventory.adjust_stock(self.product["id"], 4, idempotency_key="adj", **kw)
        again = self.inventory.adjust_stock(self.product["id"], 4, idempotency_key="adj", **kw)
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 4)
        with self.assertRaises(ConflictError):
            self.inventory.adjust_stock(self.product["id"], 5, idempotency_key="adj", **kw)
        rev = self.inventory.reverse_movement(first["id"], reason="Corrección", idempotency_key="rev")
        rev2 = self.inventory.reverse_movement(first["id"], reason="Corrección", idempotency_key="rev")
        self.assertEqual(rev["id"], rev2["id"])
        with self.assertRaises(ConflictError):
            self.inventory.reverse_movement(first["id"], reason="Distinto", idempotency_key="rev")
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 0)

    def test_failed_operation_leaves_no_partial_rows_and_key_stays_reusable(self) -> None:
        self.connection.execute(
            """CREATE TRIGGER fallo_prueba AFTER INSERT ON movimientos_inventario
               WHEN NEW.motivo = 'falla' BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END""")
        before = count(self.connection, "movimientos_inventario")
        with self.assertRaises(Exception):
            self.inventory.adjust_stock(self.product["id"], 3, unit_cost_cop=1, reason="falla",
                                        idempotency_key="f")
        self.assertEqual(count(self.connection, "movimientos_inventario"), before)
        self.assertFalse(self.connection.in_transaction)
        self.connection.execute("DROP TRIGGER fallo_prueba")
        ok = self.inventory.adjust_stock(self.product["id"], 3, unit_cost_cop=1, reason="falla",
                                         idempotency_key="f")
        self.assertEqual(count(self.connection, "movimientos_inventario"), before + 1)
        self.assertEqual(ok["clave_idempotencia"], "f")

    def test_missing_key_is_rejected_and_db_constraints_hold(self) -> None:
        with self.assertRaises(ValidationError):
            self.inventory.adjust_stock(self.product["id"], 1, unit_cost_cop=1, reason="x",
                                        idempotency_key=" ")
        base = """INSERT INTO movimientos_inventario
                  (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo, creado_en_utc,
                   motivo, fecha_negocio, clave_idempotencia, huella_solicitud)
                  VALUES (?, 1, 1, 'ajuste', '2026-10-24T15:30:00Z', 'x', '2026-10-24', ?, ?)"""
        pid = self.product["id"]
        with self.assertRaises(sqlite3.IntegrityError):  # clave sin huella
            self.connection.execute(base, (pid, "solo-clave", None))
        self.connection.execute(base, (pid, "u1", "0" * 64))
        with self.assertRaises(sqlite3.IntegrityError):  # clave duplicada
            self.connection.execute(base, (pid, "u1", "0" * 64))


class ConcurrencyTests(unittest.TestCase):
    def test_parallel_same_key_writes_once_and_conflicting_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "db.sqlite3")
            setup = open_database(path)
            migrate(setup)
            inventory, procurement, product, purchase = seed(setup)
            setup.close()

            results, barrier = [], threading.Barrier(6)

            def worker(index: int) -> None:
                connection = open_database(path)
                service = ProcurementService(connection)
                # 4 hilos: mismo contenido; 2 hilos: misma clave con importe distinto
                amount = 25_000 if index < 4 else 26_000
                barrier.wait()
                try:
                    row = service.register_supplier_payment(
                        purchase["id"], amount, method="Efectivo", idempotency_key="race")
                    results.append(("ok", row["id"], amount))
                except ConflictError:
                    results.append(("conflict", None, amount))
                finally:
                    connection.close()

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for t in threads: t.start()
            for t in threads: t.join()
            check = open_database(path)
            self.addCleanup(check.close)
            self.assertEqual(count(check, "pagos_proveedores"), 1)
            winners = {r[1] for r in results if r[0] == "ok"}
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(results), 6)
            # todos los "ok" comparten contenido del ganador; el resto son conflictos
            winner_amount = check.execute("SELECT importe_cop FROM pagos_proveedores").fetchone()[0]
            self.assertTrue(all(r[2] == winner_amount for r in results if r[0] == "ok"))
            self.assertTrue(all(r[0] == "conflict" for r in results if r[2] != winner_amount))


if __name__ == "__main__":
    unittest.main()
