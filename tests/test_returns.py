"""Devoluciones y cancelaciones de ventas (Fase 1, Entrega 4)."""

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.errors import ConflictError, ValidationError
from dragontech_manager.services.inventory import InventoryService
from dragontech_manager.services.returns import ReturnsService
from dragontech_manager.services.sales import SalesService

WHO = dict(requester="Cliente Uno", requester_type="cliente", executor="Ana")


def reversal(**kw):
    return dict(nature="correccion_registro_erroneo", source="operador", evidence="Extracto", **kw)


def make_world(connection):
    inventory = InventoryService(connection)
    sales = SalesService(connection)
    customer = CustomerService(connection).create_customer("Cliente de devolución")
    mouse = inventory.create_product(sku="MOUSE", name="Mouse", unit_cost_cop=20_000, suggested_price_cop=35_000)
    inventory.adjust_stock(mouse["id"], 10, unit_cost_cop=20_000, reason="Stock inicial", idempotency_key="seed-mouse")
    return inventory, sales, customer, mouse


class ReturnsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.c = open_database(":memory:")
        self.addCleanup(self.c.close)
        migrate(self.c)
        self.inventory, self.sales, self.customer, self.mouse = make_world(self.c)
        self.returns = ReturnsService(self.c)
        # T = 3 × 30.000 (producto) + 1 × 10.000 (servicio) = 100.000
        self.sale = self.sales.create_sale(self.customer["id"], [
            {"description": "Mouse", "quantity": 3, "unit_price_cop": 30_000, "product_id": self.mouse["id"]},
            {"description": "Configuración", "quantity": 1, "unit_price_cop": 10_000},
        ], idempotency_key="sale-ret")
        self.mouse_line, self.service_line = [l["id"] for l in self.sale["lineas"]]

    def stock(self):
        return self.inventory.get_product(self.mouse["id"])["existencia"]

    def pay(self, amount, key):
        return self.sales.register_payment(self.sale["id"], amount, method="Efectivo", idempotency_key=key)

    def ret(self, lines, key="r1", **extra):
        return self.returns.register_return(self.sale["id"], lines, reason="Cliente desiste",
                                            idempotency_key=key, **{**WHO, **extra})

    def balance(self):
        return self.sales.get_sale(self.sale["id"])

    def test_partial_return_restocks_apt_units_and_keeps_payment_history(self) -> None:
        self.pay(100_000, "p1")
        base = self.stock()
        out = self.ret([{"sale_line_id": self.mouse_line, "quantity": 2}])
        sale = out["venta"]
        self.assertEqual(self.stock(), base + 2)
        self.assertEqual((sale["devuelto_reconocido_cop"], sale["importe_neto_cop"]), (60_000, 40_000))
        self.assertEqual((sale["pagado_neto_cop"], sale["sobrepago_pendiente_cop"], sale["saldo_pendiente_cop"]),
                         (100_000, 60_000, 0))
        self.assertEqual((sale["estado_devolucion"], sale["estado_cobro"]), ("parcial", "reembolso_pendiente"))
        move = self.c.execute("SELECT * FROM movimientos_inventario WHERE devolucion_venta_linea_id IS NOT NULL").fetchone()
        self.assertEqual((move["tipo"], move["cantidad_delta"], move["costo_unitario_historico_cop"]), ("ajuste", 2, 20_000))
        self.assertIsNotNone(move["fecha_negocio"])
        self.assertEqual(len(sale["pagos"]), 1)  # el pago original no se toca

    def test_return_does_not_require_compensation_when_customer_still_owes(self) -> None:  # escenario H
        self.pay(20_000, "p1")
        sale = self.ret([{"sale_line_id": self.mouse_line, "quantity": 2}])["venta"]
        self.assertEqual((sale["importe_neto_cop"], sale["saldo_pendiente_cop"], sale["sobrepago_pendiente_cop"]),
                         (40_000, 20_000, 0))
        self.assertEqual(sale["estado_cobro"], "parcial")

    def test_total_return_of_unpaid_sale_is_cancelled_and_blocks_payments(self) -> None:
        out = self.ret([{"sale_line_id": self.mouse_line, "quantity": 3},
                        {"sale_line_id": self.service_line, "quantity": 1}])
        sale = out["venta"]
        self.assertEqual((sale["estado_devolucion"], sale["estado_cobro"], sale["saldo_pendiente_cop"]),
                         ("total", "cancelada", 0))
        with self.assertRaises(Exception):
            self.pay(1, "late")
        with self.assertRaises(sqlite3.IntegrityError):  # R4 también en base de datos
            self.c.execute("""INSERT INTO pagos_clientes (venta_id, importe_cop, tipo, metodo, metodo_pago_id,
                              registrado_en_utc, fecha_negocio) VALUES (?, 1, 'recibo', 'Efectivo', 1,
                              '2026-10-31T12:00:00Z', '2026-10-31')""", (self.sale["id"],))
        with self.assertRaises(ValidationError):
            self.ret([{"sale_line_id": self.mouse_line, "quantity": 1}], key="r2")

    def test_total_return_of_paid_sale_leaves_refund_pending(self) -> None:
        self.pay(100_000, "p1")
        sale = self.ret([{"sale_line_id": self.mouse_line, "quantity": 3},
                         {"sale_line_id": self.service_line, "quantity": 1}])["venta"]
        self.assertEqual((sale["estado_devolucion"], sale["estado_cobro"], sale["sobrepago_pendiente_cop"]),
                         ("total", "reembolso_pendiente", 100_000))

    def test_mixed_units_restock_only_apt_and_report_loss(self) -> None:
        base = self.stock()
        out = self.ret([{"sale_line_id": self.mouse_line, "quantity": 3, "restock_quantity": 2,
                         "condition": "danado", "no_restock_reason": "Pantalla quebrada"}])
        self.assertEqual(self.stock(), base + 2)
        self.assertEqual(out["venta"]["devuelto_reconocido_cop"], 90_000)
        loss = self.returns.lost_inventory(self.sale["id"])
        self.assertEqual(len(loss), 1)
        self.assertEqual((loss[0]["cantidad_no_apta"], loss[0]["costo_perdida_cop"], loss[0]["condicion"]),
                         (1, 20_000, "danado"))
        with self.assertRaises(ValidationError):  # no apto sin condición/motivo
            self.ret([{"sale_line_id": self.service_line, "quantity": 1, "restock_quantity": 1}], key="x")

    def test_fully_unfit_return_creates_no_movement(self) -> None:
        base, moves = self.stock(), self.c.execute("SELECT COUNT(*) FROM movimientos_inventario").fetchone()[0]
        self.ret([{"sale_line_id": self.mouse_line, "quantity": 1, "restock_quantity": 0,
                   "condition": "incompleto", "no_restock_reason": "Sin cargador"}])
        self.assertEqual(self.stock(), base)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM movimientos_inventario").fetchone()[0], moves)

    def test_reduced_recognized_value_requires_reason_and_distinct_authorizer(self) -> None:
        line = {"sale_line_id": self.mouse_line, "quantity": 1, "recognized_value_cop": 15_000}
        with self.assertRaises(ValidationError):  # sin motivo ni autorizador
            self.ret([line], key="a")
        line["value_adjustment_reason"] = "Caja abierta"
        with self.assertRaises(ValidationError):  # sin autorizador
            self.ret([line], key="b")
        with self.assertRaises(ValidationError):  # autorizador = ejecutor
            self.ret([line], key="c", authorizer="ana", authorization_ref="AUT-1")
        out = self.ret([line], key="d", authorizer="Supervisor", authorization_ref="AUT-1")
        self.assertEqual(out["venta"]["devuelto_reconocido_cop"], 15_000)
        self.assertEqual(out["devolucion"]["autorizador"], "Supervisor")

    def test_cumulative_quantity_limit_across_returns(self) -> None:  # R1
        self.ret([{"sale_line_id": self.mouse_line, "quantity": 2}], key="r1")
        with self.assertRaises(ValidationError):
            self.ret([{"sale_line_id": self.mouse_line, "quantity": 2}], key="r2")
        self.ret([{"sale_line_id": self.mouse_line, "quantity": 1}], key="r3")
        self.assertEqual(self.returns.returnable_lines(self.sale["id"])[0]["cantidad_disponible"], 0)

    def test_payment_limit_uses_net_of_returns(self) -> None:  # R4 / I3
        self.pay(40_000, "p1")
        self.ret([{"sale_line_id": self.mouse_line, "quantity": 2}])  # neto 40.000, pagado 40.000
        with self.assertRaises(ValidationError):
            self.pay(1, "p2")

    def test_idempotent_retry_conflict_and_no_partial_writes(self) -> None:
        lines = [{"sale_line_id": self.mouse_line, "quantity": 1}]
        first = self.ret(lines, key="same")
        again = self.ret(lines, key="same")
        self.assertTrue(again["repetido"])
        self.assertEqual(first["devolucion"]["id"], again["devolucion"]["id"])
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM cancelaciones_venta").fetchone()[0], 1)
        with self.assertRaises(ConflictError):
            self.ret([{"sale_line_id": self.mouse_line, "quantity": 2}], key="same")
        # fallo a mitad: la segunda línea viola un trigger -> nada queda escrito
        self.c.execute("""CREATE TRIGGER falla_linea_servicio BEFORE INSERT ON cancelacion_venta_lineas
                          WHEN NEW.venta_detalle_id = %d BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END""" % self.service_line)
        before = (self.c.execute("SELECT COUNT(*) FROM cancelaciones_venta").fetchone()[0],
                  self.c.execute("SELECT COUNT(*) FROM movimientos_inventario").fetchone()[0], self.stock())
        with self.assertRaises(Exception):
            self.ret([{"sale_line_id": self.mouse_line, "quantity": 1},
                      {"sale_line_id": self.service_line, "quantity": 1}], key="boom")
        self.assertEqual((self.c.execute("SELECT COUNT(*) FROM cancelaciones_venta").fetchone()[0],
                          self.c.execute("SELECT COUNT(*) FROM movimientos_inventario").fetchone()[0], self.stock()), before)
        self.assertFalse(self.c.in_transaction)

    def test_retry_after_exhausting_the_line_still_returns_original(self) -> None:
        lines = [{"sale_line_id": self.mouse_line, "quantity": 3}]
        first = self.ret(lines, key="all")
        again = self.ret(lines, key="all")  # ya no hay unidades disponibles, pero es el mismo intento
        self.assertTrue(again["repetido"])
        self.assertEqual(first["devolucion"]["id"], again["devolucion"]["id"])

    def test_records_are_immutable_and_return_movement_is_not_generically_reversible(self) -> None:
        out = self.ret([{"sale_line_id": self.mouse_line, "quantity": 1}])
        for sql in ("UPDATE cancelaciones_venta SET motivo='x'", "DELETE FROM cancelaciones_venta",
                    "UPDATE cancelacion_venta_lineas SET cantidad_devuelta=1", "DELETE FROM cancelacion_venta_lineas"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.c.execute(sql)
        movement = self.c.execute("SELECT id FROM movimientos_inventario WHERE devolucion_venta_linea_id IS NOT NULL").fetchone()[0]
        self.assertIsNotNone(self.inventory.reversal_blocked_reason(movement))
        with self.assertRaises(ConflictError):
            self.inventory.reverse_movement(movement, reason="intento", idempotency_key="rev-dev")
        with self.assertRaises(sqlite3.IntegrityError):  # trigger, aunque se salte el servicio
            self.c.execute("""INSERT INTO movimientos_inventario (producto_id, cantidad_delta, costo_unitario_historico_cop,
                              tipo, reversa_movimiento_id, creado_en_utc, motivo, fecha_negocio)
                              VALUES (?, -1, 20000, 'reversion', ?, '2026-10-31T12:00:00Z', 'x', '2026-10-31')""",
                           (self.mouse["id"], movement))
        self.assertEqual(out["devolucion"]["lineas"][0]["cantidad_reintegrada"], 1)

    def test_payment_reversal_requires_classification(self) -> None:
        pay = self.pay(10_000, "p1")["pago"]
        for kwargs in ({"nature": "otra", "source": "banco", "evidence": "x"},
                       {"nature": "reversion_financiera_real", "source": "nadie", "evidence": "x"},
                       {"nature": "reversion_financiera_real", "source": "banco", "evidence": " "}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.sales.reverse_payment(pay["id"], reason="Contracargo", **kwargs)
        with self.assertRaises(sqlite3.IntegrityError):  # trigger en inserción directa
            self.c.execute("""INSERT INTO pagos_clientes (venta_id, importe_cop, tipo, metodo, metodo_pago_id,
                              registrado_en_utc, fecha_negocio, reversa_pago_id, motivo)
                              VALUES (?, 10000, 'reversion', 'Efectivo', 1, '2026-10-31T12:00:00Z', '2026-10-31', ?, 'x')""",
                           (self.sale["id"], pay["id"]))
        rev = self.sales.reverse_payment(pay["id"], reason="Contracargo bancario", nature="reversion_financiera_real",
                                         source="banco", evidence="Extracto 2026-10-31")["pago"]
        self.assertEqual((rev["naturaleza_reversion"], rev["origen_evento"]), ("reversion_financiera_real", "banco"))
        self.assertEqual(self.balance()["pagado_neto_cop"], 0)
        self.assertEqual(self.sales.get_sale(self.sale["id"])["pagos"][0]["importe_cop"], 10_000)  # original intacto


class ReturnsConcurrencyTests(unittest.TestCase):
    def test_parallel_same_key_registers_one_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "db.sqlite3")
            setup = open_database(path)
            migrate(setup)
            inventory, sales, customer, mouse = make_world(setup)
            sale = sales.create_sale(customer["id"], [{"description": "Mouse", "quantity": 3, "unit_price_cop": 30_000,
                                                        "product_id": mouse["id"]}], idempotency_key="s")
            line = sale["lineas"][0]["id"]
            setup.close()
            results, barrier = [], threading.Barrier(5)

            def worker() -> None:
                connection = open_database(path)
                barrier.wait()
                try:
                    out = ReturnsService(connection).register_return(
                        sale["id"], [{"sale_line_id": line, "quantity": 2}], reason="x",
                        idempotency_key="race", **WHO)
                    results.append(out["devolucion"]["id"])
                finally:
                    connection.close()

            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads: t.start()
            for t in threads: t.join()
            check = open_database(path)
            self.addCleanup(check.close)
            self.assertEqual(len(set(results)), 1)
            self.assertEqual(len(results), 5)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM cancelaciones_venta").fetchone()[0], 1)
            self.assertEqual(check.execute("SELECT COUNT(*) FROM movimientos_inventario WHERE devolucion_venta_linea_id IS NOT NULL").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
