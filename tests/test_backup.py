"""Respaldos consistentes, retención rotativa y restauración verificada."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from dragontech_manager.app import initialize_database
from dragontech_manager.database import backup as backup_module
from dragontech_manager.database.backup import (
    BackupError,
    create_backup,
    list_backups,
    restore_backup,
    rotate_backups,
    validate_backup,
)
from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "data" / "dragontech_manager.sqlite3"
        self.db_path.parent.mkdir(parents=True)
        self.backup_dir = self.root / "backups"
        self.connection = open_database(self.db_path)
        self.addCleanup(self.connection.close)
        self.version = migrate(self.connection)
        self.customers = CustomerService(self.connection)
        self.customer = self.customers.create_customer("Cliente respaldado")

    def _customer_names(self, path: Path) -> list[str]:
        with closing(open_database(path)) as connection:
            return [row[0] for row in connection.execute(
                "SELECT nombre FROM clientes ORDER BY id"
            )]

    def test_backup_is_consistent_validated_and_leaves_no_temporary_files(self) -> None:
        path = create_backup(self.connection, self.backup_dir, label="prueba")
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent, self.backup_dir)
        self.assertEqual(validate_backup(path), self.version)
        self.assertEqual(self._customer_names(path), ["Cliente respaldado"])
        self.assertEqual(list_backups(self.backup_dir), [path])
        self.assertEqual(list(self.backup_dir.glob("*.tmp")), [])

    def test_backup_requires_a_committed_transaction(self) -> None:
        self.connection.execute(
            "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) "
            "VALUES ('Sin confirmar', '2026-10-24T15:30:00Z', '2026-10-24T15:30:00Z')"
        )
        with self.assertRaises(BackupError) as captured:
            create_backup(self.connection, self.backup_dir)
        self.assertIn("sin confirmar", str(captured.exception).lower())
        self.connection.rollback()
        self.assertEqual(list_backups(self.backup_dir), [])

    def test_rotation_keeps_newest_and_never_deletes_foreign_files(self) -> None:
        kept = []
        for index in range(5):
            kept.append(create_backup(self.connection, self.backup_dir, retention=3))
        foreign = self.backup_dir / "notas.txt"
        foreign.write_text("no administrado", encoding="utf-8")
        similar = self.backup_dir / "dragontech_manager_manual.sqlite3"
        similar.write_text("nombre no generado por la app", encoding="utf-8")

        backups = list_backups(self.backup_dir)
        self.assertEqual(len(backups), 3)
        self.assertEqual(set(backups), set(kept[-3:]))
        self.assertTrue(foreign.is_file())
        self.assertTrue(similar.is_file())

        removed = rotate_backups(self.backup_dir, 1)
        self.assertEqual(len(removed), 2)
        self.assertEqual(len(list_backups(self.backup_dir)), 1)
        with self.assertRaises(BackupError):
            rotate_backups(self.backup_dir, 0)

    def test_validation_rejects_empty_corrupt_missing_and_foreign_files(self) -> None:
        missing = self.backup_dir / "no-existe.sqlite3"
        with self.assertRaises(BackupError):
            validate_backup(missing)

        self.backup_dir.mkdir()
        empty = self.backup_dir / "dragontech_manager_20260101T000000000000Z_vacia.sqlite3"
        empty.write_bytes(b"")
        with self.assertRaises(BackupError):
            validate_backup(empty)

        corrupt = self.backup_dir / "dragontech_manager_20260101T000000000001Z_corrupta.sqlite3"
        corrupt.write_bytes(b"esto no es una base sqlite")
        with self.assertRaises(BackupError):
            validate_backup(corrupt)

        foreign = self.backup_dir / "ajena.sqlite3"
        with closing(sqlite3.connect(foreign)) as connection:
            connection.execute("CREATE TABLE ejemplo (id INTEGER PRIMARY KEY)")
            connection.commit()
        with self.assertRaises(BackupError):
            validate_backup(foreign)

    def test_transient_lock_is_retried_then_succeeds(self) -> None:
        original = backup_module._copy_database
        calls = {"count": 0}

        def flaky(source, target_path):
            calls["count"] += 1
            if calls["count"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return original(source, target_path)

        with patch.object(backup_module, "_copy_database", new=flaky):
            path = create_backup(
                self.connection, self.backup_dir, retries=1, retry_delay=0
            )
        self.assertEqual(calls["count"], 2)
        self.assertEqual(validate_backup(path), self.version)
        self.assertEqual(self._customer_names(path), ["Cliente respaldado"])

    def test_permanent_failure_cleans_temporary_file_and_reports_error(self) -> None:
        def always_locked(source, target_path):
            raise sqlite3.OperationalError("database is locked")

        with patch.object(backup_module, "_copy_database", new=always_locked):
            with self.assertRaises(BackupError):
                create_backup(
                    self.connection, self.backup_dir, retries=1, retry_delay=0
                )
        self.assertEqual(list_backups(self.backup_dir), [])
        self.assertEqual(list(self.backup_dir.glob("*.tmp")), [])

    def test_restore_returns_to_backup_and_keeps_a_safety_copy(self) -> None:
        snapshot = create_backup(self.connection, self.backup_dir, label="antes")
        self.customers.create_customer("Cliente posterior")
        self.connection.close()

        result = restore_backup(snapshot, self.db_path, safety_dir=self.backup_dir)
        self.assertEqual(result.schema_version, self.version)
        self.assertIsNotNone(result.safety_backup)
        self.assertEqual(self._customer_names(self.db_path), ["Cliente respaldado"])
        self.assertEqual(
            self._customer_names(result.safety_backup),
            ["Cliente respaldado", "Cliente posterior"],
        )
        self.assertEqual(validate_backup(self.db_path), self.version)

    def test_corrupt_restore_is_rejected_without_touching_the_database(self) -> None:
        self.backup_dir.mkdir()
        corrupt = self.backup_dir / "dragontech_manager_20260101T000000000002Z_mala.sqlite3"
        corrupt.write_bytes(b"archivo invalido")
        before = self.db_path.read_bytes()

        with self.assertRaises(BackupError):
            restore_backup(corrupt, self.db_path, safety_dir=self.backup_dir)

        self.assertEqual(self.db_path.read_bytes(), before)
        self.assertEqual(self._customer_names(self.db_path), ["Cliente respaldado"])

    def test_failed_post_restore_validation_recovers_the_safety_copy(self) -> None:
        snapshot = create_backup(self.connection, self.backup_dir, label="antes")
        self.customers.create_customer("Cliente posterior")
        self.connection.close()
        real_validate = backup_module.validate_backup
        calls = {"count": 0}

        def fail_once(path):
            calls["count"] += 1
            if calls["count"] == 3:
                raise BackupError("validación simulada")
            return real_validate(path)

        with patch.object(backup_module, "validate_backup", new=fail_once):
            with self.assertRaises(BackupError) as captured:
                restore_backup(snapshot, self.db_path, safety_dir=self.backup_dir)
        self.assertIn("no se completó", str(captured.exception))
        self.assertEqual(calls["count"], 3)
        self.assertEqual(
            self._customer_names(self.db_path),
            ["Cliente respaldado", "Cliente posterior"],
        )

    def test_restore_over_memory_database_is_rejected(self) -> None:
        snapshot = create_backup(self.connection, self.backup_dir)
        with self.assertRaises(BackupError):
            restore_backup(snapshot, ":memory:", safety_dir=self.backup_dir)

    def test_initialize_database_backs_up_before_migrating(self) -> None:
        connection, version = initialize_database(
            self.db_path, backup_dir=self.backup_dir
        )
        self.addCleanup(connection.close)
        self.assertEqual(version, self.version)
        backups = list_backups(self.backup_dir)
        self.assertEqual(len(backups), 1)
        self.assertIn("_inicio", backups[0].name)
        self.assertEqual(validate_backup(backups[0]), self.version)
        self.assertEqual(self._customer_names(backups[0]), ["Cliente respaldado"])

    def test_new_database_does_not_create_a_startup_backup(self) -> None:
        new_path = self.root / "nueva" / "dragontech_manager.sqlite3"
        connection, version = initialize_database(
            new_path, backup_dir=self.root / "respaldos-nuevos"
        )
        self.addCleanup(connection.close)
        self.assertEqual(version, self.version)
        self.assertEqual(list_backups(self.root / "respaldos-nuevos"), [])

    def test_startup_backup_failure_prevents_opening_the_database(self) -> None:
        with patch("dragontech_manager.app.create_backup", side_effect=BackupError("disco lleno")):
            with self.assertRaises(BackupError):
                initialize_database(self.db_path, backup_dir=self.backup_dir)
        self.assertEqual(self._customer_names(self.db_path), ["Cliente respaldado"])


if __name__ == "__main__":
    unittest.main()
