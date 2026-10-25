"""Casos de uso para propuestas a clientes."""

from datetime import date, datetime, timezone
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.proposals import ProposalRepository
from ._common import nonnegative_cop, optional_text, pagination, positive_id, required_text, timestamp_and_business_year
from .errors import ConflictError, DataIntegrityError, NotFoundError, ServiceError, ValidationError, translate_integrity_error

_MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807
_BOGOTA = ZoneInfo("America/Bogota")
_ALLOWED_STATES = {"borrador", "enviada", "aceptada", "rechazada", "vencida", "convertida", "cancelada"}
_TRANSITIONS = {
    "borrador": {"enviada", "cancelada"},
    "enviada": {"aceptada", "rechazada", "vencida", "cancelada"},
}


class ProposalService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.proposals = ProposalRepository(connection)

    @staticmethod
    def _date(value: object) -> str | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValidationError("La fecha de vencimiento debe ser una fecha de calendario.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise ValidationError("La fecha de vencimiento debe tener formato AAAA-MM-DD.") from error
        if parsed.isoformat() != value:
            raise ValidationError("La fecha de vencimiento debe tener formato AAAA-MM-DD.")
        return value

    @staticmethod
    def _lines(lines: object) -> list[dict]:
        if not isinstance(lines, (list, tuple)) or not lines:
            raise ValidationError("Agrega al menos un concepto a la propuesta.")
        prepared = []
        total = 0
        for index, line in enumerate(lines, 1):
            if not isinstance(line, dict):
                raise ValidationError(f"El concepto {index} no es válido.")
            description = required_text(line.get("description"), f"La descripción del concepto {index}")
            quantity = line.get("quantity")
            if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 1_000_000:
                raise ValidationError(f"La cantidad del concepto {index} debe ser un entero positivo.")
            unit_price = nonnegative_cop(line.get("unit_price_cop"), f"El precio del concepto {index}")
            subtotal = quantity * unit_price
            if subtotal > _MAX_SQLITE_INTEGER or total > _MAX_SQLITE_INTEGER - subtotal:
                raise ValidationError("El total de la propuesta supera el rango monetario admitido.")
            total += subtotal
            product_id = line.get("product_id")
            if product_id is not None:
                product_id = positive_id(product_id, f"El producto del concepto {index}")
            cost = line.get("historical_cost_cop")
            if cost is not None:
                cost = nonnegative_cop(cost, f"El costo histórico del concepto {index}")
            prepared.append({
                "description": description, "quantity": quantity,
                "unit_price_cop": unit_price, "historical_cost_cop": cost,
                "product_id": product_id,
            })
        return prepared

    def create_proposal(self, customer_id: int, lines: list[dict], *,
                        expires_on: str | None = None, notes: str = "",
                        conditions: str = "") -> dict:
        customer_id = positive_id(customer_id, "El cliente")
        prepared = self._lines(lines)
        expires_on = self._date(expires_on)
        notes_value = optional_text(notes, "Las observaciones", none_as_empty=True)
        conditions_value = optional_text(conditions, "Las condiciones", none_as_empty=True)
        timestamp, _ = timestamp_and_business_year()
        code = f"COT-{uuid4().hex[:12].upper()}"
        try:
            with atomic(self.connection):
                if self.connection.execute(
                    "SELECT 1 FROM clientes WHERE id = ? AND archivado_en_utc IS NULL", (customer_id,)
                ).fetchone() is None:
                    raise NotFoundError("Selecciona un cliente activo existente.")
                proposal = self.proposals.create(
                    code=code, customer_id=customer_id, created_utc=timestamp,
                    expires_on=expires_on, notes=notes_value, conditions=conditions_value,
                )
                for line in prepared:
                    self.proposals.add_line(proposal["id"], line)
                self.proposals.append_history(
                    proposal["id"], event="creada", previous=None,
                    new="borrador", detail="Propuesta creada.", created_utc=timestamp,
                )
                return self.get_proposal(proposal["id"])
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_proposal(self, proposal_id: int) -> dict:
        proposal_id = positive_id(proposal_id, "La propuesta")
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise NotFoundError("No se encontró la propuesta solicitada.")
        proposal["lineas"] = self.proposals.lines(proposal_id)
        proposal["total_cop"] = sum(
            line["cantidad"] * line["precio_unitario_cop"] for line in proposal["lineas"]
        )
        return proposal

    def list_proposals(self, *, search: str | None = None, state: str | None = None,
                       limit: int = 100, offset: int = 0) -> list[dict]:
        search_value = optional_text(search, "La búsqueda")
        if state is not None and state not in _ALLOWED_STATES:
            raise ValidationError("El filtro de estado no es válido.")
        limit, offset = pagination(limit, offset)
        return self.proposals.list(search=search_value, state=state, limit=limit, offset=offset)

    def update_proposal(self, proposal_id: int, customer_id: int, lines: list[dict], *,
                        expires_on: str | None = None, notes: str = "",
                        conditions: str = "") -> dict:
        proposal_id = positive_id(proposal_id, "La propuesta")
        customer_id = positive_id(customer_id, "El cliente")
        prepared = self._lines(lines)
        expires_on = self._date(expires_on)
        notes_value = optional_text(notes, "Las observaciones", none_as_empty=True)
        conditions_value = optional_text(conditions, "Las condiciones", none_as_empty=True)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                current = self.proposals.get(proposal_id)
                if current is None:
                    raise NotFoundError("No se encontró la propuesta que se quiere editar.")
                if current["estado"] != "borrador":
                    raise ConflictError("Solo se pueden editar propuestas en borrador.")
                if self.connection.execute(
                    "SELECT 1 FROM clientes WHERE id = ? AND archivado_en_utc IS NULL", (customer_id,)
                ).fetchone() is None:
                    raise NotFoundError("Selecciona un cliente activo existente.")
                self.proposals.update(
                    proposal_id, customer_id=customer_id, expires_on=expires_on,
                    notes=notes_value, conditions=conditions_value,
                )
                for line in prepared:
                    self.proposals.add_line(proposal_id, line)
                self.proposals.append_history(
                    proposal_id, event="editada", previous="borrador", new="borrador",
                    detail="Datos y conceptos del borrador actualizados.", created_utc=timestamp,
                )
                return self.get_proposal(proposal_id)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def transition_proposal(self, proposal_id: int, new_state: str, *, detail: str = "") -> dict:
        proposal_id = positive_id(proposal_id, "La propuesta")
        if not isinstance(new_state, str) or new_state not in _ALLOWED_STATES:
            raise ValidationError("El estado solicitado no es válido.")
        detail_value = optional_text(detail, "El detalle", none_as_empty=True)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                current = self.proposals.get(proposal_id)
                if current is None:
                    raise NotFoundError("No se encontró la propuesta solicitada.")
                if new_state not in _TRANSITIONS.get(current["estado"], set()):
                    raise ConflictError(
                        f"No se permite pasar una propuesta de «{current['estado']}» a «{new_state}»."
                    )
                if new_state == "vencida":
                    today_local = datetime.now(timezone.utc).astimezone(_BOGOTA).date().isoformat()
                    if not current["vence_el"] or current["vence_el"] > today_local:
                        raise ConflictError("Solo puede marcarse vencida cuando su fecha de vigencia ya pasó.")
                self.proposals.transition(proposal_id, new_state)
                self.proposals.append_history(
                    proposal_id, event="estado_cambiado", previous=current["estado"],
                    new=new_state, detail=detail_value, created_utc=timestamp,
                )
                return self.get_proposal(proposal_id)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def proposal_history(self, proposal_id: int) -> list[dict]:
        proposal_id = positive_id(proposal_id, "La propuesta")
        if self.proposals.get(proposal_id) is None:
            raise NotFoundError("No se encontró la propuesta solicitada.")
        return self.proposals.history(proposal_id)
