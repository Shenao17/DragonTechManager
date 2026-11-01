"""Reportes de entregas del día y arqueo de caja (Informe3 §2.7, C5).

Solo lectura. El conteo físico se compara en pantalla: no se persiste (decisión del propietario).
"""

import sqlite3
from datetime import date

from dragontech_manager.business_date import business_date_from_utc
from dragontech_manager.repositories.cash import CashRepository

from ._common import timestamp_and_business_year
from .errors import ValidationError

_ZERO = {"entregado_efectivo_cop": 0, "entregado_otros_medios_cop": 0, "comprometido_efectivo_cop": 0,
         "pendiente_efectivo_cop": 0, "anulado_efectivo_cop": 0}


def _day(value: str | None) -> str:
    if value is None:
        return business_date_from_utc(timestamp_and_business_year()[0])
    try:
        if date.fromisoformat(value).isoformat() == value:
            return value
    except (TypeError, ValueError):
        pass
    raise ValidationError("La fecha debe tener formato AAAA-MM-DD.")


class CashReportService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.repository = CashRepository(connection)

    def deliveries_of_day(self, day: str | None = None) -> dict:
        day = _day(day)
        return {"fecha": day, "por_criterio": self.repository.deliveries_by_criterion(day),
                "entregas": self.repository.effective_deliveries(day)}

    def arqueo(self, day: str | None = None, *, counted_cash_cop: int | None = None) -> dict:
        """Cifras del día y, si se informa un conteo físico de lo entregado en efectivo, su diferencia."""
        day = _day(day)
        if counted_cash_cop is not None and (isinstance(counted_cash_cop, bool) or not isinstance(counted_cash_cop, int)
                                              or counted_cash_cop < 0):
            raise ValidationError("El conteo físico debe ser un entero de pesos no negativo.")
        row = self.repository.arqueo(day) or {"fecha": day, **_ZERO}
        row["conteo_fisico_cop"] = counted_cash_cop
        row["diferencia_cop"] = None if counted_cash_cop is None else counted_cash_cop - row["entregado_efectivo_cop"]
        return row
