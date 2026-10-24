# Modelo de datos implementado

La versión 1 está implementada en `src/dragontech_manager/database/migrations/0001_initial_schema.sql`. Las claves primarias son enteros internos; los códigos visibles tienen columnas independientes. No hay datos reales cargados.

## Fechas, horas e importes

- Las marcas de tiempo se guardan como UTC en texto ISO de segundos `YYYY-MM-DDTHH:MM:SSZ`; el `CHECK` valida formato/fecha con `strftime`. La UI deberá convertirlas a `America/Bogota` al presentarlas.
- Los campos de día comercial (`fecha_venta`, fechas de compra, vencimiento, entrega y gasto) son `YYYY-MM-DD`, distintos de un instante UTC.
- Los importes y cantidades usan afinidad `INTEGER` y `CHECK(typeof(...) = 'integer')`; importes en COP no admiten fracciones. Las operaciones de negocio deben verificar que sumas y multiplicaciones no excedan el entero firmado de SQLite.

## Tablas y relaciones principales

| Área | Tablas y relaciones |
|---|---|
| Clientes/equipos | `clientes` 1:N `equipos`; nombre requerido, contacto/notas y archivado; equipo con código `EQ-AAAA-######`, tipo, marca/modelo, serial no único, especificaciones, accesorios y estado físico. |
| Servicio | `ordenes_servicio` N:1 cliente y equipo; código `OS-AAAA-######`, instante de recepción UTC, fecha de entrega comercial, diagnóstico, trabajo, estado, técnico e importe inicial. Cada visita es una fila. `servicios_adicionales` guarda descripción, importe propuesto e instante de propuesta; `decisiones_adicional` registra cada decisión aprobada/rechazada como evento inmutable con instante y evidencia. `orden_repuestos` conserva producto, cantidad, costos y precio unitario históricos. |
| Cliente/pagos | `pagos_clientes` requiere exactamente una FK entre orden o venta. Guarda recibo o reversión, valor entero, método, referencia y fecha UTC. El reverso debe coincidir con el recibo, destino e importe y solo puede registrarse una vez. |
| Cotizaciones/ventas | `cotizaciones` y `cotizacion_detalles` guardan cliente, estado, fechas, cantidades, descripción, precio y costo histórico opcional. `ventas` puede enlazar una cotización (UNIQUE) o un armado (UNIQUE); `venta_detalles` preserva descripción, cantidades, producto y valores históricos. Los detalles aceptados no se pueden reabrir/editarlos; los detalles de venta con pagos o movimientos se protegen. |
| Armados | `armados_pc` tiene cliente, estado de ensamblaje, mano de obra, pruebas, notas y fechas; se relaciona opcionalmente 1:1 con venta. `armado_componentes` conserva producto, cantidad, costo histórico, precio cobrado y serial opcional. |
| Inventario | `productos` guarda SKU único, nombre, costos/precios actuales y estado. `reservas_inventario` guarda por separado la cantidad comprometida y su origen (repuesto de orden, componente de armado o línea de venta). `movimientos_inventario` registra entradas/salidas por evento con cantidad firmada, producto, costo histórico y una referencia FK específica, o un ajuste con motivo. |
| Compras/proveedores | `proveedores` 1:N `compras`; `compra_detalles` guarda cantidad y costo histórico. `pagos_proveedores` registra pagos parciales y reversiones por separado del valor documentado de compra. |
| Gastos | `gastos` guarda egreso con fecha comercial, categoría, descripción, COP y método. Una corrección es una reversión enlazada; `v_gastos_netos` la resta sin borrar la fila original. |

Todas las relaciones históricas usan `ON DELETE RESTRICT`; no hay cascadas que borren órdenes, pagos, documentos o movimientos. Hay índices para claves foráneas y listados por estado/fecha, índices únicos para códigos/SKU/reversos y UNIQUE parciales en orígenes de movimientos.

## Pagos y saldos

- **Órdenes:** `v_saldos_ordenes.importe_acordado_cop` = importe inicial + adicionales cuya decisión más reciente sea aprobada. El importe propuesto no cuenta antes de aprobarse.
- **Ventas:** `v_saldos_ventas.importe_acordado_cop` suma cantidades por precio unitario de sus detalles.
- **Compras:** `v_saldos_compras.importe_compra_cop` suma cantidades por costo histórico.
- En las tres, el importe pagado neto se calcula desde pagos menos reversos; el saldo es importe acordado menos pago neto. No hay columnas de saldo editables ni tabla genérica de ingresos. Los ingresos de caja de clientes se cuentan desde pagos netos; compras y pagos a proveedor son conceptos distintos y los gastos son egresos operativos.
- Triggers impiden exceder el importe actual con un recibo, cambian la decisión de un adicional solo si no dejan pagos por encima del nuevo acuerdo, y bloquean cambios de detalles con pagos asociados. Los pagos son inmutables y un reverso debe ser total en esta versión.

## Inventario

- La existencia es `SUM(cantidad_delta)` y no se escribe a mano. `v_existencias` muestra existencia física, reservado y disponible.
- La reserva no crea movimiento ni descuenta existencia. El trigger exige disponibilidad al reservar; la salida física inserta un movimiento negativo, requiere una reserva coincidente, no puede exceder la existencia, consume la reserva y no admite otro movimiento para la misma línea de origen. El costo del movimiento debe coincidir con el costo histórico de su línea de origen.
- Las entradas de compra se registran al marcar la compra recibida, con una entrada positiva por detalle. Las salidas de venta, orden y armado son movimientos negativos. Los ajustes requieren motivo. Una corrección de movimiento es un movimiento compensatorio del mismo producto y magnitud; no se actualiza ni borra el original.
- Costos de documentos y movimientos son instantáneas. Cambiar el costo actual del producto no reescribe esos registros.

## Identificadores y migraciones

La tabla `secuencias` tiene clave `(entidad, anio)` y siguiente ordinal hasta 999999. `allocate_code(connection, entidad, anio)` exige transacción activa y devuelve `EQ-AAAA-######` o `OS-AAAA-######`; quien crea la fila debe usar el mismo `BEGIN IMMEDIATE` para generar el código e insertar el equipo/orden. La unicidad de los códigos queda además impuesta por SQLite. El año lo pasa el servicio usando el calendario de negocio local `America/Bogota`.

`migrate(connection)` aplica `NNNN_*.sql` en orden, registra versión/nombre/checksum SHA-256/hora UTC, revisa `integrity_check` y `foreign_key_check`, revierte DDL y versión juntos si falla y rechaza archivos editados o faltantes. No borra tablas ni ofrece downgrade. La restauración debe mantener la tabla `secuencias`, validar integridad y migrar antes de usar; no se deben editar simultáneamente dos copias restauradas.

## Límites actuales

- No hay servicios/repositorios de negocio; reglas como aceptar cotización, recibir compra, reservar, cancelar, confirmar salida física y generar códigos deben llamarse dentro de transacciones cortas por la futura capa de servicios.
- Las reservas no pueden exceder stock disponible, pero todavía no existe una rutina de servicio para hacer la reserva y confirmar su salida como una única operación coherente de interfaz.
- La recepción de inventario está modelada como una entrada por detalle al recibir la compra completa; no se implementan entregas parciales por línea.
- Las reversiones financieras son por el valor total del pago original, no parciales.
- No se implementan auditoría de cambios generales, fotos, backups, ni interfaces comerciales. Los importes se mantienen en rango entero SQLite; la futura capa de servicios debe validar posibles desbordamientos de sumas.
