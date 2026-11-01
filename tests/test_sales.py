"""Integridad de ventas, inventario asociado y pagos de clientes."""

from contextlib import closing
import shutil
import sqlite3
import tempfile
import unittest
from uuid import uuid4
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.errors import ConflictError, DataIntegrityError, NotFoundError, ValidationError
from dragontech_manager.services.inventory import InventoryService
from dragontech_manager.services.proposals import ProposalService
from dragontech_manager.services.sales import SalesService


class SalesServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.version = migrate(self.connection)
        self.customers = CustomerService(self.connection)
        self.inventory = InventoryService(self.connection)
        self.proposals = ProposalService(self.connection)
        self.sales = SalesService(self.connection)
        self.customer = self.customers.create_customer("Cliente de venta")
        self.product = self.inventory.create_product(
            sku="MOUSE-1", name="Mouse histórico", unit_cost_cop=20_000,
            suggested_price_cop=35_000,
        )
        self.inventory.adjust_stock(self.product["id"], 5, unit_cost_cop=20_000,
                                     reason="Existencia inicial de prueba", idempotency_key=uuid4().hex)

    def inventory_line(self, quantity=1, price=35_000):
        return {"description": "Mouse histórico", "quantity": quantity,
                "unit_price_cop": price, "product_id": self.product["id"]}

    def test_migration_seven_adds_idempotency_and_conversion_constraints(self) -> None:
        self.assertEqual(self.version, 11)
        sale_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(ventas)")}
        line_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(venta_detalles)")}
        payment_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(pagos_clientes)")}
        self.assertIn("clave_idempotencia", sale_columns)
        self.assertIn("huella_solicitud", sale_columns)
        self.assertIn("cotizacion_detalle_id", line_columns)
        self.assertIn("clave_idempotencia", payment_columns)

    def test_migration_from_six_preserves_sales_and_financial_history(self) -> None:
        migrations = Path(__file__).parents[1] / "src/dragontech_manager/database/migrations"
        with tempfile.TemporaryDirectory() as directory:
            old_dir = Path(directory)
            for version in range(1, 7):
                shutil.copyfile(next(migrations.glob(f"{version:04d}_*.sql")),
                                old_dir / next(migrations.glob(f"{version:04d}_*.sql")).name)
            with closing(open_database(":memory:")) as connection:
                self.assertEqual(migrate(connection, old_dir), 6)
                customer = CustomerService(connection).create_customer("Cliente legado")
                connection.execute(
                    "INSERT INTO ventas (codigo, cliente_id, fecha_venta, creado_en_utc) VALUES ('LEGACY-SALE', ?, '2026-10-24', '2026-10-24T12:00:00Z')",
                    (customer["id"],),
                )
                connection.execute(
                    "INSERT INTO venta_detalles (venta_id, descripcion, cantidad, precio_unitario_cop) VALUES (1, 'Línea legado', 1, 9000)"
                )
                connection.execute(
                    "INSERT INTO pagos_clientes (venta_id, importe_cop, tipo, metodo, registrado_en_utc) VALUES (1, 1000, 'recibo', 'Efectivo', '2026-10-24T12:00:00Z')"
                )
                connection.commit()
                self.assertEqual(migrate(connection, migrations), 11)
                self.assertEqual(connection.execute("SELECT codigo FROM ventas WHERE id=1").fetchone()[0], "LEGACY-SALE")
                self.assertEqual(connection.execute("SELECT saldo_pendiente_cop FROM v_saldos_ventas WHERE venta_id=1").fetchone()[0], 8000)

    def test_direct_sale_with_multiple_lines_snapshots_prices_and_decrements_once(self) -> None:
        lines = [self.inventory_line(2, 40_000),
                 {"description": "Instalación", "quantity": 1, "unit_price_cop": 15_000}]
        sale = self.sales.create_sale(self.customer["id"], lines, idempotency_key="sale-ui-001",
                                      sale_date="2026-10-24")
        self.assertEqual(sale["importe_acordado_cop"], 95_000)
        self.assertEqual(len(sale["lineas"]), 2)
        self.assertEqual(sale["lineas"][0]["costo_unitario_historico_cop"], 20_000)
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 3)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM movimientos_inventario WHERE venta_detalle_id IS NOT NULL"
        ).fetchone()[0], 1)
        self.inventory.update_product(self.product["id"], sku="MOUSE-1", name="Mouse nuevo",
                                      unit_cost_cop=29_000, suggested_price_cop=50_000)
        refreshed = self.sales.get_sale(sale["id"])
        self.assertEqual(refreshed["lineas"][0]["descripcion"], "Mouse histórico")
        self.assertEqual(refreshed["lineas"][0]["costo_unitario_historico_cop"], 20_000)

    def test_sale_retry_is_idempotent_and_key_cannot_be_reused_for_other_payload(self) -> None:
        line = self.inventory_line()
        original = self.sales.create_sale(self.customer["id"], [line], idempotency_key="retry-sale")
        repeated = self.sales.create_sale(self.customer["id"], [line], idempotency_key="retry-sale")
        self.assertEqual(repeated["id"], original["id"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1)
        with self.assertRaises(ConflictError):
            self.sales.create_sale(self.customer["id"], [self.inventory_line(price=36_000)],
                                   idempotency_key="retry-sale")
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 4)

    def test_insufficient_stock_rolls_back_sale_lines_reservations_and_movements(self) -> None:
        with self.assertRaises(ConflictError):
            self.sales.create_sale(self.customer["id"], [self.inventory_line(quantity=6)],
                                   idempotency_key="insufficient")
        for table in ("ventas", "venta_detalles", "reservas_inventario"):
            self.assertEqual(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 5)

    def test_two_sales_competing_for_same_stock_cannot_oversell(self) -> None:
        self.sales.create_sale(self.customer["id"], [self.inventory_line(quantity=4)],
                               idempotency_key="compete-a")
        with self.assertRaises(ConflictError):
            self.sales.create_sale(self.customer["id"], [self.inventory_line(quantity=2)],
                                   idempotency_key="compete-b")
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 1)

    def test_validation_rejects_invalid_lines_and_missing_customer(self) -> None:
        with self.assertRaises(ValidationError):
            self.sales.create_sale(self.customer["id"], [self.inventory_line(quantity=0)], idempotency_key="bad-qty")
        with self.assertRaises(ValidationError):
            self.sales.create_sale(self.customer["id"], [self.inventory_line(price=1.5)], idempotency_key="bad-price")
        with self.assertRaises(NotFoundError):
            self.sales.create_sale(999, [self.inventory_line()], idempotency_key="bad-customer")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)

    def _accepted_proposal(self, *, product_id=None):
        line = {"description": "Servicio acordado", "quantity": 1,
                "unit_price_cop": 70_000, "product_id": product_id}
        proposal = self.proposals.create_proposal(self.customer["id"], [line])
        self.proposals.transition_proposal(proposal["id"], "enviada")
        return self.proposals.transition_proposal(proposal["id"], "aceptada")

    def test_accepted_proposal_converts_atomically_and_preserves_concepts(self) -> None:
        proposal = self._accepted_proposal(product_id=self.product["id"])
        sale = self.sales.convert_accepted_proposal(proposal["id"], idempotency_key="convert-1")
        self.assertEqual(sale["cotizacion_id"], proposal["id"])
        self.assertEqual(sale["lineas"][0]["descripcion"], "Servicio acordado")
        self.assertEqual(sale["lineas"][0]["precio_unitario_cop"], 70_000)
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 4)
        self.assertEqual(self.proposals.get_proposal(proposal["id"])["estado"], "convertida")
        self.assertEqual(self.proposals.proposal_history(proposal["id"])[-1]["estado_nuevo"], "convertida")

    def test_converted_noninventory_proposal_does_not_create_stock_movements(self) -> None:
        proposal = self._accepted_proposal()
        before = self.inventory.get_product(self.product["id"])["existencia"]
        sale = self.sales.convert_accepted_proposal(proposal["id"], idempotency_key="service-conversion")
        self.assertIsNone(sale["lineas"][0]["producto_id"])
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], before)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM movimientos_inventario WHERE venta_detalle_id IN (SELECT id FROM venta_detalles WHERE venta_id=?)",
            (sale["id"],),
        ).fetchone()[0], 0)

    def test_accepting_proposal_does_not_decrement_stock_and_unaccepted_is_not_convertible(self) -> None:
        proposal = self.proposals.create_proposal(self.customer["id"], [
            {"description": "Mouse acordado", "quantity": 1, "unit_price_cop": 35_000,
             "product_id": self.product["id"]}
        ])
        self.proposals.transition_proposal(proposal["id"], "enviada")
        self.proposals.transition_proposal(proposal["id"], "aceptada")
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 5)
        other = self.proposals.create_proposal(self.customer["id"], [
            {"description": "No aceptada", "quantity": 1, "unit_price_cop": 1}
        ])
        with self.assertRaises(ConflictError):
            self.sales.convert_accepted_proposal(other["id"], idempotency_key="not-accepted")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 0)

    def test_proposal_conversion_cannot_be_duplicated_and_failure_rolls_back_everything(self) -> None:
        proposal = self._accepted_proposal(product_id=self.product["id"])
        sale = self.sales.convert_accepted_proposal(proposal["id"], idempotency_key="convert-repeat")
        self.assertEqual(self.sales.convert_accepted_proposal(
            proposal["id"], idempotency_key="convert-repeat")["id"], sale["id"])
        with self.assertRaises(ConflictError):
            self.sales.convert_accepted_proposal(proposal["id"], idempotency_key="new-convert-key")

        second = self._accepted_proposal(product_id=self.product["id"])
        self.connection.execute("""CREATE TRIGGER fail_sale_conversion BEFORE UPDATE OF estado ON cotizaciones
            WHEN NEW.estado = 'convertida' BEGIN SELECT RAISE(ABORT, 'failure'); END""")
        with self.assertRaises(DataIntegrityError):
            self.sales.convert_accepted_proposal(second["id"], idempotency_key="rollback-convert")
        self.assertIsNone(self.connection.execute("SELECT id FROM ventas WHERE cotizacion_id = ?", (second["id"],)).fetchone())
        self.assertEqual(self.proposals.get_proposal(second["id"])["estado"], "aceptada")
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 4)

    def test_payment_partials_full_balance_reversal_and_retry(self) -> None:
        sale = self.sales.create_sale(self.customer["id"], [self.inventory_line(2, 30_000)],
                                      idempotency_key="payments-sale")
        first = self.sales.register_payment(sale["id"], 20_000, method="Efectivo", idempotency_key="pay-one")
        self.assertEqual(first["venta"]["saldo_pendiente_cop"], 40_000)
        repeated = self.sales.register_payment(sale["id"], 20_000, method="Efectivo", idempotency_key="pay-one")
        self.assertTrue(repeated["repetido"])
        second = self.sales.register_payment(sale["id"], 40_000, method="Transferencia", idempotency_key="pay-two")
        self.assertEqual(second["venta"]["estado_cobro"], "completada")
        with self.assertRaises(ValidationError):
            self.sales.register_payment(sale["id"], 1, method="Efectivo", idempotency_key="overpay")
        reversal = self.sales.reverse_payment(first["pago"]["id"], reason="Pago registrado por error", nature="correccion_registro_erroneo", source="operador", evidence="Comprobante inexistente")
        self.assertEqual(reversal["venta"]["pagado_neto_cop"], 40_000)
        self.assertEqual(reversal["venta"]["saldo_pendiente_cop"], 20_000)
        self.assertEqual(len(self.sales.get_sale(sale["id"])["pagos"]), 3)
        with self.assertRaises(ConflictError):
            self.sales.reverse_payment(first["pago"]["id"], reason="Segundo intento", nature="correccion_registro_erroneo", source="operador", evidence="Comprobante inexistente")

    def test_invalid_payment_amount_and_non_sales_payment_are_rejected(self) -> None:
        sale = self.sales.create_sale(self.customer["id"], [self.inventory_line()], idempotency_key="payment-validation")
        with self.assertRaises(ValidationError):
            self.sales.register_payment(sale["id"], 0, method="Efectivo", idempotency_key="zero")
        with self.assertRaises(ValidationError):
            self.sales.register_payment(sale["id"], True, method="Efectivo", idempotency_key="bool")
        # El módulo de ventas no enruta pagos a órdenes ni crea ventas paralelas para ellas.
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], 1)

    def test_stock_movement_duplicate_is_blocked_and_sale_lines_are_immutable(self) -> None:
        sale = self.sales.create_sale(self.customer["id"], [self.inventory_line()], idempotency_key="immutable-sale")
        detail = sale["lineas"][0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO movimientos_inventario
                   (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                    venta_detalle_id, creado_en_utc, motivo, fecha_negocio)
                   VALUES (?, -1, 20000, 'venta', ?, '2026-10-24T12:00:00Z', 'Doble salida', '2026-10-24')""",
                (self.product["id"], detail["id"]),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("UPDATE venta_detalles SET precio_unitario_cop=1 WHERE id=?", (detail["id"],))

    def test_list_search_state_date_and_sales_payments_do_not_touch_order_payments(self) -> None:
        sale = self.sales.create_sale(self.customer["id"], [self.inventory_line()], idempotency_key="filter-sale",
                                      sale_date="2026-10-24")
        self.sales.register_payment(sale["id"], sale["importe_acordado_cop"], method="Tarjeta", idempotency_key="filter-pay")
        rows = self.sales.list_sales(search="Cliente de venta", state="completada",
                                    date_from="2026-10-24", date_to="2026-10-24")
        self.assertEqual(rows[0]["id"], sale["id"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM pagos_clientes WHERE orden_id IS NOT NULL").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
