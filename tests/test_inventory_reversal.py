"""El mecanismo genérico solo revierte ajustes; el resto exige su flujo."""

import unittest

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.errors import ConflictError, NotFoundError
from dragontech_manager.services.inventory import InventoryService
from dragontech_manager.services.procurement import ProcurementService
from dragontech_manager.services.sales import SalesService

UTC = "2026-10-24T15:30:00Z"


class InventoryReversalGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.inventory = InventoryService(self.connection)
        self.customers = CustomerService(self.connection)
        self.procurement = ProcurementService(self.connection)
        self.sales = SalesService(self.connection)
        self.customer = self.customers.create_customer("Cliente de reversión")
        self.supplier = self.inventory.create_supplier(name="Proveedor de reversión")
        self.product = self.inventory.create_product(
            sku="REV-1", name="Producto de reversión",
            unit_cost_cop=10_000, suggested_price_cop=20_000,
        )
        self.inventory.adjust_stock(
            self.product["id"], 10, unit_cost_cop=10_000, reason="Existencia inicial"
        )

    # ------------------------------------------------------------------ helpers
    def _movement(self, kind: str) -> dict:
        row = self.connection.execute(
            "SELECT * FROM movimientos_inventario WHERE tipo = ? ORDER BY id DESC",
            (kind,),
        ).fetchone()
        self.assertIsNotNone(row, f"No se creó un movimiento de tipo {kind}")
        return dict(row)

    def _stock(self) -> int:
        return self.inventory.get_product(self.product["id"])["existencia"]

    def _movement_count(self) -> int:
        return self.connection.execute(
            "SELECT COUNT(*) FROM movimientos_inventario"
        ).fetchone()[0]

    def _reversal_count(self) -> int:
        return self.connection.execute(
            "SELECT COUNT(*) FROM movimientos_inventario WHERE tipo = 'reversion'"
        ).fetchone()[0]

    def _assert_blocked(self, movement_id: int, *, flow: str, origin: str) -> None:
        self.assertFalse(self.inventory.can_reverse_movement(movement_id))
        reason = self.inventory.reversal_blocked_reason(movement_id)
        self.assertIn(origin, reason)
        self.assertIn(flow, reason)
        self.assertIn("trazabilidad", reason)
        before_stock = self._stock()
        before_movements = self._movement_count()
        with self.assertRaises(ConflictError) as captured:
            self.inventory.reverse_movement(movement_id, reason="Intento genérico")
        self.assertIn(flow, str(captured.exception))
        self.assertEqual(self._stock(), before_stock)
        self.assertEqual(self._movement_count(), before_movements)
        self.assertEqual(self._reversal_count(), 0)
        # Reintentar el mismo intento falla igual y no deja residuos.
        with self.assertRaises(ConflictError):
            self.inventory.reverse_movement(movement_id, reason="Reintento")
        self.assertEqual(self._movement_count(), before_movements)

    def _sale_movement(self) -> tuple[dict, dict]:
        sale = self.sales.create_sale(
            self.customer["id"],
            [{"description": "Producto de reversión", "quantity": 2,
              "unit_price_cop": 20_000, "product_id": self.product["id"]}],
            idempotency_key="reversal-sale-1",
        )
        return sale, self._movement("venta")

    # -------------------------------------------------------------------- cases
    def test_sale_movement_requires_the_sales_flow(self) -> None:
        sale, movement = self._sale_movement()
        self.assertEqual(self._stock(), 8)
        self._assert_blocked(movement["id"], flow="ventas", origin="una venta")
        current = self.sales.get_sale(sale["id"])
        self.assertEqual(current["estado"], "abierta")
        self.assertEqual(current["importe_acordado_cop"], 40_000)

    def test_purchase_movement_requires_the_purchase_flow(self) -> None:
        purchase = self.procurement.create_purchase(
            self.supplier["id"],
            [{"product_id": self.product["id"], "quantity": 3,
              "unit_cost_cop": 10_000, "description": "Compra de reversión"}],
        )
        self.procurement.transition_purchase(purchase["id"], "pendiente")
        self.procurement.transition_purchase(purchase["id"], "recibida")
        movement = self._movement("compra")
        self.assertEqual(self._stock(), 13)
        self._assert_blocked(movement["id"], flow="compras", origin="una compra")
        self.assertEqual(self.procurement.get_purchase(purchase["id"])["estado"], "recibida")

    def test_order_movement_requires_the_service_order_flow(self) -> None:
        equipment_id = self.connection.execute(
            "INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc) VALUES ('EQ-2026-000001', ?, 'PC', ?)",
            (self.customer["id"], UTC),
        ).lastrowid
        order_id = self.connection.execute(
            """INSERT INTO ordenes_servicio
               (codigo, cliente_id, equipo_id, recibido_en_utc, problema_reportado,
                importe_inicial_cop, creado_en_utc, actualizado_en_utc)
               VALUES ('OS-2026-000001', ?, ?, ?, 'Falla de prueba', 0, ?, ?)""",
            (self.customer["id"], equipment_id, UTC, UTC, UTC),
        ).lastrowid
        spare_id = self.connection.execute(
            """INSERT INTO orden_repuestos
               (orden_id, producto_id, cantidad, costo_unitario_cop,
                precio_unitario_cop, asignado_en_utc)
               VALUES (?, ?, 2, 10000, 20000, ?)""",
            (order_id, self.product["id"], UTC),
        ).lastrowid
        self.connection.execute(
            """INSERT INTO reservas_inventario
               (producto_id, orden_repuesto_id, cantidad, estado, creada_en_utc, actualizada_en_utc)
               VALUES (?, ?, 2, 'reservada', ?, ?)""",
            (self.product["id"], spare_id, UTC, UTC),
        )
        movement_id = self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                orden_repuesto_id, creado_en_utc, motivo, fecha_negocio)
               VALUES (?, -2, 10000, 'orden', ?, ?, 'Salida por orden', '2026-10-24')""",
            (self.product["id"], spare_id, UTC),
        ).lastrowid
        self.connection.commit()
        self._assert_blocked(movement_id, flow="órdenes de servicio", origin="una orden de servicio")

    def test_assembly_movement_requires_the_assembly_flow(self) -> None:
        assembly_id = self.connection.execute(
            "INSERT INTO armados_pc (codigo, cliente_id, creado_en_utc) VALUES ('ARM-REV-1', ?, ?)",
            (self.customer["id"], UTC),
        ).lastrowid
        component_id = self.connection.execute(
            """INSERT INTO armado_componentes
               (armado_id, producto_id, cantidad, costo_unitario_historico_cop,
                precio_unitario_cobrado_cop)
               VALUES (?, ?, 1, 10000, 20000)""",
            (assembly_id, self.product["id"]),
        ).lastrowid
        self.connection.execute(
            """INSERT INTO reservas_inventario
               (producto_id, armado_componente_id, cantidad, estado, creada_en_utc, actualizada_en_utc)
               VALUES (?, ?, 1, 'reservada', ?, ?)""",
            (self.product["id"], component_id, UTC, UTC),
        )
        movement_id = self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                armado_componente_id, creado_en_utc, motivo, fecha_negocio)
               VALUES (?, -1, 10000, 'armado', ?, ?, 'Salida por armado', '2026-10-24')""",
            (self.product["id"], component_id, UTC),
        ).lastrowid
        self.connection.commit()
        self._assert_blocked(movement_id, flow="ensamblajes", origin="un ensamblaje de PC")

    def test_manual_adjustments_remain_reversible(self) -> None:
        entry = self.inventory.adjust_stock(
            self.product["id"], 4, unit_cost_cop=10_000, reason="Entrada manual"
        )
        out = self.inventory.adjust_stock(
            self.product["id"], -1, unit_cost_cop=10_000, reason="Salida manual"
        )
        self.assertEqual(self._stock(), 13)
        self.assertIsNone(self.inventory.reversal_blocked_reason(out["id"]))
        self.assertTrue(self.inventory.can_reverse_movement(out["id"]))
        reversal = self.inventory.reverse_movement(out["id"], reason="Corrección manual")
        self.assertEqual(reversal["cantidad_delta"], 1)
        self.assertEqual(reversal["tipo"], "reversion")
        self.assertEqual(self._stock(), 14)
        # El movimiento de entrada sigue disponible para su propia corrección.
        self.assertTrue(self.inventory.can_reverse_movement(entry["id"]))

    def test_an_adjustment_cannot_be_reversed_twice(self) -> None:
        movement = self.inventory.adjust_stock(
            self.product["id"], 2, unit_cost_cop=10_000, reason="Entrada manual"
        )
        self.inventory.reverse_movement(movement["id"], reason="Primera corrección")
        self.assertFalse(self.inventory.can_reverse_movement(movement["id"]))
        self.assertIn(
            "ya tiene una reversión",
            self.inventory.reversal_blocked_reason(movement["id"]),
        )
        with self.assertRaises(ConflictError):
            self.inventory.reverse_movement(movement["id"], reason="Segunda corrección")

    def test_a_reversal_movement_cannot_be_reversed_again(self) -> None:
        movement = self.inventory.adjust_stock(
            self.product["id"], 2, unit_cost_cop=10_000, reason="Entrada manual"
        )
        reversal = self.inventory.reverse_movement(movement["id"], reason="Corrección")
        self.assertIn(
            "no se puede revertir de nuevo",
            self.inventory.reversal_blocked_reason(reversal["id"]),
        )
        with self.assertRaises(ConflictError):
            self.inventory.reverse_movement(reversal["id"], reason="Reintento")

    def test_missing_movement_is_reported(self) -> None:
        with self.assertRaises(NotFoundError):
            self.inventory.reversal_blocked_reason(999_999)


if __name__ == "__main__":
    unittest.main()
