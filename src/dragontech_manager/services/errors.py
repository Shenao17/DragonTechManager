"""Errores de aplicación que la futura interfaz puede presentar al usuario."""

import sqlite3


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


def translate_integrity_error(error: sqlite3.IntegrityError) -> ServiceError:
    message = str(error)
    if "UNIQUE constraint failed" in message or "PRIMARY KEY" in message:
        return ConflictError("Ya existe un registro con ese código o identificador.")
    if "FOREIGN KEY constraint failed" in message:
        return DataIntegrityError("Una referencia relacionada ya no existe o no es válida.")
    if "CHECK constraint failed" in message or "NOT NULL constraint failed" in message:
        return ValidationError("Uno o más datos no cumplen las reglas requeridas.")
    if "trigger" in message.lower():
        return DataIntegrityError("La operación contradice una regla de integridad del historial.")
    return DataIntegrityError("No se pudo guardar porque la base rechazó la operación.")
