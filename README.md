# DragonTech Manager

DragonTech Manager es una aplicación de escritorio local para administrar las operaciones de DragonTech Care: clientes, equipos, órdenes de servicio, armados de PC, inventario, ventas y finanzas.

El proyecto está en desarrollo. La arquitectura inicial y las decisiones del modelo de datos están documentadas, y existe un esqueleto de arranque. Todavía no están implementados los módulos de negocio ni el esquema SQL.

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

Para ejecutar las pruebas iniciales:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Documentación técnica

- [Arquitectura](docs/architecture.md)
- [Modelo de datos](docs/data-model.md)
