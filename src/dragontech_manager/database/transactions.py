"""Contexto transaccional SQLite con soporte para operaciones anidadas."""

from contextlib import contextmanager
import sqlite3
from uuid import uuid4


@contextmanager
def atomic(connection: sqlite3.Connection, *, immediate: bool = True):
    """Ejecuta una unidad atómica; usa savepoint si ya existe una transacción."""
    if connection.in_transaction:
        savepoint = f"sp_{uuid4().hex}"
        connection.execute(f"SAVEPOINT {savepoint}")
        try:
            yield connection
        except BaseException:
            connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        else:
            connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        return

    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
