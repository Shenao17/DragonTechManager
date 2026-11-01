"""Reglas de inventario, proveedores, compras y pagos en SQLite temporal."""

from contextlib import closing
import shutil
import sqlite3
import tempfile
import unittest
from uuid import uuid4
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.errors import ConflictError, DataIntegrityError, NotFoundError, ValidationError
from dragontech_manager.services.inventory import InventoryService
from dragontech_manager.services.procurement import ProcurementService


class InventoryProcurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.version = migrate(self.connection)
        self.inventory = InventoryService(self.connection)
        self.procurement = ProcurementService(self.connection)
        self.supplier = self.inventory.create_supplier(
            name="Proveedor de pruebas", tax_id="NIT-TEST-1", phone="3000000000",
            email="compras@example.test", address="Dirección test",
        )
        self.product = self.inventory.create_product(
            sku="RAM-16", name="Memoria de prueba", description="Módulo de prueba",
            category="Componentes", unit_cost_cop=100_000,
            suggested_price_cop=140_000, minimum_stock=2,
        )

    def test_migration_six_adds_fields_and_guards_stock(self) -> None:
        self.assertEqual(self.version, 11)
        product_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(productos)")}
        supplier_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(proveedores)")}
        detail_columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(compra_detalles)")}
        self.assertIn("categoria", product_columns)
        self.assertIn("direccion", supplier_columns)
        self.assertIn("descripcion_historica", detail_columns)
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO movimientos_inventario
                   (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo, creado_en_utc, motivo, fecha_negocio)
                   VALUES (?, -1, 1000, 'ajuste', '2026-10-24T15:30:00Z', 'prueba', '2026-10-24')""",
                (self.product["id"],),
            )
        self.connection.execute(
            "INSERT INTO compras (proveedor_id, fecha_compra, estado, creado_en_utc) VALUES (1, '2026-10-24', 'recibida', '2026-10-24T15:30:00Z')"
        )
        self.connection.execute(
            "INSERT INTO compra_detalles (compra_id, producto_id, cantidad, costo_unitario_historico_cop) VALUES (1, ?, 1, 1000)",
            (self.product["id"],),
        )
        with self.assertRaisesRegex(sqlite3.IntegrityError, "requiere un motivo"):
            self.connection.execute(
                """INSERT INTO movimientos_inventario
                   (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                    compra_detalle_id, creado_en_utc, fecha_negocio)
                   VALUES (?, 1, 1000, 'compra', 1, '2026-10-24T15:30:00Z', '2026-10-24')""",
                (self.product["id"],),
            )

    def test_migration_from_version_five_preserves_catalog_and_purchase_history(self) -> None:
        migrations = Path(__file__).parents[1] / "src/dragontech_manager/database/migrations"
        with tempfile.TemporaryDirectory() as directory:
            old_dir = Path(directory)
            for version in range(1, 6):
                source = next(migrations.glob(f"{version:04d}_*.sql"))
                shutil.copyfile(source, old_dir / source.name)
            with closing(open_database(":memory:")) as connection:
                self.assertEqual(migrate(connection, old_dir), 5)
                connection.execute(
                    "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('Cliente test', ?, ?)",
                    ("2026-10-24T15:30:00Z", "2026-10-24T15:30:00Z"),
                )
                connection.execute(
                    "INSERT INTO productos (sku, nombre, creado_en_utc) VALUES ('SKU-OLD', 'Producto anterior', ?)",
                    ("2026-10-24T15:30:00Z",),
                )
                connection.execute(
                    "INSERT INTO proveedores (nombre, creado_en_utc) VALUES ('Proveedor anterior', ?)",
                    ("2026-10-24T15:30:00Z",),
                )
                connection.execute(
                    "INSERT INTO compras (proveedor_id, fecha_compra, creado_en_utc) VALUES (1, '2026-10-24', ?)",
                    ("2026-10-24T15:30:00Z",),
                )
                connection.execute(
                    "INSERT INTO compra_detalles (compra_id, producto_id, cantidad, costo_unitario_historico_cop) VALUES (1, 1, 2, 8000)"
                )
                connection.commit()
                self.assertEqual(migrate(connection, migrations), 11)
                self.assertEqual(connection.execute("SELECT nombre FROM productos WHERE id=1").fetchone()[0], "Producto anterior")
                self.assertEqual(connection.execute("SELECT cantidad FROM compra_detalles WHERE id=1").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT descripcion_historica FROM compra_detalles WHERE id=1").fetchone()[0], "")

    def test_product_create_edit_search_and_duplicate_sku(self) -> None:
        self.assertEqual(self.product["categoria"], "Componentes")
        self.assertEqual(self.product["existencia"], 0)
        with self.assertRaises(ConflictError):
            self.inventory.create_product(sku="ram-16", name="Duplicado")
        edited = self.inventory.update_product(
            self.product["id"], sku="ram-16a", name="Memoria editada",
            category="RAM", unit_cost_cop=120_000, suggested_price_cop=160_000,
        )
        self.assertEqual(edited["sku"], "RAM-16A")
        self.assertEqual(edited["nombre"], "Memoria editada")
        self.assertEqual(edited["umbral_reposicion"], 2)
        self.assertEqual(self.inventory.list_products(search="memoria")[0]["id"], self.product["id"])
        inactive = self.inventory.update_product(
            self.product["id"], sku="RAM-16A", name="Memoria editada", active=False,
        )
        self.assertFalse(inactive["activo"])
        self.assertEqual(len(self.inventory.list_products(active=False)), 1)
        self.assertEqual(len(self.inventory.list_products(active=None)), 1)

    def test_product_validates_required_fields_integer_prices_and_stock_filter(self) -> None:
        for kwargs in (
            {"sku": "bad sku", "name": "Nombre"},
            {"sku": "GOOD", "name": " "},
            {"sku": "GOOD", "name": "Nombre", "unit_cost_cop": -1},
            {"sku": "GOOD", "name": "Nombre", "suggested_price_cop": 1.5},
            {"sku": "GOOD", "name": "Nombre", "minimum_stock": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.inventory.create_product(**kwargs)
        with self.assertRaises(ValidationError):
            self.inventory.list_products(stock_filter="inventado")
        self.assertEqual(self.inventory.stock_summary(), {"total": 1, "agotados": 1, "bajos": 0})

    def test_adjustments_prevent_negative_stock_and_reversals_are_traceable_once(self) -> None:
        movement = self.inventory.adjust_stock(
            self.product["id"], 7, unit_cost_cop=95_000, reason="Conteo inicial documentado", idempotency_key=uuid4().hex)
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 7)
        out = self.inventory.adjust_stock(
            self.product["id"], -2, unit_cost_cop=95_000, reason="Daño registrado", idempotency_key=uuid4().hex)
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 5)
        with self.assertRaises(ConflictError):
            self.inventory.adjust_stock(self.product["id"], -6, unit_cost_cop=0, reason="No debe bajar de cero", idempotency_key=uuid4().hex)
        with self.assertRaises(ConflictError):
            self.inventory.reverse_movement(movement["id"], reason="Stock ya consumido", idempotency_key=uuid4().hex)
        reversal = self.inventory.reverse_movement(out["id"], reason="Corrección de la salida", idempotency_key=uuid4().hex)
        self.assertEqual(reversal["cantidad_delta"], 2)
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 7)

    def test_adjustment_reversal_that_would_make_stock_negative_is_rejected(self) -> None:
        movement = self.inventory.adjust_stock(
            self.product["id"], 4, unit_cost_cop=10_000, reason="Conteo positivo", idempotency_key=uuid4().hex)
        self.inventory.adjust_stock(
            self.product["id"], -3, unit_cost_cop=10_000, reason="Salida respaldada", idempotency_key=uuid4().hex)
        with self.assertRaises(ConflictError):
            self.inventory.reverse_movement(movement["id"], reason="El stock ya fue consumido", idempotency_key=uuid4().hex)
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 1)

    def test_adjustments_cannot_consume_units_reserved_for_a_service_order(self) -> None:
        self.inventory.adjust_stock(self.product["id"], 5, unit_cost_cop=100_000, reason="Entrada inicial", idempotency_key=uuid4().hex)
        utc = "2026-10-24T15:30:00Z"
        self.connection.execute(
            "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('Cliente interno', ?, ?)",
            (utc, utc),
        )
        self.connection.execute(
            "INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc) VALUES ('EQ-2026-000001', 1, 'PC', ?)",
            (utc,),
        )
        self.connection.execute(
            """INSERT INTO ordenes_servicio
               (codigo, cliente_id, equipo_id, recibido_en_utc, problema_reportado,
                importe_inicial_cop, creado_en_utc, actualizado_en_utc)
               VALUES ('OS-2026-000001', 1, 1, ?, 'Falla interna', 0, ?, ?)""",
            (utc, utc, utc),
        )
        self.connection.execute(
            """INSERT INTO orden_repuestos
               (orden_id, producto_id, cantidad, costo_unitario_cop, precio_unitario_cop, asignado_en_utc)
               VALUES (1, ?, 4, 100000, 150000, ?)""", (self.product["id"], utc),
        )
        self.connection.execute(
            """INSERT INTO reservas_inventario
               (producto_id, orden_repuesto_id, cantidad, estado, creada_en_utc, actualizada_en_utc)
               VALUES (?, 1, 4, 'reservada', ?, ?)""", (self.product["id"], utc, utc),
        )
        self.connection.commit()
        with self.assertRaises(ConflictError):
            self.inventory.adjust_stock(self.product["id"], -2, unit_cost_cop=100_000,
                                        reason="No puede consumir lo reservado", idempotency_key=uuid4().hex)
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO movimientos_inventario
                   (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo, creado_en_utc, motivo, fecha_negocio)
                   VALUES (?, -2, 100000, 'ajuste', ?, 'Acceso SQL directo', '2026-10-24')""", (self.product["id"], utc)
            )
        self.assertEqual(self.inventory.get_product(self.product["id"])["disponible"], 1)

    def test_supplier_crud_and_tax_id_duplicate_validation(self) -> None:
        with self.assertRaises(ConflictError):
            self.inventory.create_supplier(name="Proveedor duplicado", tax_id="NIT-TEST-1")
        with self.assertRaises(ValidationError):
            self.inventory.create_supplier(name="Proveedor inválido", email="correo-no-valido")
        changed = self.inventory.update_supplier(
            self.supplier["id"], name="Proveedor editado", address="Nueva dirección", active=False
        )
        self.assertEqual(changed["nombre"], "Proveedor editado")
        self.assertEqual(changed["direccion"], "Nueva dirección")
        self.assertFalse(changed["activo"])
        self.assertEqual(self.inventory.list_suppliers(active=False)[0]["id"], self.supplier["id"])
        with self.assertRaises(ConflictError):
            self.procurement.create_purchase(self.supplier["id"], [self.line()])

    def line(self, product_id=None, quantity=2, cost=100_000, description=None):
        return {
            "product_id": product_id or self.product["id"], "quantity": quantity,
            "unit_cost_cop": cost, "description": description or "Memoria al momento de compra",
        }

    def test_purchase_lines_snapshots_edit_and_physical_receipt(self) -> None:
        second = self.inventory.create_product(sku="SSD-1", name="SSD prueba", unit_cost_cop=200_000)
        purchase = self.procurement.create_purchase(
            self.supplier["id"], [self.line(), self.line(second["id"], 1, 200_000)],
            reference="FAC-LOCAL-1", notes="Compra de prueba",
        )
        self.assertEqual(purchase["estado"], "borrador")
        self.assertEqual(purchase["importe_compra_cop"], 400_000)
        self.assertEqual(purchase["lineas"][0]["descripcion_historica"], "Memoria al momento de compra")
        self.procurement.transition_purchase(purchase["id"], "pendiente")
        self.procurement.transition_purchase(purchase["id"], "recibida")
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 2)
        self.assertEqual(self.inventory.get_product(second["id"])["existencia"], 1)
        self.assertEqual(self.procurement.get_purchase(purchase["id"])["estado"], "recibida")
        self.assertEqual(len(self.inventory.product_movements(self.product["id"])), 1)
        with self.assertRaises(ConflictError):
            self.procurement.transition_purchase(purchase["id"], "recibida")
        with self.assertRaises(ConflictError):
            self.procurement.update_purchase(purchase["id"], self.supplier["id"], [self.line()])

    def test_purchase_edit_is_only_allowed_while_draft_and_lines_are_validated(self) -> None:
        purchase = self.procurement.create_purchase(self.supplier["id"], [self.line()])
        updated = self.procurement.update_purchase(
            purchase["id"], self.supplier["id"], [self.line(quantity=3, cost=80_000)],
            reference="FACT-2", notes="Editada",
        )
        self.assertEqual(updated["importe_compra_cop"], 240_000)
        self.assertEqual(updated["referencia"], "FACT-2")
        with self.assertRaises(ValidationError):
            self.procurement.update_purchase(purchase["id"], self.supplier["id"], [])
        with self.assertRaises(ValidationError):
            self.procurement.create_purchase(self.supplier["id"], [self.line(quantity=0)])
        with self.assertRaises(ValidationError):
            self.procurement.create_purchase(self.supplier["id"], [self.line(cost=1.25)])

    def test_partial_full_and_reversed_supplier_payments_derive_balance(self) -> None:
        purchase = self.procurement.create_purchase(self.supplier["id"], [self.line(quantity=2, cost=50_000)])
        with self.assertRaises(ConflictError):
            self.procurement.register_supplier_payment(purchase["id"], 1, method="Efectivo", idempotency_key=uuid4().hex)
        self.procurement.transition_purchase(purchase["id"], "pendiente")
        first = self.procurement.register_supplier_payment(purchase["id"], 40_000, method="Transferencia", idempotency_key=uuid4().hex)
        current = self.procurement.get_purchase(purchase["id"])
        self.assertEqual((current["importe_compra_cop"], current["pagado_neto_cop"], current["saldo_pendiente_cop"]),
                         (100_000, 40_000, 60_000))
        with self.assertRaises(ValidationError):
            self.procurement.register_supplier_payment(purchase["id"], 60_001, method="Efectivo", idempotency_key=uuid4().hex)
        second = self.procurement.register_supplier_payment(purchase["id"], 60_000, method="Efectivo", idempotency_key=uuid4().hex)
        self.assertEqual(self.procurement.get_purchase(purchase["id"])["saldo_pendiente_cop"], 0)
        self.procurement.reverse_supplier_payment(first["id"], reason="Reversión de prueba", idempotency_key=uuid4().hex)
        self.assertEqual(self.procurement.get_purchase(purchase["id"])["saldo_pendiente_cop"], 40_000)
        with self.assertRaises(ConflictError):
            self.procurement.reverse_supplier_payment(first["id"], reason="Duplicada", idempotency_key=uuid4().hex)
        self.assertTrue(self.procurement.can_reverse_supplier_payment(second["id"]))

    def test_receipt_failure_rolls_back_state_and_all_stock_movements(self) -> None:
        second = self.inventory.create_product(sku="SSD-2", name="SSD segundo")
        purchase = self.procurement.create_purchase(
            self.supplier["id"], [self.line(), self.line(second["id"], 3, 30_000)]
        )
        self.procurement.transition_purchase(purchase["id"], "pendiente")
        second_line_id = purchase["lineas"][1]["id"]
        self.connection.execute(
            f"""CREATE TRIGGER fail_purchase_receipt BEFORE INSERT ON movimientos_inventario
                WHEN NEW.compra_detalle_id = {second_line_id}
                BEGIN SELECT RAISE(ABORT, 'forced receipt failure'); END"""
        )
        with self.assertRaises(DataIntegrityError):
            self.procurement.transition_purchase(purchase["id"], "recibida")
        self.assertEqual(self.procurement.get_purchase(purchase["id"])["estado"], "pendiente")
        self.assertEqual(self.inventory.get_product(self.product["id"])["existencia"], 0)
        self.assertEqual(self.inventory.get_product(second["id"])["existencia"], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM movimientos_inventario WHERE tipo='compra'").fetchone()[0], 0)

    def test_supplier_history_and_cancel_rules(self) -> None:
        purchase = self.procurement.create_purchase(self.supplier["id"], [self.line()])
        self.procurement.transition_purchase(purchase["id"], "pendiente")
        self.procurement.register_supplier_payment(purchase["id"], 20_000, method="Efectivo", idempotency_key=uuid4().hex)
        with self.assertRaises(ConflictError):
            self.procurement.transition_purchase(purchase["id"], "cancelada")
        self.assertEqual(len(self.procurement.supplier_purchase_history(self.supplier["id"])), 1)
        self.assertEqual(self.procurement.list_purchases(state="pendiente")[0]["id"], purchase["id"])

