# IMPLEMENTATION_ROADMAP

Fase 1 (Informe2 §9, ampliado por Informe3 §4.7). No avanzar sin autorización expresa por entrega.

| Entrega | Migración | Contenido | Estado |
|---|---|---|---|
| 1 | 0008 `payment_methods_and_business_date` | Catálogo, alias, `metodo_pago_id`, `fecha_negocio`, índices, triggers de fecha | Técnicamente validada (2026-10-31); falta solo validación visual de UI |
| 2 | 0009 `idempotency_supplier_and_inventory` | Clave+huella en `pagos_proveedores` y `movimientos_inventario` (ajustes/reversiones); `services/idempotency.py` | Implementada y verificada (162 pruebas; migración probada en copia); falta validación visual UI |
| 2b | (por definir) | `solicitudes_operacion` persistente, huella en `pagos_clientes`, `actores` — del 0009 original de Informe2/3; no incluidos en esta entrega | Pendiente de autorización |
| 3 | 0011 (parte A) `canonical_order_totals` | `v_ordenes_importes` como fuente única de extras; `v_saldos_ordenes`, `list_orders` y 3 triggers la consumen | Implementada y verificada (166 pruebas; equivalencia sobre las 5 órdenes reales); falta validación visual |
| 4 | 0010 `sale_returns_and_cancellations` | Devoluciones/cancelaciones de venta (cabecera + líneas), reintegro de inventario solo de lo apto, pérdida de no aptos, R1/R4, `v_saldos_ventas` con devoluciones, clasificación de reversión de pagos (corrección vs reversión real) | Implementada y verificada (182 pruebas; migración en copia); falta validación visual |
| 5 | 0012 (por crear) | Saldo a favor (ledger) y compensaciones reembolso/crédito/mixta: `compensaciones_cancelacion`, `movimientos_saldo_favor`, R2/R3/R5/R6/R8; recrea (DROP/CREATE) `v_saldos_ventas` y el trigger de pago de venta sumando `U`, `C`, `G` | Pendiente. Depende de `cancelaciones_venta` (0010) |
| 6 | 0013 (por crear) | `actores`, `eventos_compensacion`/confirmaciones (reembolso físico), `extinciones_deuda_venta` (condonación/castigo), recuperaciones `H`, R9–R14 | Pendiente. Depende de 0010 y 0012 |
| 6b | 0014 (por crear) | Parte B del 0011 original: `v_historial_financiero_venta`, `saldo_favor_aplicado_cop` en `v_saldos_ordenes` | Pendiente. Depende de 0012–0013 |

**Secuencia:** la base real tenía 1–9 y 11; la 0010 se aplica después (ejecutor sin contigüidad, probado en copia). Regla: ninguna migración aplicada se edita; las Entregas 5, 6 y 6b usan migraciones nuevas (0012–0014) que recrean con DROP/CREATE las vistas/triggers que necesiten ampliar (`v_saldos_ventas`, `pagos_clientes_no_sobrepagar_venta`). Numeración 0012–0014 provisional hasta autorizar cada entrega.

Fases posteriores: Fase 2 (saldo a favor en órdenes, política de entrega con saldo), usuarios/autenticación, gastos, armados, informes.
