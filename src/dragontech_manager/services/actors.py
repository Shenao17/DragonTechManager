"""Directorio de actores: quién solicita, ejecuta y autoriza (Informe3 §3).

La identidad es DECLARATIVA: el directorio reduce errores de tipeo y permite segregar por
id, pero no autentica. Las operaciones guardan además el nombre vigente (snapshot).
Un servicio acepta, por compatibilidad, texto libre en lugar de un id; esas filas quedan
con ``origen_identidad = 'legado'`` y la interfaz siempre usa el directorio.
"""

import sqlite3

from dragontech_manager.database.transactions import atomic
from dragontech_manager.repositories.actors import ActorRepository

from ._common import positive_id, required_text, timestamp_and_business_year
from .errors import NotFoundError, ValidationError, translate_integrity_error

ROLES = ("vendedor", "tecnico", "cajero", "supervisor", "propietario", "contador", "otro")
AUTH_MEDIA = ("presencial", "telefono", "whatsapp", "correo", "documento_firmado", "otro")
IDENTITY_WARNING = ("La identidad es declarativa: el directorio registra nombres, no verifica quién "
                    "está frente al equipo. No es un mecanismo de seguridad.")


def _limit(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError("El límite de autorización debe ser un entero de pesos no negativo.")
    return value


class ActorService:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.repository = ActorRepository(connection)

    # --- directorio ---
    def list_actors(self, *, active_only: bool = True) -> list[dict]:
        return self.repository.list(active_only=active_only, authorizers_only=False)

    def list_authorizers(self) -> list[dict]:
        return self.repository.list(active_only=True, authorizers_only=True)

    def get_actor(self, actor_id: int) -> dict:
        actor = self.repository.get(positive_id(actor_id, "El actor"))
        if actor is None:
            raise NotFoundError("No se encontró el actor solicitado.")
        return actor

    def _values(self, name, role, document, can_authorize, limit_cop, active, notes) -> dict:
        if role not in ROLES:
            raise ValidationError("El rol operativo no es válido.")
        for flag, label in ((can_authorize, "Puede autorizar"), (active, "Activo")):
            if not isinstance(flag, bool):
                raise ValidationError(f"{label} debe ser verdadero o falso.")
        limit = _limit(limit_cop)
        # limit None = pendiente de definir, nunca ilimitado: no autoriza importes hasta fijarlo.
        timestamp, _ = timestamp_and_business_year()
        return {"nombre": required_text(name, "El nombre"), "documento": (document or "").strip() or None,
                "rol_operativo": role, "activo": int(active), "puede_autorizar": int(can_authorize),
                "limite_autorizacion_cop": limit, "notas": (notes or "").strip(), "ahora": timestamp}

    def create_actor(self, name: str, role: str, *, document: str | None = None,
                     can_authorize: bool = False, limit_cop: int | None = None, notes: str = "") -> dict:
        values = self._values(name, role, document, can_authorize, limit_cop, True, notes)
        try:
            with atomic(self.connection):
                return self.repository.create(values)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def update_actor(self, actor_id: int, *, name: str, role: str, document: str | None = None,
                     can_authorize: bool = False, limit_cop: int | None = None, active: bool = True,
                     notes: str = "") -> dict:
        actor_id = positive_id(actor_id, "El actor")
        values = self._values(name, role, document, can_authorize, limit_cop, active, notes)
        try:
            with atomic(self.connection):
                if self.repository.get(actor_id) is None:
                    raise NotFoundError("No se encontró el actor solicitado.")
                return self.repository.update(actor_id, values)
        except sqlite3.IntegrityError as error:
            raise translate_integrity_error(error) from error

    def set_active(self, actor_id: int, active: bool) -> dict:
        actor = self.get_actor(actor_id)
        return self.update_actor(
            actor["id"], name=actor["nombre"], role=actor["rol_operativo"], document=actor["documento"],
            can_authorize=bool(actor["puede_autorizar"]), limit_cop=actor["limite_autorizacion_cop"],
            active=active, notes=actor["notas"])

    # --- resolución para operaciones ---
    def _active(self, actor_id: int, label: str) -> dict:
        actor = self.repository.get(positive_id(actor_id, label))
        if actor is None or not actor["activo"]:
            raise ValidationError(f"{label} no existe o está inactivo en el directorio de actores.")
        return actor

    def identify(self, executor: object, authorizer: object = None, *, amount: int | None = None,
                 requester: object = None, authorizer_required: bool = False) -> dict:
        """Resuelve ejecutor/autorizador/solicitante y valida segregación y límites.

        Devuelve nombres (snapshot), ids (``None`` si es legado) y ``origen_identidad``.
        No se mezclan ids del directorio con texto libre en una misma operación.
        """
        use_directory = isinstance(executor, int) and not isinstance(executor, bool)
        if not use_directory:
            if authorizer is not None and isinstance(authorizer, int) and not isinstance(authorizer, bool):
                raise ValidationError("No se mezclan actores del directorio con texto libre.")
            name = required_text(executor, "El responsable de ejecución")
            auth = (authorizer or "").strip() if isinstance(authorizer, str) else ""
            if authorizer_required and not auth:
                raise ValidationError("El autorizador es obligatorio.")
            if auth and auth.casefold() == name.casefold():
                raise ValidationError("El autorizador debe ser distinto de quien ejecuta la operación.")
            return {"ejecutor_id": None, "ejecutor_nombre": name, "autorizador_id": None,
                    "autorizador_nombre": auth, "solicitante_id": None,
                    "solicitante_nombre": requester if isinstance(requester, str) else None,
                    "origen_identidad": "legado"}
        ejecutor = self._active(executor, "El responsable de ejecución")
        autorizador = None
        if authorizer not in (None, "", 0):
            if not isinstance(authorizer, int) or isinstance(authorizer, bool):
                raise ValidationError("No se mezclan actores del directorio con texto libre.")
            autorizador = self._active(authorizer, "El autorizador")
            if not autorizador["puede_autorizar"]:
                raise ValidationError(f"{autorizador['nombre']} no tiene permiso para autorizar.")
            if autorizador["id"] == ejecutor["id"]:
                raise ValidationError("El autorizador debe ser distinto de quien ejecuta la operación.")
            if amount:
                limit = autorizador["limite_autorizacion_cop"]
                if limit is None:
                    raise ValidationError(
                        f"{autorizador['nombre']} no tiene límite de autorización definido; el propietario debe fijarlo.")
                if amount > limit:
                    raise ValidationError(
                        f"El importe supera el límite de autorización de {autorizador['nombre']} ({limit}).")
        elif authorizer_required:
            raise ValidationError("El autorizador es obligatorio.")
        solicitante = None
        if requester is not None and isinstance(requester, int) and not isinstance(requester, bool):
            solicitante = self._active(requester, "El solicitante")
        return {"ejecutor_id": ejecutor["id"], "ejecutor_nombre": ejecutor["nombre"],
                "autorizador_id": autorizador["id"] if autorizador else None,
                "autorizador_nombre": autorizador["nombre"] if autorizador else "",
                "solicitante_id": solicitante["id"] if solicitante else None,
                "solicitante_nombre": solicitante["nombre"] if solicitante else (requester if isinstance(requester, str) else None),
                "origen_identidad": "directorio"}
