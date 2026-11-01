# IMPLEMENTATION_ROADMAP

Fase 1 (Informe2 §9, ampliado por Informe3 §4.7). No avanzar sin autorización expresa por entrega.

| Entrega | Migración | Contenido | Estado |
|---|---|---|---|
| 1 | 0008 `payment_methods_and_business_date` | Catálogo, alias, `metodo_pago_id`, `fecha_negocio`, índices, triggers de fecha | Técnicamente validada (2026-10-31); falta solo validación visual de UI |
| 2 | 0009 `idempotency_supplier_and_inventory` | Clave+huella en `pagos_proveedores` y `movimientos_inventario` (ajustes/reversiones); `services/idempotency.py` | Implementada y verificada (162 pruebas; migración probada en copia); falta validación visual UI |
| 2b | (por definir) | `solicitudes_operacion` persistente, huella en `pagos_clientes`, `actores` — del 0009 original de Informe2/3; no incluidos en esta entrega | Pendiente de autorización |
| 3 | 0011 (parte A) `canonical_order_totals` | `v_ordenes_importes` como fuente única de extras; `v_saldos_ordenes`, `list_orders` y 3 triggers la consumen | Implementada y verificada (166 pruebas; equivalencia sobre las 5 órdenes reales); falta validación visual |
| 4 | 0010 `sale_returns_and_cancellations` | Devoluciones/cancelaciones de venta (cabecera + líneas), reintegro de inventario solo de lo apto, pérdida de no aptos, R1/R4, `v_saldos_ventas` con devoluciones, clasificación de reversión de pagos (corrección vs reversión real) | Implementada y verificada (182 pruebas; migración en copia); falta validación visual |
| 5 | 0012 `credit_ledger_and_compensations` | Compensaciones reembolso/crédito/mixta (`compensaciones_cancelacion`), entrega física con eventos append-only (`eventos_compensacion`: voucher, entrega única, anulación, investigación), ledger de saldo a favor (`movimientos_saldo_favor`), aplicación a ventas, R2/R3/R4/R5/R6(parcial)/R8, `v_ventas_posicion` (fuente única), `v_saldos_ventas` ampliada, `v_saldos_favor`, `v_compensaciones_pendientes` | Implementada y verificada (211 pruebas; migración en copia); falta validación visual |
| 6 | 0013 (por crear) | `actores` (identidad de ejecutor/autorizador/receptor, hoy texto declarativo), `extinciones_deuda_venta` y anulaciones (condonación/castigo), recuperaciones `H`, deuda por reversión real (`N0`, `F`), anulación automática de compromisos no financiados tras una reversión real, R9–R14, ajustes de saldo a favor | Pendiente. Depende de 0010 y 0012 |
| 6b | 0014 (por crear) | Parte B del 0011 original: `v_historial_financiero_venta`, `saldo_favor_aplicado_cop` en `v_saldos_ordenes` (y uso de crédito en órdenes: Fase 2) | Pendiente. Depende de 0012–0013 |

**Secuencia:** versiones aplicadas en la base real: 1–12 (la 0010 se aplicó tras la 0011, la 0012 tras ambas). Ninguna migración aplicada se edita; 0013–0014 son provisionales y recrearán con DROP/CREATE las vistas/triggers que amplíen (`v_ventas_posicion`, `v_saldos_ventas`, triggers de pago/compensación). **Dependencia pendiente:** la parte B del 0011 requiere 0012 y 0013.

Fases posteriores: Fase 2 (saldo a favor en órdenes, política de entrega con saldo), usuarios/autenticación, gastos, armados, informes.
