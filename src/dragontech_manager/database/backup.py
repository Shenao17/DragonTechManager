"""Copias de seguridad consistentes de la base SQLite local.

Usa la API de respaldo en línea de SQLite (``Connection.backup``), que copia
una imagen coherente del archivo aunque la aplicación mantenga la base abierta
y existan lecturas en curso. Nunca se copia el archivo con operaciones de
sistema de archivos mientras SQLite lo está escribiendo.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

BACKUP_PREFIX = "dragontech_manager_"
BACKUP_SUFFIX = ".sqlite3"
DEFAULT_RETENTION = 10
_NAME = re.compile(r"^dragontech_manager_(\d{8}T\d{12}Z)_([a-z0-9_-]+)\.sqlite3$")
_SIDECARS = ("-wal", "-shm", "-journal")


class BackupError(RuntimeError):
    """La copia de seguridad no se pudo crear, validar o restaurar."""


@dataclass(frozen=True)
class RestoreResult:
    """Resultado de una restauración verificada."""

    database_path: Path
    safety_backup: Path | None
    schema_version: int


def default_backup_directory(database_path: str | Path) -> Path:
    """Directorio de respaldos contiguo a la base de datos."""
    return Path(database_path).parent / "backups"


def backup_name(label: str = "manual") -> str:
    """Nombre ordenable cronológicamente y seguro para el sistema de archivos."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe_label = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-_") or "manual"
    return f"{BACKUP_PREFIX}{stamp}_{safe_label[:40]}{BACKUP_SUFFIX}"


def list_backups(backup_dir: str | Path) -> list[Path]:
    """Copias administradas por la aplicación, de la más reciente a la más antigua."""
    directory = Path(backup_dir)
    if not directory.is_dir():
        return []
    return sorted(
        (path for path in directory.iterdir() if _NAME.match(path.name) and path.is_file()),
        key=lambda path: path.name,
        reverse=True,
    )


def rotate_backups(backup_dir: str | Path, keep: int = DEFAULT_RETENTION) -> list[Path]:
    """Elimina las copias más antiguas conservando las ``keep`` más recientes.

    Solo toca archivos con el nombre que genera esta aplicación, de modo que
    otros archivos del directorio nunca se borran.
    """
    if isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
        raise BackupError("La retención debe ser un entero igual o mayor que uno.")
    backups = list_backups(backup_dir)
    removed: list[Path] = []
    for path in backups[keep:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError as error:
            raise BackupError(f"No se pudo eliminar la copia antigua {path.name}: {error}") from error
    return removed


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    return connection


def validate_backup(backup_path: str | Path) -> int:
    """Verifica que el archivo sea una base completa y devuelve su versión de esquema.

    Comprueba tamaño, ``PRAGMA integrity_check``, claves foráneas y la presencia
    del historial de migraciones. Lanza ``BackupError`` ante cualquier anomalía.
    """
    path = Path(backup_path)
    if not path.is_file():
        raise BackupError(f"No existe la copia de seguridad: {path}")
    if path.stat().st_size == 0:
        raise BackupError(f"La copia de seguridad está vacía: {path}")
    try:
        with closing(_open_read_only(path)) as connection:
            integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
            if integrity != ["ok"]:
                raise BackupError(f"La copia no pasó integrity_check: {integrity!r}")
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise BackupError("La copia contiene referencias de claves foráneas inválidas.")
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            if exists is None:
                raise BackupError("La copia no contiene el historial de migraciones de DragonTech.")
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    except sqlite3.Error as error:
        raise BackupError(f"La copia de seguridad no es una base SQLite válida: {error}") from error
    if version is None:
        raise BackupError("La copia no registra ninguna versión de esquema.")
    return int(version)


def _copy_database(source: sqlite3.Connection, target_path: Path) -> None:
    """Copia una instantánea coherente mediante la API en línea de SQLite."""
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target, pages=-1, sleep=0.05)
    finally:
        target.close()


def create_backup(
    connection: sqlite3.Connection,
    backup_dir: str | Path,
    *,
    label: str = "manual",
    retention: int = DEFAULT_RETENTION,
    retries: int = 2,
    retry_delay: float = 0.2,
) -> Path:
    """Crea, valida y publica una copia consistente; luego aplica la retención.

    Reintenta ante bloqueos transitorios de SQLite. El archivo final solo
    aparece cuando la copia ya pasó la validación de integridad.
    """
    if connection.in_transaction:
        raise BackupError(
            "Hay una operación sin confirmar. Confírmala o descártala antes de crear la copia."
        )
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        raise BackupError("El número de reintentos debe ser un entero igual o mayor que cero.")
    directory = Path(backup_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise BackupError(f"No se pudo crear el directorio de respaldos: {error}") from error
    if not directory.is_dir():
        raise BackupError(f"La ruta de respaldos no es un directorio: {directory}")

    name = backup_name(label)
    final_path = directory / name
    temp_path = directory / f".{name}.{uuid4().hex}.tmp"
    try:
        attempt = 0
        while True:
            try:
                _copy_database(connection, temp_path)
                break
            except sqlite3.OperationalError as error:
                if attempt >= retries:
                    raise BackupError(f"SQLite no pudo completar la copia: {error}") from error
                attempt += 1
                time.sleep(retry_delay)
            except sqlite3.Error as error:
                raise BackupError(f"SQLite no pudo completar la copia: {error}") from error
        try:
            source_version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
        except sqlite3.Error as error:
            raise BackupError(
                f"No se pudo leer la versión de la base de origen: {error}"
            ) from error
        copied_version = validate_backup(temp_path)
        if source_version is not None and copied_version != source_version:
            raise BackupError("La copia quedó en una versión de esquema distinta a la de origen.")
        os.replace(temp_path, final_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    rotate_backups(directory, retention)
    return final_path


def _remove_sidecars(database_path: Path) -> None:
    for suffix in _SIDECARS:
        Path(f"{database_path}{suffix}").unlink(missing_ok=True)


def restore_backup(
    backup_path: str | Path,
    database_path: str | Path,
    *,
    safety_dir: str | Path | None = None,
    retention: int = DEFAULT_RETENTION,
) -> RestoreResult:
    """Restaura una copia validada sobre ``database_path``.

    Antes de reemplazar la base actual crea una copia de seguridad etiquetada
    ``pre-restauracion``. El reemplazo es atómico y la base restaurada se vuelve
    a validar; si falla, se recupera automáticamente la copia de seguridad.
    El llamador debe cerrar las conexiones abiertas antes de invocar esta función.
    """
    source = Path(backup_path)
    target = Path(database_path)
    if str(target) == ":memory:":
        raise BackupError("No se puede restaurar una copia sobre una base en memoria.")
    expected_version = validate_backup(source)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise BackupError(f"No se pudo preparar el directorio de la base: {error}") from error

    safety: Path | None = None
    if target.is_file() and target.stat().st_size > 0:
        try:
            from dragontech_manager.database.connection import open_database

            with closing(open_database(target)) as current:
                safety = create_backup(
                    current,
                    Path(safety_dir) if safety_dir is not None else default_backup_directory(target),
                    label="pre-restauracion",
                    retention=retention,
                )
        except (sqlite3.Error, BackupError) as error:
            raise BackupError(
                f"No se pudo respaldar la base actual antes de restaurar: {error}"
            ) from error

    def _publish(source_file: Path) -> None:
        temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            shutil.copyfile(source_file, temp)
            _remove_sidecars(target)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    try:
        _publish(source)
        restored_version = validate_backup(target)
        if restored_version != expected_version:
            raise BackupError("La base restaurada no coincide con la versión de la copia.")
    except Exception as error:
        if safety is not None:
            try:
                _publish(safety)
            except Exception as recovery_error:  # pragma: no cover - doble fallo excepcional
                raise BackupError(
                    "La restauración falló y no se pudo recuperar la base anterior. "
                    f"La copia de seguridad está en {safety}. Detalle: {recovery_error}"
                ) from error
            raise BackupError(
                "La restauración no se completó; se recuperó la base anterior desde "
                f"{safety.name}. Detalle: {error}"
            ) from error
        raise BackupError(
            "La restauración no se completó y la base de destino no tenía datos previos. "
            f"Detalle: {error}"
        ) from error
    return RestoreResult(
        database_path=target, safety_backup=safety, schema_version=expected_version
    )
