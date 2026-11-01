# IMPLEMENTATION_ROADMAP

Fase 1 (Informe2 §9, ampliado por Informe3 §4.7). No avanzar sin autorización expresa por entrega.

| Entrega | Migración | Contenido | Estado |
|---|---|---|---|
| 1 | 0008 `payment_methods_and_business_date` | Catálogo, alias, `metodo_pago_id`, `fecha_negocio`, índices, triggers de fecha | Técnicamente validada (2026-10-31); falta solo validación visual de UI |
| 2 | 0009 `idempotency_and_operation_intents` | `solicitudes_operacion`, idempotencia proveedores/inventario, huella en pagos, `actores` | Pendiente |
| 3 | 0010 `sale_returns_credit_and_confirmations` | Cancelaciones/devoluciones, ledger de saldo a favor, reembolsos, confirmaciones, extinción de deuda | Pendiente |
| 4 | 0011 `canonical_order_totals_and_history` | `v_ordenes_importes`, historial financiero, reportes | Pendiente |

Fases posteriores: Fase 2 (saldo a favor en órdenes, política de entrega con saldo), usuarios/autenticación, gastos, armados, informes.
