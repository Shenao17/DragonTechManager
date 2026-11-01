"""Saldo a favor del cliente: consulta y aplicación a ventas (Informe2 §6)."""

import sqlite3

from dragontech_manager.business_date import business_date_from_utc
from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.compensations import CompensationRepository

from . import idempotency
from ._common import positive_id, required_text, timestamp_and_business_year
from .actors import ActorService
from .operations import OperationRegistry
from .errors import NotFoundError, ValidationError, translate_integrity_error
from .sales import SalesService


class CreditService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.repository = CompensationRepository(connection)
        self.sales = SalesService(connection)
        self.actors = ActorService(connection)
        self.operations = OperationRegistry(connection)

    def balance(self, customer_id: int) -> dict:
        row = self.repository.balance(positive_id(customer_id, "El cliente"))
        if row is None:
            raise NotFoundError("No se encontró el cliente solicitado.")
        return row

    def movements(self, customer_id: int) -> list[dict]:
        return self.repository.ledger(positive_id(customer_id, "El cliente"))

    def apply_to_sale(self, sale_id: int, amount_cop: int, *, reason: str, registered_by: str | int,
                      idempotency_key: str) -> dict:
        """Aplica saldo a favor a una venta (R4: nunca supera su saldo pendiente)."""
        sale_id = positive_id(sale_id, "La venta")
        if isinstance(amount_cop, bool) or not isinstance(amount_cop, int) or amount_cop <= 0:
            raise ValidationError("El importe a aplicar debe ser un entero de pesos mayor que cero.")
        reason_value = required_text(reason, "El motivo")
        who = self.actors.identify(registered_by)
        registered = who["ejecutor_nombre"]
        key = idempotency.validate_key(idempotency_key)
        request_fp = idempotency.fingerprint({"op": "aplicar_saldo_favor_venta", "venta_id": sale_id,
                                              "importe_cop": amount_cop, "motivo": reason_value,
                                              "registrado_por": registered, "registrado_por_id": who["ejecutor_id"]})
        timestamp, _ = timestamp_and_business_year()
        payload = {"sale_id": sale_id, "amount_cop": amount_cop, "reason": reason_value,
                   "registered_by": registered_by}
        with self.operations.track(key, "aplicar_saldo_favor", request_fp, registered, payload,
                                   f"Aplicar {amount_cop} de saldo a favor a la venta #{sale_id}") as tracker:
            try:
                with atomic(self.connection):
                    prior = self.repository.ledger_by_key(key)
                    if idempotency.is_replay(prior, request_fp):
                        tracker.complete("movimiento_saldo_favor", prior["id"])
                        return self._result(prior, repeated=True)
                    position = self.repository.position(sale_id)
                    if position is None:
                        raise NotFoundError("No se encontró la venta solicitada.")
                    balance = self.repository.balance(position["cliente_id"])["saldo_disponible_cop"]
                    if amount_cop > balance:
                        raise ValidationError(f"El cliente solo tiene {balance} de saldo a favor disponible.")
                    pending = position["pagable"]  # ya descuenta devoluciones, crédito y extinciones
                    if amount_cop > pending:
                        raise ValidationError(f"La venta solo tiene {pending} de saldo cobrable.")
                    movement = self.repository.apply_to_sale({
                        "cliente_id": position["cliente_id"], "importe_cop": -amount_cop,
                        "venta_id": sale_id, "fecha_negocio": business_date_from_utc(timestamp),
                        "registrado_en_utc": timestamp, "motivo": reason_value,
                        "registrado_por": registered, "clave_idempotencia": key,
                        "huella_solicitud": request_fp, "registrado_por_id": who["ejecutor_id"],
                        "origen_identidad": who["origen_identidad"]})
                    tracker.complete("movimiento_saldo_favor", movement["id"])
                    return self._result(movement, repeated=False)
            except sqlite3.IntegrityError as error:
                raise translate_integrity_error(error) from error

    def _result(self, movement: dict, *, repeated: bool) -> dict:
        return {"movimiento": movement, "saldo": self.balance(movement["cliente_id"]),
                "venta": self.sales.get_sale(movement["venta_id"]), "repetido": repeated}
