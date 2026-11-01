# PROJECT_STATE

Actualizado: 2026-10-31. Rama `main`, sin commits nuevos de Fase 1 (cambios sin confirmar).

## Estado por estado de verificación
**Implementado y verificado** (suite completa 152 pruebas, 2026-10-31):
- Fase 0: respaldos/restauración, guard de reversión de inventario, errores de integridad.
- Clientes, equipos, órdenes (con pagos), propuestas, inventario, compras, ventas directas y pagos/reversiones.
- Fase 1 · Entrega 1 (migración `0008`): catálogo de métodos de pago, alias, `fecha_negocio` en `pagos_clientes`, `pagos_proveedores`, `movimientos_inventario`; vistas `v_*_contables`; servicio `PaymentMethodService`; UI con combos del catálogo. Técnicamente validada; falta solo validación visual de UI.

- Fase 1 · Entrega 2 (migración `0009`): idempotencia (clave + huella SHA-256) en pagos/reversiones de proveedor y ajustes/reversiones de inventario; `services/idempotency.py` (`validate_key`, `fingerprint`, `is_replay`, `IntentKey`). UI conserva una clave por intención y bloquea el botón durante el envío.

- Fase 1 · Entrega 3 (migración `0011`, parte A): `v_ordenes_importes` es la única definición del importe acordado de órdenes; `v_saldos_ordenes`, `ServiceOrderRepository.list_orders` y los triggers `pagos_clientes_no_sobrepagar_orden`, `orden_no_reducir_deuda_pagada`, `decisiones_adicional_no_reduce_deuda_pagada` la consumen (mismas reglas y mensajes). Resuelve I10.
- Fase 1 · Entrega 4 (migración `0010`): `cancelaciones_venta` + `cancelacion_venta_lineas` (append-only, idempotentes), `ReturnsService`, `ui/returns.py` (botón «Registrar devolución» en el detalle de venta). Reintegra a stock solo lo apto (movimiento `ajuste` con `devolucion_venta_linea_id`), `v_devoluciones_no_reintegradas`, `v_saldos_ventas` con `devuelto_reconocido_cop`, `sobrepago_pendiente_cop`, `estado_devolucion`, `estado_cobro` (`reembolso_pendiente`). Reversión de pagos de venta clasificada (`naturaleza_reversion`, `origen_evento`, `evidencia_reversion`).
- Corrección de selección de productos en líneas de venta y compra (ver KNOWN_ISSUES). Falta validación visual.
- Fase 1 · Entrega 5 (migración `0012`): `CompensationService` (commit reembolso/crédito/mixta, prepare, confirm_delivery, annul, mark_under_investigation), `CreditService` (balance, apply_to_sale), `ui/compensations.py` + botones en el detalle de venta («Compensar devolución», «Reembolsos y crédito», «Aplicar saldo a favor»). `v_ventas_posicion` es la fuente única de `P, U, T, R, C, C_e, G, D`.
- Fase 1 · Entrega 6 (migraciones `0013`, `0014`): directorio de actores (`ActorService`, `ui/actors.py`, botón «Actores…» en Ventas); `DebtService` (condonación, castigo, anulación de extinción, recuperaciones H) y `ui/debt.py` («Deuda y cartera» en el detalle de venta); `v_saldos_ventas` con deuda/residuo/estados; reversión financiera real anula compromisos sin preparar; `v_historial_financiero_venta`, `v_cartera_ventas`, `saldo_favor_aplicado_cop` en `v_saldos_ordenes`. Identidad **declarativa**.
- Pendientes de Fase 1 (migraciones `0015`-`0017`): solicitudes de operación persistentes (`services/operations.py`, `operation_retry.py`; integradas en pagos de venta/orden, devoluciones, compensaciones y eventos, saldo a favor y deuda); huella persistente en pagos de cliente; panel «Pendientes» (`ui/pending.py`, botón en la barra superior y al iniciar la app); corrección de entregas (`correct_delivery_data`, `report_delivery_not_occurred`); reportes `v_entregas_del_dia`/`v_arqueo_caja` (`ui/cash.py`, «Arqueo de caja…» en Ventas); asistente «Cancelar venta…».

**Pendiente:** validación visual de la Entrega 6 y los puntos de `KNOWN_ISSUES.md` → «Pendientes de cierre de la Fase 1». Después: Fase 2 (saldo a favor en órdenes, política de entrega con saldo), autenticación, gastos, armados, informes.
**Sin flujo**: armados de PC, gastos, informes, devoluciones/cancelaciones, saldo a favor.

## Esquema
Versión 17. Migraciones 0001–0017 (la 0010 se aplicó después de la 0011 en bases ya migradas) en `src/dragontech_manager/database/migrations/`.

## Documentos fuente
`docs/Informe2 - Diseño Fase 1 (Revisión).md`, `docs/Informe3 - Cierre de decisiones Fase 1.md`, `docs/Nota de corrección - Reversión externa Informe3.md` (originales aprobados; no modificar). Técnicos: `docs/architecture.md`, `data-model.md`, `backups.md`, `fase-0.md`.
