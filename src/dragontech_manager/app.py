"""Composición de la aplicación Qt y apertura segura de la base local."""

import sys
import sqlite3
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from dragontech_manager import __version__
from dragontech_manager.database.backup import (
    DEFAULT_RETENTION,
    create_backup,
    default_backup_directory,
)
from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.ui.main_window import MainWindow
from dragontech_manager.ui.theme import apply_theme, load_theme_preference

ORGANIZATION_NAME = "DragonTech"
APPLICATION_NAME = "DragonTech Manager"
DATABASE_FILENAME = "dragontech_manager.sqlite3"


def application_data_directory() -> Path:
    """Devuelve el directorio persistente recomendado por Qt para esta app."""
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not location:
        raise OSError("Qt no encontró una ubicación de datos escribible para la aplicación.")
    directory = Path(location)
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise OSError(f"La ruta de datos no es un directorio: {directory}")
    return directory


def _has_migration_history(connection: sqlite3.Connection) -> bool:
    """Indica si la base ya tiene esquema gestionado por migraciones."""
    try:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone() is not None
    except sqlite3.Error:
        return False


def initialize_database(
    database_path: str | Path,
    *,
    backup_dir: str | Path | None = None,
    backup_retention: int = DEFAULT_RETENTION,
) -> tuple[sqlite3.Connection, int]:
    """Abre y migra la base sin borrar ni reemplazar un archivo existente.

    Si se indica ``backup_dir`` y la base ya tenía esquema, crea una copia
    consistente antes de aplicar migraciones. Así toda actualización deja un
    punto de restauración validado.
    """
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_file():
        raise OSError(f"La ruta de la base de datos no es un archivo: {path}")

    connection = open_database(path)
    try:
        if (
            backup_dir is not None
            and path.is_file()
            and path.stat().st_size > 0
            and _has_migration_history(connection)
        ):
            create_backup(
                connection, backup_dir, label="inicio", retention=backup_retention
            )
        version = migrate(connection)
    except Exception:
        connection.close()
        raise
    return connection, version


def create_main_window(
    connection: sqlite3.Connection | None = None,
    *,
    database_path: str | Path | None = None,
    schema_version: int | None = None,
    settings: QSettings | None = None,
) -> MainWindow:
    """Construye la ventana; sin conexión usa SQLite en memoria para pruebas."""
    owns_connection = connection is None
    if connection is None:
        connection = open_database(":memory:")
        schema_version = migrate(connection)
    path_text = str(database_path) if database_path is not None else "Base de datos temporal en memoria"
    return MainWindow(
        connection,
        database_path=path_text,
        schema_version=schema_version or 0,
        owns_connection=owns_connection,
        settings=settings,
    )


def main(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(__version__)
    apply_theme(app, load_theme_preference())

    database_path: Path | None = None
    connection: sqlite3.Connection | None = None
    try:
        database_path = application_data_directory() / DATABASE_FILENAME
        connection, schema_version = initialize_database(
            database_path, backup_dir=default_backup_directory(database_path)
        )
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        QMessageBox.critical(
            None,
            "No se pudo iniciar DragonTech Manager",
            "La base de datos local no pudo abrirse o migrarse. No se eliminó ni se reemplazó "
            "ningún archivo existente. Revisa permisos y espacio disponible.\n\n"
            f"Ubicación: {database_path or 'no disponible'}\n"
            f"Detalle: {error}",
        )
        return 1

    window = MainWindow(
        connection,
        database_path=str(database_path),
        schema_version=schema_version,
    )
    window.show()
    return app.exec()
