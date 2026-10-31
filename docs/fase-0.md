# Fase 0 — Contención de riesgos

Fecha: 2026-10-31
Punto de restauración Git: etiqueta `fase0-pre` sobre `b6902a3`.

## Alcance autorizado

1. Respaldos consistentes, rotativos, validados y con restauración comprobada.
2. Bloqueo de la reversión genérica de movimientos originados por ventas, compras,
   órdenes y ensamblajes.
3. `refresh` en la vista de inventario.
4. Mensajes específicos para errores de integridad.
5. Pruebas de cada corrección, incluidos errores, reintentos y recuperación.

No se modificó la lógica de pagos, ventas ni órdenes. No se agregaron migraciones.
No se alteró ningún registro histórico.

## Cambios realizados

### Nuevo: `src/dragontech_manager/database/backup.py`

- `create_backup()` usa `sqlite3.Connection.backup` (instantánea coherente en línea),
  publica con reemplazo atómico y valida antes de publicar.
- Reintenta bloqueos transitorios de SQLite y limpia archivos temporales ante fallo.
- `validate_backup()` comprueba tamaño, `integrity_check`, `foreign_key_check`,
  existencia de `schema_migrations` y versión de esquema.
- `rotate_backups()` conserva las copias más recientes y solo borra archivos con el
  patrón propio de la aplicación.
- `restore_backup()` valida la copia, respalda la base actual como
  `pre-restauracion`, reemplaza de forma atómica, revalida y recupera la copia de
  seguridad si la validación posterior falla.
- Retención por defecto: 10 copias.

### `src/dragontech_manager/app.py`

- `initialize_database()` acepta `backup_dir` y crea una copia etiquetada `inicio`
  antes de aplicar migraciones cuando la base ya tiene esquema.
- El arranque real usa `backups/` junto al archivo de datos.
- Una falla de respaldo impide abrir la base en modo de escritura, en lugar de
  continuar sin punto de restauración.

### `src/dragontech_manager/services/inventory.py`

- El mecanismo genérico de reversión solo acepta movimientos `ajuste`.
- Movimientos con `venta_detalle_id`, `compra_detalle_id`, `orden_repuesto_id` o
  `armado_componente_id` se rechazan con un mensaje que indica el flujo correcto.
- `reversal_blocked_reason()` permite a la interfaz explicar el bloqueo.
- No se crea ningún movimiento de reversión cuando la operación se rechaza.

### `src/dragontech_manager/ui/inventory.py`

- `InventoryWorkspacePage.refresh()` recarga productos, proveedores y compras; la
  navegación principal ya invoca `refresh()` cuando existe.
- El botón de reversión se deshabilita para movimientos con origen documental y
  muestra el motivo en su tooltip.

### `src/dragontech_manager/services/errors.py`

- `translate_integrity_error()` traduce `UNIQUE`, `NOT NULL`, `CHECK` y
  `FOREIGN KEY` indicando el campo cuando SQLite lo informa.
- Los mensajes de `RAISE(ABORT, ...)` de los triggers se conservan íntegros, ya que
  son reglas de negocio en español.
- Los mensajes internos no reconocidos no se filtran al usuario.

## Compatibilidad y datos

- Sin migraciones nuevas: el esquema permanece en la versión 7.
- Sin cambios en tablas, triggers ni registros existentes.
- La restauración reemplaza el archivo completo, por lo que exige la aplicación
  cerrada; está documentado en `docs/backups.md`.
- La copia de seguridad se crea con la API de SQLite, no con `cp`, para evitar
  imágenes inconsistentes.

## Verificación

- Suite completa: **143 pruebas, todas correctas** (109 previas + 34 nuevas).
- Prueba de aceptación sobre una copia de la base real:
  - copia de inicio válida en versión 7;
  - restauración devolvió los conteos originales;
  - la copia `pre-restauracion` conservó el cambio posterior;
  - `integrity_check` de la base restaurada: `ok`.
- La base real no fue modificada.

## Límites que quedan para fases posteriores

- Interfaz gráfica de restauración.
- Copia de los respaldos a un medio externo.
- Cifrado de respaldos.
- Corrección de ventas mediante cancelación/devolución (Fase 1).
- Política de entrega de órdenes con saldo pendiente (Fase 2).
