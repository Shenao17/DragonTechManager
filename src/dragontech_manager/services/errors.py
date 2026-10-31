"""Errores de aplicación que la interfaz puede presentar al usuario."""

import re
import sqlite3

_UNIQUE = re.compile(r"UNIQUE constraint failed: (.+)")
_NOT_NULL = re.compile(r"NOT NULL constraint failed: (.+)")
_CHECK = re.compile(r"CHECK constraint failed: (.+)")
_FOREIGN_KEY = "FOREIGN KEY constraint failed"
# SQLite reporta los mensajes propios de RAISE(ABORT, ...) sin prefijo técnico.
# Todo lo que no coincide con las familias anteriores proviene de un trigger.
_INTERNAL_HINTS = ("constraint failed", "datatype mismatch", "database disk image")

_FIELD_LABELS = {
    "sku": "el código (SKU)",
    "codigo": "el código",
    "nombre": "el nombre",
    "identificacion_fiscal": "la identificación fiscal",
    "correo": "el correo",
    "telefono": "el teléfono",
    "documento": "el documento",
    "numero_serie": "el número de serie",
    "clave_idempotencia": "la clave de reintento",
    "referencia": "la referencia",
    "cliente_id": "el cliente",
    "producto_id": "el producto",
    "proveedor_id": "el proveedor",
    "orden_id": "la orden",
    "venta_id": "la venta",
    "compra_id": "la compra",
}


class ServiceError(Exception):
    """Error esperado al ejecutar un caso de uso."""


class ValidationError(ServiceError):
    """Entrada inválida antes de persistirla."""


class NotFoundError(ServiceError):
    """No existe el registro solicitado."""


class ConflictError(ServiceError):
    """La operación entra en conflicto con un dato ya registrado."""


class DataIntegrityError(ServiceError):
    """La base rechazó la operación por una regla de integridad."""


def _qualified_fields(raw: str) -> list[str]:
    fields: list[str] = []
    for part in raw.split(","):
        column = part.strip().split(".")[-1]
        if column and column not in fields:
            fields.append(column)
    return fields


def _describe_fields(fields: list[str]) -> str:
    if not fields:
        return ""
    labels = [_FIELD_LABELS.get(field, field.replace("_", " ")) for field in fields]
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " y " + labels[-1]


def translate_integrity_error(error: sqlite3.IntegrityError) -> ServiceError:
    """Convierte un error de SQLite en un mensaje específico y comprensible.

    Conserva el detalle de los ``RAISE(ABORT, ...)`` de los triggers, que son
    reglas de negocio escritas en español, y traduce las restricciones
    estructurales indicando el campo concreto cuando SQLite lo informa.
    """
    message = str(error).strip()

    match = _UNIQUE.search(message)
    if match:
        fields = _qualified_fields(match.group(1))
        described = _describe_fields(fields)
        if described:
            return ConflictError(f"Ya existe un registro con {described} igual.")
        return ConflictError("Ya existe un registro con ese código o identificador.")

    match = _NOT_NULL.search(message)
    if match:
        fields = _qualified_fields(match.group(1))
        described = _describe_fields(fields)
        if described:
            return ValidationError(f"Falta un dato obligatorio: {described}.")
        return ValidationError("Falta un dato obligatorio para guardar el registro.")

    match = _CHECK.search(message)
    if match:
        fields = _qualified_fields(match.group(1))
        described = _describe_fields(fields)
        if described and all(field in _FIELD_LABELS for field in fields):
            return ValidationError(f"El valor de {described} no cumple las reglas requeridas.")
        return ValidationError("Uno o más datos no cumplen las reglas requeridas.")

    if _FOREIGN_KEY in message:
        return DataIntegrityError(
            "Una referencia relacionada ya no existe o no es válida."
        )

    lowered = message.lower()
    if message and not any(hint in lowered for hint in _INTERNAL_HINTS):
        # Mensaje de RAISE(...) de un trigger: es la regla de negocio concreta.
        return DataIntegrityError(message)

    return DataIntegrityError("No se pudo guardar porque la base rechazó la operación.")
