# Modelo de datos implementado

Las migraciones `0001` y `0002` forman el esquema comercial inicial; `0003_service_order_status_history.sql` añade el historial inmutable de órdenes, `0004_service_order_test_results.sql` agrega pruebas técnicas, `0005_customer_proposals.sql` agrega condiciones e historial de propuestas, `0006_inventory_procurement.sql` agrega datos de catálogo/proveedor y protecciones de inventario, y `0007_sales_and_payments.sql` agrega idempotencia de ventas/pagos y restricciones de conversión de propuestas. Las migraciones nuevas no borran ni recrean datos. Las claves primarias son enteros internos; los códigos visibles tienen columnas independientes.

## Fechas, horas e importes

- Las marcas de tiempo se guardan como UTC en texto ISO de segundos `YYYY-MM-DDTHH:MM:SSZ`; el `CHECK` valida formato/fecha con `strftime`. La UI las convierte a `America/Bogota` al presentarlas.
- Los campos de día comercial (`fecha_venta`, fechas de compra, vencimiento, entrega y gasto) son `YYYY-MM-DD`, distintos de un instante UTC.
- Los importes y cantidades usan afinidad `INTEGER` y `CHECK(typeof(...) = 'integer')`; importes en COP no admiten fracciones. Las operaciones de negocio deben verificar que sumas y multiplicaciones no excedan el entero firmado de SQLite.

## Tablas y relaciones principales

| Área | Tablas y relaciones |
|---|---|
| Clientes/equipos | `clientes` 1:N `equipos`; nombre requerido, contacto/notas y archivado; equipo con código `EQ-AAAA-######`, tipo, marca/modelo, serial no único, especificaciones, accesorios y estado físico. |
| Servicio | `ordenes_servicio` N:1 cliente y equipo; código `OS-AAAA-######`, instante de recepción UTC, fecha de entrega comercial, diagnóstico, trabajo, pruebas técnicas, estado, técnico e importe inicial. Cada visita es una fila. `historial_estados_orden` conserva estado anterior/nuevo, instante UTC y motivo, con actualización/borrado bloqueados. `servicios_adicionales` guarda descripción, importe propuesto e instante de propuesta; `decisiones_adicional` conserva eventos inmutables de decisión con instante UTC y nota/evidencia ingresada por el usuario. `orden_repuestos` conserva producto, cantidad, costos y precio unitario históricos. |
| Cliente/pagos | `pagos_clientes` requiere exactamente una FK entre orden o venta. Guarda recibo o reversión, valor entero, método, referencia y fecha UTC. El reverso debe coincidir con el recibo, destino e importe y solo puede registrarse una vez. |
| Propuestas/cotizaciones | `cotizaciones` y `cotizacion_detalles` guardan cliente, código `COT-` más identificador aleatorio, estado, vencimiento, observaciones, condiciones y conceptos históricos. `historial_cotizaciones` es inmutable. Una venta puede enlazar una cotización (UNIQUE) o un armado (UNIQUE); `venta_detalles.cotizacion_detalle_id` enlaza una única línea a su origen para preservar texto, cantidad, precio y producto aceptados. |
| Ventas | `ventas` guarda código único, cliente, fecha comercial, nota opcional, estado persistido y clave de idempotencia opcional UNIQUE. `venta_detalles` guarda descripción, cantidad, precio COP, costo histórico, producto opcional y, para conversiones, línea de cotización origen. Cada venta creada por servicio es confirmada inmediatamente; las líneas y cabecera son inmutables. |
| Armados | `armados_pc` tiene cliente, estado de ensamblaje, mano de obra, pruebas, notas y fechas; se relaciona opcionalmente 1:1 con venta. `armado_componentes` conserva producto, cantidad, costo histórico, precio cobrado y serial opcional. |
| Inventario | `productos` guarda SKU único, nombre, descripción, categoría, costos/precios actuales, umbral de reposición opcional y estado activo. `reservas_inventario` guarda por separado la cantidad comprometida y su origen (repuesto de orden, componente de armado o línea de venta). `movimientos_inventario` registra entradas/salidas por evento con cantidad firmada, producto, costo histórico y referencia FK específica, o un ajuste/reversión con motivo. `v_existencias` deriva existencia física, reservas y disponibilidad; el stock no se edita en el producto. |
| Compras/proveedores | `proveedores` 1:N `compras`; contiene nombre, identificación fiscal, teléfono, correo, dirección, notas y estado activo. `compra_detalles` guarda producto, cantidad, costo histórico y `descripcion_historica`. `pagos_proveedores` registra pagos parciales y reversiones por separado del valor documentado de compra; `v_saldos_compras` deriva total, pagado neto y saldo. |
| Gastos | `gastos` guarda egreso con fecha comercial, categoría, descripción, COP y método. Una corrección es una reversión enlazada; `v_gastos_netos` la resta sin borrar la fila original. |

Todas las relaciones históricas usan `ON DELETE RESTRICT`; no hay cascadas que borren órdenes, pagos, documentos o movimientos. Hay índices para claves foráneas y listados por estado/fecha, índices únicos para códigos/SKU/reversos y UNIQUE parciales en orígenes de movimientos.

## Pagos y saldos

- **Órdenes:** `v_saldos_ordenes.importe_acordado_cop` = importe inicial + adicionales cuya decisión más reciente sea aprobada. El importe propuesto no cuenta antes de aprobarse.
- **Ventas:** `v_saldos_ventas.importe_acordado_cop` suma cantidades por precio unitario de sus detalles; la vista deriva también `estado_cobro` (`abierta`, `parcial`, `completada` o `cancelada`).
- **Compras:** `v_saldos_compras.importe_compra_cop` suma cantidades por costo histórico.
- En las tres, el importe pagado neto se calcula desde pagos menos reversos; el saldo es importe acordado menos pago neto. No hay columnas de saldo editables ni tabla genérica de ingresos. Los ingresos de caja de clientes se cuentan desde pagos netos; compras y pagos a proveedor son conceptos distintos y los gastos son egresos operativos.
- Triggers impiden exceder el importe actual con un recibo, cambian la decisión de un adicional solo si no dejan pagos por encima del nuevo acuerdo, y bloquean cambios de detalles con pagos asociados. Los pagos son inmutables y un reverso debe ser total en esta versión.
- Las claves idempotentes guardadas en `ventas` y `pagos_clientes` permiten reintentar la misma solicitud sin crear un segundo registro; reutilizar la clave con datos distintos se rechaza. Para ello, el llamador conserva y reutiliza la misma clave durante el reintento.

## Inventario

- La existencia es `SUM(cantidad_delta)` y no se escribe a mano. `v_existencias` muestra existencia física, reservado y disponible.
- La reserva no crea movimiento ni descuenta existencia. El trigger exige disponibilidad al reservar; la salida física inserta un movimiento negativo, requiere una reserva coincidente, no puede exceder la existencia, consume la reserva y no admite otro movimiento para la misma línea de origen. El costo del movimiento debe coincidir con el costo histórico de su línea de origen.
- La migración `0002` impide que una reversión negativa reduzca la existencia por debajo de cero. Si una entrada errónea ya se consumió, primero debe corregirse la salida correspondiente; la reversión insegura se rechaza.
- Las entradas de compra se registran al marcar la compra recibida, con una entrada positiva por detalle. Las salidas de venta, orden y armado son movimientos negativos. Todo movimiento nuevo requiere motivo no vacío. Los ajustes y reversos no pueden reducir el stock por debajo de las reservas activas. Una corrección de movimiento es un movimiento compensatorio del mismo producto y magnitud; no se actualiza ni borra el original.
- Costos de documentos y movimientos son instantáneas. Cambiar el costo actual del producto no reescribe esos registros.
- Una venta directa o conversión confirmada crea una reserva por línea de producto y la salida física dentro de una sola transacción; los triggers existentes consumen la reserva y prohíben movimientos duplicados por línea. Aceptar una propuesta no modifica stock; convertirla sí confirma la venta y consume existencias si sus conceptos tienen `producto_id`.

## Identificadores y migraciones

La tabla `secuencias` tiene clave `(entidad, anio)` y siguiente ordinal hasta 999999. `allocate_code(connection, entidad, anio)` exige transacción activa y devuelve `EQ-AAAA-######` o `OS-AAAA-######`; quien crea la fila debe usar el mismo `BEGIN IMMEDIATE` para generar el código e insertar el equipo/orden. La unicidad de los códigos queda además impuesta por SQLite. El año lo pasa el servicio usando el calendario de negocio local `America/Bogota`.

`migrate(connection)` aplica `NNNN_*.sql` en orden, registra versión/nombre/checksum SHA-256/hora UTC, revisa `integrity_check` y `foreign_key_check`, revierte DDL y versión juntos si falla y rechaza archivos editados o faltantes. No borra tablas ni ofrece downgrade. La restauración debe mantener la tabla `secuencias`, validar integridad y migrar antes de usar; no se deben editar simultáneamente dos copias restauradas.

La migración `0003` agrega `historial_estados_orden` y crea un evento de punto de partida por cada orden preexistente: el estado vigente, con estado anterior nulo y una nota explícita de que las transiciones previas no se conocen. No inventa fechas anteriores ni modifica órdenes. El migrador no ofrece downgrade automático; esta migración no tiene un script de reversión porque borrar el historial después de usarlo destruiría trazabilidad.

## Servicios y errores actuales

`CustomerService` crea, obtiene, busca y actualiza clientes. `EquipmentService` registra, consulta, busca y actualiza equipos, y devuelve su historial de órdenes. `ServiceOrderService` abre órdenes, consulta el detalle, actualiza diagnóstico/trabajo/técnico y aplica transiciones válidas. El `cliente_id` de una orden conserva al solicitante en esa visita y puede diferir del cliente propietario actual del equipo. Los resultados de repositorio y servicio son diccionarios con las columnas de SQLite.

`ProposalService` crea propuestas con al menos un concepto, consulta detalle/listados paginados, filtra por estado y busca código/cliente. Valida fechas comerciales, cantidades y precios enteros COP, y detecta desbordamiento de los totales antes de guardar. El código visible `COT-XXXXXXXXXXXX` usa UUID aleatorio y queda protegido además por UNIQUE; no consume la secuencia reservada a equipos/órdenes. La creación, edición de borrador (reemplazo atómico de líneas) y eventos de historial usan transacciones.

`InventoryService` crea, consulta, busca, filtra y edita productos y proveedores; el SKU se normaliza a mayúsculas y es UNIQUE. La identificación fiscal de proveedor se valida por servicio dentro de transacción porque el esquema preexistente no le asigna una restricción UNIQUE. Los productos no se borran: se inactivan. Los ajustes llevan cantidad con signo, costo histórico y motivo; los reversos de movimientos son compensatorios, únicos y solo se admiten si no hacen negativo el stock ni rebajan unidades comprometidas.

`ProcurementService` crea y edita compras en borrador con varias líneas y snapshots de descripción, cantidad y costo unitario. Los estados usados son los existentes en SQLite: `borrador`, `pendiente`, `recibida` y `cancelada`. El flujo válido es borrador→pendiente/cancelada y pendiente→recibida/cancelada; recibir guarda fecha comercial y movimientos de entrada por detalle en la misma transacción. Los índices existentes impiden movimientos de compra duplicados por línea y un trigger de la migración `0006` mantiene inmutables compras recibidas. Las líneas antiguas con descripción histórica vacía no pueden reconstruir el nombre original; la UI lo marca como snapshot previo no disponible.

`SalesService` lista y busca ventas con total/pagos/saldo derivados, crea ventas directas con conceptos inventariables o no inventariables y convierte solo propuestas aceptadas. La conversión se ata a la línea original con FK UNIQUE, copia descripción/cantidad/precio y mantiene al cliente; una restricción del esquema evita convertir propuestas sin venta completa. Los productos inventariables se validan contra stock disponible bajo `BEGIN IMMEDIATE`, luego se reservan y descuentan por movimiento en la misma transacción. La clave de idempotencia y huella de solicitud hacen repetible el reintento exacto sin crear otra venta.

Los pagos de venta usan `pagos_clientes` existente y `v_saldos_ventas`: recibos positivos, reversos completos e inmutables; nunca se guarda una columna de saldo. El servicio rechaza importe no positivo, pago superior al saldo y pago repetido incompatible con su clave idempotente. La vista deriva el estado de cobro desde el importe total y pago neto. Los pagos de órdenes siguen en la misma tabla relacional, pero esta interfaz no ofrece aún el caso de uso de cobro de orden y nunca crea una venta para cobrarla.

Los pagos a proveedor se registran solo en compras confirmadas o recibidas, se limitan al saldo y permanecen en `pagos_proveedores`. El saldo viene de la vista `v_saldos_compras`, no se edita. Se permiten pagos parciales, el pago completo y una reversión completa trazable por cada pago original; una compra con historial de pago no se edita. No se crean gastos generales ni cobros de clientes a partir de estas operaciones.

Los estados almacenados en `cotizaciones` son `borrador`, `enviada`, `aceptada`, `rechazada`, `vencida`, `convertida` y `cancelada`. Los casos de uso implementan `borrador → enviada/cancelada` y `enviada → aceptada/rechazada/vencida/cancelada`. `vencida` solo se permite si la fecha de vigencia ya pasó en calendario `America/Bogota`. Los estados finales no pueden reabrirse por el servicio. Solo borradores se editan. `convertida` está reservado para un flujo futuro de ventas y no se establece actualmente. No se automatizan vencimientos.

Los servicios validan texto, IDs, paginación, estado e importes enteros dentro del rango de SQLite. Los códigos y sus filas se guardan juntos con `BEGIN IMMEDIATE`; si la inserción falla, tanto el registro como el ordinal se revierten. Los errores esperados se presentan como `ValidationError`, `NotFoundError`, `ConflictError` o `DataIntegrityError`.

### Estados de órdenes

Los estados almacenados son `recibida`, `diagnostico`, `espera_aprobacion`, `en_proceso`, `lista`, `entregada` y `cancelada`. `recibida → diagnostico` permite iniciar la evaluación; para pasar a reparación se exige diagnóstico. Si hay adicionales pendientes, solo se permite `diagnostico → espera_aprobacion`; después de decidir todos, se permite `espera_aprobacion → en_proceso`. Para `en_proceso → lista` se exige trabajo realizado y resultados de pruebas. No se habilitan cancelación, reapertura ni transiciones de retroceso. El servicio valida y registra la transición en una transacción con el evento de `historial_estados_orden`. Para `entregada` asigna `fecha_entrega` usando el día local de Bogotá y conserva el instante UTC en el historial.

El flujo de adicionales reutiliza `servicios_adicionales` y `decisiones_adicional`. Las propuestas solo se registran durante diagnóstico/espera de aprobación, una vez guardado el diagnóstico, con precio positivo. Cada propuesta no decidida puede recibir una única decisión a través del servicio; una repetición se rechaza. La decisión guarda UTC y una nota ingresada por el operador sobre lo comunicado por el cliente; esa nota no autentica su identidad. No se editan ni borran propuestas con decisión. La vista de saldos suma cada línea únicamente cuando su decisión vigente es aprobada; las pendientes y rechazadas no afectan el importe acordado. Al aprobar una línea, su importe se incorpora una sola vez.

Una propuesta aprobada no puede revalorizarse. Registrar otra propuesta exige una nueva decisión, y la nueva línea se interpreta como un cargo adicional distinto. El esquema no modela reemplazar/corregir el precio de una línea ya aprobada ni recalcular pagos ante esa sustitución; esa operación queda pendiente de una regla comercial explícita. El servicio no admite una segunda decisión sobre la misma propuesta; la corrección de una decisión ya registrada tampoco tiene aún un flujo definido.

El campo `pruebas_realizadas` se agregó en `0004` de forma aditiva con `DEFAULT ''`, preservando órdenes existentes. Los resultados deben guardarse separados de `trabajo_realizado` y ambos son obligatorios para marcar lista. La entrega actual registra estado, fecha comercial y evento UTC. No hay una política definida de saldo mínimo para entregar, ni campos de receptor/firma; por ello la transición no exige pago total ni afirma una firma o identidad verificada. La nota opcional de entrega puede documentar el evento sin sustituir un comprobante formal.

La entidad de orden guarda su solicitante/equipo mediante claves foráneas, pero no conserva snapshots históricos de nombre de cliente ni de marca/modelo del equipo. Editar los datos maestros no reescribe `ordenes_servicio` ni cambia sus claves; las etiquetas consultadas mediante joins muestran los datos maestros actuales. Para conservar valores exactos “como se recibieron” se requeriría una futura extensión con snapshots/cambios versionados. Los eventos de estado históricos previos a `0003` no se pueden reconstruir: la migración solo anota el estado vigente al activar el historial.

## Auditoría funcional y límites

| Función | Estado | Alcance verificado / falta |
|---|---|---|
| Clientes | Parcial | Crear, buscar, listar y editar por servicio/UI. No hay archivado UI, historial de cambios ni auditoría general. |
| Equipos | Parcial | Registrar, buscar, listar, editar y consultar órdenes relacionadas. El código no cambia; propietarios/atributos previos no tienen snapshots versionados. |
| Órdenes, diagnóstico, trabajo, pruebas y entrega | Parcial | Alta, listado, detalle, edición técnica, diagnóstico/trabajo/pruebas, transiciones e historial. Entrega registra fecha y evento; saldo total, receptor/firma y comprobante formal no tienen regla/campos definidos. Fotografías y edición de repuestos pendientes. |
| Servicios adicionales/aprobaciones | Parcial | Propuestas, aprobación/rechazo, evidencia ingresada, UTC e historial usan las tablas existentes. Cada propuesta recibe una decisión por servicio; las pendientes bloquean avance y no afectan el importe acordado. Revisión/sustitución de una propuesta aprobada no está modelada. |
| Anticipos, pagos parciales, saldos y reversos | Parcial | Ventas: UI/servicio de pagos, saldo derivado, sobrepago bloqueado y reverso completo trazable. Órdenes: esquema y triggers existentes, sin UI/servicio de cobro. |
| Propuestas a clientes | Parcial | Listado, búsqueda/filtro, borradores, líneas, total, detalle, estados e historial; las aceptadas se convierten atómicamente en venta. No hay exportación/envío externo. |
| Ventas y pagos | Parcial | Venta directa, búsqueda/listado/detalle, conversión de propuesta, cobros parciales/completos y reversos implementados. Faltan ventas desde armados, devoluciones/cancelación y comprobantes/exportación. |
| Inventario, movimientos y reservas | Parcial | Productos, búsqueda/filtros, edición, alertas, historial, ajustes/reversos y salidas de venta confirmadas. Entradas por compras son transaccionales; salidas de órdenes/armados esperan sus flujos de confirmación. No hay conteos cíclicos ni importación masiva. |
| Proveedores, compras y pagos | Parcial | CRUD/inactivación de proveedores, historial relacionado, compras multínea, borrador/pendiente/recibida/cancelada, snapshot, recepción y pagos parciales/reversos están implementados. Sin órdenes de compra externas, recepción parcial, comprobantes, reportes ni contabilidad/fiscalidad. |
| Armado de PC y costos históricos | Parcial | Esquema y snapshots de componentes/costos; seguimiento UI/servicios/ventas pendientes. |
| Dashboard e informes | Parcial | Dashboard muestra conteos reales de pendientes/en proceso/listas, hasta ocho órdenes recientes con cliente/equipo/fecha/estado y acceso a detalle; las acciones rápidas abren formularios reales. Informes financieros/comerciales exportables pendientes. |
| Copias de seguridad/restauración | Pendiente | Precauciones documentadas; rutina de respaldo y recuperación no implementada. |
| Configuración/tema e información | Parcial | Selector claro/oscuro persistente con `QSettings`, información de versión y runtime. Más opciones de configuración pendientes. |
| Actualizaciones | Parcial | Checker de metadatos listo para canal HTTPS, timeout y ejecución en worker. Sin remoto/canal configurado; no descarga ni instala, y no verifica criptográficamente firmas. |
| Distribución | Pendiente | Sin empaquetado ni instalador. |

Las reversiones financieras actualmente son por el valor total del pago original, no parciales. Los importes se mantienen en rango entero SQLite; los futuros servicios financieros deben validar desbordamientos de sumas.
