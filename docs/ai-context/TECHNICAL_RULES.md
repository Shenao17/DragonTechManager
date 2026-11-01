# TECHNICAL_RULES

- Capas: UI (`ui/`) → servicios (`services/`) → repositorios (`repositories/`) → SQLite. Lógica de negocio solo en servicios y triggers.
- Migraciones: secuenciales `NNNN_nombre.sql`, atómicas, con checksum; nunca editar las aplicadas. Respaldo previo automático (Fase 0).
- Tablas financieras/inventario inmutables por triggers; columnas nuevas vía `ALTER TABLE ADD COLUMN` (NULL en histórico) + vistas.
- Triggers de inserción obligan `fecha_negocio`; todo INSERT directo (tests incluidos) debe suministrarla.
- Operaciones multi-tabla en `atomic(connection)`; `sqlite3.IntegrityError` se traduce con `translate_integrity_error`.
- Fecha de negocio: `dragontech_manager.business_date.business_date_from_utc`.
- Idempotencia: `services/idempotency.py`; consultar la clave dentro de `atomic` (BEGIN IMMEDIATE) antes de validar estado; claves ≤120 caracteres; en UI usar `IntentKey` (una clave por intención, se descarta al éxito).
- Saldo cobrable de una venta: `v_ventas_posicion.pagable`; pagos, uso de crédito, condonación y recuperación leen de ahí (una sola definición). Actores: `ActorService.identify` valida en servicio; los triggers repiten las reglas en base de datos.
- Operaciones financieras con clave: envolver en `OperationRegistry.track(...)` (solicitud persistente) y llamar `tracker.complete(entidad, id)` dentro de la transacción del negocio; añadir el tipo a `ENTITIES` y a `operation_retry._dispatch`. Las pruebas leen la versión de esquema de `tests/_schema.py`.
- Python 3.14 + PySide6 en `.venv`; sin dependencias nuevas.
