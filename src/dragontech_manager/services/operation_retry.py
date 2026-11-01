"""Reintento de solicitudes pendientes tras un reinicio: reejecuta la operación con la MISMA clave.

Las solicitudes guardan su carga útil canónica; aquí se despachan al servicio que las produjo.
Si la operación ya se había confirmado, el servicio devuelve el registro original (idempotencia).
"""

import json
import sqlite3

from .compensations import CompensationService
from .credit import CreditService
from .debt import DebtService
from .errors import NotFoundError, ValidationError
from .operations import OperationRegistry
from .returns import ReturnsService
from .sales import SalesService
from .service_orders import ServiceOrderService


def _dispatch(connection: sqlite3.Connection, operation: str, p: dict, key: str):
    if operation == "pago_venta":
        return SalesService(connection).register_payment(
            p["sale_id"], p["amount_cop"], method=p["method"], reference=p["reference"], idempotency_key=key)
    if operation == "pago_orden":
        return ServiceOrderService(connection).register_payment(
            p["order_id"], p["amount_cop"], method=p["method"], reference=p["reference"], idempotency_key=key)
    if operation == "devolucion_venta":
        return ReturnsService(connection).register_return(
            p["sale_id"], p["lines"], reason=p["reason"], requester=p["requester"], requester_type=p["requester_type"],
            executor=p["executor"], authorizer=p["authorizer"], authorization_ref=p["authorization_ref"],
            idempotency_key=key)
    if operation == "compensacion_venta":
        return CompensationService(connection).commit(
            p["sale_id"], refund_cop=p["refund_cop"], credit_cop=p["credit_cop"], method=p["method"],
            reason=p["reason"], executor=p["executor"], authorizer=p["authorizer"],
            authorization_ref=p["authorization_ref"], customer_consent=p["customer_consent"], idempotency_key=key)
    if operation == "aplicar_saldo_favor":
        return CreditService(connection).apply_to_sale(
            p["sale_id"], p["amount_cop"], reason=p["reason"], registered_by=p["registered_by"], idempotency_key=key)
    if operation in {"condonacion", "castigo"}:
        service = DebtService(connection)
        common = dict(reason=p["reason"], executor=p["executor"], authorizer=p["authorizer"],
                      authorization_ref=p["authorization_ref"], authorization_medium=p["authorization_medium"],
                      idempotency_key=key, cancellation_id=p["cancellation_id"])
        if operation == "condonacion":
            return service.forgive(p["sale_id"], p["amount_cop"], **common)
        return service.write_off(p["sale_id"], p["amount_cop"], collection_evidence=p["collection_evidence"], **common)
    if operation == "anulacion_extincion":
        return DebtService(connection).annul_extinction(
            p["extinction_id"], p["amount_cop"], reason=p["reason"], executor=p["executor"],
            authorizer=p["authorizer"], authorization_ref=p["authorization_ref"],
            authorization_medium=p["authorization_medium"], idempotency_key=key)
    if operation == "recuperacion_deuda":
        return DebtService(connection).record_recovery(
            p["sale_id"], p["amount_cop"], method=p["method"], reason=p["reason"], reference=p["reference"],
            executor=p["executor"], authorizer=p["authorizer"], authorization_ref=p["authorization_ref"],
            authorization_medium=p["authorization_medium"], idempotency_key=key)
    if operation == "evento_compensacion":
        return CompensationService(connection).replay_event(p["kind"], p["compensation_id"], p["payload"], key)
    raise ValidationError(f"No se sabe reintentar operaciones de tipo «{operation}».")


def retry(connection: sqlite3.Connection, key: str) -> dict:
    row = connection.execute("SELECT * FROM solicitudes_operacion WHERE clave_idempotencia = ?", (key,)).fetchone()
    if row is None:
        raise NotFoundError("No se encontró la solicitud.")
    if row["estado"] != "pendiente":
        raise ValidationError(f"La solicitud está {row['estado']}; solo se reintenta una pendiente.")
    OperationRegistry(connection).reconcile()
    row = connection.execute("SELECT * FROM solicitudes_operacion WHERE clave_idempotencia = ?", (key,)).fetchone()
    if row["estado"] == "completada":
        return {"solicitud": dict(row), "reintentada": False}
    result = _dispatch(connection, row["tipo_operacion"], json.loads(row["carga_util"]), key)
    return {"solicitud": dict(connection.execute(
        "SELECT * FROM solicitudes_operacion WHERE clave_idempotencia = ?", (key,)).fetchone()),
        "resultado": result, "reintentada": True}
