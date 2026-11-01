"""Catálogo de métodos de pago y fecha de negocio (Fase 1, Entrega 1)."""

import shutil
import sqlite3
import tempfile
import unittest
from uuid import uuid4
from contextlib import closing
from pathlib import Path
from unittest import mock

from dragontech_manager.business_date import business_date_from_utc
from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.errors import ConflictError, ValidationError
from dragontech_manager.services.inventory import InventoryService
from dragontech_manager.services.payment_methods import PaymentMethodService
from dragontech_manager.services.procurement import ProcurementService
from dragontech_manager.services.sales import SalesService

MIGRATIONS = Path(__file__).parents[1] / "src/dragontech_manager/database/migrations"
NIGHT_UTC = "2026-10-25T04:30:00Z"  # 23:30 del 24 en Bogotá


class PaymentMethodTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.methods = PaymentMethodService(self.connection)
        self.sales = SalesService(self.connection)
        customer = CustomerService(self.connection).create_customer("Cliente métodos")
        self.sale = self.sales.create_sale(
            customer["id"], [{"description": "Servicio", "quantity": 1, "unit_price_cop": 50_000}],
            idempotency_key="methods-sale",
        )

    def test_catalog_scopes_and_legacy_csx(self) -> None:
        client = {m["codigo"] for m in self.methods.list_methods("cliente")}
        supplier = {m["codigo"] for m in self.methods.list_methods("proveedor")}
        self.assertEqual(client, {"EFECTIVO", "TRANSFERENCIA", "TARJETA", "OTRO"})
        self.assertEqual(supplier, client | {"CSX"})
        with self.assertRaises(ValidationError):
            self.methods.resolve("CSX", "cliente")
        with self.assertRaises(ValidationError):
            self.methods.resolve("Nequi", "cliente")
        self.assertEqual(self.methods.resolve("tarjeta de débito", "cliente")["codigo"], "TARJETA")

    def test_payment_stores_catalog_method_and_night_business_date(self) -> None:
        with mock.patch("dragontech_manager.services.sales.timestamp_and_business_year",
                        return_value=(NIGHT_UTC, 2026)):
            result = self.sales.register_payment(
                self.sale["id"], 10_000, method="efectivo", idempotency_key="night-pay")
            reversal = self.sales.reverse_payment(result["pago"]["id"], reason="Error de captura", nature="correccion_registro_erroneo", source="operador", evidence="Sin abono en extracto")
        payment = result["pago"]
        self.assertEqual(payment["metodo"], "Efectivo")
        self.assertEqual(payment["fecha_negocio"], "2026-10-24")
        self.assertEqual(payment["registrado_en_utc"], NIGHT_UTC)
        self.assertEqual(reversal["pago"]["metodo_pago_id"], payment["metodo_pago_id"])
        self.assertEqual(reversal["pago"]["fecha_negocio"], "2026-10-24")

    def test_retry_with_other_method_conflicts(self) -> None:
        self.sales.register_payment(self.sale["id"], 5_000, method="Efectivo", idempotency_key="same")
        again = self.sales.register_payment(self.sale["id"], 5_000, method="EFECTIVO", idempotency_key="same")
        self.assertTrue(again["repetido"])
        with self.assertRaises(ConflictError):
            self.sales.register_payment(self.sale["id"], 5_000, method="Tarjeta", idempotency_key="same")

    def test_database_rejects_missing_or_future_business_date_and_bad_method(self) -> None:
        sql = """INSERT INTO pagos_clientes
                 (venta_id, importe_cop, tipo, metodo, metodo_pago_id, registrado_en_utc, fecha_negocio)
                 VALUES (1, 100, 'recibo', 'Efectivo', ?, '2026-10-24T15:30:00Z', ?)"""
        efectivo = self.methods.resolve("Efectivo", "cliente")["id"]
        csx = self.connection.execute("SELECT id FROM metodos_pago WHERE codigo='CSX'").fetchone()[0]
        for args in ((efectivo, None), (efectivo, "2026-10-25"), (None, "2026-10-24"), (csx, "2026-10-24")):
            with self.subTest(args=args), self.assertRaises(sqlite3.IntegrityError):
                self.connection.execute(sql, args)
        with self.assertRaises(sqlite3.IntegrityError):  # texto distinto del catálogo
            self.connection.execute(sql.replace("'Efectivo'", "'efectivo'"), (efectivo, "2026-10-24"))
        self.connection.execute(sql, (efectivo, "2026-10-23"))  # fecha anterior permitida

    def test_catalog_is_not_deletable_and_identity_is_stable(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM metodos_pago WHERE codigo='CSX'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("UPDATE metodos_pago SET nombre='X' WHERE codigo='CSX'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM metodos_pago_alias")
        self.connection.execute("UPDATE metodos_pago SET activo=0 WHERE codigo='OTRO'")
        with self.assertRaises(ValidationError):
            self.methods.resolve("Otro", "cliente")

    def test_inventory_movement_has_business_date_and_requires_it(self) -> None:
        inventory = InventoryService(self.connection)
        product = inventory.create_product(sku="P-FECHA", name="Producto", unit_cost_cop=100,
                                           suggested_price_cop=200)
        with mock.patch("dragontech_manager.services.inventory.timestamp_and_business_year",
                        return_value=(NIGHT_UTC, 2026)):
            inventory.adjust_stock(product["id"], 3, unit_cost_cop=100, reason="Conteo nocturno", idempotency_key=uuid4().hex)
        row = self.connection.execute(
            "SELECT creado_en_utc, fecha_negocio FROM movimientos_inventario").fetchone()
        self.assertEqual((row[0], row[1]), (NIGHT_UTC, "2026-10-24"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO movimientos_inventario
                   (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo, creado_en_utc, motivo)
                   VALUES (?, 1, 100, 'ajuste', ?, 'sin fecha')""", (product["id"], NIGHT_UTC))

    def test_supplier_payment_uses_catalog_and_accepts_legacy_csx(self) -> None:
        inventory = InventoryService(self.connection)
        procurement = ProcurementService(self.connection)
        supplier = inventory.create_supplier(name="Proveedor métodos")
        product = inventory.create_product(sku="P-PROV", name="Prod", unit_cost_cop=1000,
                                           suggested_price_cop=2000)
        purchase = procurement.create_purchase(supplier["id"], [
            {"product_id": product["id"], "quantity": 1, "unit_cost_cop": 10_000,
            "description": "Compra"}])
        procurement.transition_purchase(purchase["id"], "pendiente")
        payment = procurement.register_supplier_payment(purchase["id"], 4_000, method="csx", idempotency_key=uuid4().hex)
        self.assertEqual((payment["metodo"], payment["fecha_negocio"] is not None), ("CSX", True))
        with self.assertRaises(ValidationError):
            procurement.register_supplier_payment(purchase["id"], 1_000, method="Desconocido", idempotency_key=uuid4().hex)

    def test_migration_keeps_legacy_rows_unmodified_and_views_resolve_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory)
            for version in range(1, 8):
                path = next(MIGRATIONS.glob(f"{version:04d}_*.sql"))
                shutil.copyfile(path, old / path.name)
            with closing(open_database(":memory:")) as connection:
                self.assertEqual(migrate(connection, old), 7)
                customer = CustomerService(connection).create_customer("Legado")
                connection.execute(
                    "INSERT INTO ventas (codigo, cliente_id, fecha_venta, creado_en_utc) VALUES ('L-1', ?, '2026-10-24', '2026-10-24T12:00:00Z')",
                    (customer["id"],))
                connection.execute(
                    "INSERT INTO venta_detalles (venta_id, descripcion, cantidad, precio_unitario_cop) VALUES (1, 'x', 1, 9000)")
                connection.execute(
                    "INSERT INTO pagos_clientes (venta_id, importe_cop, tipo, metodo, registrado_en_utc) VALUES (1, 1000, 'recibo', 'Tarjeta', ?)",
                    (NIGHT_UTC,))
                connection.commit()
                self.assertEqual(migrate(connection, MIGRATIONS), 11)
                raw = connection.execute("SELECT metodo_pago_id, fecha_negocio FROM pagos_clientes").fetchone()
                self.assertEqual((raw[0], raw[1]), (None, None))
                view = connection.execute(
                    """SELECT v.fecha_negocio_efectiva, v.fecha_derivada, m.codigo
                       FROM v_pagos_clientes_contables v
                       JOIN metodos_pago m ON m.id = v.metodo_pago_id_efectivo""").fetchone()
                self.assertEqual(tuple(view), ("2026-10-24", 1, "TARJETA"))

    def test_business_date_helper_handles_midnight_boundary(self) -> None:
        self.assertEqual(business_date_from_utc("2026-10-25T04:59:59Z"), "2026-10-24")
        self.assertEqual(business_date_from_utc("2026-10-25T05:00:00Z"), "2026-10-25")


if __name__ == "__main__":
    unittest.main()
