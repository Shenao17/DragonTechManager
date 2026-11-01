# TECHNICAL_RULES

- Capas: UI (`ui/`) → servicios (`services/`) → repositorios (`repositories/`) → SQLite. Lógica de negocio solo en servicios y triggers.
- Migraciones: secuenciales `NNNN_nombre.sql`, atómicas, con checksum; nunca editar las aplicadas. Respaldo previo automático (Fase 0).
- Tablas financieras/inventario inmutables por triggers; columnas nuevas vía `ALTER TABLE ADD COLUMN` (NULL en histórico) + vistas.
- Triggers de inserción obligan `fecha_negocio`; todo INSERT directo (tests incluidos) debe suministrarla.
- Operaciones multi-tabla en `atomic(connection)`; `sqlite3.IntegrityError` se traduce con `translate_integrity_error`.
- Fecha de negocio: `dragontech_manager.business_date.business_date_from_utc`.
- Python 3.14 + PySide6 en `.venv`; sin dependencias nuevas.
