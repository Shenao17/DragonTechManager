# Modelo de datos inicial

Este es el diseño lógico propuesto para SQLite; todavía no es un esquema SQL implementado. Todas las claves primarias son enteros internos. Las referencias usan claves foráneas. Fechas y horas se guardan en ISO 8601 local/UTC con una política única por definir antes de implementar; importes COP son enteros positivos o no negativos según el campo.

## Entidades y relaciones

### Clientes y equipos

- **`clientes`**: `id`, `nombre` (requerido), `telefono`, `whatsapp`, `correo`, `notas`, `creado_en`, `actualizado_en`, `archivado_en` opcional. Índice de búsqueda en nombre/teléfono; no imponer unicidad global al teléfono porque una familia puede compartirlo.
- **`equipos`**: `id`, `codigo` (único, formato `EQ-AAAA-######`), `cliente_id` FK, `tipo`, `marca`, `modelo`, `serial` opcional, `especificaciones`, `accesorios_recibidos`, `estado_fisico`, `creado_en`, `archivado_en`. Índice por `cliente_id`, índice parcial de serial no vacío si se confirma que el serial identifica equipo sin ambigüedad.
- Cardinalidad: cliente 1:N equipos. Un equipo conserva su cliente actual; cada orden conserva además `cliente_id` como fotografía de quién solicitó esa visita.

### Servicio técnico

- **`ordenes_servicio`**: `id`, `codigo` único `OS-AAAA-######`, `cliente_id` FK, `equipo_id` FK, `recibido_en`, `fecha_entrega` opcional, `problema_reportado`, `diagnostico`, `trabajo_realizado`, `estado`, `tecnico`, `importe_inicial_cop` entero no negativo, `creado_en`, `actualizado_en`. Índices por código (UNIQUE), estado/fecha y cliente/equipo con fecha.
- Cada visita es una orden nueva; no se recicla una orden para una visita posterior.
- **`servicios_adicionales`**: `id`, `orden_id` FK, `descripcion`, `importe_cop` entero positivo, `estado` (propuesto/aprobado/rechazado), `propuesto_en`, `aprobado_en`, `aprobado_por`/medio y nota de evidencia. El estado aprobado requiere fecha/evidencia. Un adicional suma al importe de la orden solo al aprobarse y dentro de la misma transacción que registra la aprobación.
- **`orden_repuestos`** (líneas de repuestos usados): `id`, `orden_id` FK, `producto_id` FK, `cantidad` positiva, `costo_unitario_cop` capturado, `precio_unitario_cop` acordado y vínculo a aprobación cuando aplique. Índices por orden y producto. Su salida de stock referencia esta línea una sola vez.

### Pagos, cuentas por cobrar y ventas

- **`pagos`**: `id`, `orden_id` nullable FK, `venta_id` nullable FK, `importe_cop` positivo, `tipo` (recibo/reversión), `metodo`, `referencia`, `registrado_en`, `reversa_pago_id` nullable FK a `pagos`, `motivo`. Un `CHECK` exige exactamente uno de `orden_id` o `venta_id`. Para reversión se conserva el mismo destino y `reversa_pago_id` es único, evitando revertir dos veces el mismo pago.
- Un trigger/servicio verificará que una reversión apunte a un recibo, destino y monto idénticos, y que la suma de reversiones no supere el recibo. Los pagos no se borran en la aplicación. Una corrección es reversión más un nuevo recibo correcto.
- **Importe acordado**: orden = importe inicial + adicionales aprobados; venta = suma de sus líneas vigentes. **Pagado neto** = recibos menos reversión. **Saldo** = importe acordado menos pagado neto. El saldo es una consulta, no una columna editable. Un pago no se asigna parcialmente a varias cuentas en esta versión.
- Esto separa valor vendido/acordado de efectivo recibido. El ingreso de caja se informa desde recibos netos; no se crea otra fila de ingreso por cada pago en una tabla genérica, y un gasto no reduce el saldo de clientes.
- **`cotizaciones`**: `id`, `codigo` opcional único, `cliente_id` FK, `creada_en`, `vence_en`, `estado` (borrador/enviada/aceptada/rechazada/vencida), `notas`, `total_cop` calculado desde detalles.
- **`cotizacion_detalles`**: `id`, `cotizacion_id` FK, descripción, cantidad positiva, precio unitario COP y tipo opcional. Conserva instantánea del precio cotizado.
- **`ventas`**: `id`, `codigo` único, `cliente_id` FK, `cotizacion_id` opcional FK UNIQUE, `armado_pc_id` opcional FK UNIQUE, `fecha`, `estado`, notas. La venta se crea desde la cotización aceptada copiando sus líneas; cambios posteriores no alteran el documento original.
- **`venta_detalles`**: `id`, `venta_id` FK, descripción, cantidad, precio unitario y costo unitario histórico opcional, `producto_id` nullable FK. Un armado se vende como una línea comercial (PC armada); sus piezas se detallan técnicamente en el armado para no descontarlas otra vez como líneas individuales.
- Índices: pagos por destino y fecha, venta por cliente/fecha, detalles por su padre. `CHECK` de cantidades/importes y estados permitidos.

### Armados de PC

- **`armados_pc`**: `id`, `codigo` único, `cliente_id` FK, `venta_id` opcional UNIQUE FK, estado de proceso, fechas, mano de obra COP, notas de ensamblaje, pruebas y entrega. Mantiene seguimiento técnico independiente aunque se relacione con una venta.
- **`armado_componentes`**: `id`, `armado_id` FK, `producto_id` FK, cantidad positiva, `costo_unitario_cop` y precio cobrado capturados al asignar, serie opcional, notas. Índices por armado y producto.
- Los costos capturados no se recalculan con el precio/costo actual de `productos`. Una línea técnica causa como máximo una salida de inventario, ligada por `armado_componente_id` único. La salida ocurre una vez al confirmar la entrega/consumo según el evento que se fije en implementación; recomendación: confirmar al entregar, con reserva lógica si luego se necesita evitar vender stock comprometido.

### Productos, inventario, proveedores y compras

- **`productos`**: `id`, `sku` UNIQUE, `nombre`, `descripcion`, `costo_actual_cop`, `precio_actual_cop`, `activo`, umbral de reposición opcional. Existencia no editable: se deriva de movimientos.
- **`movimientos_inventario`**: `id`, `producto_id` FK, `cantidad_delta` entero no cero, `costo_unitario_cop` histórico, `tipo` (recepción, venta, orden, armado, ajuste, reversión), `creado_en`, motivo y exactamente un origen opcional entre `compra_detalle_id`, `venta_detalle_id`, `orden_repuesto_id`, `armado_componente_id`; movimiento manual usa origen nulo y requiere motivo. Índices por producto/fecha. Índices UNIQUE parciales para cada origen impiden dos movimientos originales desde la misma línea.
- Reversar una salida crea movimiento compensatorio enlazado mediante `reversa_movimiento_id` UNIQUE; no se modifica ni elimina el original. Las restricciones y el servicio validan el sentido de la cantidad respecto del tipo/origen. Un único origen por fila evita referencias polimórficas sin integridad referencial.
- **`proveedores`**: `id`, nombre requerido, identificación fiscal opcional, teléfono, correo, notas, activo.
- **`compras`**: `id`, `proveedor_id` FK, referencia, fechas de pedido/recepción, estado y notas.
- **`compra_detalles`**: `id`, `compra_id` FK, `producto_id` FK, cantidad positiva, costo unitario COP histórico y cantidad recibida. Una recepción crea movimiento positivo por línea y no puede recibirse dos veces la misma cantidad.
- Existencia = suma de `cantidad_delta` por producto. Recepción de compra suma; venta, repuesto y componente consumido restan. Confirmar un documento y crear sus movimientos es una transacción única. Ajustes requieren motivo y usuario local/técnico si se incorpora ese dato.

### Gastos

- **`gastos`**: `id`, fecha, categoría, descripción, importe COP positivo, método y referencia/notas. Son egresos efectivos independientes de compras de inventario (una compra se representa como compra y su pago/estado, no como gasto duplicado). La política de registro de pagos a proveedores queda para precisar antes de implementar contabilidad por pagar.

## Restricciones e índices transversales

- `FOREIGN KEY` con política restrictiva para datos históricos; usar archivado/estado en vez de borrado en cascada para clientes, equipos, ventas y órdenes.
- `CHECK` para importes no negativos/positivos, cantidades válidas, estados enumerados, XOR del destino de pago y origen único del movimiento.
- `UNIQUE` en códigos visibles, SKU, serial cuando sea aplicable, reversión de pago/movimiento y vínculos 1:1.
- Índices en todas las FK consultadas, fechas de listado y estados de trabajo. Evitar índices redundantes sobre claves ya únicas.
- Activar FK por conexión (SQLite no las activa por defecto). Las migraciones comprobarán `PRAGMA foreign_key_check`.

## Secuencias de códigos

Una tabla `secuencias` (entidad, año, siguiente_ordinal; PK compuesta entidad/año) asigna equipo y orden. Dentro de `BEGIN IMMEDIATE`: obtener/incrementar secuencia y crear entidad con `EQ-2026-000001` / `OS-2026-000001`; confirmar ambas cosas o revertirlas juntas. UNIQUE en `codigo` impide colisiones. El año se toma de la fecha de creación local establecida por la aplicación, no del reloj en múltiples momentos de la transacción.

Una instalación local mantiene una única base activa. Las copias contienen también secuencias. Tras restaurar una copia antigua se comparan los ordinales existentes por año con `siguiente_ordinal` y se avanza al máximo + 1 antes de reanudar. No se editan dos copias de la misma base en paralelo ni se fusionan bases por copiar archivos; para eso se requeriría una estrategia de identidad/consolidación distinta.

## Decisiones pendientes antes del SQL

El modelo permite avanzar, pero antes del esquema definitivo deben cerrarse: convención de zona horaria; evento exacto de consumo de stock para órdenes y armados (recomendación: al confirmar entrega, o recepción/uso según proceso real); tratamiento de pagos y saldos a proveedores (no duplicarlos como gastos); y si se aceptan seriales repetidos entre tipos de equipo. Las fotos quedan fuera de esta primera estructura y se diseñarán cuando se implemente esa función.
