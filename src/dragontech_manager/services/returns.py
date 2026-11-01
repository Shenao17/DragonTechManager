"""Devoluciones y cancelaciones de ventas (Fase 1, Entrega 4).

Reglas aprobadas (Informe2 §2, §4, §5; Informe3 §1.1):
- Devolver no exige que exista compensación (R1): la devolución solo está limitada
  por las cantidades vendidas y aún no devueltas.
- La cancelación total es derivada: todas las unidades devueltas. Que esté liquidada
  se ve en ``v_saldos_ventas.estado_cobro``; los reembolsos y el saldo a favor llegan
  en entregas posteriores.
- Solo lo apto vuelve a stock; lo no apto se reporta como pérdida, no como existencia.
- Un valor reconocido menor al precio exige motivo y autorizador distinto del ejecutor.
"""

import sqlite3

from dragontech_manager.business_date import business_date_from_utc
from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.returns import ReturnsRepository
from dragontech_manager.repositories.sales import SalesRepository

from . import idempotency
from ._common import positive_id, required_text, timestamp_and_business_year
from .actors import ActorService
from .operations import OperationRegistry
from .errors import ConflictError, NotFoundError, ValidationError, translate_integrity_error
from .sales import SalesService

_CONDITIONS = {"danado", "incompleto", "no_apto", "otro"}
_REQUESTER_TYPES = {"cliente", "interno"}


def _int(value: object, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationError(f"{label} debe ser un entero {'mayor que cero' if minimum else 'no negativo'}.")
    return value


class ReturnsService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.repository = ReturnsRepository(connection)
        self.sales = SalesRepository(connection)
        self.sales_service = SalesService(connection)
        self.actors = ActorService(connection)
        self.operations = OperationRegistry(connection)

    def returnable_lines(self, sale_id: int) -> list[dict]:
        sale_id = positive_id(sale_id, "La venta")
        if self.sales.get_sale(sale_id) is None:
            raise NotFoundError("No se encontró la venta solicitada.")
        return self.repository.returnable_lines(sale_id)

    def list_returns(self, sale_id: int) -> list[dict]:
        sale_id = positive_id(sale_id, "La venta")
        result = self.repository.list_for_sale(sale_id)
        for item in result:
            item["lineas"] = self.repository.lines_of(item["id"])
        return result

    def cancellation_status(self, sale_id: int) -> dict:
        """Qué falta para considerar cancelada y liquidada una venta (Informe3 §1.1, §1.10 #11, A6).

        No existe un concepto de «cancelación comercial» aparte: una venta solo se cierra como
        cancelada cuando TODAS sus unidades fueron devueltas y no queda cargo por cobrar, deuda
        sin extinguir ni reembolso por entregar. Si el cliente retiene bienes o servicios, ese valor
        es un cargo explícito (deuda) que debe cobrarse, condonarse o castigarse."""
        sale = self.sales.get_sale(positive_id(sale_id, "La venta"))
        if sale is None:
            raise NotFoundError("No se encontró la venta solicitada.")
        pending_units = sale["unidades_vendidas"] - sale["unidades_devueltas"]
        blockers = []
        if pending_units > 0:
            blockers.append(f"Quedan {pending_units} unidad(es) sin devolver; el valor retenido es un cargo explícito "
                            f"({sale['importe_neto_cop']}) que debe cobrarse, condonarse o castigarse.")
        if sale["deuda_pendiente_cop"] > 0:
            blockers.append(f"Hay {sale['deuda_pendiente_cop']} de deuda sin cobrar, condonar ni castigar.")
        if sale["sobrepago_pendiente_cop"] > 0:
            blockers.append(f"Hay {sale['sobrepago_pendiente_cop']} pagados en exceso sin compensar al cliente.")
        if sale["reembolso_por_entregar_cop"] > 0:
            blockers.append(f"Hay {sale['reembolso_por_entregar_cop']} de reembolso comprometido sin entregar.")
        return {"venta": sale, "unidades_pendientes": pending_units, "bloqueos": blockers,
                "cerrada": sale["estado_comercial"] == "cancelada_liquidada" and not blockers}

    def lost_inventory(self, sale_id: int) -> list[dict]:
        return self.repository.lost_inventory(positive_id(sale_id, "La venta"))

    def _prepare_lines(self, sale_id: int, lines: object, has_authorizer: bool) -> list[dict]:
        if not isinstance(lines, (list, tuple)) or not lines:
            raise ValidationError("Indica al menos una línea para devolver.")
        available = {row["venta_detalle_id"]: row for row in self.repository.returnable_lines(sale_id)}
        prepared, seen = [], set()
        for raw in lines:
            if not isinstance(raw, dict):
                raise ValidationError("Cada línea de devolución debe ser un diccionario.")
            line_id = positive_id(raw.get("sale_line_id"), "La línea de venta")
            if line_id in seen:
                raise ValidationError("Una línea de venta solo puede aparecer una vez por devolución.")
            seen.add(line_id)
            source = available.get(line_id)
            if source is None:
                raise ValidationError("La línea indicada no pertenece a la venta.")
            quantity = _int(raw.get("quantity"), "La cantidad devuelta", minimum=1)
            has_product = source["producto_id"] is not None
            restock = raw.get("restock_quantity", quantity if has_product else 0)
            restock = _int(restock, "La cantidad reintegrada", minimum=0)
            if restock > quantity:
                raise ValidationError("No se puede reintegrar más de lo devuelto.")
            if restock and not has_product:
                raise ValidationError("Solo se reintegra inventario de líneas con producto.")
            condition = raw.get("condition")
            no_restock_reason = (raw.get("no_restock_reason") or "").strip()
            if has_product and restock < quantity:
                if condition not in _CONDITIONS:
                    raise ValidationError(f"«{source['descripcion']}»: indica la condición de las unidades no aptas.")
                if not no_restock_reason:
                    raise ValidationError(f"«{source['descripcion']}»: indica el motivo del no reintegro.")
            full_value = quantity * source["precio_unitario_cop"]
            recognized = raw.get("recognized_value_cop", full_value)
            recognized = _int(recognized, "El valor reconocido", minimum=0)
            if recognized > full_value:
                raise ValidationError("El valor reconocido no puede superar el precio de lo devuelto.")
            adjustment_reason = (raw.get("value_adjustment_reason") or "").strip()
            if recognized < full_value:
                if not adjustment_reason:
                    raise ValidationError(f"«{source['descripcion']}»: un valor reconocido menor requiere motivo.")
                if not has_authorizer:
                    raise ValidationError("Un valor reconocido menor al precio requiere autorizador y referencia.")
            prepared.append({
                "venta_detalle_id": line_id, "cantidad_devuelta": quantity,
                "cantidad_reintegrada": restock,
                "condicion_no_apta": condition if has_product and restock < quantity else None,
                "motivo_no_reintegro": no_restock_reason if has_product and restock < quantity else "",
                "importe_reconocido_cop": recognized, "motivo_ajuste_valor": adjustment_reason,
            })
        return prepared

    def _check_available(self, sale_id: int, prepared: list[dict]) -> None:
        """R1: separado de la normalización para que un reintento no dependa del stock actual."""
        available = {row["venta_detalle_id"]: row for row in self.repository.returnable_lines(sale_id)}
        for line in prepared:
            source = available[line["venta_detalle_id"]]
            if line["cantidad_devuelta"] > source["cantidad_disponible"]:
                raise ValidationError(
                    f"«{source['descripcion']}»: se pueden devolver como máximo "
                    f"{source['cantidad_disponible']} unidad(es).")

    def register_return(self, sale_id: int, lines: list[dict], *, reason: str, requester: str | int,
                        requester_type: str, executor: str | int, idempotency_key: str,
                        authorizer: str | int = "", authorization_ref: str = "") -> dict:
        sale_id = positive_id(sale_id, "La venta")
        reason_value = required_text(reason, "El motivo")
        if requester_type not in _REQUESTER_TYPES:
            raise ValidationError("El tipo de solicitante debe ser cliente o interno.")
        if requester_type == "cliente" and not isinstance(requester, str):
            raise ValidationError("El cliente que solicita se registra por nombre.")
        who = self.actors.identify(executor, authorizer or None, requester=requester)
        requester_value = who["solicitante_nombre"] or required_text(requester, "El solicitante")
        executor_value = who["ejecutor_nombre"]
        authorizer_value = who["autorizador_nombre"]
        reference_value = (authorization_ref or "").strip()
        if bool(authorizer_value) != bool(reference_value):
            raise ValidationError("El autorizador y la referencia de autorización van juntos.")
        key = idempotency.validate_key(idempotency_key)
        timestamp, _ = timestamp_and_business_year()
        if self.sales.get_sale(sale_id) is None:
            raise NotFoundError("No se encontró la venta solicitada.")
        prepared = self._prepare_lines(sale_id, lines, bool(authorizer_value))  # solo lectura
        request_fp = idempotency.fingerprint({
            "op": "devolucion_venta", "venta_id": sale_id,
            "lineas": sorted(prepared, key=lambda item: item["venta_detalle_id"]),
            "motivo": reason_value, "solicitante": requester_value,
            "solicitante_tipo": requester_type, "ejecutor": executor_value,
            "autorizador": authorizer_value, "referencia": reference_value,
            "ejecutor_id": who["ejecutor_id"], "autorizador_id": who["autorizador_id"]})
        payload = {"sale_id": sale_id, "lines": list(lines), "reason": reason_value, "requester": requester,
                   "requester_type": requester_type, "executor": executor, "authorizer": authorizer or "",
                   "authorization_ref": reference_value}
        with self.operations.track(key, "devolucion_venta", request_fp, executor_value, payload,
                                   f"Devolución de {sum(l['cantidad_devuelta'] for l in prepared)} unidad(es) de la venta #{sale_id}") as tracker:
            try:
                with atomic(self.connection):
                    prior = self.repository.get_by_key(key)
                    if idempotency.is_replay(prior, request_fp):
                        tracker.complete("cancelacion_venta", prior["id"])
                        return self._result(prior, repeated=True)
                    self._check_available(sale_id, prepared)
                    header = self.repository.create({
                        "venta_id": sale_id, "motivo": reason_value, "solicitante": requester_value,
                        "solicitante_tipo": requester_type, "solicitado_en_utc": timestamp,
                        "responsable_ejecucion": executor_value, "ejecutado_en_utc": timestamp,
                        "autorizador": authorizer_value,
                        "autorizado_en_utc": timestamp if authorizer_value else None,
                        "referencia_autorizacion": reference_value,
                        "fecha_negocio": business_date_from_utc(timestamp),
                        "clave_idempotencia": key, "huella_solicitud": request_fp,
                        "solicitante_id": who["solicitante_id"], "ejecutor_id": who["ejecutor_id"],
                        "autorizador_id": who["autorizador_id"], "origen_identidad": who["origen_identidad"]})
                    for line in prepared:
                        self.repository.add_line({**line, "cancelacion_id": header["id"]})
                    tracker.complete("cancelacion_venta", header["id"])
                    return self._result(header, repeated=False)
            except sqlite3.IntegrityError as error:
                raise translate_integrity_error(error) from error

    def _result(self, header: dict, *, repeated: bool) -> dict:
        return {"devolucion": {**header, "lineas": self.repository.lines_of(header["id"])},
                "venta": self.sales_service.get_sale(header["venta_id"]), "repetido": repeated}
