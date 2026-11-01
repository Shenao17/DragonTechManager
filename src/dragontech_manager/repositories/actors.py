"""Persistencia del directorio de actores."""

import sqlite3

from ._rows import row_dict, rows_dict


class ActorRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def get(self, actor_id: int) -> dict | None:
        return row_dict(self.connection.execute("SELECT * FROM actores WHERE id = ?", (actor_id,)).fetchone())

    def list(self, *, active_only: bool, authorizers_only: bool) -> list[dict]:
        return rows_dict(self.connection.execute(
            """SELECT * FROM actores
               WHERE (? = 0 OR activo = 1) AND (? = 0 OR puede_autorizar = 1)
               ORDER BY activo DESC, lower(nombre)""",
            (int(active_only), int(authorizers_only))).fetchall())

    def create(self, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """INSERT INTO actores (nombre, documento, rol_operativo, activo, puede_autorizar,
                   limite_autorizacion_cop, creado_en_utc, actualizado_en_utc, notas)
               VALUES (:nombre, :documento, :rol_operativo, :activo, :puede_autorizar,
                       :limite_autorizacion_cop, :ahora, :ahora, :notas) RETURNING *""", values).fetchone())

    def update(self, actor_id: int, values: dict) -> dict:
        return row_dict(self.connection.execute(
            """UPDATE actores SET nombre = :nombre, documento = :documento, rol_operativo = :rol_operativo,
                   activo = :activo, puede_autorizar = :puede_autorizar,
                   limite_autorizacion_cop = :limite_autorizacion_cop, actualizado_en_utc = :ahora,
                   notas = :notas WHERE id = :id RETURNING *""", {**values, "id": actor_id}).fetchone())
