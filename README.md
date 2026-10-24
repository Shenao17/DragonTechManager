# DragonTech Manager

DragonTech Manager es una aplicación de escritorio local para administrar las operaciones de DragonTech Care: clientes, equipos, órdenes de servicio, armados de PC, inventario, ventas y finanzas.

El proyecto está en desarrollo. Ya incluye un esquema SQLite inicial versionado, infraestructura de conexión y migraciones, vistas de saldos/existencias y pruebas de integridad. Todavía no están implementados los módulos comerciales, repositorios ni servicios de negocio.

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

Inicia el esqueleto de escritorio:

```bash
PYTHONPATH=src python -m dragontech_manager
```

Para ejecutar la suite de pruebas:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

La base todavía no se crea al iniciar la interfaz. Para inicializar una base de desarrollo desde código, abre una conexión con `dragontech_manager.database.connection.open_database(ruta)` y aplica `dragontech_manager.database.migrations.migrate(conexion)`. No se incluye ni se crea una base con datos comerciales en el repositorio.

## Documentación técnica

- [Arquitectura](docs/architecture.md)
- [Modelo de datos](docs/data-model.md)

El esquema SQL inicial está en `src/dragontech_manager/database/migrations/0001_initial_schema.sql`. Las migraciones aplicadas no deben editarse; los cambios futuros se agregan con un número de versión nuevo.
