# CHANGELOG_AI

## 2026-10-31 — Fase 1 · Entrega 1
- Migración `0008`: `metodos_pago`, `metodos_pago_alias` (semilla EFECTIVO, TRANSFERENCIA, TARJETA, OTRO, CSX legado; alias de textos históricos), columnas `metodo_pago_id`/`fecha_negocio`, índices, triggers de inserción (fecha obligatoria y no futura; método activo/aplicable; texto = nombre del catálogo), bloqueo de borrado/identidad del catálogo, vistas `v_pagos_clientes_contables`, `v_pagos_proveedores_contables`, `v_movimientos_contables`.
- Nuevo: `business_date.py`, `services/payment_methods.py`, `repositories/payment_methods.py`.
- Servicios de ventas, órdenes y compras: resuelven método vía catálogo (id o nombre/alias), idempotencia compara `metodo_pago_id`, fecha de negocio en pagos y reversiones. Movimientos de inventario registran `fecha_negocio`.
- UI: combos del catálogo en pagos de venta, orden y proveedor (antes listas distintas/texto libre).
- Pruebas: nuevo `tests/test_payment_methods.py`; ajustados INSERT directos y versión esperada (8) en pruebas existentes.

## 2026-10-31 — Fase 1 · Entrega 2
- Migración `0009`: `clave_idempotencia` + `huella_solicitud` en `pagos_proveedores` y `movimientos_inventario` (CHECK de longitud, índice único parcial, trigger que exige ambas juntas).
- Nuevo `services/idempotency.py`; `SalesService` reutiliza su `fingerprint`.
- Servicios/repositorios de inventario y compras: reintento con misma clave+huella devuelve la fila original; otra huella → `ConflictError` sin escrituras; la búsqueda ocurre dentro de `BEGIN IMMEDIATE`.
- UI (ajuste, reversión de movimiento, pago y reversión de proveedor): `IntentKey` por intención, botones deshabilitados durante el envío.
- Pruebas: `tests/test_idempotency.py` (10, incl. concurrencia con 6 hilos y conexiones separadas); llamadas existentes actualizadas con clave; versión esperada 9.
