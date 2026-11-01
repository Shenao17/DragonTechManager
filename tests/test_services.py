"""Pruebas aisladas de servicios y repositorios con SQLite en memoria."""

import unittest
from uuid import uuid4
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.dashboard import DashboardService
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

    def test_customer_update_validates_and_preserves_omitted_optional_fields(self) -> None:
        customer = self.customers.create_customer(
            "Nombre original", phone="3001234567", email="original@example.test", notes="Nota"
        )
        updated = self.customers.update_customer(customer["id"], name="Nombre actualizado")
        self.assertEqual(updated["nombre"], "Nombre actualizado")
        self.assertEqual(updated["telefono"], "3001234567")
        self.assertEqual(updated["correo"], "original@example.test")
        self.assertEqual(updated["notas"], "Nota")
        with self.assertRaises(ValidationError):
            self.customers.update_customer(customer["id"], name=" ")
        with self.assertRaises(ValidationError):
            self.customers.update_customer(customer["id"], name="Nombre", email="correo inválido")
        with self.assertRaises(NotFoundError):
            self.customers.update_customer(999, name="Nombre")

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

    def test_equipment_search_returns_owner_and_supported_fields(self) -> None:
        customer, _equipment = self.make_customer_and_equipment()
        rows = self.equipment.list_equipment(search="SERIAL-TEST")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cliente_nombre"], customer["nombre"])
        current_year = datetime.now(ZoneInfo("America/Bogota")).year
        self.assertEqual(rows[0]["codigo"], f"EQ-{current_year:04d}-000001")
        self.assertEqual(self.equipment.list_equipment(search="No coincide"), [])

    def test_equipment_update_keeps_code_and_omitted_optional_fields(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        updated = self.equipment.update_equipment(
            equipment["id"], equipment_type="Torre renovada", model="Modelo nuevo"
        )
        self.assertEqual(updated["codigo"], equipment["codigo"])
        self.assertEqual(updated["cliente_id"], customer["id"])
        self.assertEqual(updated["tipo"], "Torre renovada")
        self.assertEqual(updated["marca"], "Marca de prueba")
        self.assertEqual(updated["modelo"], "Modelo nuevo")
        self.assertEqual(updated["serial"], "SERIAL-TEST")
        with self.assertRaises(NotFoundError):
            self.equipment.update_equipment(equipment["id"], customer_id=999)
        with self.assertRaises(ValidationError):
            self.equipment.update_equipment(equipment["id"], equipment_type=" ")
        with self.assertRaises(NotFoundError):
            self.equipment.update_equipment(999, equipment_type="Torre")

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
        listed = self.orders.list_orders()[0]
        self.assertEqual(listed["cliente_nombre"], customer["nombre"])
        self.assertEqual(listed["equipo_codigo"], equipment["codigo"])
        self.assertEqual(listed["importe_acordado_cop"], 125000)
        detail = self.orders.get_order_detail(order["id"])
        self.assertEqual(detail["cliente_solicitante_nombre"], customer["nombre"])
        self.assertEqual(detail["equipo_codigo"], equipment["codigo"])
        self.assertEqual(detail["importe_acordado_cop"], 125000)
        initial_events = self.orders.get_status_history(order["id"])
        self.assertEqual(len(initial_events), 1)
        self.assertIsNone(initial_events[0]["estado_anterior"])
        self.assertEqual(initial_events[0]["estado_nuevo"], "recibida")

    def test_order_transitions_work_history_and_delivery_date(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(customer["id"], equipment["id"], "No enciende")
        order_id = order["id"]
        self.assertEqual(self.orders.allowed_next_states(order_id), ["diagnostico"])
        with self.assertRaises(ValidationError):
            self.orders.transition_order(order_id, "en_proceso")
        self.orders.transition_order(order_id, "diagnostico", reason="Equipo recibido")
        self.assertEqual(self.orders.allowed_next_states(order_id), [])
        with self.assertRaises(ValidationError):
            self.orders.transition_order(order_id, "en_proceso")
        self.orders.update_technical_details(
            order_id, diagnosis="Fuente con falla", work_performed="", tests_performed="", technician="Técnico"
        )
        self.assertEqual(self.orders.allowed_next_states(order_id), ["en_proceso"])
        self.orders.transition_order(order_id, "en_proceso")
        self.assertEqual(self.orders.allowed_next_states(order_id), [])
        with self.assertRaises(ValidationError):
            self.orders.transition_order(order_id, "lista")
        self.orders.update_technical_details(
            order_id,
            diagnosis="Fuente con falla",
            work_performed="Se reemplazó la fuente",
            tests_performed="Prueba de encendido y estabilidad aprobadas",
            technician="Técnico",
        )
        self.assertEqual(self.orders.allowed_next_states(order_id), ["lista"])
        self.orders.transition_order(order_id, "lista")
        self.assertEqual(self.orders.allowed_next_states(order_id), ["entregada"])
        delivered = self.orders.transition_order(order_id, "entregada", reason="Entrega al solicitante")
        self.assertRegex(delivered["fecha_entrega"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(self.orders.allowed_next_states(order_id), [])
        events = self.orders.get_status_history(order_id)
        self.assertEqual([event["estado_nuevo"] for event in events], [
            "recibida", "diagnostico", "en_proceso", "lista", "entregada"
        ])
        self.assertEqual(events[-1]["motivo"], "Entrega al solicitante")
        self.assertRegex(events[-1]["cambiado_en_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        with self.assertRaises(ValidationError):
            self.orders.update_technical_details(order_id, diagnosis="Editar", work_performed="", technician="")

    def test_additional_service_proposal_decision_and_agreed_total_are_transactional(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "No enciende", initial_amount_cop=10000
        )
        with self.assertRaises(ValidationError):
            self.orders.propose_additional_service(order["id"], "Cambio de fuente", 25000)
        self.orders.transition_order(order["id"], "diagnostico")
        self.orders.update_technical_details(
            order["id"], diagnosis="Fuente dañada", work_performed="", tests_performed=""
        )
        proposal = self.orders.propose_additional_service(order["id"], "Cambio de fuente", 25000)
        self.assertEqual(self.orders.list_additional_services(order["id"])[0]["estado"], "pendiente")
        self.assertEqual(self.orders.get_order_detail(order["id"])["importe_acordado_cop"], 10000)
        self.assertEqual(self.orders.allowed_next_states(order["id"]), ["espera_aprobacion"])
        with self.assertRaises(ConflictError):
            self.orders.propose_additional_service(order["id"], "Cambio de fuente", 25000)

        self.orders.transition_order(order["id"], "espera_aprobacion")
        approved = self.orders.decide_additional_service(
            proposal["id"], "aprobado", "Cliente indicó aprobación por llamada; nota registrada por técnico."
        )
        self.assertEqual(approved["estado"], "aprobado")
        self.assertEqual(len(self.orders.list_additional_decision_history(proposal["id"])), 1)
        self.assertRegex(approved["decidido_en_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(self.orders.get_order_detail(order["id"])["importe_acordado_cop"], 35000)
        self.assertEqual(self.orders.allowed_next_states(order["id"]), ["en_proceso"])
        with self.assertRaises(ConflictError):
            self.orders.decide_additional_service(proposal["id"], "aprobado", "Segundo clic")
        with self.assertRaises(ConflictError):
            self.orders.decide_additional_service(proposal["id"], "rechazado", "Cambio no soportado")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE servicios_adicionales SET importe_propuesto_cop = 30000 WHERE id = ?",
                (proposal["id"],),
            )
        self.assertEqual(self.orders.get_order_detail(order["id"])["importe_acordado_cop"], 35000)

        revised = self.orders.propose_additional_service(
            order["id"], "Revisión adicional con alcance actualizado", 30000
        )
        self.assertEqual(revised["id"] != proposal["id"], True)
        revised_state = next(
            item for item in self.orders.list_additional_services(order["id"])
            if item["id"] == revised["id"]
        )
        self.assertEqual(revised_state["estado"], "pendiente")
        self.assertEqual(self.orders.get_order_detail(order["id"])["importe_acordado_cop"], 35000)

    def test_additional_rejection_does_not_change_total_and_failed_decision_rolls_back(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "Falla", initial_amount_cop=12000
        )
        self.orders.transition_order(order["id"], "diagnostico")
        self.orders.update_technical_details(
            order["id"], diagnosis="Diagnóstico", work_performed="", tests_performed=""
        )
        proposal = self.orders.propose_additional_service(order["id"], "Repuesto opcional", 5000)
        self.orders.transition_order(order["id"], "espera_aprobacion")
        rejected = self.orders.decide_additional_service(
            proposal["id"], "rechazado", "Cliente indicó rechazo por WhatsApp."
        )
        self.assertEqual(rejected["estado"], "rechazado")
        self.assertEqual(self.orders.get_order_detail(order["id"])["importe_acordado_cop"], 12000)
        self.assertEqual(self.orders.allowed_next_states(order["id"]), ["en_proceso"])
        with self.assertRaises(ConflictError):
            self.orders.decide_additional_service(proposal["id"], "rechazado", "Decisión duplicada")

        other = self.orders.propose_additional_service(order["id"], "Trabajo adicional", 2500)
        self.connection.execute(
            f"""CREATE TRIGGER fail_additional_decision BEFORE INSERT ON decisiones_adicional
                WHEN NEW.servicio_adicional_id = {other['id']}
                BEGIN SELECT RAISE(ABORT, 'forced decision failure'); END"""
        )
        with self.assertRaises(DataIntegrityError):
            self.orders.decide_additional_service(other["id"], "aprobado", "Llamada registrada")
        self.assertEqual(self.orders.list_additional_decision_history(other["id"]), [])
        self.assertEqual(self.orders.get_order_detail(order["id"])["importe_acordado_cop"], 12000)

    def test_approval_rejects_cop_total_overflow_without_recording_decision(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        maximum = 9_223_372_036_854_775_807
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "Falla", initial_amount_cop=maximum
        )
        self.orders.transition_order(order["id"], "diagnostico")
        self.orders.update_technical_details(
            order["id"], diagnosis="Diagnóstico", work_performed="", tests_performed=""
        )
        proposal = self.orders.propose_additional_service(order["id"], "Repuesto", 1)
        with self.assertRaises(ValidationError):
            self.orders.decide_additional_service(proposal["id"], "aprobado", "Aprobación anotada")
        self.assertEqual(self.orders.list_additional_decision_history(proposal["id"]), [])
        self.assertEqual(self.orders.get_order_detail(order["id"])["importe_acordado_cop"], maximum)

    def test_order_approval_states_block_work_until_additional_decisions_exist(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(customer["id"], equipment["id"], "Falla")
        self.connection.execute(
            """INSERT INTO servicios_adicionales (orden_id, descripcion, importe_propuesto_cop, propuesto_en_utc)
               VALUES (?, 'Repuesto pendiente', 20000, '2026-10-24T15:30:00Z')""",
            (order["id"],),
        )
        self.orders.transition_order(order["id"], "diagnostico")
        self.assertEqual(self.orders.allowed_next_states(order["id"]), [])
        self.orders.update_technical_details(
            order["id"], diagnosis="Diagnóstico", work_performed="", tests_performed=""
        )
        self.assertEqual(self.orders.allowed_next_states(order["id"]), ["espera_aprobacion"])
        with self.assertRaises(ValidationError):
            self.orders.transition_order(order["id"], "en_proceso")
        self.orders.transition_order(order["id"], "espera_aprobacion")
        self.assertEqual(self.orders.allowed_next_states(order["id"]), [])
        self.connection.execute(
            """INSERT INTO decisiones_adicional
               (servicio_adicional_id, decision, decidido_en_utc, evidencia)
               VALUES (1, 'aprobado', '2026-10-24T15:31:00Z', 'Aprobación de prueba')"""
        )
        self.assertEqual(self.orders.allowed_next_states(order["id"]), ["en_proceso"])
        self.orders.transition_order(order["id"], "en_proceso")
        self.assertEqual(self.orders.get_order(order["id"])["estado"], "en_proceso")
        with self.assertRaises(ValidationError):
            self.orders.transition_order(order["id"], "recibida")

    def test_order_status_and_history_roll_back_together_if_history_write_fails(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(customer["id"], equipment["id"], "Falla")
        self.orders.transition_order(order["id"], "diagnostico")
        self.orders.update_technical_details(
            order["id"], diagnosis="Diagnóstico", work_performed="", tests_performed=""
        )
        self.connection.execute(
            """CREATE TRIGGER fail_status_event BEFORE INSERT ON historial_estados_orden
               WHEN NEW.estado_nuevo = 'en_proceso'
               BEGIN SELECT RAISE(ABORT, 'forced history failure'); END"""
        )
        with self.assertRaises(DataIntegrityError):
            self.orders.transition_order(order["id"], "en_proceso")
        self.assertEqual(self.orders.get_order(order["id"])["estado"], "diagnostico")
        self.assertEqual(len(self.orders.get_status_history(order["id"])), 2)

    def test_dashboard_summary_uses_real_order_states_and_reports_empty_database(self) -> None:
        dashboard = DashboardService(self.connection)
        self.assertEqual(
            dashboard.order_summary(),
            {"pendientes": 0, "en_proceso": 0, "listas": 0, "entregadas": 0, "total": 0},
        )
        customer, equipment = self.make_customer_and_equipment()
        self.orders.open_service_order(customer["id"], equipment["id"], "Pendiente")
        self.connection.execute("UPDATE ordenes_servicio SET estado = 'en_proceso' WHERE id = 1")
        self.orders.open_service_order(customer["id"], equipment["id"], "Lista")
        self.connection.execute("UPDATE ordenes_servicio SET estado = 'lista' WHERE id = 2")
        summary = dashboard.order_summary()
        self.assertEqual(summary["pendientes"], 0)
        self.assertEqual(summary["en_proceso"], 1)
        self.assertEqual(summary["listas"], 1)
        self.assertEqual(summary["total"], 2)

    def test_dashboard_recent_orders_returns_bounded_real_rows_newest_first(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        first = self.orders.open_service_order(customer["id"], equipment["id"], "Orden anterior")
        second = self.orders.open_service_order(customer["id"], equipment["id"], "Orden reciente")
        dashboard = DashboardService(self.connection)

        rows = dashboard.recent_orders(limit=1)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], second["id"])
        self.assertEqual(rows[0]["codigo"], second["codigo"])
        self.assertNotEqual(rows[0]["id"], first["id"])
        self.assertEqual(rows[0]["cliente_nombre"], customer["nombre"])
        self.assertEqual(rows[0]["equipo_codigo"], equipment["codigo"])

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

    def test_order_payment_advances_and_partials_update_balance(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "Falla de encendido", initial_amount_cop=100_000
        )
        bal_initial = self.orders.get_order_balance(order["id"])
        self.assertEqual(bal_initial["importe_acordado_cop"], 100_000)
        self.assertEqual(bal_initial["pagado_neto_cop"], 0)
        self.assertEqual(bal_initial["saldo_pendiente_cop"], 100_000)

        # Anticipo
        res1 = self.orders.register_payment(
            order["id"], 30_000, method="Efectivo", idempotency_key="ord-pay-1", reference="Anticipo inicial"
        )
        self.assertFalse(res1["repetido"])
        self.assertEqual(res1["balance"]["pagado_neto_cop"], 30_000)
        self.assertEqual(res1["balance"]["saldo_pendiente_cop"], 70_000)

        # Abono parcial
        res2 = self.orders.register_payment(
            order["id"], 40_000, method="Transferencia bancaria", idempotency_key="ord-pay-2", reference="Abono intermedio"
        )
        self.assertFalse(res2["repetido"])
        self.assertEqual(res2["balance"]["pagado_neto_cop"], 70_000)
        self.assertEqual(res2["balance"]["saldo_pendiente_cop"], 30_000)

        # Saldo exacto
        res3 = self.orders.register_payment(
            order["id"], 30_000, method="Tarjeta de débito", idempotency_key="ord-pay-3"
        )
        self.assertFalse(res3["repetido"])
        self.assertEqual(res3["balance"]["pagado_neto_cop"], 100_000)
        self.assertEqual(res3["balance"]["saldo_pendiente_cop"], 0)

        # Verificar lista de pagos
        payments = self.orders.list_order_payments(order["id"])
        self.assertEqual(len(payments), 3)
        for p in payments:
            self.assertEqual(p["tipo"], "recibo")
            self.assertFalse(p["reversado"])

    def test_order_payment_idempotency_and_retry(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "Mantenimiento", initial_amount_cop=50_000
        )
        first = self.orders.register_payment(
            order["id"], 25_000, method="Efectivo", idempotency_key="idem-key-1", reference="Recibo 1"
        )
        self.assertFalse(first["repetido"])

        # Reintento con los mismos datos devuelve el resultado original
        retry = self.orders.register_payment(
            order["id"], 25_000, method="Efectivo", idempotency_key="idem-key-1", reference="Recibo 1"
        )
        self.assertTrue(retry["repetido"])
        self.assertEqual(retry["pago"]["id"], first["pago"]["id"])
        self.assertEqual(retry["balance"]["saldo_pendiente_cop"], 25_000)

        # Reintento con la misma clave pero datos distintos genera conflicto
        with self.assertRaises(ConflictError):
            self.orders.register_payment(
                order["id"], 10_000, method="Efectivo", idempotency_key="idem-key-1"
            )

    def test_order_payment_validation_zero_negative_and_overpayment(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "Reparación", initial_amount_cop=40_000
        )
        with self.assertRaises(ValidationError):
            self.orders.register_payment(order["id"], 0, method="Efectivo", idempotency_key="zero-pay")
        with self.assertRaises(ValidationError):
            self.orders.register_payment(order["id"], -5000, method="Efectivo", idempotency_key="neg-pay")
        with self.assertRaises(ValidationError):
            self.orders.register_payment(order["id"], True, method="Efectivo", idempotency_key="bool-pay")
        with self.assertRaises(ValidationError):
            self.orders.register_payment(order["id"], 40_001, method="Efectivo", idempotency_key="over-pay")
        with self.assertRaises(ValidationError):
            self.orders.register_payment(order["id"], 10_000, method="   ", idempotency_key="blank-method")

    def test_order_payment_reversal_updates_balance_and_blocks_duplicate(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "Cambio pantalla", initial_amount_cop=80_000
        )
        pay = self.orders.register_payment(
            order["id"], 50_000, method="Transferencia", idempotency_key="rev-test-pay"
        )
        self.assertEqual(pay["balance"]["saldo_pendiente_cop"], 30_000)

        # Motivo obligatorio
        with self.assertRaises(ValidationError):
            self.orders.reverse_payment(pay["pago"]["id"], reason="  ")

        # Reversión válida
        rev = self.orders.reverse_payment(pay["pago"]["id"], reason="Error en comprobante bancario")
        self.assertEqual(rev["pago"]["tipo"], "reversion")
        self.assertEqual(rev["pago"]["reversa_pago_id"], pay["pago"]["id"])
        self.assertEqual(rev["balance"]["pagado_neto_cop"], 0)
        self.assertEqual(rev["balance"]["saldo_pendiente_cop"], 80_000)

        # Reversión duplicada rechazada
        with self.assertRaises(ConflictError):
            self.orders.reverse_payment(pay["pago"]["id"], reason="Segundo intento de reversión")

        # No se puede revertir una reversión
        with self.assertRaises(ConflictError):
            self.orders.reverse_payment(rev["pago"]["id"], reason="Revertir la reversión")

        # Verificar lista de pagos
        payments = self.orders.list_order_payments(order["id"])
        self.assertEqual(len(payments), 2)
        orig_entry = next(p for p in payments if p["id"] == pay["pago"]["id"])
        rev_entry = next(p for p in payments if p["id"] == rev["pago"]["id"])
        self.assertTrue(orig_entry["reversado"])
        self.assertEqual(rev_entry["tipo"], "reversion")
        self.assertEqual(rev_entry["motivo"], "Error en comprobante bancario")

    def test_order_payment_canceled_order_blocks_new_payments_but_allows_reversal(self) -> None:
        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "Revisión general", initial_amount_cop=50_000
        )
        pay = self.orders.register_payment(
            order["id"], 20_000, method="Efectivo", idempotency_key="cancel-anticipo"
        )

        # Cancelar orden (desde recibida no se puede cancelar directamente, vamos a diagnostico o cancelamos por SQL/transición)
        self.orders.transition_order(order["id"], "diagnostico")
        self.orders.update_technical_details(order["id"], diagnosis="Inviable reparación", work_performed="")
        # Para pasar a cancelada: la máquina de estados _ORDER_TRANSITIONS define:
        # "cancelada": set(). Desde recibida/diagnostico, ¿se puede cancelar?
        # En _ORDER_TRANSITIONS:
        # "recibida": {"diagnostico"},
        # "diagnostico": {"espera_aprobacion", "en_proceso"}
        # Forcemos estado cancelada en la base para verificar la regla del servicio
        self.connection.execute("UPDATE ordenes_servicio SET estado = 'cancelada' WHERE id = ?", (order["id"],))

        with self.assertRaises(ConflictError):
            self.orders.register_payment(order["id"], 10_000, method="Efectivo", idempotency_key="cancel-pay")

        # Reversión de anticipo sí debe estar permitida para devolver dinero
        rev = self.orders.reverse_payment(pay["pago"]["id"], reason="Devolución de anticipo por orden cancelada")
        self.assertEqual(rev["balance"]["pagado_neto_cop"], 0)

    def test_order_payment_isolation_from_sales(self) -> None:
        from dragontech_manager.services.inventory import InventoryService
        from dragontech_manager.services.sales import SalesService
        sales_svc = SalesService(self.connection)
        inv_svc = InventoryService(self.connection)

        customer, equipment = self.make_customer_and_equipment()
        order = self.orders.open_service_order(
            customer["id"], equipment["id"], "Limpieza", initial_amount_cop=40_000
        )
        ord_pay = self.orders.register_payment(
            order["id"], 15_000, method="Efectivo", idempotency_key="isolated-ord-pay"
        )

        prod = inv_svc.create_product(sku="ISO-PART", name="Pieza aislada", unit_cost_cop=5_000, suggested_price_cop=10_000)
        inv_svc.adjust_stock(prod["id"], 10, unit_cost_cop=5_000, reason="Stock", idempotency_key=uuid4().hex)
        sale = sales_svc.create_sale(
            customer["id"],
            [{"description": "Pieza aislada", "quantity": 1, "unit_price_cop": 10_000, "product_id": prod["id"]}],
            idempotency_key="isolated-sale",
        )
        sale_pay = sales_svc.register_payment(sale["id"], 10_000, method="Efectivo", idempotency_key="isolated-sale-pay")

        # Los pagos de la orden no incluyen los de la venta
        ord_payments = self.orders.list_order_payments(order["id"])
        self.assertEqual(len(ord_payments), 1)
        self.assertEqual(ord_payments[0]["id"], ord_pay["pago"]["id"])

        # Intentar revertir el pago de venta desde el servicio de órdenes debe fallar
        with self.assertRaises(NotFoundError):
            self.orders.reverse_payment(sale_pay["pago"]["id"], reason="Intento inválido cruzado")


if __name__ == "__main__":
    unittest.main()
