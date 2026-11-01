# TESTING_NOTES

```bash
source .venv/bin/activate
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
PYTHONPATH=src python -m unittest tests.test_payment_methods   # Entrega 1
```
- Última ejecución completa: 2026-10-31, 162 pruebas OK (Entrega 2). `PYTHONPATH=src python -m unittest tests.test_idempotency` para la entrega.
- Críticas por módulo: pagos (`test_sales`, `test_services`, `test_inventory`), esquema/migraciones (`test_database_schema`, `test_payment_methods`), respaldos (`test_backup`).
- Validación manual de UI pendiente: diálogos de pago de venta, orden y compra con combos de catálogo.

## Validación de migración 0008 (2026-10-31)
Sobre copia de la base real (v7, original intacta, sha256 verificado): migra a v8, segunda ejecución no reaplica, conteos y contenido de 9 tablas conservados, `integrity_check` ok, `foreign_key_check` vacío, vistas contables resuelven legado (3 pagos cliente, 5 proveedor incl. CSX, 3 movimientos), triggers rechazan inserciones sin fecha y UPDATE de legado. Base nueva: v8, idempotente, 5 métodos y 8 alias.

## Migración 0009 (2026-10-31)
Copia de la base real (v8): migra a v9, segunda ejecución no reaplica, tablas conservadas, filas históricas con clave NULL, integrity_check ok, foreign_key_check vacío, ajuste idempotente probado en la copia; base nueva v9. Original solo leída (modo ro).
- UI pendiente de validación visual: ajuste/reversión de inventario y pago/reversión de proveedor (botón se deshabilita durante el envío).
