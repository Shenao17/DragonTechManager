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

**Aprobado y pendiente**: Entregas 5–6b (ver roadmap: saldo a favor y compensaciones, actores/reembolsos físicos/extinción de deuda, parte B del 0011 ( Informe2 §9, Informe3 §4.7) y lo no cubierto del 0009 original (ver roadmap, fila 2b).
**Sin flujo**: armados de PC, gastos, informes, devoluciones/cancelaciones, saldo a favor.

## Esquema
Versión 11. Migraciones 0001–0011 (la 0010 se aplicó después de la 0011 en bases ya migradas) en `src/dragontech_manager/database/migrations/`.

## Documentos fuente
`docs/Informe2 - Diseño Fase 1 (Revisión).md`, `docs/Informe3 - Cierre de decisiones Fase 1.md`, `docs/Nota de corrección - Reversión externa Informe3.md` (originales aprobados; no modificar). Técnicos: `docs/architecture.md`, `data-model.md`, `backups.md`, `fase-0.md`.
