"""Deuda de ventas: condonación, castigo, anulación de extinciones y recuperaciones H.

Reglas aprobadas (Informe3 §1, Nota de corrección):
- La deuda no se extingue con pagos ficticios ni borrando filas: condonación y castigo son
  hechos append-only que no mueven caja; una anulación restaura la deuda sin borrar el original.
- ``N0 = C_e + G - D``;  ``Q <= MAX(0, N0 - H)`` (R9);  H solo cubre la deuda que no cabe
  en un pago normal de la venta y SÍ mueve caja sin aumentar ``P``.
- Todo hecho exige ejecutor y autorizador distintos del directorio, límite de autorización
  definido, referencia y medio de autorización. El castigo exige evidencia de gestión de cobro.
"""

import sqlite3

from dragontech_manager.business_date import business_date_from_utc
from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.debt import DebtRepository

from . import idempotency
from ._common import positive_id, required_text, timestamp_and_business_year
from .actors import AUTH_MEDIA, ActorService
from .operations import OperationRegistry
from .errors import ConflictError, NotFoundError, ValidationError, translate_integrity_error
from .payment_methods import PaymentMethodService


_KIND_LABEL = {"condonacion": "Condonación", "castigo": "Castigo"}


def _pesos(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{label} debe ser un entero de pesos mayor que cero.")
    return value


class DebtService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.repository = DebtRepository(connection)
        self.actors = ActorService(connection)
        self.methods = PaymentMethodService(connection)
        self.operations = OperationRegistry(connection)

    # --- consulta ---
    def liquidation(self, sale_id: int) -> dict:
        row = self.repository.liquidation(positive_id(sale_id, "La venta"))
        if row is None:
            raise NotFoundError("No se encontró la venta solicitada.")
        return row

    def list_for_sale(self, sale_id: int) -> dict:
        sale_id = positive_id(sale_id, "La venta")
        return {"liquidacion": self.liquidation(sale_id),
                "extinciones": self.repository.extinctions_for_sale(sale_id),
                "recuperaciones": self.repository.recoveries_for_sale(sale_id)}

    def history(self, sale_id: int) -> list[dict]:
        return self.repository.history(positive_id(sale_id, "La venta"))

    def portfolio(self) -> list[dict]:
        return self.repository.portfolio()

    # --- comunes ---
    def _authorization(self, executor, authorizer, medium, reference, amount) -> dict:
        who = self.actors.identify(executor, authorizer, amount=amount, authorizer_required=True)
        if who["origen_identidad"] != "directorio":
            raise ValidationError("Condonar, castigar o recuperar exige actores del directorio.")
        if medium not in AUTH_MEDIA:
            raise ValidationError("Indica el medio de autorización (presencial, teléfono, WhatsApp, correo, documento firmado u otro).")
        return {**who, "medio_autorizacion": medium,
                "referencia_autorizacion": required_text(reference, "La referencia de autorización")}

    def _run(self, key: str, finder, fingerprint_payload: dict, build, wrap, *, operation: str,
             requested_by: str, replay_payload: dict, summary: str, entity: str):
        key = idempotency.validate_key(key)
        request_fp = idempotency.fingerprint(fingerprint_payload)
        timestamp, _ = timestamp_and_business_year()
        with self.operations.track(key, operation, request_fp, requested_by, replay_payload,
                                   summary) as tracker:
            try:
                with atomic(self.connection):
                    prior = finder(key)
                    if idempotency.is_replay(prior, request_fp):
                        tracker.complete(entity, prior["id"])
                        return wrap(prior, True)
                    row = build(key, request_fp, timestamp, business_date_from_utc(timestamp))
                    tracker.complete(entity, row["id"])
                    return wrap(row, False)
            except sqlite3.IntegrityError as error:
                raise translate_integrity_error(error) from error

    # --- extinción ---
    def _extinguish(self, kind: str, sale_id, amount, *, reason, executor, authorizer, authorization_ref,
                    authorization_medium, idempotency_key, collection_evidence="", cancellation_id=None) -> dict:
        sale_id = positive_id(sale_id, "La venta")
        amount = _pesos(amount, "El importe")
        reason_value = required_text(reason, "El motivo")
        evidence = (collection_evidence or "").strip()
        if kind == "castigo" and not evidence:
            raise ValidationError("El castigo exige evidencia de las gestiones de cobro realizadas.")
        who = self._authorization(executor, authorizer, authorization_medium, authorization_ref, amount)
        payload = {"op": kind, "venta_id": sale_id, "importe_cop": amount, "motivo": reason_value,
                   "evidencia": evidence, "ejecutor_id": who["ejecutor_id"], "autorizador_id": who["autorizador_id"],
                   "referencia": who["referencia_autorizacion"], "medio": authorization_medium,
                   "cancelacion_id": cancellation_id}

        def build(key, fp, timestamp, business_date):
            position = self.repository.position(sale_id)
            if position is None:
                raise NotFoundError("No se encontró la venta solicitada.")
            pending = max(0, position["n0"] - position["h"] - position["q"])
            if amount > pending:
                raise ValidationError(f"El importe ({amount}) supera la deuda pendiente de la venta ({pending}).")
            return self.repository.add_extinction({
                "venta_id": sale_id, "cancelacion_id": cancellation_id, "tipo": kind, "importe_cop": amount,
                "motivo": reason_value, "evidencia_cobro": evidence,
                "referencia_autorizacion": who["referencia_autorizacion"], "medio_autorizacion": authorization_medium,
                "autorizador_id": who["autorizador_id"], "autorizador_nombre": who["autorizador_nombre"],
                "ejecutor_id": who["ejecutor_id"], "ejecutor_nombre": who["ejecutor_nombre"],
                "fecha_negocio": business_date, "registrado_en_utc": timestamp,
                "clave_idempotencia": key, "huella_solicitud": fp})
        replay = {"sale_id": sale_id, "amount_cop": amount, "reason": reason_value, "executor": executor,
                  "authorizer": authorizer, "authorization_ref": authorization_ref,
                  "authorization_medium": authorization_medium, "collection_evidence": evidence,
                  "cancellation_id": cancellation_id}
        return self._run(idempotency_key, self.repository.extinction_by_key, payload, build,
                         lambda row, repeated: {"extincion": row, "liquidacion": self.liquidation(sale_id),
                                                "repetido": repeated},
                         operation=kind, requested_by=who["ejecutor_nombre"], replay_payload=replay,
                         summary=f"{_KIND_LABEL[kind]} de {amount} en la venta #{sale_id}", entity="extincion_deuda")

    def forgive(self, sale_id: int, amount_cop: int, **kwargs) -> dict:
        """Condonación: renuncia comercial a cobrar (no mueve caja)."""
        return self._extinguish("condonacion", sale_id, amount_cop, **kwargs)

    def write_off(self, sale_id: int, amount_cop: int, *, collection_evidence: str, **kwargs) -> dict:
        """Castigo: reconocimiento de crédito incobrable tras gestiones (no mueve caja)."""
        return self._extinguish("castigo", sale_id, amount_cop, collection_evidence=collection_evidence, **kwargs)

    def annul_extinction(self, extinction_id: int, amount_cop: int, *, reason: str, executor, authorizer,
                         authorization_ref: str, authorization_medium: str, idempotency_key: str) -> dict:
        """Anula total o parcialmente una extinción: la deuda reaparece; el hecho original se conserva."""
        extinction_id = positive_id(extinction_id, "La extinción")
        amount = _pesos(amount_cop, "El importe")
        reason_value = required_text(reason, "El motivo")
        who = self._authorization(executor, authorizer, authorization_medium, authorization_ref, None)
        payload = {"op": "anulacion_extincion", "extincion_id": extinction_id, "importe_cop": amount,
                   "motivo": reason_value, "ejecutor_id": who["ejecutor_id"], "autorizador_id": who["autorizador_id"],
                   "referencia": who["referencia_autorizacion"], "medio": authorization_medium}
        holder = {}

        def build(key, fp, timestamp, business_date):
            extinction = self.repository.extinction(extinction_id)
            if extinction is None:
                raise NotFoundError("No se encontró la extinción solicitada.")
            holder["sale"] = extinction["venta_id"]
            if amount > extinction["importe_vigente_cop"]:
                raise ValidationError(f"Solo quedan {extinction['importe_vigente_cop']} vigentes en esa extinción.")
            return self.repository.add_cancellation({
                "extincion_id": extinction_id, "importe_anulado_cop": amount, "motivo": reason_value,
                "referencia_autorizacion": who["referencia_autorizacion"], "medio_autorizacion": authorization_medium,
                "autorizador_id": who["autorizador_id"], "autorizador_nombre": who["autorizador_nombre"],
                "ejecutor_id": who["ejecutor_id"], "ejecutor_nombre": who["ejecutor_nombre"],
                "fecha_negocio": business_date, "registrado_en_utc": timestamp,
                "clave_idempotencia": key, "huella_solicitud": fp})

        def wrap(row, repeated):
            sale = self.repository.extinction(row["extincion_id"])["venta_id"]
            return {"anulacion": row, "liquidacion": self.liquidation(sale), "repetido": repeated}
        replay = {"extinction_id": extinction_id, "amount_cop": amount, "reason": reason_value, "executor": executor,
                  "authorizer": authorizer, "authorization_ref": authorization_ref,
                  "authorization_medium": authorization_medium}
        return self._run(idempotency_key, self.repository.cancellation_by_key, payload, build, wrap,
                         operation="anulacion_extincion", requested_by=who["ejecutor_nombre"], replay_payload=replay,
                         summary=f"Anulación de {amount} de la extinción #{extinction_id}", entity="anulacion_extincion")

    # --- recuperación H ---
    def record_recovery(self, sale_id: int, amount_cop: int, *, method, reason: str, executor, authorizer,
                        authorization_ref: str, authorization_medium: str, idempotency_key: str,
                        reference: str = "") -> dict:
        """Dinero real que entra para cubrir deuda que NO cabe en un pago de venta (no aumenta P)."""
        sale_id = positive_id(sale_id, "La venta")
        amount = _pesos(amount_cop, "El importe")
        reason_value = required_text(reason, "El motivo")
        method_row = self.methods.resolve(method, "cliente")
        who = self._authorization(executor, authorizer, authorization_medium, authorization_ref, amount)
        payload = {"op": "recuperacion_deuda", "venta_id": sale_id, "importe_cop": amount,
                   "metodo_pago_id": method_row["id"], "referencia": (reference or "").strip(),
                   "motivo": reason_value, "ejecutor_id": who["ejecutor_id"], "autorizador_id": who["autorizador_id"],
                   "ref_autorizacion": who["referencia_autorizacion"], "medio": authorization_medium}

        def build(key, fp, timestamp, business_date):
            position = self.repository.position(sale_id)
            if position is None:
                raise NotFoundError("No se encontró la venta solicitada.")
            payable = max(0, position["t"] - position["r"] - position["p"] - position["u"])
            room = max(0, position["n0"] - payable - position["h"])
            if amount > room:
                raise ValidationError(
                    f"La recuperación ({amount}) solo puede cubrir {room}: el resto se cobra como pago normal de la venta.")
            return self.repository.add_recovery({
                "venta_id": sale_id, "importe_cop": amount, "metodo_pago_id": method_row["id"],
                "referencia": (reference or "").strip(), "motivo": reason_value,
                "referencia_autorizacion": who["referencia_autorizacion"], "medio_autorizacion": authorization_medium,
                "autorizador_id": who["autorizador_id"], "autorizador_nombre": who["autorizador_nombre"],
                "ejecutor_id": who["ejecutor_id"], "ejecutor_nombre": who["ejecutor_nombre"],
                "fecha_negocio": business_date, "registrado_en_utc": timestamp,
                "clave_idempotencia": key, "huella_solicitud": fp})
        replay = {"sale_id": sale_id, "amount_cop": amount, "method": method_row["id"], "reason": reason_value,
                  "reference": (reference or "").strip(), "executor": executor, "authorizer": authorizer,
                  "authorization_ref": authorization_ref, "authorization_medium": authorization_medium}
        return self._run(idempotency_key, self.repository.recovery_by_key, payload, build,
                         lambda row, repeated: {"recuperacion": row, "liquidacion": self.liquidation(sale_id),
                                                "repetido": repeated},
                         operation="recuperacion_deuda", requested_by=who["ejecutor_nombre"], replay_payload=replay,
                         summary=f"Recuperación de {amount} en la venta #{sale_id}", entity="recuperacion_deuda")
