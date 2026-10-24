"""Asignación transaccional de códigos legibles para equipos y órdenes."""

import sqlite3

_PREFIXES = {"equipo": "EQ", "orden_servicio": "OS"}


def allocate_code(connection: sqlite3.Connection, entity: str, year: int) -> str:
    """Reserva el siguiente código dentro de una transacción abierta.

    La inserción del registro que usa el código debe ocurrir en esa misma
    transacción. Al revertirla, también se revierte el ordinal reservado.
    """
    if not connection.in_transaction:
        raise RuntimeError("allocate_code requiere una transacción activa")
    try:
        prefix = _PREFIXES[entity]
    except KeyError as exc:
        raise ValueError(f"Entidad sin secuencia visible: {entity}") from exc
    if not 1 <= year <= 9999:
        raise ValueError("El año debe estar entre 0001 y 9999")

    row = connection.execute(
        """INSERT INTO secuencias (entidad, anio, siguiente_ordinal)
           VALUES (?, ?, 2)
           ON CONFLICT (entidad, anio) DO UPDATE
             SET siguiente_ordinal = siguiente_ordinal + 1
             WHERE siguiente_ordinal <= 999999
           RETURNING siguiente_ordinal - 1""",
        (entity, year),
    ).fetchone()
    if row is None:
        raise OverflowError(f"Se agotaron los códigos de {entity} para {year}")
    return f"{prefix}-{year:04d}-{row[0]:06d}"
