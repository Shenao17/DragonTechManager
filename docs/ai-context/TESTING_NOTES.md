# TESTING_NOTES

```bash
source .venv/bin/activate
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
PYTHONPATH=src python -m unittest tests.test_payment_methods   # Entrega 1
```
- Última ejecución completa: 2026-10-31, 211 pruebas OK (Entrega 5). `PYTHONPATH=src python -m unittest tests.test_idempotency` para la entrega.
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
