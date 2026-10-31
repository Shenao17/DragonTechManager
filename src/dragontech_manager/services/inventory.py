"""Casos de uso para productos, proveedores y trazabilidad del inventario."""

import re
import sqlite3

from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.inventory import InventoryRepository
from ._common import nonnegative_cop, optional_text, pagination, positive_id, required_text, timestamp_and_business_year
from .errors import ConflictError, NotFoundError, ValidationError, translate_integrity_error

_SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,49}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_INTEGER = 9_223_372_036_854_775_807
_STOCK_FILTERS = {"todos", "agotado", "bajo", "disponible"}
_UNSET = object()
# El mecanismo genérico solo corrige ajustes manuales. Los movimientos con
# origen documental se corrigen desde su flujo de negocio para que la venta,
# compra, orden o armado quede consistente con el inventario.
_SOURCE_FLOWS = (
    ("venta_detalle_id", "una venta", "ventas"),
    ("compra_detalle_id", "una compra", "compras"),
    ("orden_repuesto_id", "una orden de servicio", "órdenes de servicio"),
    ("armado_componente_id", "un ensamblaje de PC", "ensamblajes"),
)


class InventoryService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.repository = InventoryRepository(connection)

    @staticmethod
    def _product_values(*, sku: object, name: object, description: object,
                        category: object, unit_cost_cop: object,
                        suggested_price_cop: object, minimum_stock: object,
                        active: object = True) -> dict:
        sku_value = required_text(sku, "El código del producto").upper()
        if not _SKU_RE.fullmatch(sku_value):
            raise ValidationError("El código admite hasta 50 letras, números y los símbolos . _ / -.")
        if not isinstance(active, bool):
            raise ValidationError("El estado activo debe ser verdadero o falso.")
        if minimum_stock is not None:
            if isinstance(minimum_stock, bool) or not isinstance(minimum_stock, int) or not 0 <= minimum_stock <= _MAX_INTEGER:
                raise ValidationError("El stock mínimo debe ser un entero igual o mayor que cero.")
        return {
            "sku": sku_value,
            "name": required_text(name, "El nombre del producto"),
            "description": optional_text(description, "La descripción", none_as_empty=True),
            "category": optional_text(category, "La categoría", none_as_empty=True),
            "unit_cost_cop": nonnegative_cop(unit_cost_cop, "El costo unitario"),
            "suggested_price_cop": nonnegative_cop(suggested_price_cop, "El precio sugerido"),
            "minimum_stock": minimum_stock,
            "active": active,
        }

    def create_product(self, *, sku: str, name: str, description: str = "",
                       category: str = "", unit_cost_cop: int = 0,
                       suggested_price_cop: int = 0, minimum_stock: int | None = None) -> dict:
        values = self._product_values(
            sku=sku, name=name, description=description, category=category,
            unit_cost_cop=unit_cost_cop, suggested_price_cop=suggested_price_cop,
            minimum_stock=minimum_stock,
        )
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                product = self.repository.create_product(values, timestamp)
                return self.get_product(product["id"])
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_product(self, product_id: int) -> dict:
        product_id = positive_id(product_id, "El producto")
        product = self.repository.get_product(product_id)
        if product is None:
            raise NotFoundError("No se encontró el producto solicitado.")
        return product

    def update_product(self, product_id: int, *, sku: str, name: str,
                       description: str | object = _UNSET,
                       category: str | object = _UNSET,
                       unit_cost_cop: int | object = _UNSET,
                       suggested_price_cop: int | object = _UNSET,
                       minimum_stock: int | None | object = _UNSET,
                       active: bool | object = _UNSET) -> dict:
        product_id = positive_id(product_id, "El producto")
        try:
            with atomic(self.connection):
                current = self.repository.get_product(product_id)
                if current is None:
                    raise NotFoundError("No se encontró el producto que se quiere editar.")
                values = self._product_values(
                    sku=sku, name=name,
                    description=current["descripcion"] if description is _UNSET else description,
                    category=current["categoria"] if category is _UNSET else category,
                    unit_cost_cop=current["costo_actual_cop"] if unit_cost_cop is _UNSET else unit_cost_cop,
                    suggested_price_cop=current["precio_actual_cop"] if suggested_price_cop is _UNSET else suggested_price_cop,
                    minimum_stock=current["umbral_reposicion"] if minimum_stock is _UNSET else minimum_stock,
                    active=bool(current["activo"]) if active is _UNSET else active,
                )
                updated = self.repository.update_product(product_id, values)
                if updated is None:
                    raise NotFoundError("No se encontró el producto que se quiere editar.")
                return updated
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def list_products(self, *, search: str | None = None, stock_filter: str = "todos",
                      active: bool | None = True, limit: int = 100, offset: int = 0) -> list[dict]:
        if stock_filter not in _STOCK_FILTERS:
            raise ValidationError("El filtro de existencias no es válido.")
        if active is not None and not isinstance(active, bool):
            raise ValidationError("El filtro de actividad no es válido.")
        return self.repository.list_products(
            search=optional_text(search, "La búsqueda"), stock_filter=stock_filter,
            active=active, limit=limit, offset=offset,
        )

    def product_movements(self, product_id: int, *, limit: int = 100, offset: int = 0) -> list[dict]:
        product_id = positive_id(product_id, "El producto")
        self.get_product(product_id)
        limit, offset = pagination(limit, offset)
        return self.repository.list_movements(product_id, limit=limit, offset=offset)

    def can_reverse_movement(self, movement_id: int) -> bool:
        movement_id = positive_id(movement_id, "El movimiento")
        movement = self.repository.get_movement(movement_id)
        return bool(movement and self._reversal_blocked_reason(movement) is None)

    def _reversal_blocked_reason(self, movement: dict) -> str | None:
        if movement["tipo"] == "reversion":
            return "Un movimiento de reversión no se puede revertir de nuevo."
        if self.repository.movement_reversal_exists(movement["id"]):
            return "Este movimiento ya tiene una reversión registrada."
        for column, origin, flow in _SOURCE_FLOWS:
            if movement.get(column) is not None:
                return (
                    f"Este movimiento proviene de {origin}. El mecanismo genérico solo "
                    f"revierte ajustes: corrige la operación desde el flujo de {flow} para "
                    "conservar la trazabilidad."
                )
        return None

    def reversal_blocked_reason(self, movement_id: int) -> str | None:
        """Motivo por el que el mecanismo genérico no puede revertir el movimiento.

        Devuelve ``None`` cuando la reversión genérica sí está permitida.
        """
        movement_id = positive_id(movement_id, "El movimiento")
        movement = self.repository.get_movement(movement_id)
        if movement is None:
            raise NotFoundError("No se encontró el movimiento solicitado.")
        return self._reversal_blocked_reason(movement)

    def get_movement(self, movement_id: int) -> dict:
        movement_id = positive_id(movement_id, "El movimiento")
        movement = self.repository.get_movement(movement_id)
        if movement is None:
            raise NotFoundError("No se encontró el movimiento solicitado.")
        return movement

    def stock_summary(self) -> dict[str, int]:
        return self.repository.stock_summary()

    def adjust_stock(self, product_id: int, quantity_delta: int, *,
                     unit_cost_cop: int, reason: str) -> dict:
        product_id = positive_id(product_id, "El producto")
        if isinstance(quantity_delta, bool) or not isinstance(quantity_delta, int) or quantity_delta == 0 or abs(quantity_delta) > _MAX_INTEGER:
            raise ValidationError("El ajuste debe ser una cantidad entera distinta de cero.")
        unit_cost_cop = nonnegative_cop(unit_cost_cop, "El costo histórico")
        reason_value = required_text(reason, "El motivo del ajuste")
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                stock = self.repository.stock_and_reserved(product_id)
                if stock is None:
                    raise NotFoundError("No se encontró el producto que se quiere ajustar.")
                on_hand, reserved = stock
                if on_hand + quantity_delta < reserved:
                    raise ConflictError("El ajuste dejaría el stock por debajo de las unidades reservadas.")
                return self.repository.add_movement(
                    product_id=product_id, delta=quantity_delta, cost_cop=unit_cost_cop,
                    kind="ajuste", created_utc=timestamp, reason=reason_value,
                )
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def reverse_movement(self, movement_id: int, *, reason: str) -> dict:
        movement_id = positive_id(movement_id, "El movimiento")
        reason_value = required_text(reason, "El motivo de reversión")
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                original = self.repository.get_movement(movement_id)
                if original is None:
                    raise NotFoundError("No se encontró el movimiento que se quiere corregir.")
                blocked = self._reversal_blocked_reason(original)
                if blocked:
                    raise ConflictError(blocked)
                stock = self.repository.stock_and_reserved(original["producto_id"])
                if stock is None or stock[0] - original["cantidad_delta"] < stock[1]:
                    raise ConflictError("La reversión dejaría el stock por debajo de las unidades reservadas.")
                return self.repository.add_movement(
                    product_id=original["producto_id"], delta=-original["cantidad_delta"],
                    cost_cop=original["costo_unitario_historico_cop"], kind="reversion",
                    created_utc=timestamp, reason=reason_value,
                    reverses_movement_id=movement_id,
                )
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    @staticmethod
    def _supplier_values(*, name: object, tax_id: object, phone: object,
                         email: object, address: object, notes: object,
                         active: object = True) -> dict:
        if not isinstance(active, bool):
            raise ValidationError("El estado activo debe ser verdadero o falso.")
        tax_value = optional_text(tax_id, "La identificación fiscal")
        email_value = optional_text(email, "El correo")
        if email_value and (len(email_value) > 254 or not _EMAIL_RE.fullmatch(email_value)):
            raise ValidationError("El correo del proveedor no tiene un formato válido.")
        return {
            "name": required_text(name, "El nombre del proveedor"),
            "tax_id": tax_value,
            "phone": optional_text(phone, "El teléfono"),
            "email": email_value,
            "address": optional_text(address, "La dirección", none_as_empty=True),
            "notes": optional_text(notes, "Las notas", none_as_empty=True),
            "active": active,
        }

    def create_supplier(self, *, name: str, tax_id: str | None = None,
                        phone: str | None = None, email: str | None = None,
                        address: str = "", notes: str = "") -> dict:
        values = self._supplier_values(name=name, tax_id=tax_id, phone=phone,
                                       email=email, address=address, notes=notes)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                if values["tax_id"] and self.repository.supplier_tax_id_exists(values["tax_id"]):
                    raise ConflictError("Ya existe un proveedor con esa identificación fiscal.")
                return self.repository.create_supplier(values, timestamp)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_supplier(self, supplier_id: int) -> dict:
        supplier_id = positive_id(supplier_id, "El proveedor")
        supplier = self.repository.get_supplier(supplier_id)
        if supplier is None:
            raise NotFoundError("No se encontró el proveedor solicitado.")
        return supplier

    def update_supplier(self, supplier_id: int, *, name: str,
                        tax_id: str | None | object = _UNSET,
                        phone: str | None | object = _UNSET,
                        email: str | None | object = _UNSET,
                        address: str | object = _UNSET,
                        notes: str | object = _UNSET,
                        active: bool | object = _UNSET) -> dict:
        supplier_id = positive_id(supplier_id, "El proveedor")
        try:
            with atomic(self.connection):
                current = self.repository.get_supplier(supplier_id)
                if current is None:
                    raise NotFoundError("No se encontró el proveedor que se quiere editar.")
                values = self._supplier_values(
                    name=name,
                    tax_id=current["identificacion_fiscal"] if tax_id is _UNSET else tax_id,
                    phone=current["telefono"] if phone is _UNSET else phone,
                    email=current["correo"] if email is _UNSET else email,
                    address=current["direccion"] if address is _UNSET else address,
                    notes=current["notas"] if notes is _UNSET else notes,
                    active=bool(current["activo"]) if active is _UNSET else active,
                )
                if values["tax_id"] and self.repository.supplier_tax_id_exists(values["tax_id"], except_id=supplier_id):
                    raise ConflictError("Ya existe otro proveedor con esa identificación fiscal.")
                updated = self.repository.update_supplier(supplier_id, values)
                if updated is None:
                    raise NotFoundError("No se encontró el proveedor que se quiere editar.")
                return updated
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def list_suppliers(self, *, search: str | None = None, active: bool | None = True,
                       limit: int = 100, offset: int = 0) -> list[dict]:
        if active is not None and not isinstance(active, bool):
            raise ValidationError("El filtro de actividad no es válido.")
        return self.repository.list_suppliers(
            search=optional_text(search, "La búsqueda"), active=active,
            limit=limit, offset=offset,
        )
