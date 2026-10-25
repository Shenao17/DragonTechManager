"""Casos de uso de compras y cuentas por pagar a proveedores."""

from datetime import date, datetime, timezone
import sqlite3
from zoneinfo import ZoneInfo

from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.inventory import InventoryRepository
from dragontech_manager.repositories.procurement import ProcurementRepository
from ._common import nonnegative_cop, optional_text, pagination, positive_id, required_text, timestamp_and_business_year
from .errors import ConflictError, NotFoundError, ValidationError, translate_integrity_error

_BOGOTA = ZoneInfo("America/Bogota")
_MAX_INTEGER = 9_223_372_036_854_775_807
_PURCHASE_STATES = {"borrador", "pendiente", "recibida", "cancelada"}


class ProcurementService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.repository = ProcurementRepository(connection)
        self.inventory = InventoryRepository(connection)

    @staticmethod
    def _calendar_date(value: object | None, label: str) -> str:
        if value is None:
            return datetime.now(timezone.utc).astimezone(_BOGOTA).date().isoformat()
        if not isinstance(value, str):
            raise ValidationError(f"{label} debe tener formato AAAA-MM-DD.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValidationError(f"{label} debe tener formato AAAA-MM-DD.") from error
        if parsed.isoformat() != value:
            raise ValidationError(f"{label} debe tener formato AAAA-MM-DD.")
        return value

    @staticmethod
    def _lines(lines: object) -> list[dict]:
        if not isinstance(lines, (list, tuple)) or not lines:
            raise ValidationError("Agrega al menos un producto a la compra.")
        prepared: list[dict] = []
        total = 0
        seen_products: set[int] = set()
        for number, line in enumerate(lines, 1):
            if not isinstance(line, dict):
                raise ValidationError(f"La línea {number} no es válida.")
            product_id = positive_id(line.get("product_id"), f"El producto de la línea {number}")
            if product_id in seen_products:
                raise ValidationError("Cada producto debe aparecer una sola vez; ajusta su cantidad en la línea existente.")
            seen_products.add(product_id)
            quantity = line.get("quantity")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 1_000_000:
                raise ValidationError(f"La cantidad de la línea {number} debe ser un entero positivo.")
            cost = nonnegative_cop(line.get("unit_cost_cop"), f"El costo de la línea {number}")
            subtotal = quantity * cost
            if subtotal > _MAX_INTEGER or total > _MAX_INTEGER - subtotal:
                raise ValidationError("El total de la compra supera el rango monetario admitido por SQLite.")
            total += subtotal
            description = optional_text(line.get("description"), f"La descripción de la línea {number}")
            prepared.append({
                "product_id": product_id, "quantity": quantity,
                "unit_cost_cop": cost, "description": description or "",
            })
        return prepared

    def _validate_supplier_and_products(self, supplier_id: int, lines: list[dict], *,
                                        require_active_products: bool) -> None:
        supplier = self.connection.execute(
            "SELECT activo FROM proveedores WHERE id = ?", (supplier_id,)
        ).fetchone()
        if supplier is None:
            raise NotFoundError("Selecciona un proveedor existente.")
        if not supplier["activo"]:
            raise ConflictError("El proveedor está inactivo y no admite nuevas compras.")
        for line in lines:
            product = self.connection.execute(
                "SELECT nombre, activo FROM productos WHERE id = ?", (line["product_id"],)
            ).fetchone()
            if product is None:
                raise NotFoundError("Uno de los productos de la compra ya no existe.")
            if require_active_products and not product["activo"]:
                raise ConflictError(f"El producto «{product['nombre']}» está inactivo.")
            if not line["description"]:
                line["description"] = product["nombre"]

    def create_purchase(self, supplier_id: int, lines: list[dict], *,
                        reference: str = "", purchase_date: str | None = None,
                        notes: str = "") -> dict:
        supplier_id = positive_id(supplier_id, "El proveedor")
        prepared = self._lines(lines)
        purchase_date = self._calendar_date(purchase_date, "La fecha de compra")
        reference_value = optional_text(reference, "La referencia", none_as_empty=True)
        notes_value = optional_text(notes, "Las observaciones", none_as_empty=True)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                self._validate_supplier_and_products(supplier_id, prepared, require_active_products=True)
                purchase = self.repository.create_purchase(
                    supplier_id=supplier_id, reference=reference_value,
                    purchase_date=purchase_date, notes=notes_value, created_utc=timestamp,
                )
                for line in prepared:
                    self.repository.add_purchase_line(purchase["id"], line)
                return self.get_purchase(purchase["id"])
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_purchase(self, purchase_id: int) -> dict:
        purchase_id = positive_id(purchase_id, "La compra")
        purchase = self.repository.get_purchase(purchase_id)
        if purchase is None:
            raise NotFoundError("No se encontró la compra solicitada.")
        purchase["lineas"] = self.repository.purchase_lines(purchase_id)
        purchase["pagos"] = self.repository.list_supplier_payments(purchase_id)
        return purchase

    def update_purchase(self, purchase_id: int, supplier_id: int, lines: list[dict], *,
                        reference: str = "", purchase_date: str | None = None,
                        notes: str = "") -> dict:
        purchase_id = positive_id(purchase_id, "La compra")
        supplier_id = positive_id(supplier_id, "El proveedor")
        prepared = self._lines(lines)
        purchase_date = self._calendar_date(purchase_date, "La fecha de compra")
        reference_value = optional_text(reference, "La referencia", none_as_empty=True)
        notes_value = optional_text(notes, "Las observaciones", none_as_empty=True)
        try:
            with atomic(self.connection):
                current = self.repository.get_purchase(purchase_id)
                if current is None:
                    raise NotFoundError("No se encontró la compra que se quiere editar.")
                if current["estado"] != "borrador":
                    raise ConflictError("Solo se pueden editar compras en borrador.")
                if self.repository.purchase_has_payment_history(purchase_id):
                    raise ConflictError("No se edita una compra que conserve historial de pagos o reversiones.")
                self._validate_supplier_and_products(supplier_id, prepared, require_active_products=True)
                self.repository.update_purchase(
                    purchase_id, supplier_id=supplier_id, reference=reference_value,
                    purchase_date=purchase_date, notes=notes_value,
                )
                for line in prepared:
                    self.repository.add_purchase_line(purchase_id, line)
                return self.get_purchase(purchase_id)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def list_purchases(self, *, search: str | None = None, state: str | None = None,
                       limit: int = 100, offset: int = 0) -> list[dict]:
        search_value = optional_text(search, "La búsqueda")
        if state is not None and state not in _PURCHASE_STATES:
            raise ValidationError("El filtro de estado de compra no es válido.")
        limit, offset = pagination(limit, offset)
        return self.repository.list_purchases(
            search=search_value, state=state, limit=limit, offset=offset,
        )

    def transition_purchase(self, purchase_id: int, new_state: str) -> dict:
        purchase_id = positive_id(purchase_id, "La compra")
        if new_state not in _PURCHASE_STATES:
            raise ValidationError("El estado solicitado para la compra no es válido.")
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                current = self.repository.get_purchase(purchase_id)
                if current is None:
                    raise NotFoundError("No se encontró la compra solicitada.")
                if current["estado"] == "borrador" and new_state in {"pendiente", "cancelada"}:
                    if new_state == "pendiente" and not self.repository.purchase_lines(purchase_id):
                        raise ValidationError("Agrega al menos un producto antes de confirmar la compra.")
                elif current["estado"] == "pendiente" and new_state in {"recibida", "cancelada"}:
                    if new_state == "cancelada" and current["pagado_neto_cop"] != 0:
                        raise ConflictError("Revierte los pagos registrados antes de cancelar la compra.")
                else:
                    raise ConflictError(f"No se permite pasar una compra de «{current['estado']}» a «{new_state}».")

                if new_state == "recibida":
                    lines = self.repository.purchase_lines(purchase_id)
                    if not lines:
                        raise ValidationError("La compra no tiene líneas que puedan recibirse.")
                    received_on = datetime.now(timezone.utc).astimezone(_BOGOTA).date().isoformat()
                    self.repository.set_purchase_state(purchase_id, "recibida", received_on=received_on)
                    for line in lines:
                        self.inventory.add_movement(
                            product_id=line["producto_id"], delta=line["cantidad"],
                            cost_cop=line["costo_unitario_historico_cop"], kind="compra",
                            created_utc=timestamp, reason=f"Recepción de compra #{purchase_id}",
                            purchase_line_id=line["id"],
                        )
                else:
                    self.repository.set_purchase_state(purchase_id, new_state)
                return self.get_purchase(purchase_id)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def register_supplier_payment(self, purchase_id: int, amount_cop: int, *,
                                  method: str, reference: str = "") -> dict:
        purchase_id = positive_id(purchase_id, "La compra")
        amount_cop = nonnegative_cop(amount_cop, "El pago")
        if amount_cop <= 0:
            raise ValidationError("El pago debe ser mayor que cero.")
        method_value = required_text(method, "El medio de pago")
        reference_value = optional_text(reference, "La referencia", none_as_empty=True)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                purchase = self.repository.get_purchase(purchase_id)
                if purchase is None:
                    raise NotFoundError("No se encontró la compra a la que se quiere asociar el pago.")
                if purchase["estado"] not in {"pendiente", "recibida"}:
                    raise ConflictError("Los pagos se registran cuando la compra está confirmada o recibida.")
                if amount_cop > purchase["saldo_pendiente_cop"]:
                    raise ValidationError("El pago supera el saldo pendiente de la compra.")
                return self.repository.add_supplier_payment(
                    purchase_id=purchase_id, amount_cop=amount_cop,
                    method=method_value, reference=reference_value, timestamp_utc=timestamp,
                )
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def reverse_supplier_payment(self, payment_id: int, *, reason: str) -> dict:
        payment_id = positive_id(payment_id, "El pago")
        reason_value = required_text(reason, "El motivo de reversión")
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                original = self.repository.get_supplier_payment(payment_id)
                if original is None:
                    raise NotFoundError("No se encontró el pago que se quiere revertir.")
                if original["tipo"] != "pago":
                    raise ConflictError("Solo se pueden revertir pagos originales.")
                if self.repository.payment_reversal_exists(payment_id):
                    raise ConflictError("Este pago ya tiene una reversión registrada.")
                return self.repository.reverse_supplier_payment(
                    original, reason=reason_value, timestamp_utc=timestamp,
                )
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def can_reverse_supplier_payment(self, payment_id: int) -> bool:
        payment_id = positive_id(payment_id, "El pago")
        original = self.repository.get_supplier_payment(payment_id)
        return bool(original and original["tipo"] == "pago"
                    and not self.repository.payment_reversal_exists(payment_id))

    def supplier_purchase_history(self, supplier_id: int, *, limit: int = 100) -> list[dict]:
        supplier_id = positive_id(supplier_id, "El proveedor")
        self.get_supplier_for_history(supplier_id)
        limit, _ = pagination(limit, 0)
        return self.repository.list_supplier_purchases(supplier_id, limit=limit)

    def get_supplier_for_history(self, supplier_id: int) -> dict:
        row = self.connection.execute("SELECT * FROM proveedores WHERE id=?", (supplier_id,)).fetchone()
        if row is None:
            raise NotFoundError("No se encontró el proveedor solicitado.")
        return dict(row)
