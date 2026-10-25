"""Casos de uso de órdenes de servicio."""

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from dragontech_manager.database.sequences import allocate_code
from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.customers import CustomerRepository
from dragontech_manager.repositories.equipment import EquipmentRepository
from dragontech_manager.repositories.service_orders import ServiceOrderRepository
from ._common import nonnegative_cop, optional_text, pagination, positive_id, required_text, timestamp_and_business_year
from .errors import ConflictError, NotFoundError, ValidationError, translate_integrity_error

_ORDER_STATES = {
    "recibida", "diagnostico", "espera_aprobacion", "en_proceso",
    "lista", "entregada", "cancelada",
}
_ORDER_TRANSITIONS = {
    "recibida": {"diagnostico"},
    "diagnostico": {"espera_aprobacion", "en_proceso"},
    "espera_aprobacion": {"en_proceso"},
    "en_proceso": {"lista"},
    "lista": {"entregada"},
    "entregada": set(),
    "cancelada": set(),
}
_BOGOTA = ZoneInfo("America/Bogota")
_UNSET = object()
_DECISIONS = {"aprobado", "rechazado"}
_MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807


class ServiceOrderService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.customers = CustomerRepository(connection)
        self.equipment = EquipmentRepository(connection)
        self.orders = ServiceOrderRepository(connection)

    def open_service_order(
        self,
        customer_id: int,
        equipment_id: int,
        problem_reported: str,
        *,
        initial_amount_cop: int = 0,
        diagnosis: str | None = None,
        technician: str | None = None,
    ) -> dict:
        customer_id = positive_id(customer_id, "El cliente")
        equipment_id = positive_id(equipment_id, "El equipo")
        problem = required_text(problem_reported, "El problema reportado")
        amount = nonnegative_cop(initial_amount_cop, "El importe inicial")
        diagnosis_value = optional_text(diagnosis, "El diagnóstico", none_as_empty=True)
        technician_value = optional_text(technician, "El técnico", none_as_empty=True)
        timestamp, year = timestamp_and_business_year()

        try:
            with atomic(self.connection):
                if self.customers.get(customer_id) is None:
                    raise NotFoundError("No se encontró el cliente solicitado.")
                equipment = self.equipment.get(equipment_id)
                if equipment is None:
                    raise NotFoundError("No se encontró el equipo solicitado.")

                code = allocate_code(self.connection, "orden_servicio", year)
                order = self.orders.create(
                    code=code,
                    customer_id=customer_id,
                    equipment_id=equipment_id,
                    received_at_utc=timestamp,
                    problem_reported=problem,
                    initial_amount_cop=amount,
                    diagnosis=diagnosis_value,
                    technician=technician_value,
                    status="recibida",
                )
                self.orders.add_status_event(
                    order["id"],
                    previous_state=None,
                    new_state="recibida",
                    timestamp_utc=timestamp,
                    reason="Recepción inicial de la orden.",
                )
                return order
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_order(self, order_id: int) -> dict:
        order_id = positive_id(order_id, "La orden")
        order = self.orders.get(order_id)
        if order is None:
            raise NotFoundError("No se encontró la orden solicitada.")
        return order

    def get_order_detail(self, order_id: int) -> dict:
        order_id = positive_id(order_id, "La orden")
        order = self.orders.get_detail(order_id)
        if order is None:
            raise NotFoundError("No se encontró la orden solicitada.")
        return order

    def get_status_history(self, order_id: int) -> list[dict]:
        order_id = positive_id(order_id, "La orden")
        if self.orders.get(order_id) is None:
            raise NotFoundError("No se encontró la orden solicitada.")
        return self.orders.status_history(order_id)

    def allowed_next_states(self, order_id: int) -> list[str]:
        order = self.get_order(order_id)
        state = order["estado"]
        allowed = set(_ORDER_TRANSITIONS[state])
        if state == "diagnostico":
            has_pending = self.orders.has_pending_additional_decisions(order["id"])
            has_diagnosis = bool(order["diagnostico"].strip())
            allowed = (
                {"espera_aprobacion"}
                if has_pending and has_diagnosis
                else {"en_proceso"}
                if not has_pending and has_diagnosis
                else set()
            )
        elif state == "espera_aprobacion":
            allowed = (
                {"en_proceso"}
                if not self.orders.has_pending_additional_decisions(order["id"])
                and bool(order["diagnostico"].strip())
                else set()
            )
        elif state == "en_proceso":
            allowed = (
                {"lista"}
                if order["trabajo_realizado"].strip()
                and order["pruebas_realizadas"].strip()
                and not self.orders.has_pending_additional_decisions(order["id"])
                else set()
            )
        return sorted(allowed)

    def list_additional_services(self, order_id: int) -> list[dict]:
        order_id = positive_id(order_id, "La orden")
        if self.orders.get(order_id) is None:
            raise NotFoundError("No se encontró la orden solicitada.")
        return self.orders.list_additional_services(order_id)

    def list_additional_decision_history(self, additional_id: int) -> list[dict]:
        additional_id = positive_id(additional_id, "El servicio adicional")
        if self.orders.additional_service(additional_id) is None:
            raise NotFoundError("No se encontró el servicio adicional solicitado.")
        return self.orders.additional_decision_history(additional_id)

    def propose_additional_service(
        self, order_id: int, description: str, amount_cop: int
    ) -> dict:
        order_id = positive_id(order_id, "La orden")
        description_value = required_text(description, "La descripción del servicio adicional")
        amount = nonnegative_cop(amount_cop, "El precio propuesto")
        if amount == 0:
            raise ValidationError("El precio propuesto debe ser mayor que cero.")
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                order = self.orders.get(order_id)
                if order is None:
                    raise NotFoundError("No se encontró la orden solicitada.")
                if order["estado"] not in {"diagnostico", "espera_aprobacion"}:
                    raise ValidationError(
                        "Los servicios adicionales se proponen durante el diagnóstico, antes de iniciar la reparación."
                    )
                if not order["diagnostico"].strip():
                    raise ValidationError("Guarda el diagnóstico antes de proponer un servicio adicional.")
                if self.orders.has_pending_duplicate_proposal(order_id, description_value, amount):
                    raise ConflictError("Ya existe esta propuesta pendiente para la orden.")
                return self.orders.create_additional_service(
                    order_id, description_value, amount, timestamp
                )
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def decide_additional_service(
        self, additional_id: int, decision: str, evidence: str
    ) -> dict:
        additional_id = positive_id(additional_id, "El servicio adicional")
        if not isinstance(decision, str) or decision not in _DECISIONS:
            raise ValidationError("La decisión debe ser aprobación o rechazo.")
        evidence_value = required_text(evidence, "La nota de confirmación del cliente")
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                additional = self.orders.additional_service(additional_id)
                if additional is None:
                    raise NotFoundError("No se encontró el servicio adicional solicitado.")
                order = self.orders.get(additional["orden_id"])
                if order["estado"] not in {"diagnostico", "espera_aprobacion"}:
                    raise ValidationError(
                        "La decisión debe registrarse antes de iniciar la reparación."
                    )
                if self.orders.additional_decision_history(additional_id):
                    raise ConflictError(
                        "Esta propuesta ya tiene una decisión registrada. Cree una nueva propuesta para una solicitud distinta; el historial no se reemplaza."
                    )
                if decision == "aprobado":
                    current_detail = self.orders.get_detail(order["id"])
                    current_amount = current_detail["importe_acordado_cop"]
                    if additional["importe_propuesto_cop"] > _MAX_SQLITE_INTEGER - current_amount:
                        raise ValidationError(
                            "El importe acordado superaría el máximo que SQLite puede almacenar como entero COP."
                        )
                self.orders.add_additional_decision(
                    additional_id, decision, timestamp, evidence_value
                )
                entries = self.orders.list_additional_services(order["id"])
                return next(item for item in entries if item["id"] == additional_id)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def update_technical_details(
        self,
        order_id: int,
        *,
        diagnosis: str,
        work_performed: str,
        tests_performed: str | object = _UNSET,
        technician: str | None = None,
    ) -> dict:
        order_id = positive_id(order_id, "La orden")
        diagnosis_value = optional_text(diagnosis, "El diagnóstico", none_as_empty=True)
        work_value = optional_text(work_performed, "El trabajo realizado", none_as_empty=True)
        tests_value = (
            _UNSET
            if tests_performed is _UNSET
            else optional_text(tests_performed, "Las pruebas realizadas", none_as_empty=True)
        )
        technician_value = optional_text(technician, "El técnico", none_as_empty=True)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                current = self.orders.get(order_id)
                if current is None:
                    raise NotFoundError("No se encontró la orden que se quiere actualizar.")
                if current["estado"] in {"entregada", "cancelada"}:
                    raise ValidationError("No se pueden modificar los datos técnicos de una orden cerrada.")
                updated = self.orders.update_technical_details(
                    order_id,
                    diagnosis=diagnosis_value,
                    work_performed=work_value,
                    tests_performed=(
                        current["pruebas_realizadas"]
                        if tests_value is _UNSET
                        else tests_value
                    ),
                    technician=technician_value,
                    timestamp_utc=timestamp,
                )
                if updated is None:
                    raise NotFoundError("No se encontró la orden que se quiere actualizar.")
                return updated
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def transition_order(
        self,
        order_id: int,
        new_state: str,
        *,
        reason: str | None = None,
        diagnosis: str | object = _UNSET,
        work_performed: str | object = _UNSET,
        tests_performed: str | object = _UNSET,
        technician: str | None | object = _UNSET,
    ) -> dict:
        order_id = positive_id(order_id, "La orden")
        if not isinstance(new_state, str) or new_state not in _ORDER_STATES:
            raise ValidationError("El nuevo estado de la orden no es válido.")
        reason_value = optional_text(reason, "El motivo", none_as_empty=True)
        timestamp, _ = timestamp_and_business_year()
        local_delivery_date = None
        if new_state == "entregada":
            local_delivery_date = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            ).astimezone(_BOGOTA).date().isoformat()
        try:
            with atomic(self.connection):
                current = self.orders.get(order_id)
                if current is None:
                    raise NotFoundError("No se encontró la orden que se quiere actualizar.")
                if current["estado"] in {"entregada", "cancelada"}:
                    raise ValidationError("Una orden cerrada no admite cambios de estado.")
                if (
                    diagnosis is not _UNSET
                    or work_performed is not _UNSET
                    or tests_performed is not _UNSET
                    or technician is not _UNSET
                ):
                    self.orders.update_technical_details(
                        order_id,
                        diagnosis=(
                            current["diagnostico"]
                            if diagnosis is _UNSET
                            else optional_text(diagnosis, "El diagnóstico", none_as_empty=True)
                        ),
                        work_performed=(
                            current["trabajo_realizado"]
                            if work_performed is _UNSET
                            else optional_text(work_performed, "El trabajo realizado", none_as_empty=True)
                        ),
                        tests_performed=(
                            current["pruebas_realizadas"]
                            if tests_performed is _UNSET
                            else optional_text(tests_performed, "Las pruebas realizadas", none_as_empty=True)
                        ),
                        technician=(
                            current["tecnico"]
                            if technician is _UNSET
                            else optional_text(technician, "El técnico", none_as_empty=True)
                        ),
                        timestamp_utc=timestamp,
                    )
                    current = self.orders.get(order_id)
                allowed = self.allowed_next_states(order_id)
                if new_state not in allowed:
                    if current["estado"] == "en_proceso" and new_state == "lista":
                        if not current["trabajo_realizado"].strip():
                            raise ValidationError("Registra el trabajo realizado antes de marcar la orden como lista.")
                        if not current["pruebas_realizadas"].strip():
                            raise ValidationError("Registra las pruebas realizadas antes de marcar la orden como lista.")
                    if current["estado"] == "diagnostico" and new_state == "en_proceso" and not current["diagnostico"].strip():
                        raise ValidationError("Registra el diagnóstico antes de iniciar la reparación.")
                    if current["estado"] == "diagnostico" and new_state == "espera_aprobacion" and not current["diagnostico"].strip():
                        raise ValidationError("Registra el diagnóstico antes de solicitar aprobación de adicionales.")
                    if current["estado"] == "espera_aprobacion" and new_state == "en_proceso" and not current["diagnostico"].strip():
                        raise ValidationError("Registra el diagnóstico antes de iniciar la reparación.")
                    if current["estado"] == "diagnostico" and new_state == "en_proceso" and self.orders.has_pending_additional_decisions(order_id):
                        raise ValidationError(
                            "Hay servicios adicionales sin decisión; registra su aprobación o rechazo antes de continuar."
                        )
                    raise ValidationError(
                        f"No se permite pasar de '{current['estado']}' a '{new_state}'."
                    )
                updated = self.orders.update_status(
                    order_id,
                    previous_state=current["estado"],
                    new_state=new_state,
                    timestamp_utc=timestamp,
                    delivery_date=local_delivery_date,
                )
                if updated is None:
                    raise ValidationError("La orden cambió mientras se procesaba; vuelve a cargarla.")
                self.orders.add_status_event(
                    order_id,
                    previous_state=current["estado"],
                    new_state=new_state,
                    timestamp_utc=timestamp,
                    reason=reason_value,
                )
                return updated
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def list_orders(
        self,
        *,
        state: str | None = None,
        customer_id: int | None = None,
        equipment_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        if state is not None and (
            not isinstance(state, str) or state not in _ORDER_STATES
        ):
            raise ValidationError("El estado de la orden no es válido.")
        if customer_id is not None:
            customer_id = positive_id(customer_id, "El cliente")
        if equipment_id is not None:
            equipment_id = positive_id(equipment_id, "El equipo")
        limit, offset = pagination(limit, offset)
        return self.orders.list_orders(
            state=state,
            customer_id=customer_id,
            equipment_id=equipment_id,
            limit=limit,
            offset=offset,
        )
