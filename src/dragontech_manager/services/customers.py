"""Casos de uso de clientes."""

import sqlite3

from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.customers import CustomerRepository
from ._common import optional_text, pagination, positive_id, required_text, timestamp_and_business_year
from .errors import NotFoundError, translate_integrity_error


class CustomerService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.customers = CustomerRepository(connection)

    def create_customer(
        self,
        name: str,
        *,
        phone: str | None = None,
        whatsapp: str | None = None,
        email: str | None = None,
        notes: str | None = None,
    ) -> dict:
        name_value = required_text(name, "El nombre")
        phone_value = optional_text(phone, "El teléfono")
        whatsapp_value = optional_text(whatsapp, "El WhatsApp")
        email_value = optional_text(email, "El correo")
        notes_value = optional_text(notes, "Las notas", none_as_empty=True)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                return self.customers.create(
                    name=name_value,
                    phone=phone_value,
                    whatsapp=whatsapp_value,
                    email=email_value,
                    notes=notes_value,
                    timestamp_utc=timestamp,
                )
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def get_customer(self, customer_id: int) -> dict:
        customer_id = positive_id(customer_id, "El cliente")
        customer = self.customers.get(customer_id)
        if customer is None:
            raise NotFoundError("No se encontró el cliente solicitado.")
        return customer

    def list_customers(
        self, *, search: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        search_value = optional_text(search, "La búsqueda")
        limit, offset = pagination(limit, offset)
        return self.customers.list(search=search_value, limit=limit, offset=offset)
