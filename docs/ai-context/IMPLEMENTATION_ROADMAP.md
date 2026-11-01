# IMPLEMENTATION_ROADMAP

Fase 1 (Informe2 §9, ampliado por Informe3 §4.7). No avanzar sin autorización expresa por entrega.

| Entrega | Migración | Contenido | Estado |
|---|---|---|---|
| 1 | 0008 `payment_methods_and_business_date` | Catálogo, alias, `metodo_pago_id`, `fecha_negocio`, índices, triggers de fecha | Técnicamente validada (2026-10-31); falta solo validación visual de UI |
| 2 | 0009 `idempotency_supplier_and_inventory` | Clave+huella en `pagos_proveedores` y `movimientos_inventario` (ajustes/reversiones); `services/idempotency.py` | Implementada y verificada (162 pruebas; migración probada en copia); falta validación visual UI |
| 2b | 0015 `persistent_operation_requests` (pendientes, bloque 3) | `solicitudes_operacion` persistentes + `huella_solicitud` en `pagos_clientes`; `OperationRegistry`, reintento tras reinicio | Implementada y verificada |
| 3 | 0011 (parte A) `canonical_order_totals` | `v_ordenes_importes` como fuente única de extras; `v_saldos_ordenes`, `list_orders` y 3 triggers la consumen | Implementada y verificada (166 pruebas; equivalencia sobre las 5 órdenes reales); falta validación visual |
| 4 | 0010 `sale_returns_and_cancellations` | Devoluciones/cancelaciones de venta (cabecera + líneas), reintegro de inventario solo de lo apto, pérdida de no aptos, R1/R4, `v_saldos_ventas` con devoluciones, clasificación de reversión de pagos (corrección vs reversión real) | Implementada y verificada (182 pruebas; migración en copia); falta validación visual |
| 5 | 0012 `credit_ledger_and_compensations` | Compensaciones reembolso/crédito/mixta (`compensaciones_cancelacion`), entrega física con eventos append-only (`eventos_compensacion`: voucher, entrega única, anulación, investigación), ledger de saldo a favor (`movimientos_saldo_favor`), aplicación a ventas, R2/R3/R4/R5/R6(parcial)/R8, `v_ventas_posicion` (fuente única), `v_saldos_ventas` ampliada, `v_saldos_favor`, `v_compensaciones_pendientes` | Implementada y verificada (211 pruebas; migración en copia); falta validación visual |
| 6 | 0013 `actors_debt_extinction_and_reversal` | Directorio `actores` (identidad declarativa) y columnas de actor en operaciones anteriores; `extinciones_deuda_venta`, `anulaciones_extincion_deuda`, `recuperaciones_deuda_venta` (H); `v_ventas_posicion`/`v_saldos_ventas` ampliadas (N0, F, deuda, estados); R9/R14/PA3; anulación automática de compromisos SIN preparar tras reversión financiera real; `ActorService`, `DebtService`, UI (Actores…, Deuda y cartera) | Implementada y verificada (232 pruebas; migración en copia); falta validación visual |
| 6b | 0014 `financial_history_and_order_credit_column` | Parte B del 0011 original: `v_historial_financiero_venta` (suma de residuo = F; suma de caja = P + H − C_e), `v_cartera_ventas`, `saldo_favor_aplicado_cop` en `v_saldos_ordenes` (0 hasta Fase 2) | Implementada y verificada |

**Secuencia:** versiones en la base real antes de esta entrega: 1–12; se añaden 13 y 14 en orden. La parte B del 0011 quedó cubierta por la 0014 (sin editar el 0011 aplicado). Ninguna migración aplicada se edita.

| P1 | 0016 `delivery_corrections_and_investigations` (pendientes, bloque 1) | Evento `corregida` (datos / entrega no ocurrida = reversión de reembolso entregado, R13-C rechaza), investigación sobre entregas registradas, panel «Pendientes» al iniciar | Implementada y verificada; falta validación visual |
| P2 | 0017 `delivery_and_cash_reports` (pendientes, bloque 2) | `v_entregas_efectivas`, `v_entregas_del_dia`, `v_arqueo_caja`; asistente «Cancelar venta…» y `cancellation_status` (sin concepto nuevo) | Implementada y verificada; falta validación visual |

**Estado de la Fase 1:** entregas 1-6 y pendientes P1-P3 implementadas. Quedan abiertos solo los puntos de `KNOWN_ISSUES.md` → «Pendientes de cierre de la Fase 1» (ver abajo) y tu validación visual; **no se declara cerrada** hasta entonces.

Fases posteriores: Fase 2 (saldo a favor en órdenes, política de entrega con saldo), usuarios/autenticación, gastos, armados, informes.
