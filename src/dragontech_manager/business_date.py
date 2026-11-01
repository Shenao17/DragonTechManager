"""Fecha de negocio: día calendario local de Bogotá (UTC-5, sin horario de verano)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_BOGOTA = ZoneInfo("America/Bogota")
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def business_date_from_utc(timestamp_utc: str) -> str:
    """Día comercial ``AAAA-MM-DD`` de un instante UTC ``%Y-%m-%dT%H:%M:%SZ``."""
    instant = datetime.strptime(timestamp_utc, UTC_FORMAT).replace(tzinfo=timezone.utc)
    return instant.astimezone(_BOGOTA).date().isoformat()
