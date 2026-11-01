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

## 2026-10-31 — Corrección: datos obsoletos al seleccionar productos
- Nuevo `ui/product_defaults.py`; `SaleLineDialog` y `PurchaseLineDialog` lo usan. Sin cambios de servicios, migraciones ni reglas financieras. Pruebas: `tests/test_product_selection_ui.py`; suite completa 193 OK.

## 2026-10-31 — Fase 1 · Entrega 5 (0012)
- Migración `0012_credit_ledger_and_compensations`: `tipos_origen_saldo_favor`, `compensaciones_cancelacion`, `eventos_compensacion`, `movimientos_saldo_favor` (todas append-only, claves únicas, huellas); vistas `v_compensaciones_estado`, `v_ventas_posicion`, `v_saldos_ventas` (recreada: añade crédito aplicado, reembolsos comprometidos/entregados, crédito generado, exceso reembolsado), `v_saldos_favor`, `v_compensaciones_pendientes`; triggers R2/R3/regla de oro/R8, generación única de crédito, saldo ≥ 0, R4 con crédito, validación de eventos de entrega, R6 para correcciones de registro.
- Nuevo `services/compensations.py`, `services/credit.py`, `repositories/compensations.py`, `ui/compensations.py`; `SaleDetailsDialog` con tres acciones nuevas.
- Pruebas: `tests/test_compensations.py` (19, incl. concurrencia), `tests/test_compensations_ui.py`; versión de esquema esperada 12.

## 2026-11-01 — Fase 1 · Entrega 6 (0013 + 0014)
- Aprobaciones del propietario (A1–A6, B1–B7, ID1–ID6, PA1–PA6 como recomendadas; historial solo el diseñado; H en tabla propia).
- Migración `0013`: `actores`; columnas de actor/origen en `cancelaciones_venta`, `compensaciones_cancelacion`, `eventos_compensacion`, `movimientos_saldo_favor`, `pagos_clientes` + triggers de validación (activo, `puede_autorizar`, distinto, límite definido); `extinciones_deuda_venta`, `anulaciones_extincion_deuda`, `recuperaciones_deuda_venta`; `v_ventas_posicion`/`v_saldos_ventas` ampliadas (recreadas con las columnas previas); `pagos_clientes_no_sobrepagar_venta`, `saldo_favor_validar`, `eventos_compensacion_validar` recreados (saldo cobrable `pagable` = MIN(T−R−P−U, N0−H−Q)); trigger que anula compromisos sin preparar tras reversión real.
- Migración `0014`: `v_historial_financiero_venta`, `v_cartera_ventas`, `v_saldos_ordenes` con `saldo_favor_aplicado_cop`.
- Nuevos: `services/actors.py`, `services/debt.py`, `repositories/actors.py`, `repositories/debt.py`, `ui/actors.py`, `ui/debt.py`. Servicios de devolución, compensación, crédito y reversión de pago aceptan actores del directorio (o texto legado); los diálogos de UI usan selectores de actores.
- Pruebas: `tests/test_debt_actors.py` (19, incl. concurrencia y fallo atómico), `tests/test_debt_ui.py`; versión de esquema esperada 14.

## 2026-11-01 — Pendientes de Fase 1 (0015, 0016, 0017)
- Bloque 3 · `0015`: `solicitudes_operacion` (estados pendiente/completada/abandonada, transiciones protegidas, sin borrado), `pagos_clientes.huella_solicitud` (+ filas históricas con clave sin huella se comparan campo a campo). `services/operations.py` (`OperationRegistry.begin/track/complete/note_rejection/reconcile/abandon`) y `services/operation_retry.py`; integrado en pagos de venta/orden, devoluciones, compensaciones y sus eventos, aplicación de saldo a favor y operaciones de deuda.
- Bloque 1 · `0016`: columnas `correccion_tipo`, `ocurrido_corregido_en_utc`, `receptor`, `evidencia` en eventos; `v_compensaciones_estado` recreada (marcas `en_investigacion`, `liberada`); `v_compensaciones_pendientes`, `v_investigaciones_compensacion`; triggers `compensaciones_validar` y `eventos_compensacion_validar` recreados (investigar entregas registradas; corrección de datos; entrega no ocurrida con R13-C). `CompensationService.correct_delivery_data`, `report_delivery_not_occurred`; `ui/pending.py`, botón «Pendientes (n)» y panel al iniciar (`app.main`).
- Bloque 2 · `0017`: `v_entregas_efectivas`, `v_entregas_del_dia`, `v_arqueo_caja`; `services/cash.py`, `ui/cash.py`; `ReturnsService.cancellation_status`, `ui/cancel_sale.py`.
- Pruebas: `test_operations.py` (8), `test_delivery_corrections.py` (9), `test_pending_ui.py` (3), `test_cash_and_cancellation.py` (8); `tests/_schema.py` evita editar la versión esperada en cada migración.
