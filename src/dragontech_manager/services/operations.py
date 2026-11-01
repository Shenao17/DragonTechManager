"""Solicitudes de operación persistentes (Informe2 §3.2-3.5).

Protocolo: ``begin`` confirma la intención en su PROPIA transacción antes de ejecutar;
la operación de negocio corre en una transacción única y la marca ``completada`` en esa
misma transacción (``Tracker.complete``). Si el proceso muere, la intención queda
``pendiente`` con la misma clave y carga, y puede reintentarse o abandonarse.
"""

import json
import sqlite3
from contextlib import contextmanager

from dragontech_manager.database.transactions import atomic

from ._common import timestamp_and_business_year
from .errors import ConflictError, NotFoundError, ServiceError, ValidationError

# tipo de operación -> (tabla de negocio, etiqueta de entidad, sufijos de clave derivados)
ENTITIES = {
    "pago_venta": ("pagos_clientes", "pago_cliente", ("",)),
    "pago_orden": ("pagos_clientes", "pago_cliente", ("",)),
    "devolucion_venta": ("cancelaciones_venta", "cancelacion_venta", ("",)),
    "compensacion_venta": ("compensaciones_cancelacion", "compensacion", (":r", ":c")),
    "evento_compensacion": ("eventos_compensacion", "evento_compensacion", ("",)),
    "aplicar_saldo_favor": ("movimientos_saldo_favor", "movimiento_saldo_favor", ("",)),
    "condonacion": ("extinciones_deuda_venta", "extincion_deuda", ("",)),
    "castigo": ("extinciones_deuda_venta", "extincion_deuda", ("",)),
    "anulacion_extincion": ("anulaciones_extincion_deuda", "anulacion_extincion", ("",)),
    "recuperacion_deuda": ("recuperaciones_deuda_venta", "recuperacion_deuda", ("",)),
}
REJECTED = "Rechazada: "


class Tracker:
    def __init__(self, registry: "OperationRegistry", key: str) -> None:
        self._registry, self.key = registry, key

    def complete(self, entity_type: str, entity_id: int) -> None:
        """Marca la solicitud completada; debe llamarse dentro de la transacción del negocio."""
        self._registry.complete(self.key, entity_type, entity_id)


class OperationRegistry:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def _get(self, key: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM solicitudes_operacion WHERE clave_idempotencia = ?", (key,)).fetchone()
        return dict(row) if row else None

    def begin(self, key: str, operation: str, fingerprint: str, requested_by: str, payload: dict,
              summary: str) -> dict:
        timestamp, _ = timestamp_and_business_year()
        try:
            with atomic(self.connection):
                row = self._get(key)
                if row is None:
                    self.connection.execute(
                        """INSERT INTO solicitudes_operacion
                           (clave_idempotencia, tipo_operacion, huella_solicitud, estado, solicitado_por,
                            creada_en_utc, resumen, carga_util)
                           VALUES (?, ?, ?, 'pendiente', ?, ?, ?, ?)""",
                        (key, operation, fingerprint, requested_by or "No indicado", timestamp, summary,
                         json.dumps(payload, ensure_ascii=False, sort_keys=True)))
                    return self._get(key)
                if row["huella_solicitud"] != fingerprint or row["tipo_operacion"] != operation:
                    raise ConflictError("La clave de reintento ya se usó con otra solicitud.")
                if row["estado"] == "abandonada":
                    raise ConflictError("Esa solicitud fue abandonada; la clave está retirada. Inicia una nueva.")
                return row
        except sqlite3.IntegrityError as error:
            raise ValidationError(f"No se pudo registrar la solicitud: {error}") from error

    def complete(self, key: str, entity_type: str, entity_id: int) -> None:
        timestamp, _ = timestamp_and_business_year()
        cursor = self.connection.execute(
            """UPDATE solicitudes_operacion SET estado = 'completada', entidad_tipo = ?, entidad_id = ?,
                   completada_en_utc = ?, detalle = ''
               WHERE clave_idempotencia = ? AND estado = 'pendiente'""",
            (entity_type, entity_id, timestamp, key))
        if cursor.rowcount == 0:
            row = self._get(key)
            if row is None or row["estado"] == "abandonada":
                raise ConflictError("La solicitud fue abandonada o no existe; no se puede completar.")

    def note_rejection(self, key: str, message: str) -> None:
        """Anota la causa de un rechazo definitivo (la operación hizo rollback completo)."""
        try:
            with atomic(self.connection):
                self.connection.execute(
                    "UPDATE solicitudes_operacion SET detalle = ? WHERE clave_idempotencia = ? AND estado = 'pendiente'",
                    (REJECTED + message, key))
        except sqlite3.Error:
            pass  # anotar es informativo; nunca debe ocultar el error original

    @contextmanager
    def track(self, key: str, operation: str, fingerprint: str, requested_by: str, payload: dict, summary: str):
        self.begin(key, operation, fingerprint, requested_by, payload, summary)
        try:
            yield Tracker(self, key)
        except ServiceError as error:
            self.note_rejection(key, str(error))
            raise

    # --- recuperación al iniciar (Informe2 §3.5) ---
    def _existing_entity(self, row: dict) -> tuple[str, int] | None:
        table, label, suffixes = ENTITIES.get(row["tipo_operacion"], (None, None, ()))
        if table is None:
            return None
        for suffix in suffixes:
            found = self.connection.execute(
                f"SELECT id FROM {table} WHERE clave_idempotencia = ?", (row["clave_idempotencia"] + suffix,)).fetchone()
            if found:
                return label, found[0]
        return None

    def reconcile(self) -> int:
        """Pasa a completada las pendientes cuya entidad ya existe (no debería ocurrir por atomicidad)."""
        fixed = 0
        for row in self.pending():
            entity = self._existing_entity(row)
            if entity:
                with atomic(self.connection):
                    self.complete(row["clave_idempotencia"], *entity)
                fixed += 1
        return fixed

    def pending(self) -> list[dict]:
        return [dict(r) for r in self.connection.execute(
            "SELECT * FROM solicitudes_operacion WHERE estado = 'pendiente' ORDER BY creada_en_utc, id")]

    def abandon(self, key: str, reason: str) -> dict:
        """Retira una intención sin efecto financiero (no borra nada)."""
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("Indica el motivo para abandonar la solicitud.")
        with atomic(self.connection):
            row = self._get(key)
            if row is None:
                raise NotFoundError("No se encontró la solicitud.")
            if row["estado"] != "pendiente":
                raise ConflictError(f"La solicitud está {row['estado']}; solo se abandona una pendiente.")
            if self._existing_entity(row):
                raise ConflictError("La operación ya produjo un registro; no se puede abandonar (reconcilia primero).")
            self.connection.execute(
                "UPDATE solicitudes_operacion SET estado = 'abandonada', detalle = ? WHERE clave_idempotencia = ?",
                (f"Abandonada: {reason}", key))
            return self._get(key)
