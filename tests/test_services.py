"""Pruebas aisladas de servicios y repositorios con SQLite en memoria."""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.equipment import EquipmentService
from dragontech_manager.services.errors import (
    ConflictError,
    DataIntegrityError,
    NotFoundError,
    ValidationError,
)
from dragontech_manager.services.service_orders import ServiceOrderService


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.customers = CustomerService(self.connection)
        self.equipment = EquipmentService(self.connection)
        self.orders = ServiceOrderService(self.connection)

    def make_customer_and_equipment(self) -> tuple[dict, dict]:
        customer = self.customers.create_customer(
            "  Ana de prueba ", phone="3000000000", email="ana@example.test"
        )
        equipment = self.equipment.register_equipment(
            customer["id"],
            "Portátil",
            brand="Marca de prueba",
            model="Modelo X",
            serial="SERIAL-TEST",
            specifications="16 GB RAM",
            accessories_received="Cargador",
            physical_condition="Rayón en tapa",
        )
        return customer, equipment

    def test_create_get_and_search_customers(self) -> None:
        created = self.customers.create_customer("  Cliente local  ", notes="Nota")
        self.assertEqual(created["nombre"], "Cliente local")
        self.assertEqual(created["notas"], "Nota")
        self.assertRegex(created["creado_en_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(self.customers.get_customer(created["id"])["id"], created["id"])
        self.assertEqual(self.customers.list_customers(search="local")[0]["id"], created["id"])
        self.assertEqual(self.customers.list_customers(search="' OR 1=1 --"), [])

    def test_customer_validation_and_missing_customer_lookup(self) -> None:
        with self.assertRaises(ValidationError):
            self.customers.create_customer("  ")
        with self.assertRaises(ValidationError):
            self.customers.create_customer("Cliente", phone=42)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            self.customers.get_customer(True)
        with self.assertRaises(NotFoundError):
            self.customers.get_customer(999)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 0)

    def test_register_equipment_with_optional_fields_and_list_by_customer(self) -> None:
        customer = self.customers.create_customer("Cliente de equipo")
        first = self.equipment.register_equipment(
            customer["id"], "Torre", brand="Marca", model="Modelo", serial="S-1"
        )
        second = self.equipment.register_equipment(customer["id"], "Portátil")
        current_year = datetime.now(ZoneInfo("America/Bogota")).year
        self.assertRegex(first["codigo"], rf"^EQ-{current_year:04d}-\d{{6}}$")
        self.assertNotEqual(first["codigo"], second["codigo"])
        self.assertEqual(first["marca"], "Marca")
        self.assertIsNone(second["serial"])
        self.assertEqual([row["id"] for row in self.equipment.list_equipment_for_customer(customer["id"])], [second["id"], first["id"]])

    def test_equipment_rejects_missing_customer_and_invalid_type_without_consuming_sequence(self) -> None:
        with self.assertRaises(NotFoundError):
            self.equipment.register_equipment(99, "Portátil")
        customer = self.customers.create_customer("Cliente válido")
        with self.assertRaises(ValidationError):
            self.equipment.register_equipment(customer["id"], " ")
        self.assertIsNone(
            self.connection.execute(
                "SELECT 1 FROM secuencias WHERE entidad = 'equipo'"
            ).fetchone()
        )
        equipment = self.equipment.register_equipment(customer["id"], "Portátil")
        self.assertTrue(equipment["codigo"].endswith("000001"))

    def test_order_creation_query_status_and_equipment_history(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"],
            equipment["id"],
            "No enciende",
            initial_amount_cop=125000,
            diagnosis="Pendiente de revisión",
            technician="Técnico local",
        )
        current_year = datetime.now(ZoneInfo("America/Bogota")).year
        self.assertRegex(order["codigo"], rf"^OS-{current_year:04d}-\d{{6}}$")
        self.assertEqual(order["estado"], "recibida")
        self.assertEqual(order["cliente_id"], customer["id"])
        self.assertEqual(order["equipo_id"], equipment["id"])
        self.assertEqual(order["importe_inicial_cop"], 125000)
        self.assertEqual(self.orders.get_order(order["id"])["codigo"], order["codigo"])
        self.assertEqual(self.orders.list_orders(state="recibida")[0]["id"], order["id"])
        history = self.equipment.get_equipment_history(equipment["id"])
        self.assertEqual(history["equipment"]["id"], equipment["id"])
        self.assertEqual([row["id"] for row in history["service_orders"]], [order["id"]])

    def test_equipment_history_is_not_silently_limited_to_500_orders(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        self.connection.executemany(
            """INSERT INTO ordenes_servicio
               (codigo, cliente_id, equipo_id, recibido_en_utc, problema_reportado,
                importe_inicial_cop, creado_en_utc, actualizado_en_utc)
               VALUES (?, ?, ?, '2026-10-24T15:30:00Z', 'Prueba', 0,
                       '2026-10-24T15:30:00Z', '2026-10-24T15:30:00Z')""",
            [
                (f"OS-2026-{sequence:06d}", customer["id"], equipment["id"])
                for sequence in range(1, 502)
            ],
        )
        history = self.equipment.get_equipment_history(equipment["id"])
        self.assertEqual(len(history["service_orders"]), 501)

    def test_order_input_validation_and_missing_or_mismatched_references(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        with self.assertRaises(NotFoundError):
            self.orders.open_service_order(999, equipment["id"], "Problema")
        with self.assertRaises(NotFoundError):
            self.orders.open_service_order(customer["id"], 999, "Problema")
        with self.assertRaises(ValidationError):
            self.orders.open_service_order(customer["id"], equipment["id"], " ")
        with self.assertRaises(ValidationError):
            self.orders.open_service_order(customer["id"], equipment["id"], "Problema", initial_amount_cop=1.5)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            self.orders.open_service_order(
                customer["id"],
                equipment["id"],
                "Problema",
                initial_amount_cop=9_223_372_036_854_775_808,
            )
        with self.assertRaises(ValidationError):
            self.orders.list_orders(state="estado-inventado")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM ordenes_servicio").fetchone()[0], 0)
        self.assertIsNone(
            self.connection.execute(
                "SELECT 1 FROM secuencias WHERE entidad = 'orden_servicio'"
            ).fetchone()
        )

    def test_order_keeps_requesting_customer_snapshot_separate_from_equipment_owner(self) -> None:
        _, equipment = self.make_customer_and_equipment()
        requester = self.customers.create_customer("Solicitante distinto")
        order = self.orders.open_service_order(requester["id"], equipment["id"], "Revisión solicitada")
        self.assertEqual(order["cliente_id"], requester["id"])
        self.assertEqual(order["equipo_id"], equipment["id"])

    def test_order_and_code_sequence_roll_back_together_on_insert_failure(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        self.connection.execute(
            """CREATE TRIGGER force_order_failure BEFORE INSERT ON ordenes_servicio
               BEGIN SELECT RAISE(ABORT, 'forced failure for regression test'); END"""
        )
        with self.assertRaises(DataIntegrityError):
            self.orders.open_service_order(customer["id"], equipment["id"], "No inicia")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM ordenes_servicio").fetchone()[0], 0)
        self.assertIsNone(
            self.connection.execute(
                "SELECT 1 FROM secuencias WHERE entidad = 'orden_servicio'"
            ).fetchone()
        )

        self.connection.execute("DROP TRIGGER force_order_failure")
        order = self.orders.open_service_order(customer["id"], equipment["id"], "No inicia")
        self.assertTrue(order["codigo"].endswith("000001"))

    def test_integrity_conflict_is_translated_without_losing_sequence(self) -> None:
        customer = self.customers.create_customer("Cliente")
        current_year = datetime.now(ZoneInfo("America/Bogota")).year
        self.connection.execute(
            "INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc) VALUES (?, ?, ?, ?)",
            (f"EQ-{current_year:04d}-000001", customer["id"], "Torre", "2026-10-24T15:30:00Z"),
        )
        self.connection.execute(
            "INSERT INTO secuencias (entidad, anio, siguiente_ordinal) VALUES ('equipo', ?, 1)",
            (current_year,),
        )
        with self.assertRaises(ConflictError):
            self.equipment.register_equipment(customer["id"], "Torre")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM equipos").fetchone()[0], 1)
        self.assertEqual(
            self.connection.execute(
                "SELECT siguiente_ordinal FROM secuencias WHERE entidad = 'equipo' AND anio = ?",
                (current_year,),
            ).fetchone()[0],
            1,
        )

    def test_nested_service_operation_uses_savepoint_and_outer_rollback(self) -> None:
        customer = self.customers.create_customer("Cliente")
        self.connection.execute("BEGIN IMMEDIATE")
        equipment = self.equipment.register_equipment(customer["id"], "Torre")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM equipos").fetchone()[0], 1)
        self.connection.rollback()
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM equipos").fetchone()[0], 0)
        self.assertIsNone(
            self.connection.execute("SELECT 1 FROM secuencias WHERE entidad = 'equipo'").fetchone()
        )


if __name__ == "__main__":
    unittest.main()
