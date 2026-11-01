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

    def register_return(self, sale_id: int, lines: list[dict], *, reason: str, requester: str,
                        requester_type: str, executor: str, idempotency_key: str,
                        authorizer: str = "", authorization_ref: str = "") -> dict:
        sale_id = positive_id(sale_id, "La venta")
        reason_value = required_text(reason, "El motivo")
        requester_value = required_text(requester, "El solicitante")
        executor_value = required_text(executor, "El responsable de ejecución")
        if requester_type not in _REQUESTER_TYPES:
            raise ValidationError("El tipo de solicitante debe ser cliente o interno.")
        authorizer_value = (authorizer or "").strip()
        reference_value = (authorization_ref or "").strip()
        if bool(authorizer_value) != bool(reference_value):
            raise ValidationError("El autorizador y la referencia de autorización van juntos.")
        if authorizer_value and authorizer_value.casefold() == executor_value.casefold():
            raise ValidationError("El autorizador debe ser distinto de quien ejecuta la devolución.")
        key = idempotency.validate_key(idempotency_key)
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                if self.sales.get_sale(sale_id) is None:
                    raise NotFoundError("No se encontró la venta solicitada.")
                prepared = self._prepare_lines(sale_id, lines, bool(authorizer_value))
                request_fp = idempotency.fingerprint({
                    "op": "devolucion_venta", "venta_id": sale_id,
                    "lineas": sorted(prepared, key=lambda item: item["venta_detalle_id"]),
                    "motivo": reason_value, "solicitante": requester_value,
                    "solicitante_tipo": requester_type, "ejecutor": executor_value,
                    "autorizador": authorizer_value, "referencia": reference_value})
                prior = self.repository.get_by_key(key)
                if idempotency.is_replay(prior, request_fp):
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
                    "clave_idempotencia": key, "huella_solicitud": request_fp})
                for line in prepared:
                    self.repository.add_line({**line, "cancelacion_id": header["id"]})
                return self._result(header, repeated=False)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def _result(self, header: dict, *, repeated: bool) -> dict:
        return {"devolucion": {**header, "lineas": self.repository.lines_of(header["id"])},
                "venta": self.sales_service.get_sale(header["venta_id"]), "repetido": repeated}
