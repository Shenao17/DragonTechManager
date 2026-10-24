# DragonTech Manager

DragonTech Manager es una aplicación de escritorio local para administrar las operaciones de DragonTech Care: clientes, equipos, órdenes de servicio, armados de PC, inventario, ventas y finanzas.

El proyecto está en desarrollo. Incluye un esquema SQLite versionado, repositorios y servicios para clientes, equipos y órdenes, además de una interfaz inicial para esos flujos. Cotizaciones, ventas, armados de PC, inventario y finanzas aún no tienen operaciones de usuario.

## Requisitos actuales

- Ubuntu Linux
- Python 3.14.4
- Entorno virtual en `.venv`
- PySide6 instalado dentro del entorno virtual
- SQLite, incluido en Python

## Preparar el entorno

Desde la carpeta raíz del proyecto, activa el entorno virtual:

```bash
source .venv/bin/activate
```

Inicia la aplicación de escritorio:

```bash
PYTHONPATH=src python -m dragontech_manager
```

Para ejecutar la suite de pruebas:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

En el primer inicio, la aplicación crea el directorio de datos de usuario, crea una base SQLite vacía y ejecuta las migraciones versionadas. Los inicios posteriores reutilizan esa base y aplican solo migraciones pendientes. No se cargan clientes ni otros datos de demostración. Si no puede acceder al directorio o migrar la base, la aplicación muestra el error y no reemplaza la base existente.

La ubicación se obtiene de `QStandardPaths.AppDataLocation` y de la identidad de organización/aplicación:

- Linux: normalmente `~/.local/share/DragonTech/DragonTech Manager/dragontech_manager.sqlite3`.
- Windows: normalmente `%APPDATA%/DragonTech/DragonTech Manager/dragontech_manager.sqlite3`.
- macOS: normalmente `~/Library/Application Support/DragonTech/DragonTech Manager/dragontech_manager.sqlite3`.

Qt puede ajustar la ruta según la configuración del sistema. La pantalla Información muestra la ruta efectiva. La copia de seguridad y restauración desde la interfaz todavía no están implementadas; antes de restaurar una copia, cierra la aplicación y valida integridad y migraciones según [la arquitectura](docs/architecture.md).

La suite de pruebas se ejecuta con:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

## Documentación técnica

- [Arquitectura](docs/architecture.md)
- [Modelo de datos](docs/data-model.md)

El esquema SQL inicial está en `src/dragontech_manager/database/migrations/0001_initial_schema.sql`. Las migraciones aplicadas no deben editarse; los cambios futuros se agregan con un número de versión nuevo.
