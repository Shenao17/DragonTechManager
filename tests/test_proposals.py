"""Pruebas de persistencia y reglas para propuestas a clientes."""

import sqlite3
import shutil
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.errors import ConflictError, DataIntegrityError, NotFoundError, ValidationError
from dragontech_manager.services.proposals import ProposalService


class ProposalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.version = migrate(self.connection)
        self.customers = CustomerService(self.connection)
        self.service = ProposalService(self.connection)
        self.customer = self.customers.create_customer("Cliente de propuesta")

    def line(self, description="Servicio técnico", quantity=2, price=125_000):
        return {"description": description, "quantity": quantity, "unit_price_cop": price}

    def test_migration_adds_conditions_and_immutable_history(self) -> None:
        self.assertEqual(self.version, 7)
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(cotizaciones)")}
        self.assertIn("condiciones", columns)
        proposal = self.service.create_proposal(self.customer["id"], [self.line()])
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM historial_cotizaciones WHERE cotizacion_id = ?", (proposal["id"],))

    def test_migration_from_version_four_preserves_proposals_and_lines(self) -> None:
        migrations = Path(__file__).parents[1] / "src/dragontech_manager/database/migrations"
        with tempfile.TemporaryDirectory() as directory:
            old_dir = Path(directory)
            for version in range(1, 5):
                source = next(migrations.glob(f"{version:04d}_*.sql"))
                shutil.copyfile(source, old_dir / source.name)
            with closing(open_database(":memory:")) as connection:
                self.assertEqual(migrate(connection, old_dir), 4)
                connection.execute(
                    "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('Conservado', ?, ?)",
                    ("2026-10-24T15:30:00Z", "2026-10-24T15:30:00Z"),
                )
                connection.execute(
                    "INSERT INTO cotizaciones (codigo, cliente_id, creada_en_utc) VALUES ('COT-LEGACY', 1, ?)",
                    ("2026-10-24T15:30:00Z",),
                )
                connection.execute(
                    "INSERT INTO cotizacion_detalles (cotizacion_id, descripcion, cantidad, precio_unitario_cop) VALUES (1, 'Detalle preservado', 2, 3000)"
                )
                connection.commit()
                self.assertEqual(migrate(connection, migrations), 7)
                self.assertEqual(connection.execute("SELECT condiciones FROM cotizaciones WHERE id=1").fetchone()[0], "")
                self.assertEqual(connection.execute("SELECT descripcion FROM cotizacion_detalles WHERE id=1").fetchone()[0], "Detalle preservado")
                baseline = connection.execute(
                    "SELECT evento, estado_nuevo, detalle FROM historial_cotizaciones WHERE cotizacion_id=1"
                ).fetchone()
                self.assertEqual(baseline[0:2], ("historial_inicial", "borrador"))
                self.assertIn("eventos anteriores no están disponibles", baseline[2])

    def test_create_read_list_search_and_integer_totals(self) -> None:
        proposal = self.service.create_proposal(
            self.customer["id"], [self.line(), self.line("Memoria", 1, 80_000)],
            expires_on="2030-05-20", notes="Observación", conditions="Vigencia indicada",
        )
        self.assertRegex(proposal["codigo"], r"^COT-[A-F0-9]{12}$")
        self.assertEqual(proposal["total_cop"], 330_000)
        self.assertEqual(proposal["condiciones"], "Vigencia indicada")
        self.assertEqual(self.service.get_proposal(proposal["id"])["lineas"][0]["descripcion"], "Servicio técnico")
        self.assertEqual(self.service.list_proposals(search=proposal["codigo"])[0]["id"], proposal["id"])
        self.assertEqual(self.service.list_proposals(search="Cliente de propuesta")[0]["total_cop"], 330_000)
        self.assertEqual(self.service.list_proposals(state="borrador")[0]["id"], proposal["id"])

    def test_edit_draft_replaces_lines_and_records_history(self) -> None:
        proposal = self.service.create_proposal(self.customer["id"], [self.line()])
        updated = self.service.update_proposal(
            proposal["id"], self.customer["id"], [self.line("Reemplazo", 3, 50_000)],
            notes="Actualizada", conditions="Condiciones revisadas",
        )
        self.assertEqual(updated["total_cop"], 150_000)
        self.assertEqual(updated["lineas"][0]["descripcion"], "Reemplazo")
        self.assertEqual([row["evento"] for row in self.service.proposal_history(proposal["id"])], ["creada", "editada"])

    def test_validate_customer_lines_dates_and_total_range(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.create_proposal(999, [self.line()])
        with self.assertRaises(ValidationError):
            self.service.create_proposal(self.customer["id"], [])
        with self.assertRaises(ValidationError):
            self.service.create_proposal(self.customer["id"], [self.line(quantity=0)])
        with self.assertRaises(ValidationError):
            self.service.create_proposal(self.customer["id"], [self.line(price=-1)])
        with self.assertRaises(ValidationError):
            self.service.create_proposal(self.customer["id"], [self.line(price=1.5)])
        with self.assertRaises(ValidationError):
            self.service.create_proposal(self.customer["id"], [self.line(quantity=1_000_000, price=9_223_372_036_855)])
        with self.assertRaises(ValidationError):
            self.service.create_proposal(self.customer["id"], [self.line()], expires_on="2030-02-30")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM cotizaciones").fetchone()[0], 0)

    def test_transition_policy_and_edit_lock(self) -> None:
        proposal = self.service.create_proposal(self.customer["id"], [self.line()])
        with self.assertRaises(ConflictError):
            self.service.transition_proposal(proposal["id"], "aceptada")
        sent = self.service.transition_proposal(proposal["id"], "enviada")
        self.assertEqual(sent["estado"], "enviada")
        with self.assertRaises(ConflictError):
            self.service.update_proposal(proposal["id"], self.customer["id"], [self.line()])
        accepted = self.service.transition_proposal(proposal["id"], "aceptada", detail="Confirmación telefónica anotada")
        self.assertEqual(accepted["estado"], "aceptada")
        with self.assertRaises(ConflictError):
            self.service.transition_proposal(proposal["id"], "rechazada")
        history = self.service.proposal_history(proposal["id"])
        self.assertEqual([event["estado_nuevo"] for event in history], ["borrador", "enviada", "aceptada"])

    def test_expired_state_requires_past_expiry_date(self) -> None:
        proposal = self.service.create_proposal(self.customer["id"], [self.line()], expires_on="2999-01-01")
        self.service.transition_proposal(proposal["id"], "enviada")
        with self.assertRaises(ConflictError):
            self.service.transition_proposal(proposal["id"], "vencida")

    def test_history_failure_rolls_back_proposal_and_edits(self) -> None:
        self.connection.execute("""CREATE TRIGGER fail_proposal_history BEFORE INSERT ON historial_cotizaciones
            BEGIN SELECT RAISE(ABORT, 'failure'); END""")
        with self.assertRaises(DataIntegrityError):
            self.service.create_proposal(self.customer["id"], [self.line()])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM cotizaciones").fetchone()[0], 0)
        self.connection.execute("DROP TRIGGER fail_proposal_history")
        proposal = self.service.create_proposal(self.customer["id"], [self.line()])
        self.connection.execute("CREATE TRIGGER fail_proposal_edit BEFORE INSERT ON historial_cotizaciones WHEN NEW.evento = 'editada' BEGIN SELECT RAISE(ABORT, 'failure'); END")
        with self.assertRaises(DataIntegrityError):
            self.service.update_proposal(proposal["id"], self.customer["id"], [self.line("Cambio")])
        loaded = self.service.get_proposal(proposal["id"])
        self.assertEqual(loaded["lineas"][0]["descripcion"], "Servicio técnico")

    def test_missing_proposal_lookup(self) -> None:
        with self.assertRaises(NotFoundError):
            self.service.get_proposal(999)

