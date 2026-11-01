"""Consultas del catálogo de métodos de pago."""

import sqlite3

from ._rows import row_dict, rows_dict


class PaymentMethodRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_methods(self, *, scope: str | None, only_active: bool) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT * FROM metodos_pago
               WHERE (? IS NULL OR (? = 'cliente' AND aplica_cliente = 1)
                                OR (? = 'proveedor' AND aplica_proveedor = 1))
                 AND (? = 0 OR activo = 1)
               ORDER BY orden, nombre""",
            (scope, scope, scope, int(only_active)),
        ).fetchall())

    def get(self, method_id: int) -> dict | None:
        return row_dict(self.connection.execute(
            "SELECT * FROM metodos_pago WHERE id = ?", (method_id,)
        ).fetchone())

    def get_by_alias(self, alias: str) -> dict | None:
        return row_dict(self.connection.execute(
            """SELECT m.* FROM metodos_pago m
               JOIN metodos_pago_alias a ON a.metodo_pago_id = m.id
               WHERE a.alias_normalizado = lower(trim(?))""",
            (alias,),
        ).fetchone())
