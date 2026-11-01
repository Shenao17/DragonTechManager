"""Casos de uso transaccionales de ventas y cuentas por cobrar."""

from datetime import date, datetime, timezone
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.inventory import InventoryRepository
from dragontech_manager.repositories.proposals import ProposalRepository
from dragontech_manager.repositories.sales import SalesRepository
from dragontech_manager.business_date import business_date_from_utc
from .payment_methods import PaymentMethodService
from ._common import nonnegative_cop, optional_text, pagination, positive_id, required_text, timestamp_and_business_year
from .idempotency import fingerprint as _fingerprint
from .errors import ConflictError, NotFoundError, ValidationError, translate_integrity_error

_MAX = 9_223_372_036_854_775_807
_BOGOTA = ZoneInfo("America/Bogota")


_REVERSAL_NATURES = {"correccion_registro_erroneo", "reversion_financiera_real"}
_REVERSAL_SOURCES = {"banco", "operador", "conciliacion", "otro"}


class SalesService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.sales = SalesRepository(connection)
        self.inventory = InventoryRepository(connection)
        self.proposals = ProposalRepository(connection)
        self.methods = PaymentMethodService(connection)

    @staticmethod
    def _key(value: object) -> str:
        key = required_text(value, "La clave de idempotencia")
        if len(key) > 120:
            raise ValidationError("La clave de idempotencia no puede superar 120 caracteres.")
        return key

    @staticmethod
    def _sale_date(value: object | None) -> str:
        result = value if value is not None else datetime.now(timezone.utc).astimezone(_BOGOTA).date().isoformat()
        if not isinstance(result, str):
            raise ValidationError("La fecha de venta debe tener formato AAAA-MM-DD.")
        try:
            parsed = date.fromisoformat(result)
        except ValueError as error:
            raise ValidationError("La fecha de venta debe tener formato AAAA-MM-DD.") from error
        if parsed.isoformat() != result:
            raise ValidationError("La fecha de venta debe tener formato AAAA-MM-DD.")
        return result

    @staticmethod
    def _lines(lines: object, *, from_proposal: bool = False) -> list[dict]:
        if not isinstance(lines, (list, tuple)) or not lines:
            raise ValidationError("Agrega al menos un concepto a la venta.")
        result: list[dict] = []
        total = 0
        for index, raw in enumerate(lines, 1):
            if not isinstance(raw, dict):
                raise ValidationError(f"La línea {index} no es válida.")
            description = required_text(raw.get("description"), f"La descripción de la línea {index}")
            quantity = raw.get("quantity")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 1_000_000:
                raise ValidationError(f"La cantidad de la línea {index} debe ser un entero positivo.")
            price = nonnegative_cop(raw.get("unit_price_cop"), f"El precio de la línea {index}")
            subtotal = quantity * price
            if subtotal > _MAX or total > _MAX - subtotal:
                raise ValidationError("El total de venta supera el rango monetario admitido por SQLite.")
            total += subtotal
            product_id = raw.get("product_id")
            if product_id is not None:
                product_id = positive_id(product_id, f"El producto de la línea {index}")
            cost = raw.get("historical_cost_cop")
            if cost is not None:
                cost = nonnegative_cop(cost, f"El costo histórico de la línea {index}")
            if product_id is None and not from_proposal and cost is not None:
                raise ValidationError("Un concepto no inventariable no puede declarar costo histórico de producto.")
            result.append({
                "description": description, "quantity": quantity,
                "unit_price_cop": price, "product_id": product_id,
                "historical_cost_cop": cost,
            })
        return result

    def _customer_exists(self, customer_id: int) -> None:
        if self.connection.execute(
            "SELECT 1 FROM clientes WHERE id = ? AND archivado_en_utc IS NULL", (customer_id,)
        ).fetchone() is None:
            raise NotFoundError("Selecciona un cliente activo existente.")

    def _prepare_inventory_lines(self, lines: list[dict], *, allow_inactive: bool) -> list[dict]:
        totals: dict[int, int] = {}
        for line in lines:
            if line["product_id"] is None:
                continue
            product = self.connection.execute(
                "SELECT id, nombre, costo_actual_cop, activo FROM productos WHERE id = ?",
                (line["product_id"],),
            ).fetchone()
            if product is None:
                raise NotFoundError("Uno de los productos de la venta ya no existe.")
            if not allow_inactive and not product["activo"]:
                raise ConflictError(f"El producto «{product['nombre']}» está inactivo.")
            if line["historical_cost_cop"] is None:
                line["historical_cost_cop"] = product["costo_actual_cop"]
            totals[product["id"]] = totals.get(product["id"], 0) + line["quantity"]
        for product_id, quantity in totals.items():
            stock = self.inventory.stock_and_reserved(product_id)
            if stock is None:
                raise NotFoundError("No se encontró la existencia del producto.")
            if quantity > stock[0] - stock[1]:
                raise ConflictError(
                    f"Existencias insuficientes: disponibles {stock[0] - stock[1]}, solicitadas {quantity}."
                )
        return lines

    def _create_committed_sale(self, *, customer_id: int, lines: list[dict],
                               proposal_id: int | None, sale_date: str,
                               notes: str, key: str, fingerprint: str,
                               timestamp: str) -> dict:
        sale = self.sales.create_sale(
            code=f"VTA-{uuid4().hex.upper()}", customer_id=customer_id,
            proposal_id=proposal_id, sale_date=sale_date, notes=notes,
            created_utc=timestamp, idempotency_key=key, request_hash=fingerprint,
        )
        for line in lines:
            detail = self.sales.add_line(sale["id"], line)
            if line["product_id"] is None:
                continue
            product_id = line["product_id"]
            self.inventory.reserve_sale_line(
                product_id=product_id, sale_line_id=detail["id"],
                quantity=line["quantity"], timestamp_utc=timestamp,
            )
            # La salida física y el consumo de la reserva los garantiza el trigger
            # existente. Está dentro de la misma transacción de la venta.
            self.inventory.add_movement(
                product_id=product_id, delta=-line["quantity"],
                cost_cop=line["historical_cost_cop"] or 0, kind="venta",
                created_utc=timestamp, reason=f"Salida confirmada por venta {sale['codigo']}",
                sale_line_id=detail["id"],
            )
        return sale

    def create_sale(self, customer_id: int, lines: list[dict], *,
                    idempotency_key: str, sale_date: str | None = None,
                    notes: str = "") -> dict:
        customer_id = positive_id(customer_id, "El cliente")
        key = self._key(idempotency_key)
        prepared = self._lines(lines)
        sale_date = self._sale_date(sale_date)
        notes_value = optional_text(notes, "Las observaciones", none_as_empty=True)
        fingerprint = _fingerprint({"kind": "directa", "customer_id": customer_id,
                                    "date": sale_date, "notes": notes_value, "lines": prepared})
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                prior = self.sales.get_by_idempotency_key(key)
                if prior:
                    if prior["huella_solicitud"] != fingerprint:
                        raise ConflictError("La clave de reintento ya se usó con otra solicitud de venta.")
                    return self.get_sale(prior["id"])
                self._customer_exists(customer_id)
                self._prepare_inventory_lines(prepared, allow_inactive=False)
                sale = self._create_committed_sale(
                    customer_id=customer_id, lines=prepared, proposal_id=None,
                    sale_date=sale_date, notes=notes_value, key=key,
                    fingerprint=fingerprint, timestamp=timestamp,
                )
                return self.get_sale(sale["id"])
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def convert_accepted_proposal(self, proposal_id: int, *, idempotency_key: str) -> dict:
        proposal_id = positive_id(proposal_id, "La propuesta")
        key = self._key(idempotency_key)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                proposal = self.proposals.get(proposal_id)
                if proposal is None:
                    raise NotFoundError("No se encontró la propuesta que se quiere convertir.")
                fingerprint = _fingerprint({"kind": "propuesta", "proposal_id": proposal_id})
                prior_key = self.sales.get_by_idempotency_key(key)
                if prior_key:
                    if prior_key["huella_solicitud"] != fingerprint:
                        raise ConflictError("La clave de reintento ya se usó con otra solicitud de venta.")
                    return self.get_sale(prior_key["id"])
                existing = self.sales.get_by_proposal(proposal_id)
                if existing:
                    raise ConflictError(f"La propuesta ya fue convertida en la venta {existing['codigo']}.")
                if proposal["estado"] != "aceptada":
                    raise ConflictError("Solo se pueden convertir propuestas aceptadas.")
                proposal_lines = self.proposals.lines(proposal_id)
                if not proposal_lines:
                    raise ConflictError("La propuesta aceptada no tiene conceptos para convertir.")
                prepared = self._lines([
                    {"description": line["descripcion"], "quantity": line["cantidad"],
                     "unit_price_cop": line["precio_unitario_cop"], "product_id": line["producto_id"],
                     "historical_cost_cop": line["costo_unitario_historico_cop"]}
                    for line in proposal_lines
                ], from_proposal=True)
                for line, proposal_line in zip(prepared, proposal_lines, strict=True):
                    line["proposal_line_id"] = proposal_line["id"]
                self._prepare_inventory_lines(prepared, allow_inactive=True)
                sale = self._create_committed_sale(
                    customer_id=proposal["cliente_id"], lines=prepared,
                    proposal_id=proposal_id,
                    sale_date=datetime.now(timezone.utc).astimezone(_BOGOTA).date().isoformat(),
                    notes=f"Convertida de propuesta {proposal['codigo']}", key=key,
                    fingerprint=fingerprint, timestamp=timestamp,
                )
                self.connection.execute("UPDATE cotizaciones SET estado = 'convertida' WHERE id = ?", (proposal_id,))
                self.proposals.append_history(
                    proposal_id, event="estado_cambiado", previous="aceptada",
                    new="convertida", detail=f"Convertida en venta {sale['codigo']}",
                    created_utc=timestamp,
                )
                return self.get_sale(sale["id"])
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_sale(self, sale_id: int) -> dict:
        sale_id = positive_id(sale_id, "La venta")
        sale = self.sales.get_sale(sale_id)
        if sale is None:
            raise NotFoundError("No se encontró la venta solicitada.")
        sale["lineas"] = self.sales.lines(sale_id)
        sale["pagos"] = self.sales.payments(sale_id)
        return sale

    def list_sales(self, *, search: str | None = None, state: str | None = None,
                   date_from: str | None = None, date_to: str | None = None,
                   limit: int = 100, offset: int = 0) -> list[dict]:
        if state is not None and state not in {"abierta", "parcial", "completada", "cancelada", "reembolso_pendiente"}:
            raise ValidationError("El filtro de estado de venta no es válido.")
        for value, label in ((date_from, "La fecha inicial"), (date_to, "La fecha final")):
            if value is not None:
                self._sale_date(value)
        if date_from and date_to and date_from > date_to:
            raise ValidationError("La fecha inicial no puede ser posterior a la fecha final.")
        search_value = optional_text(search, "La búsqueda")
        limit, offset = pagination(limit, offset)
        return self.sales.list_sales(search=search_value, state=state,
                                     date_from=date_from, date_to=date_to,
                                     limit=limit, offset=offset)

    def register_payment(self, sale_id: int, amount_cop: int, *, method: str | int,
                         idempotency_key: str, reference: str = "") -> dict:
        sale_id = positive_id(sale_id, "La venta")
        amount_cop = nonnegative_cop(amount_cop, "El pago")
        if amount_cop <= 0:
            raise ValidationError("El pago debe ser mayor que cero.")
        method_row = self.methods.resolve(method, "cliente")
        reference_value = optional_text(reference, "La referencia", none_as_empty=True)
        key = self._key(idempotency_key)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                prior = self.sales.get_payment_by_key(key)
                if prior:
                    if (prior["venta_id"] != sale_id or prior["importe_cop"] != amount_cop
                            or prior["metodo_pago_id"] != method_row["id"]
                            or prior["referencia"] != reference_value
                            or prior["tipo"] != "recibo"):
                        raise ConflictError("La clave de reintento ya se usó con otro pago.")
                    return {"pago": prior, "venta": self.get_sale(sale_id), "repetido": True}
                sale = self.sales.get_sale(sale_id)
                if sale is None:
                    raise NotFoundError("No se encontró la venta asociada al pago.")
                if sale["estado_cobro"] == "cancelada":
                    raise ConflictError("No se aceptan pagos para una venta cancelada.")
                if amount_cop > sale["saldo_pendiente_cop"]:
                    raise ValidationError("El pago supera el saldo pendiente de la venta.")
                payment = self.sales.create_payment(
                    sale_id=sale_id, amount_cop=amount_cop, method=method_row["nombre"],
                    method_id=method_row["id"], reference=reference_value or "",
                    timestamp_utc=timestamp, business_date=business_date_from_utc(timestamp),
                    idempotency_key=key,
                )
                return {"pago": payment, "venta": self.get_sale(sale_id), "repetido": False}
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def reverse_payment(self, payment_id: int, *, reason: str, nature: str, source: str,
                        evidence: str) -> dict:
        """Revierte un pago de venta sin tocar el original.

        ``nature`` distingue ``correccion_registro_erroneo`` (el dinero nunca ingresó)
        de ``reversion_financiera_real`` (ingresó y fue revertido); ``source`` es solo
        la procedencia y no cambia el tratamiento contable (Nota de corrección §2.6).
        """
        payment_id = positive_id(payment_id, "El pago")
        reason_value = required_text(reason, "El motivo de reversión")
        if nature not in _REVERSAL_NATURES:
            raise ValidationError("Indica si es una corrección de registro erróneo o una reversión financiera real.")
        if source not in _REVERSAL_SOURCES:
            raise ValidationError("Indica el origen del evento: banco, operador, conciliación u otro.")
        evidence_value = required_text(evidence, "La evidencia de la reversión")
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                original = self.sales.get_payment(payment_id)
                if original is None or original["venta_id"] is None:
                    raise NotFoundError("No se encontró el pago de venta que se quiere revertir.")
                if original["tipo"] != "recibo":
                    raise ConflictError("Solo se pueden revertir pagos originales.")
                if self.sales.payment_reversed(payment_id):
                    raise ConflictError("Este pago ya tiene una reversión registrada.")
                reversal = self.sales.reverse_payment(
                    original, reason=reason_value, timestamp_utc=timestamp,
                    business_date=business_date_from_utc(timestamp),
                    nature=nature, source=source, evidence=evidence_value)
                return {"pago": reversal, "venta": self.get_sale(original["venta_id"])}
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

