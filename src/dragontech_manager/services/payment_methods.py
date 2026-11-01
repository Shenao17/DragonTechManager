"""Catálogo único de métodos de pago para clientes y proveedores."""

import sqlite3

from ..repositories.payment_methods import PaymentMethodRepository
from .errors import ValidationError

_SCOPES = {"cliente": "aplica_cliente", "proveedor": "aplica_proveedor"}


class PaymentMethodService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.repository = PaymentMethodRepository(connection)

    def list_methods(self, scope: str | None = None, *, only_active: bool = True) -> list[dict]:
        if scope is not None and scope not in _SCOPES:
            raise ValidationError("El ámbito del método de pago no es válido.")
        return self.repository.list_methods(scope=scope, only_active=only_active)

    def resolve(self, method: object, scope: str) -> dict:
        """Devuelve el método activo aplicable a ``scope``.

        Acepta el id del catálogo o un nombre/alias conocido (incluye textos legados).
        Un texto desconocido se rechaza: no se crean métodos implícitos.
        """
        if scope not in _SCOPES:
            raise ValidationError("El ámbito del método de pago no es válido.")
        if isinstance(method, bool):
            raise ValidationError("El medio de pago no es válido.")
        if isinstance(method, int):
            found = self.repository.get(method)
        elif isinstance(method, str) and method.strip():
            found = self.repository.get_by_alias(method)
        else:
            raise ValidationError("El medio de pago es obligatorio.")
        if found is None:
            raise ValidationError("El medio de pago no existe en el catálogo.")
        if not found["activo"]:
            raise ValidationError(f"El medio de pago «{found['nombre']}» está inactivo.")
        if not found[_SCOPES[scope]]:
            raise ValidationError(
                f"El medio de pago «{found['nombre']}» no aplica a pagos de {scope}s."
            )
        return found
