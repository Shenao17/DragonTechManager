"""Claves de idempotencia y huellas SHA-256 de solicitudes.

Contrato (Informe2 §3.6): la clave identifica una *intención* del usuario y se
reutiliza solo en sus reintentos; la huella es el SHA-256 del contenido canónico.
Misma clave + misma huella devuelve el resultado original; misma clave + otra
huella es un conflicto y no escribe nada.
"""

import hashlib
import json
from uuid import uuid4

from .errors import ConflictError, ValidationError

MAX_KEY_LENGTH = 120


def new_key() -> str:
    return uuid4().hex


def validate_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("La clave de idempotencia es obligatoria.")
    key = value.strip()
    if len(key) > MAX_KEY_LENGTH:
        raise ValidationError(
            f"La clave de idempotencia no puede superar {MAX_KEY_LENGTH} caracteres."
        )
    return key


def fingerprint(payload: dict) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def is_replay(prior: dict | None, request_fingerprint: str) -> bool:
    """True si ``prior`` es el resultado de esta misma solicitud.

    Lanza ``ConflictError`` si la clave ya se usó con otro contenido.
    """
    if prior is None:
        return False
    if prior.get("huella_solicitud") != request_fingerprint:
        raise ConflictError("La clave de reintento ya se usó con otra solicitud.")
    return True


def is_replay_or_legacy(prior: dict | None, request_fingerprint: str, legacy_equal: bool) -> bool:
    """Como ``is_replay``, pero las filas históricas con clave y sin huella se comparan campo a campo."""
    if prior is not None and prior.get("huella_solicitud") is None:
        if not legacy_equal:
            raise ConflictError("La clave de reintento ya se usó con otra solicitud.")
        return True
    return is_replay(prior, request_fingerprint)


class IntentKey:
    """Conserva la clave de una intención de UI mientras no se complete.

    ``for_payload`` devuelve la misma clave mientras el contenido no cambie, así un
    reintento tras un fallo (o un doble clic) no genera una operación nueva.
    ``complete`` descarta la intención tras un éxito.
    """

    def __init__(self) -> None:
        self._key: str | None = None
        self._fingerprint: str | None = None

    def for_payload(self, payload: dict) -> str:
        current = fingerprint(payload)
        if self._key is None or self._fingerprint != current:
            self._key, self._fingerprint = new_key(), current
        return self._key

    def complete(self) -> None:
        self._key = self._fingerprint = None
