"""Configuración común para conexiones SQLite locales."""

import sqlite3
from os import PathLike


def open_database(path: str | PathLike[str]) -> sqlite3.Connection:
    """Abre SQLite con claves foráneas y timeout de bloqueo habilitados.

    La función no crea tablas ni aplica migraciones. El llamador es responsable
    de cerrar la conexión, preferiblemente con ``contextlib.closing``.
    """
    connection = sqlite3.connect(path, timeout=5.0)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.row_factory = sqlite3.Row
        return connection
    except Exception:
        connection.close()
        raise
