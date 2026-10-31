# Respaldos y restauración

## Qué se copia y cómo

La aplicación usa la **API de respaldo en línea de SQLite** (`sqlite3.Connection.backup`),
no una copia de archivo con el sistema operativo. SQLite entrega una instantánea
coherente de la base aunque la aplicación esté abierta y existan lecturas en curso,
incluyendo el contenido pendiente de `WAL` si estuviera activo.

Cada copia se escribe primero en un archivo temporal oculto y solo se publica con
un reemplazo atómico después de superar:

1. `PRAGMA integrity_check` igual a `ok`.
2. `PRAGMA foreign_key_check` sin violaciones.
3. Presencia del historial `schema_migrations`.
4. Coincidencia de la versión de esquema con la base de origen.

Si la copia falla, el archivo temporal se elimina y no queda una copia parcial
con apariencia válida.

## Cuándo se crean

- **Al iniciar la aplicación**, antes de aplicar migraciones, si la base ya tiene
  esquema. Etiqueta: `inicio`.
- **Antes de restaurar**, como red de seguridad de la base que se va a reemplazar.
  Etiqueta: `pre-restauracion`.
- **Manualmente**, mediante `create_backup(...)` desde la API.

## Ubicación y retención

Las copias se guardan en el directorio `backups/` contiguo a la base de datos:

```text
~/.local/share/DragonTech/DragonTech Manager/
├── dragontech_manager.sqlite3
└── backups/
    ├── dragontech_manager_20261031T211619505492Z_inicio.sqlite3
    └── dragontech_manager_20261031T211619515851Z_pre-restauracion.sqlite3
```

El nombre incluye la fecha UTC con microsegundos y una etiqueta. La retención por
defecto conserva las **10 copias más recientes** y elimina las anteriores. La
rotación solo toca archivos con el patrón que genera la aplicación; cualquier otro
archivo del directorio se conserva.

## Reintentos

Si SQLite responde con un bloqueo transitorio (`database is locked`), la creación
se reintenta hasta dos veces con una pausa corta. Un bloqueo persistente produce
`BackupError` y la aplicación no publica una copia incompleta.

## Restauración

La restauración verifica la copia, respalda la base actual, reemplaza el archivo
de forma atómica y vuelve a validar el resultado. Si la validación posterior falla,
recupera automáticamente la copia de seguridad creada antes de restaurar.

**Requisito operativo:** cierra DragonTech Manager antes de restaurar. El
reemplazo del archivo no puede convivir con una conexión abierta de la aplicación.

```bash
cd "/ruta/a/DragonTech Manager"
PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path
from dragontech_manager.database.backup import restore_backup, list_backups

db = Path.home() / ".local/share/DragonTech/DragonTech Manager/dragontech_manager.sqlite3"
backup = list_backups(db.parent / "backups")[0]
result = restore_backup(backup, db)
print("Restaurado a la versión", result.schema_version)
print("Copia de seguridad previa:", result.safety_backup)
PY
```

Para listar y validar copias antes de restaurar:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path
from dragontech_manager.database.backup import list_backups, validate_backup

db = Path.home() / ".local/share/DragonTech/DragonTech Manager/dragontech_manager.sqlite3"
for path in list_backups(db.parent / "backups"):
    print(validate_backup(path), path.name)
PY
```

## Límites conocidos de esta fase

- La restauración no tiene interfaz gráfica todavía; requiere cerrar la aplicación
  y ejecutar la API documentada.
- Los respaldos viven en el mismo disco que la base. Para protección ante fallo de
  hardware hace falta copiar periódicamente el directorio `backups/` a otro medio.
- No hay cifrado de las copias: heredan los permisos del directorio de datos del
  usuario.
