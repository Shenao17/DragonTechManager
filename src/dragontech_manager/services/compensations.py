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
from .actors import ActorService
from .operations import OperationRegistry
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
        self.actors = ActorService(connection)
        self.operations = OperationRegistry(connection)

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
               method: str | int | None = None, reason: str, executor: str | int, authorizer: str | int,
               authorization_ref: str, customer_consent: bool = False,
               idempotency_key: str) -> dict:
        sale_id = positive_id(sale_id, "La venta")
        refund = _amount(refund_cop, "El reembolso")
        credit = _amount(credit_cop, "El crédito")
        if refund + credit <= 0:
            raise ValidationError("Indica un reembolso, un crédito o ambos (compensación mixta).")
        reason_value = required_text(reason, "El motivo")
        reference_value = required_text(authorization_ref, "La referencia de autorización")
        who = self.actors.identify(executor, authorizer, amount=refund + credit, authorizer_required=True)
        executor_value, authorizer_value = who["ejecutor_nombre"], who["autorizador_nombre"]
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
            "referencia": reference_value, "consentimiento": customer_consent,
            "ejecutor_id": who["ejecutor_id"], "autorizador_id": who["autorizador_id"]})
        timestamp, _ = timestamp_and_business_year()
        payload = {"sale_id": sale_id, "refund_cop": refund, "credit_cop": credit,
                   "method": method_row["id"] if method_row else None, "reason": reason_value,
                   "executor": executor, "authorizer": authorizer, "authorization_ref": reference_value,
                   "customer_consent": customer_consent}
        with self.operations.track(key, "compensacion_venta", request_fp, executor_value, payload,
                                   f"Compensación de {refund + credit} para la venta #{sale_id}") as tracker:
            try:
                with atomic(self.connection):
                    prior = [row for row in (self.repository.by_key(f"{key}:r"),
                                             self.repository.by_key(f"{key}:c")) if row]
                    if prior:
                        for row in prior:
                            idempotency.is_replay(row, request_fp)
                        if len(prior) != (1 if not (refund and credit) else 2):
                            raise ConflictError("La clave de reintento ya se usó con otra solicitud.")
                        tracker.complete("compensacion", prior[0]["id"])
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
                        "huella_solicitud": request_fp, "ejecutor_id": who["ejecutor_id"],
                        "autorizador_id": who["autorizador_id"], "origen_identidad": who["origen_identidad"]}
                    created = []
                    if refund:
                        created.append(self.repository.create({
                            **base, "tipo": "reembolso", "importe_cop": refund,
                            "metodo_pago_id": method_row["id"], "clave_idempotencia": f"{key}:r"}))
                    if credit:
                        created.append(self.repository.create({
                            **base, "tipo": "credito", "importe_cop": credit, "metodo_pago_id": None,
                            "clave_idempotencia": f"{key}:c"}))
                    tracker.complete("compensacion", created[0]["id"])
                    return self._commit_result(sale_id, created, repeated=False)
            except sqlite3.IntegrityError as error:
                raise translate_integrity_error(error) from error

    def _commit_result(self, sale_id: int, rows: list[dict], *, repeated: bool) -> dict:
        return {"compensaciones": [self.repository.get(row["id"]) for row in rows],
                "venta": self.sales.get_sale(sale_id), "repetido": repeated}

    # --- eventos de entrega ---
    def _event(self, compensation_id: int, kind: str, key: str, payload: dict, build, who_args=None) -> dict:
        compensation_id = positive_id(compensation_id, "La compensación")
        key = idempotency.validate_key(key)
        request_fp = idempotency.fingerprint({"op": f"compensacion_{kind}",
                                              "compensacion_id": compensation_id, **payload})
        timestamp, _ = timestamp_and_business_year()
        registrant = payload.get("registrado_por")
        if isinstance(registrant, int) and not isinstance(registrant, bool):
            registrant = self.actors.get_actor(registrant)["nombre"]
        with self.operations.track(key, "evento_compensacion", request_fp, str(registrant or "") or "No indicado",
                                   {"kind": kind, "compensation_id": compensation_id, "payload": payload},
                                   f"Evento {kind} de la compensación #{compensation_id}") as tracker:
            try:
                with atomic(self.connection):
                    prior = self.repository.event_by_key(key)
                    if idempotency.is_replay(prior, request_fp):
                        tracker.complete("evento_compensacion", prior["id"])
                        return self._event_result(prior, repeated=True)
                    compensation = self.repository.get(compensation_id)
                    if compensation is None:
                        raise NotFoundError("No se encontró la compensación solicitada.")
                    if compensation["tipo"] != "reembolso":
                        raise ConflictError("Solo los reembolsos tienen entrega física; el crédito se acredita al comprometerse.")
                    values = build(compensation, timestamp)
                    if who_args is not None:
                        executor_arg, authorizer_arg = who_args
                        who = self.actors.identify(executor_arg, authorizer_arg or None,
                                                   amount=compensation["importe_cop"] if authorizer_arg else None)
                        values = {**values, "registrado_por": who["ejecutor_nombre"],
                                  "autorizador": who["autorizador_nombre"],
                                  "registrado_por_id": who["ejecutor_id"], "autorizador_id": who["autorizador_id"],
                                  "origen_identidad": who["origen_identidad"]}
                    event = self.repository.add_event({
                        "compensacion_id": compensation_id, "tipo": kind, "registrado_en_utc": timestamp,
                        "autorizador": "", "referencia_autorizacion": "", "voucher_codigo": None,
                        "medio": None, "referencia_externa": None, "importe_cop": None, "motivo": "",
                        "clave_idempotencia": key, "huella_solicitud": request_fp,
                        "ocurrido_en_utc": timestamp, **values})
                    tracker.complete("evento_compensacion", event["id"])
                    return self._event_result(event, repeated=False)
            except sqlite3.IntegrityError as error:
                raise translate_integrity_error(error) from error

    def correct_delivery_data(self, compensation_id: int, *, reason: str, registered_by: str | int,
                              authorizer: str | int, authorization_ref: str, idempotency_key: str,
                              medium: str | None = None, external_reference: str | None = None,
                              occurred_at_utc: str | None = None, receiver: str | None = None) -> dict:
        """Corrige datos de una entrega ya registrada (medio, referencia, fecha efectiva, receptor).

        No cambia importes ni el estado financiero: es un evento nuevo, autorizado y motivado."""
        reason_value = required_text(reason, "El motivo")
        reference_value = required_text(authorization_ref, "La referencia de autorización")
        if authorizer in (None, ""):
            raise ValidationError("El autorizador es obligatorio.")
        if medium is not None and medium not in _MEDIA:
            raise ValidationError("El medio debe ser efectivo, transferencia o tarjeta.")
        if occurred_at_utc is not None:
            try:
                datetime.strptime(occurred_at_utc, UTC_FORMAT)
            except (TypeError, ValueError) as error:
                raise ValidationError("La fecha efectiva debe tener formato AAAA-MM-DDTHH:MM:SSZ.") from error
        reference = (external_reference or "").strip() or None
        receptor = (receiver or "").strip() or None
        if not any((medium, reference, occurred_at_utc, receptor)):
            raise ValidationError("Indica al menos un dato a corregir: medio, referencia, fecha efectiva o receptor.")

        def build(compensation: dict, _timestamp: str) -> dict:
            if compensation["estado"] not in {"entregada", "corregida"}:
                raise ConflictError(f"La compensación está {compensation['estado']}; solo se corrige una entrega registrada.")
            return {"motivo": reason_value, "referencia_autorizacion": reference_value, "correccion_tipo": "datos",
                    "medio": medium, "referencia_externa": reference, "ocurrido_corregido_en_utc": occurred_at_utc,
                    "receptor": receptor}
        return self._event(compensation_id, "corregida", idempotency_key,
                           {"correccion_tipo": "datos", "motivo": reason_value, "registrado_por": registered_by,
                            "autorizador": authorizer, "referencia": reference_value, "medio": medium,
                            "referencia_externa": reference, "ocurrido_corregido": occurred_at_utc,
                            "receptor": receptor}, build, (registered_by, authorizer))

    def report_delivery_not_occurred(self, compensation_id: int, *, reason: str, evidence: str,
                                     registered_by: str | int, authorizer: str | int, authorization_ref: str,
                                     idempotency_key: str) -> dict:
        """Reversión de un reembolso entregado: deja constancia de que la entrega NO ocurrió.

        Exige una investigación abierta, evidencia y autorizador; libera el compromiso (deja de contar
        como comprometido y entregado) y se rechaza si dejaría condonaciones o recuperaciones por
        encima de la deuda (R13-C). El evento ``entregada`` original se conserva."""
        reason_value = required_text(reason, "El motivo")
        evidence_value = required_text(evidence, "La evidencia")
        reference_value = required_text(authorization_ref, "La referencia de autorización")
        if authorizer in (None, ""):
            raise ValidationError("El autorizador es obligatorio.")

        def build(compensation: dict, _timestamp: str) -> dict:
            if compensation["estado"] not in {"entregada", "corregida"}:
                raise ConflictError(f"La compensación está {compensation['estado']}; solo se revierte una entrega registrada.")
            if not compensation["en_investigacion"]:
                raise ConflictError("Abre primero una investigación sobre la entrega (Informe3 §2.3).")
            return {"motivo": reason_value, "referencia_autorizacion": reference_value, "evidencia": evidence_value,
                    "correccion_tipo": "entrega_no_ocurrida"}
        return self._event(compensation_id, "corregida", idempotency_key,
                           {"correccion_tipo": "entrega_no_ocurrida", "motivo": reason_value, "evidencia": evidence_value,
                            "registrado_por": registered_by, "autorizador": authorizer, "referencia": reference_value},
                           build, (registered_by, authorizer))

    def replay_event(self, kind: str, compensation_id: int, payload: dict, key: str) -> dict:
        """Reejecuta un evento pendiente con su clave original (usado por el reintento tras reinicio)."""
        if kind == "preparada":
            return self.prepare(compensation_id, registered_by=payload["registrado_por"],
                                idempotency_key=key, medium=payload.get("medio"))
        if kind == "entregada":
            return self.confirm_delivery(
                compensation_id, registered_by=payload["registrado_por"], idempotency_key=key,
                medium=payload.get("medio"), external_reference=payload.get("referencia") or "",
                occurred_at_utc=payload.get("ocurrido_en"))
        if kind == "anulada":
            return self.annul(compensation_id, reason=payload["motivo"], registered_by=payload["registrado_por"],
                              authorizer=payload["autorizador"], authorization_ref=payload["referencia"],
                              idempotency_key=key)
        if kind == "en_investigacion":
            return self.mark_under_investigation(compensation_id, reason=payload["motivo"],
                                                 registered_by=payload["registrado_por"], idempotency_key=key)
        if kind == "corregida" and payload.get("correccion_tipo") == "datos":
            return self.correct_delivery_data(
                compensation_id, reason=payload["motivo"], registered_by=payload["registrado_por"],
                authorizer=payload["autorizador"], authorization_ref=payload["referencia"], idempotency_key=key,
                medium=payload.get("medio"), external_reference=payload.get("referencia_externa"),
                occurred_at_utc=payload.get("ocurrido_corregido"), receiver=payload.get("receptor"))
        if kind == "corregida" and payload.get("correccion_tipo") == "entrega_no_ocurrida":
            return self.report_delivery_not_occurred(
                compensation_id, reason=payload["motivo"], evidence=payload["evidencia"],
                registered_by=payload["registrado_por"], authorizer=payload["autorizador"],
                authorization_ref=payload["referencia"], idempotency_key=key)
        raise ValidationError(f"No se sabe reintentar eventos de tipo «{kind}».")

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

    def prepare(self, compensation_id: int, *, registered_by: str | int, idempotency_key: str,
                medium: str | None = None) -> dict:
        """Prepara la entrega: el voucher es determinista, reimprimirlo no crea otro."""
        registered = registered_by

        def build(compensation: dict, _timestamp: str) -> dict:
            if compensation["estado"] not in {"comprometida"}:
                raise ConflictError(f"La compensación está {compensation['estado']}; no se puede preparar.")
            return {"voucher_codigo": self._voucher(compensation), "medio": self._medium(compensation, medium)}
        return self._event(compensation_id, "preparada", idempotency_key,
                           {"registrado_por": registered, "medio": medium}, build, (registered, None))

    def confirm_delivery(self, compensation_id: int, *, registered_by: str | int, idempotency_key: str,
                         medium: str | None = None, external_reference: str = "",
                         occurred_at_utc: str | None = None) -> dict:
        """Registra que el dinero se entregó (la entrega puede preceder al registro)."""
        registered = registered_by
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
            return {"medio": self._medium(compensation, medium),
                    "voucher_codigo": prepared["voucher_codigo"] if prepared else self._voucher(compensation),
                    "importe_cop": compensation["importe_cop"], "referencia_externa": reference or None,
                    "ocurrido_en_utc": occurred_at_utc or timestamp}
        return self._event(compensation_id, "entregada", idempotency_key,
                           {"registrado_por": registered, "medio": medium, "referencia": reference,
                            "ocurrido_en": occurred_at_utc}, build, (registered, None))

    def annul(self, compensation_id: int, *, reason: str, registered_by: str | int, authorizer: str | int,
              authorization_ref: str, idempotency_key: str) -> dict:
        """Anula un compromiso no entregado (libera el tope); requiere autorizador distinto."""
        reason_value = required_text(reason, "El motivo")
        registered = registered_by
        if authorizer in (None, ""):
            raise ValidationError("El autorizador es obligatorio.")
        reference_value = required_text(authorization_ref, "La referencia de autorización")

        def build(compensation: dict, _timestamp: str) -> dict:
            if compensation["estado"] in {"entregada", "anulada", "corregida"}:
                raise ConflictError(f"La compensación está {compensation['estado']}; no se puede anular.")
            return {"motivo": reason_value, "referencia_autorizacion": reference_value}
        return self._event(compensation_id, "anulada", idempotency_key,
                           {"motivo": reason_value, "registrado_por": registered,
                            "autorizador": authorizer, "referencia": reference_value}, build,
                           (registered, authorizer))

    def mark_under_investigation(self, compensation_id: int, *, reason: str, registered_by: str | int,
                                 idempotency_key: str) -> dict:
        """Duda sobre una entrega preparada: bloquea nuevas entregas hasta resolverla."""
        reason_value = required_text(reason, "El motivo")
        registered = registered_by

        def build(compensation: dict, _timestamp: str) -> dict:
            if compensation["estado"] not in {"preparada", "entregada", "corregida"}:
                raise ConflictError("Solo se investiga una entrega preparada o ya registrada.")
            if compensation["en_investigacion"]:
                raise ConflictError("Ya hay una investigación abierta para esta compensación.")
            return {"motivo": reason_value}
        return self._event(compensation_id, "en_investigacion", idempotency_key,
                           {"motivo": reason_value, "registrado_por": registered}, build, (registered, None))
