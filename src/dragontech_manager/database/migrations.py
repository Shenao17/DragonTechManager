"""Migraciones SQLite versionadas y aplicadas de forma atómica."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_MIGRATION_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_DEFAULT_MIGRATIONS = Path(__file__).with_name("migrations")


class MigrationError(RuntimeError):
    """La base no puede migrarse con seguridad."""


def _statements(script: str) -> list[str]:
    """Divide SQL respetando bloques como CREATE TRIGGER ... BEGIN/END."""
    statements: list[str] = []
    current = ""
    for line in script.splitlines(keepends=True):
        current += line
        if sqlite3.complete_statement(current):
            if current.strip():
                statements.append(current)
            current = ""
    if current.strip():
        raise MigrationError("La migración termina con una sentencia SQL incompleta")
    return statements


def _check_integrity(connection: sqlite3.Connection) -> None:
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    if integrity != ["ok"]:
        raise MigrationError(f"La base no pasó PRAGMA integrity_check: {integrity!r}")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(f"La migración dejó violaciones de claves foráneas: {violations!r}")


def migrate(connection: sqlite3.Connection, migrations_dir: Path | None = None) -> int:
    """Aplica migraciones pendientes; conserva el historial y detecta cambios.

    Debe ejecutarse sobre una conexión abierta mediante ``open_database``.
    El DDL y el registro de versión se confirman juntos por migración.
    """
    if connection.in_transaction:
        raise MigrationError(
            "Confirme o revierta la transacción activa antes de ejecutar migraciones."
        )
    directory = migrations_dir or _DEFAULT_MIGRATIONS
    files: list[tuple[int, str, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if not match:
            raise MigrationError(f"Nombre de migración no válido: {path.name}")
        files.append((int(match.group(1)), path.name, path))
    versions = [version for version, _, _ in files]
    if len(set(versions)) != len(versions):
        raise MigrationError("Hay números de migración duplicados")

    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version INTEGER PRIMARY KEY,
               name TEXT NOT NULL UNIQUE,
               checksum_sha256 TEXT NOT NULL,
               applied_at_utc TEXT NOT NULL
           )"""
    )
    applied = {
        row["version"]: (row["name"], row["checksum_sha256"])
        for row in connection.execute(
            "SELECT version, name, checksum_sha256 FROM schema_migrations"
        )
    }
    available = {version: (name, path) for version, name, path in files}
    missing = set(applied) - set(available)
    if missing:
        raise MigrationError(f"Faltan archivos de migraciones ya aplicadas: {sorted(missing)}")

    for version, (name, checksum) in applied.items():
        source = available[version][1].read_bytes()
        if available[version][0] != name or hashlib.sha256(source).hexdigest() != checksum:
            raise MigrationError(f"La migración aplicada {version:04d} fue modificada")

    for version, name, path in files:
        if version in applied:
            continue
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        statements = _statements(source.decode("utf-8"))
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in statements:
                connection.execute(statement)
            _check_integrity(connection)
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            connection.execute(
                """INSERT INTO schema_migrations
                   (version, name, checksum_sha256, applied_at_utc)
                   VALUES (?, ?, ?, ?)""",
                (version, name, digest, timestamp),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise

    _check_integrity(connection)
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return row[0] or 0


def check_integrity(connection: sqlite3.Connection) -> None:
    """Lanza ``MigrationError`` si la base tiene claves foráneas inválidas."""
    _check_integrity(connection)
