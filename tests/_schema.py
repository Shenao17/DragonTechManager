"""Versión de esquema vigente, derivada de los archivos de migración (evita editar pruebas en cada migración)."""

from pathlib import Path

MIGRATIONS = Path(__file__).parents[1] / "src/dragontech_manager/database/migrations"
LATEST_VERSION = max(int(path.name[:4]) for path in MIGRATIONS.glob("*.sql"))
MIGRATION_COUNT = len(list(MIGRATIONS.glob("*.sql")))
