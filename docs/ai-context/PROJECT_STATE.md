# PROJECT_STATE

Actualizado: 2026-10-31. Rama `main`, sin commits nuevos de Fase 1 (cambios sin confirmar).

## Estado por estado de verificación
**Implementado y verificado** (suite completa 152 pruebas, 2026-10-31):
- Fase 0: respaldos/restauración, guard de reversión de inventario, errores de integridad.
- Clientes, equipos, órdenes (con pagos), propuestas, inventario, compras, ventas directas y pagos/reversiones.
- Fase 1 · Entrega 1 (migración `0008`): catálogo de métodos de pago, alias, `fecha_negocio` en `pagos_clientes`, `pagos_proveedores`, `movimientos_inventario`; vistas `v_*_contables`; servicio `PaymentMethodService`; UI con combos del catálogo. Técnicamente validada; falta solo validación visual de UI.

**Aprobado y pendiente**: Entregas 2–4 de Fase 1 (migraciones 0009–0011; Informe2 §9, Informe3 §4.7).
**Sin flujo**: armados de PC, gastos, informes, devoluciones/cancelaciones, saldo a favor.

## Esquema
Versión 8. Migraciones 0001–0008 en `src/dragontech_manager/database/migrations/`.

## Documentos fuente
`docs/Informe2 - Diseño Fase 1 (Revisión).md`, `docs/Informe3 - Cierre de decisiones Fase 1.md`, `docs/Nota de corrección - Reversión externa Informe3.md` (originales aprobados; no modificar). Técnicos: `docs/architecture.md`, `data-model.md`, `backups.md`, `fase-0.md`.
