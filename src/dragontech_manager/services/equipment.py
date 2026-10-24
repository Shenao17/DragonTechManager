"""Casos de uso de equipos e historial técnico."""

import sqlite3

from dragontech_manager.database.sequences import allocate_code
from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.customers import CustomerRepository
from dragontech_manager.repositories.equipment import EquipmentRepository
from dragontech_manager.repositories.service_orders import ServiceOrderRepository
from ._common import optional_text, positive_id, required_text, timestamp_and_business_year
from .errors import NotFoundError, translate_integrity_error


class EquipmentService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.customers = CustomerRepository(connection)
        self.equipment = EquipmentRepository(connection)
        self.orders = ServiceOrderRepository(connection)

    def register_equipment(
        self,
        customer_id: int,
        equipment_type: str,
        *,
        brand: str | None = None,
        model: str | None = None,
        serial: str | None = None,
        specifications: str | None = None,
        accessories_received: str | None = None,
        physical_condition: str | None = None,
    ) -> dict:
        customer_id = positive_id(customer_id, "El cliente")
        type_value = required_text(equipment_type, "El tipo de equipo")
        values = {
            "brand": optional_text(brand, "La marca", none_as_empty=True),
            "model": optional_text(model, "El modelo", none_as_empty=True),
            "serial": optional_text(serial, "El serial"),
            "specifications": optional_text(specifications, "Las especificaciones", none_as_empty=True),
            "accessories_received": optional_text(accessories_received, "Los accesorios", none_as_empty=True),
            "physical_condition": optional_text(physical_condition, "El estado físico", none_as_empty=True),
        }
        timestamp, year = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                if self.customers.get(customer_id) is None:
                    raise NotFoundError("No se encontró el cliente al que se quiere asociar el equipo.")
                code = allocate_code(self.connection, "equipo", year)
                return self.equipment.create(
                    code=code,
                    customer_id=customer_id,
                    equipment_type=type_value,
                    timestamp_utc=timestamp,
                    **values,
                )
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_equipment(self, equipment_id: int) -> dict:
        equipment_id = positive_id(equipment_id, "El equipo")
        equipment = self.equipment.get(equipment_id)
        if equipment is None:
            raise NotFoundError("No se encontró el equipo solicitado.")
        return equipment

    def list_equipment_for_customer(self, customer_id: int) -> list[dict]:
        customer_id = positive_id(customer_id, "El cliente")
        if self.customers.get(customer_id) is None:
            raise NotFoundError("No se encontró el cliente solicitado.")
        return self.equipment.list_for_customer(customer_id)

    def get_equipment_history(self, equipment_id: int) -> dict:
        equipment_id = positive_id(equipment_id, "El equipo")
        equipment = self.equipment.get(equipment_id)
        if equipment is None:
            raise NotFoundError("No se encontró el equipo solicitado.")
        orders = self.orders.history_for_equipment(equipment_id)
        return {"equipment": equipment, "service_orders": orders}
