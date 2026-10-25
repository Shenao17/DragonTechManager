# Modelo de datos implementado

Las migraciones `0001` y `0002` forman el esquema comercial inicial; `0003_service_order_status_history.sql` añade el historial inmutable de estados. Las claves primarias son enteros internos; los códigos visibles tienen columnas independientes. La migración nueva no borra ni recrea datos. No hay datos reales cargados en el repositorio.

## Fechas, horas e importes

- Las marcas de tiempo se guardan como UTC en texto ISO de segundos `YYYY-MM-DDTHH:MM:SSZ`; el `CHECK` valida formato/fecha con `strftime`. La UI las convierte a `America/Bogota` al presentarlas.
- Los campos de día comercial (`fecha_venta`, fechas de compra, vencimiento, entrega y gasto) son `YYYY-MM-DD`, distintos de un instante UTC.
- Los importes y cantidades usan afinidad `INTEGER` y `CHECK(typeof(...) = 'integer')`; importes en COP no admiten fracciones. Las operaciones de negocio deben verificar que sumas y multiplicaciones no excedan el entero firmado de SQLite.

## Tablas y relaciones principales

| Área | Tablas y relaciones |
|---|---|
| Clientes/equipos | `clientes` 1:N `equipos`; nombre requerido, contacto/notas y archivado; equipo con código `EQ-AAAA-######`, tipo, marca/modelo, serial no único, especificaciones, accesorios y estado físico. |
| Servicio | `ordenes_servicio` N:1 cliente y equipo; código `OS-AAAA-######`, instante de recepción UTC, fecha de entrega comercial, diagnóstico, trabajo, estado, técnico e importe inicial. Cada visita es una fila. `historial_estados_orden` conserva estado anterior/nuevo, instante UTC y motivo, con actualización/borrado bloqueados. `servicios_adicionales` guarda descripción, importe propuesto e instante de propuesta; `decisiones_adicional` registra cada decisión aprobada/rechazada como evento inmutable con instante y evidencia. `orden_repuestos` conserva producto, cantidad, costos y precio unitario históricos. |
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
- La migración `0002` impide que una reversión negativa reduzca la existencia por debajo de cero. Si una entrada errónea ya se consumió, primero debe corregirse la salida correspondiente; la reversión insegura se rechaza.
- Las entradas de compra se registran al marcar la compra recibida, con una entrada positiva por detalle. Las salidas de venta, orden y armado son movimientos negativos. Los ajustes requieren motivo. Una corrección de movimiento es un movimiento compensatorio del mismo producto y magnitud; no se actualiza ni borra el original.
- Costos de documentos y movimientos son instantáneas. Cambiar el costo actual del producto no reescribe esos registros.

## Identificadores y migraciones

La tabla `secuencias` tiene clave `(entidad, anio)` y siguiente ordinal hasta 999999. `allocate_code(connection, entidad, anio)` exige transacción activa y devuelve `EQ-AAAA-######` o `OS-AAAA-######`; quien crea la fila debe usar el mismo `BEGIN IMMEDIATE` para generar el código e insertar el equipo/orden. La unicidad de los códigos queda además impuesta por SQLite. El año lo pasa el servicio usando el calendario de negocio local `America/Bogota`.

`migrate(connection)` aplica `NNNN_*.sql` en orden, registra versión/nombre/checksum SHA-256/hora UTC, revisa `integrity_check` y `foreign_key_check`, revierte DDL y versión juntos si falla y rechaza archivos editados o faltantes. No borra tablas ni ofrece downgrade. La restauración debe mantener la tabla `secuencias`, validar integridad y migrar antes de usar; no se deben editar simultáneamente dos copias restauradas.

La migración `0003` agrega `historial_estados_orden` y crea un evento de punto de partida por cada orden preexistente: el estado vigente, con estado anterior nulo y una nota explícita de que las transiciones previas no se conocen. No inventa fechas anteriores ni modifica órdenes. El migrador no ofrece downgrade automático; esta migración no tiene un script de reversión porque borrar el historial después de usarlo destruiría trazabilidad.

## Servicios y errores actuales

`CustomerService` crea, obtiene, busca y actualiza clientes. `EquipmentService` registra, consulta, busca y actualiza equipos, y devuelve su historial de órdenes. `ServiceOrderService` abre órdenes, consulta el detalle, actualiza diagnóstico/trabajo/técnico y aplica transiciones válidas. El `cliente_id` de una orden conserva al solicitante en esa visita y puede diferir del cliente propietario actual del equipo. Los resultados de repositorio y servicio son diccionarios con las columnas de SQLite.

Los servicios validan texto, IDs, paginación, estado e importes enteros dentro del rango de SQLite. Los códigos y sus filas se guardan juntos con `BEGIN IMMEDIATE`; si la inserción falla, tanto el registro como el ordinal se revierten. Los errores esperados se presentan como `ValidationError`, `NotFoundError`, `ConflictError` o `DataIntegrityError`.

### Estados de órdenes

Los estados almacenados son `recibida`, `diagnostico`, `espera_aprobacion`, `en_proceso`, `lista`, `entregada` y `cancelada`. La ruta normal de la primera etapa es `recibida → diagnostico → en_proceso → lista → entregada`; `diagnostico → espera_aprobacion → en_proceso` se usa cuando hay servicios adicionales sin decisión. No se habilitan cancelación, reapertura ni transiciones de retroceso. El servicio verifica la ruta bajo transacción `BEGIN IMMEDIATE`, y registra el cambio en `historial_estados_orden` en la misma transacción. Para marcar `lista` exige que exista trabajo realizado; los datos técnicos pueden guardarse junto con la transición y se revierten si esta falla. Para `entregada` asigna `fecha_entrega` usando el día local de Bogotá y conserva la marca de modificación UTC.

La entidad de orden guarda su solicitante/equipo mediante claves foráneas, pero no conserva snapshots históricos de nombre de cliente ni de marca/modelo del equipo. Editar los datos maestros no reescribe `ordenes_servicio` ni cambia sus claves; las etiquetas consultadas mediante joins muestran los datos maestros actuales. Para conservar valores exactos “como se recibieron” se requeriría una futura extensión con snapshots/cambios versionados. Los eventos de estado históricos previos a `0003` no se pueden reconstruir: la migración solo anota el estado vigente al activar el historial.

## Auditoría funcional y límites

| Función | Estado | Alcance verificado / falta |
|---|---|---|
| Clientes | Parcial | Crear, buscar, listar y editar por servicio/UI. No hay archivado UI, historial de cambios ni auditoría general. |
| Equipos | Parcial | Registrar, buscar, listar, editar y consultar órdenes relacionadas. El código no cambia; propietarios/atributos previos no tienen snapshots versionados. |
| Órdenes, diagnóstico, trabajo y entrega | Parcial | Alta, listado, filtro por estado, detalle, edición técnica, ruta validada e historial. La fecha de entrega se registra en la transición. Fotografías y edición de repuestos siguen pendientes. |
| Servicios adicionales/aprobaciones | Parcial | Tablas, eventos y restricciones de datos existen. No hay todavía pantallas/servicios para proponer/aprobar/rechazar; las órdenes en espera no avanzan hasta que esas decisiones existan. |
| Anticipos, pagos parciales, saldos y reversos | Parcial | Tablas, vistas y triggers de integridad implementados. No hay UI ni servicios de cobro/reversión. |
| Cotizaciones y ventas | Parcial | Esquema y cálculos de saldo implementados. Casos de uso e interfaz pendientes. |
| Inventario, movimientos y reservas | Parcial | Esquema, vistas y protecciones SQL implementados. No hay flujo de usuario/servicios de reserva, recepción o salida. |
| Proveedores, compras y pagos | Parcial | Esquema con pagos parciales y saldos, sin servicios/UI. Recepción modelada para compra completa, sin entregas parciales por línea. |
| Armado de PC y costos históricos | Parcial | Esquema y snapshots de componentes/costos; seguimiento UI/servicios/ventas pendientes. |
| Dashboard e informes | Parcial | Dashboard muestra conteos reales de pendientes/en proceso/listas, hasta ocho órdenes recientes con cliente/equipo/fecha/estado y acceso a detalle; las acciones rápidas abren formularios reales. Informes financieros/comerciales exportables pendientes. |
| Copias de seguridad/restauración | Pendiente | Precauciones documentadas; rutina de respaldo y recuperación no implementada. |
| Configuración/tema e información | Parcial | Selector claro/oscuro persistente con `QSettings`, información de versión y runtime. Más opciones de configuración pendientes. |
| Actualizaciones | Parcial | Checker de metadatos listo para canal HTTPS, timeout y ejecución en worker. Sin remoto/canal configurado; no descarga ni instala, y no verifica criptográficamente firmas. |
| Distribución | Pendiente | Sin empaquetado ni instalador. |

Las reversiones financieras actualmente son por el valor total del pago original, no parciales. Los importes se mantienen en rango entero SQLite; los futuros servicios financieros deben validar desbordamientos de sumas.
