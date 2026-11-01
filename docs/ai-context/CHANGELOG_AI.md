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

## 2026-10-31 — Fase 1 · Entrega 3 (0011 parte A)
- Migración `0011_canonical_order_totals`: vista `v_ordenes_importes` (`importe_inicial_cop`, `extras_aprobados_cop`, `importe_acordado_cop`); `v_saldos_ordenes` recreada sobre ella (mismas columnas); triggers de sobrepago de orden, reducción de importe inicial y rechazo de adicional recreados sobre la vista (se elimina el self-join redundante).
- `ServiceOrderRepository.list_orders` usa `v_ordenes_importes`.
- Pruebas: `tests/test_order_totals.py` (equivalencia con la fórmula previa, saldos, reglas de triggers); versión esperada de esquema 11.

## 2026-10-31 — Fase 1 · Entrega 4 (0010)
- Migración `0010_sale_returns_and_cancellations`: tablas `cancelaciones_venta`/`cancelacion_venta_lineas` (inmutables, clave+huella únicas), triggers R1, condición/valor reconocido, reintegro automático de inventario, bloqueo de reversión genérica del movimiento (I9), recreación del trigger de pago de venta (R4: tope = vendido − devuelto reconocido), columnas de clasificación de reversión de pagos + trigger, nuevas `v_saldos_ventas` (misma salida cuando no hay devoluciones) y `v_devoluciones_no_reintegradas`.
- Nuevo `repositories/returns.py`, `services/returns.py` (`ReturnsService.register_return/returnable_lines/list_returns/lost_inventory`), `ui/returns.py`.
- `SalesService.reverse_payment` exige `nature`, `source`, `evidence`; guarda de cancelación ahora usa `estado_cobro`.
- Corregido en desarrollo: el reintento de una devolución ya agotada validaba disponibilidad antes de detectar el replay; ahora se detecta primero.
- Pruebas: `tests/test_returns.py` (14, incl. concurrencia), `tests/test_returns_ui.py` (2).
