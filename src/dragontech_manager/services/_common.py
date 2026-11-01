"""Validación y utilidades comunes de servicios."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..business_date import business_date_from_utc  # noqa: F401  (reexportado)
from .errors import ValidationError

_BOGOTA = ZoneInfo("America/Bogota")
_MAX_SQLITE_INTEGER = 9_223_372_036_854_775_807


def timestamp_and_business_year() -> tuple[str, int]:
    instant = datetime.now(timezone.utc).replace(microsecond=0)
    timestamp = instant.strftime("%Y-%m-%dT%H:%M:%SZ")
    return timestamp, instant.astimezone(_BOGOTA).year


def required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} es obligatorio.")
    return value.strip()


def optional_text(value: object, label: str, *, none_as_empty: bool = False) -> str | None:
    if value is None:
        return "" if none_as_empty else None
    if not isinstance(value, str):
        raise ValidationError(f"{label} debe ser texto.")
    return value.strip() or ("" if none_as_empty else None)


def positive_id(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 < value <= _MAX_SQLITE_INTEGER
    ):
        raise ValidationError(f"{label} debe ser un identificador entero positivo.")
    return value


def nonnegative_cop(value: object, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= _MAX_SQLITE_INTEGER
    ):
        raise ValidationError(
            f"{label} debe ser un entero de pesos colombianos dentro del rango admitido por SQLite."
        )
    return value


def pagination(limit: object, offset: object) -> tuple[int, int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValidationError("El límite debe ser un entero entre 1 y 500.")
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or not 0 <= offset <= _MAX_SQLITE_INTEGER
    ):
        raise ValidationError("El desplazamiento debe ser un entero igual o mayor que cero.")
    return limit, offset
