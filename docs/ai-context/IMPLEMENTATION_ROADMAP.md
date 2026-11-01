# IMPLEMENTATION_ROADMAP

Fase 1 (Informe2 §9, ampliado por Informe3 §4.7). No avanzar sin autorización expresa por entrega.

| Entrega | Migración | Contenido | Estado |
|---|---|---|---|
| 1 | 0008 `payment_methods_and_business_date` | Catálogo, alias, `metodo_pago_id`, `fecha_negocio`, índices, triggers de fecha | Técnicamente validada (2026-10-31); falta solo validación visual de UI |
| 2 | 0009 `idempotency_supplier_and_inventory` | Clave+huella en `pagos_proveedores` y `movimientos_inventario` (ajustes/reversiones); `services/idempotency.py` | Implementada y verificada (162 pruebas; migración probada en copia); falta validación visual UI |
| 2b | (por definir) | `solicitudes_operacion` persistente, huella en `pagos_clientes`, `actores` — del 0009 original de Informe2/3; no incluidos en esta entrega | Pendiente de autorización |
| 3 | 0011 (parte A) `canonical_order_totals` | `v_ordenes_importes` como fuente única de extras; `v_saldos_ordenes`, `list_orders` y 3 triggers la consumen | Implementada y verificada (166 pruebas; equivalencia sobre las 5 órdenes reales); falta validación visual |
| 4a | 0010 `sale_returns_credit_and_confirmations` | Cancelaciones/devoluciones, ledger de saldo a favor, reembolsos, confirmaciones, extinción de deuda | Pendiente |
| 4b | 0012 (por confirmar) | Parte B del 0011 original: `v_historial_financiero_venta`, `v_devoluciones_no_reintegradas`, `saldo_favor_aplicado_cop` en `v_saldos_ordenes`; depende de 0010 | Pendiente |

**Secuencia:** 0010 aún no existe en disco. La base queda con versiones 1–9 y 11. El ejecutor aplica cualquier versión no aplicada sin exigir contigüidad, por lo que 0010 se aplicará después (válido: no toca vistas/triggers de órdenes). No renumerar 0011.

Fases posteriores: Fase 2 (saldo a favor en órdenes, política de entrega con saldo), usuarios/autenticación, gastos, armados, informes.
