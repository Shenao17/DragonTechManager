"""Casos de uso de órdenes de servicio."""

import sqlite3

from dragontech_manager.database.sequences import allocate_code
from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.customers import CustomerRepository
from dragontech_manager.repositories.equipment import EquipmentRepository
from dragontech_manager.repositories.service_orders import ServiceOrderRepository
from ._common import nonnegative_cop, optional_text, pagination, positive_id, required_text, timestamp_and_business_year
from .errors import NotFoundError, ValidationError, translate_integrity_error

_ORDER_STATES = {
    "recibida", "diagnostico", "espera_aprobacion", "en_proceso",
    "lista", "entregada", "cancelada",
}


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
                return self.orders.create(
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
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_order(self, order_id: int) -> dict:
        order_id = positive_id(order_id, "La orden")
        order = self.orders.get(order_id)
        if order is None:
            raise NotFoundError("No se encontró la orden solicitada.")
        return order

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
