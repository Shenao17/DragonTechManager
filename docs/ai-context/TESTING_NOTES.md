# TESTING_NOTES

```bash
source .venv/bin/activate
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
PYTHONPATH=src python -m unittest tests.test_payment_methods   # Entrega 1
```
- Última ejecución completa: 2026-10-31, 152 pruebas (tras corregir un conteo de migraciones en `test_database_schema`, que se re-ejecutó OK por separado).
- Críticas por módulo: pagos (`test_sales`, `test_services`, `test_inventory`), esquema/migraciones (`test_database_schema`, `test_payment_methods`), respaldos (`test_backup`).
- Validación manual de UI pendiente: diálogos de pago de venta, orden y compra con combos de catálogo.

## Validación de migración 0008 (2026-10-31)
Sobre copia de la base real (v7, original intacta, sha256 verificado): migra a v8, segunda ejecución no reaplica, conteos y contenido de 9 tablas conservados, `integrity_check` ok, `foreign_key_check` vacío, vistas contables resuelven legado (3 pagos cliente, 5 proveedor incl. CSX, 3 movimientos), triggers rechazan inserciones sin fecha y UPDATE de legado. Base nueva: v8, idempotente, 5 métodos y 8 alias.
