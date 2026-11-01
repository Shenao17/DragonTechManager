"""Compensaciones de devoluciones: reembolso, crédito o mixta, y su entrega física.

Reglas aprobadas (Informe2 §2-§4, Informe3 §2, Nota de corrección):
- D = P + U - (T - R). R2: C + G <= MAX(0, D). R3: el reembolso no supera el dinero
  neto recibido P. R8: el crédito que sustituye efectivo exige consentimiento.
- Toda compensación exige autorizador distinto del ejecutor.
- Compromiso, entrega y confirmación son hechos distintos: el estado se deriva de
  eventos append-only; nunca se auto-anula una entrega preparada.
- Una compensación mixta son dos compromisos (reembolso + crédito) creados en una sola
  transacción con claves derivadas ``<clave>:r`` y ``<clave>:c``.
"""

import sqlite3
from datetime import datetime, timezone

from dragontech_manager.business_date import UTC_FORMAT, business_date_from_utc
from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.compensations import CompensationRepository

from . import idempotency
from ._common import positive_id, required_text, timestamp_and_business_year
from .errors import ConflictError, NotFoundError, ValidationError, translate_integrity_error
from .payment_methods import PaymentMethodService
from .sales import SalesService

_MEDIA = {"efectivo", "transferencia", "tarjeta"}
_MAX_KEY = idempotency.MAX_KEY_LENGTH - 2


def _amount(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{label} debe ser un entero de pesos no negativo.")
    return value


class CompensationService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.repository = CompensationRepository(connection)
        self.methods = PaymentMethodService(connection)
        self.sales = SalesService(connection)

    # --- consulta ---
    def list_for_sale(self, sale_id: int) -> list[dict]:
        sale_id = positive_id(sale_id, "La venta")
        items = self.repository.list_for_sale(sale_id)
        for item in items:
            item["eventos"] = self.repository.events(item["id"])
        return items

    def pending_deliveries(self) -> list[dict]:
        return self.repository.pending()

    def position(self, sale_id: int) -> dict:
        position = self.repository.position(positive_id(sale_id, "La venta"))
        if position is None:
            raise NotFoundError("No se encontró la venta solicitada.")
        return position

    # --- compromiso ---
    def commit(self, sale_id: int, *, refund_cop: int = 0, credit_cop: int = 0,
               method: str | int | None = None, reason: str, executor: str, authorizer: str,
               authorization_ref: str, customer_consent: bool = False,
               idempotency_key: str) -> dict:
        sale_id = positive_id(sale_id, "La venta")
        refund = _amount(refund_cop, "El reembolso")
        credit = _amount(credit_cop, "El crédito")
        if refund + credit <= 0:
            raise ValidationError("Indica un reembolso, un crédito o ambos (compensación mixta).")
        reason_value = required_text(reason, "El motivo")
        executor_value = required_text(executor, "El responsable de ejecución")
        authorizer_value = required_text(authorizer, "El autorizador")
        reference_value = required_text(authorization_ref, "La referencia de autorización")
        if authorizer_value.casefold() == executor_value.casefold():
            raise ValidationError("El autorizador debe ser distinto de quien ejecuta la compensación.")
        if not isinstance(customer_consent, bool):
            raise ValidationError("El consentimiento del cliente debe ser verdadero o falso.")
        key = idempotency.validate_key(idempotency_key)
        if len(key) > _MAX_KEY:
            raise ValidationError(f"La clave de idempotencia no puede superar {_MAX_KEY} caracteres aquí.")
        method_row = None
        if refund:
            method_row = self.methods.resolve(method, "cliente")
            if method_row["familia"] not in _MEDIA:
                raise ValidationError("El reembolso debe hacerse por efectivo, transferencia o tarjeta.")
        request_fp = idempotency.fingerprint({
            "op": "compensacion_venta", "venta_id": sale_id, "reembolso_cop": refund,
            "credito_cop": credit, "metodo_pago_id": method_row["id"] if method_row else None,
            "motivo": reason_value, "ejecutor": executor_value, "autorizador": authorizer_value,
            "referencia": reference_value, "consentimiento": customer_consent})
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                prior = [row for row in (self.repository.by_key(f"{key}:r"),
                                         self.repository.by_key(f"{key}:c")) if row]
                if prior:
                    for row in prior:
                        idempotency.is_replay(row, request_fp)
                    if len(prior) != (1 if not (refund and credit) else 2):
                        raise ConflictError("La clave de reintento ya se usó con otra solicitud.")
                    return self._commit_result(sale_id, prior, repeated=True)
                position = self.repository.position(sale_id)
                if position is None:
                    raise NotFoundError("No se encontró la venta solicitada.")
                if position["u_devueltas"] == 0:
                    raise ValidationError("Solo se compensa una venta con una devolución registrada.")
                available = max(0, position["d"] - position["c_comprometido"] - position["g"])
                if refund + credit > available:
                    raise ValidationError(
                        f"La compensación ({refund + credit}) supera el sobrepago disponible ({available}).")
                if credit > position["u"] and not customer_consent:
                    raise ValidationError(
                        "El crédito que sustituye efectivo requiere el consentimiento explícito del cliente.")
                if refund and position["c_comprometido"] + refund > position["p"]:
                    raise ValidationError("El reembolso supera el dinero neto recibido en la venta.")
                base = {
                    "venta_id": sale_id, "cancelacion_id": None, "motivo": reason_value,
                    "responsable_ejecucion": executor_value, "autorizador": authorizer_value,
                    "autorizado_en_utc": timestamp, "referencia_autorizacion": reference_value,
                    "consentimiento_cliente": int(customer_consent),
                    "fecha_negocio": business_date_from_utc(timestamp), "registrado_en_utc": timestamp,
                    "huella_solicitud": request_fp}
                created = []
                if refund:
                    created.append(self.repository.create({
                        **base, "tipo": "reembolso", "importe_cop": refund,
                        "metodo_pago_id": method_row["id"], "clave_idempotencia": f"{key}:r"}))
                if credit:
                    created.append(self.repository.create({
                        **base, "tipo": "credito", "importe_cop": credit, "metodo_pago_id": None,
                        "clave_idempotencia": f"{key}:c"}))
                return self._commit_result(sale_id, created, repeated=False)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def _commit_result(self, sale_id: int, rows: list[dict], *, repeated: bool) -> dict:
        return {"compensaciones": [self.repository.get(row["id"]) for row in rows],
                "venta": self.sales.get_sale(sale_id), "repetido": repeated}

    # --- eventos de entrega ---
    def _event(self, compensation_id: int, kind: str, key: str, payload: dict, build) -> dict:
        compensation_id = positive_id(compensation_id, "La compensación")
        key = idempotency.validate_key(key)
        request_fp = idempotency.fingerprint({"op": f"compensacion_{kind}",
                                              "compensacion_id": compensation_id, **payload})
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                prior = self.repository.event_by_key(key)
                if idempotency.is_replay(prior, request_fp):
                    return self._event_result(prior, repeated=True)
                compensation = self.repository.get(compensation_id)
                if compensation is None:
                    raise NotFoundError("No se encontró la compensación solicitada.")
                if compensation["tipo"] != "reembolso":
                    raise ConflictError("Solo los reembolsos tienen entrega física; el crédito se acredita al comprometerse.")
                values = build(compensation, timestamp)
                event = self.repository.add_event({
                    "compensacion_id": compensation_id, "tipo": kind, "registrado_en_utc": timestamp,
                    "autorizador": "", "referencia_autorizacion": "", "voucher_codigo": None,
                    "medio": None, "referencia_externa": None, "importe_cop": None, "motivo": "",
                    "clave_idempotencia": key, "huella_solicitud": request_fp,
                    "ocurrido_en_utc": timestamp, **values})
                return self._event_result(event, repeated=False)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def _event_result(self, event: dict, *, repeated: bool) -> dict:
        compensation = self.repository.get(event["compensacion_id"])
        return {"evento": event, "compensacion": compensation,
                "venta": self.sales.get_sale(compensation["venta_id"]), "repetido": repeated}

    @staticmethod
    def _voucher(compensation: dict) -> str:
        year = business_date_from_utc(compensation["registrado_en_utc"])[:4]
        return f"RC-{year}-{compensation['id']:06d}"

    @staticmethod
    def _medium(compensation: dict, medium: str | None) -> str:
        chosen = medium or compensation["metodo_familia"]
        if chosen not in _MEDIA:
            raise ValidationError("El medio debe ser efectivo, transferencia o tarjeta.")
        return chosen

    def prepare(self, compensation_id: int, *, registered_by: str, idempotency_key: str,
                medium: str | None = None) -> dict:
        """Prepara la entrega: el voucher es determinista, reimprimirlo no crea otro."""
        registered = required_text(registered_by, "Quien registra")

        def build(compensation: dict, _timestamp: str) -> dict:
            if compensation["estado"] not in {"comprometida"}:
                raise ConflictError(f"La compensación está {compensation['estado']}; no se puede preparar.")
            return {"registrado_por": registered, "voucher_codigo": self._voucher(compensation),
                    "medio": self._medium(compensation, medium)}
        return self._event(compensation_id, "preparada", idempotency_key,
                           {"registrado_por": registered, "medio": medium}, build)

    def confirm_delivery(self, compensation_id: int, *, registered_by: str, idempotency_key: str,
                         medium: str | None = None, external_reference: str = "",
                         occurred_at_utc: str | None = None) -> dict:
        """Registra que el dinero se entregó (la entrega puede preceder al registro)."""
        registered = required_text(registered_by, "Quien registra")
        reference = (external_reference or "").strip()
        if occurred_at_utc is not None:
            try:
                datetime.strptime(occurred_at_utc, UTC_FORMAT).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError) as error:
                raise ValidationError("La fecha efectiva debe tener formato AAAA-MM-DDTHH:MM:SSZ.") from error

        def build(compensation: dict, timestamp: str) -> dict:
            if compensation["estado"] not in {"comprometida", "preparada", "en_investigacion"}:
                raise ConflictError(f"La compensación está {compensation['estado']}; no admite entrega.")
            prepared = self.repository.event_of_type(compensation["id"], "preparada")
            if occurred_at_utc is not None and occurred_at_utc > timestamp:
                raise ValidationError("La fecha efectiva de la entrega no puede ser futura.")
            return {"registrado_por": registered, "medio": self._medium(compensation, medium),
                    "voucher_codigo": prepared["voucher_codigo"] if prepared else self._voucher(compensation),
                    "importe_cop": compensation["importe_cop"], "referencia_externa": reference or None,
                    "ocurrido_en_utc": occurred_at_utc or timestamp}
        return self._event(compensation_id, "entregada", idempotency_key,
                           {"registrado_por": registered, "medio": medium, "referencia": reference,
                            "ocurrido_en": occurred_at_utc}, build)

    def annul(self, compensation_id: int, *, reason: str, registered_by: str, authorizer: str,
              authorization_ref: str, idempotency_key: str) -> dict:
        """Anula un compromiso no entregado (libera el tope); requiere autorizador distinto."""
        reason_value = required_text(reason, "El motivo")
        registered = required_text(registered_by, "Quien registra")
        authorizer_value = required_text(authorizer, "El autorizador")
        reference_value = required_text(authorization_ref, "La referencia de autorización")
        if authorizer_value.casefold() == registered.casefold():
            raise ValidationError("El autorizador debe ser distinto de quien registra la anulación.")

        def build(compensation: dict, _timestamp: str) -> dict:
            if compensation["estado"] in {"entregada", "anulada", "corregida"}:
                raise ConflictError(f"La compensación está {compensation['estado']}; no se puede anular.")
            return {"registrado_por": registered, "motivo": reason_value, "autorizador": authorizer_value,
                    "referencia_autorizacion": reference_value}
        return self._event(compensation_id, "anulada", idempotency_key,
                           {"motivo": reason_value, "registrado_por": registered,
                            "autorizador": authorizer_value, "referencia": reference_value}, build)

    def mark_under_investigation(self, compensation_id: int, *, reason: str, registered_by: str,
                                 idempotency_key: str) -> dict:
        """Duda sobre una entrega preparada: bloquea nuevas entregas hasta resolverla."""
        reason_value = required_text(reason, "El motivo")
        registered = required_text(registered_by, "Quien registra")

        def build(compensation: dict, _timestamp: str) -> dict:
            if compensation["estado"] != "preparada":
                raise ConflictError("Solo se investiga una entrega preparada.")
            return {"registrado_por": registered, "motivo": reason_value}
        return self._event(compensation_id, "en_investigacion", idempotency_key,
                           {"motivo": reason_value, "registrado_por": registered}, build)
