# TESTING_NOTES

```bash
source .venv/bin/activate
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
PYTHONPATH=src python -m unittest tests.test_payment_methods   # Entrega 1
```
- Última ejecución completa: 2026-10-31, 260 pruebas OK (pendientes de Fase 1). `PYTHONPATH=src python -m unittest tests.test_idempotency` para la entrega.
- Críticas por módulo: pagos (`test_sales`, `test_services`, `test_inventory`), esquema/migraciones (`test_database_schema`, `test_payment_methods`), respaldos (`test_backup`).
- Validación manual de UI pendiente: diálogos de pago de venta, orden y compra con combos de catálogo.

## Validación de migración 0008 (2026-10-31)
Sobre copia de la base real (v7, original intacta, sha256 verificado): migra a v8, segunda ejecución no reaplica, conteos y contenido de 9 tablas conservados, `integrity_check` ok, `foreign_key_check` vacío, vistas contables resuelven legado (3 pagos cliente, 5 proveedor incl. CSX, 3 movimientos), triggers rechazan inserciones sin fecha y UPDATE de legado. Base nueva: v8, idempotente, 5 métodos y 8 alias.

## Migración 0009 (2026-10-31)
Copia de la base real (v8): migra a v9, segunda ejecución no reaplica, tablas conservadas, filas históricas con clave NULL, integrity_check ok, foreign_key_check vacío, ajuste idempotente probado en la copia; base nueva v9. Original solo leída (modo ro).
- UI pendiente de validación visual: ajuste/reversión de inventario y pago/reversión de proveedor (botón se deshabilita durante el envío).

## Migración 0011A (2026-10-31)
Copia de la base real (v9): migra a 11, no reaplica, 5 órdenes con importes/pagado/saldo idénticos antes y después (v_saldos_ordenes, list_orders y v_ordenes_importes), tablas conservadas, integrity ok, fk vacío; base nueva v11. Original intacta (sha256). Sin cambio visible esperado en UI: comprobar listado de órdenes y detalle/saldos.

## Migración 0010 (2026-10-31)
Copia de la base real (versiones 1–9,11): aplica 0010 fuera de orden, versión máxima 11, no reaplica, venta real idéntica (1.450.000 pagada), tablas conservadas, pagos históricos con clasificación NULL, integrity ok, fk vacío; devolución de prueba + reintento idempotente en la copia. Base nueva v11. Original intacta (sha256).
Validación visual pendiente: detalle de venta → «Registrar devolución» (parcial/total, no apto, valor reducido con autorizador) y «Revertir pago seleccionado» (nuevo diálogo con naturaleza/origen/evidencia).

## Migración 0012 (2026-10-31)
Copia de la base real (1–11): migra a 12, no reaplica, `v_saldos_ventas` histórica idéntica (4 ventas), tablas conservadas, ledger/compensaciones vacíos, integrity ok, fk vacío. Flujo de prueba en la copia: devolución → compensación mixta (reembolso+crédito) → voucher → entrega → replay idempotente; base nueva v12; original intacta (sha256).
Validación visual pendiente: detalle de venta con devolución → «Compensar devolución» (reembolso/crédito/mixta), «Reembolsos y crédito» (preparar voucher, confirmar entrega, anular, investigar) y «Aplicar saldo a favor» en otra venta del mismo cliente.

## Migraciones 0013-0014 (2026-11-01)
Copia de la base real (1–12): migra a 14, no reaplica, 5 ventas y 5 órdenes con saldos idénticos antes/después, tablas históricas conservadas, suma de residuo del historial = residuo de liquidación por venta, integrity ok, fk vacío; condonación de una deuda real de la copia (venta impaga) + reintento idempotente; base nueva v14; original intacta (sha256).
Validación visual pendiente: «Actores…» (Ventas), devolución/compensación/crédito/reversión de pago con selectores de actores, «Deuda y cartera» (condonar, castigar, anular, recuperación) y el aviso de identidad declarativa.

## Migraciones 0015-0017 (2026-11-01)
Copia de la base real (1-14): migra a 17, no reaplica; `v_saldos_ventas`, `v_saldos_ordenes` y `v_historial_financiero_venta` idénticos antes/después; tablas históricas conservadas; 10 pagos históricos con clave sin huella respetados; integrity ok, fk vacío; pago con fallo simulado → solicitud pendiente → reintento con la misma clave → un solo pago; base nueva v17; original intacta (sha256). La copia contiene una compensación en investigación (de tus pruebas): aparecerá en el panel de pendientes.
Validación visual pendiente: botón «Pendientes» y panel al iniciar (entregas por confirmar; solicitudes con Reintentar/Abandonar), «Corregir datos de la entrega» / «Declarar que la entrega no ocurrió» en «Reembolsos y crédito», «Arqueo de caja…» (Ventas), «Cancelar venta…» (detalle de venta).
