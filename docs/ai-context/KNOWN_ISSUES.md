# KNOWN_ISSUES

## Abiertos (de Informe2 §7; corrección prevista en entregas 2–4)
- I1–I3: corregidos en Entrega 4 para devoluciones (R1/R4, `estado_cobro` derivado). `v_saldos_ventas` sigue sin crédito/compensaciones (Entrega 5).
- I4: `pagos_clientes` sin `huella_solicitud` (la comparación sigue campo a campo en servicios de venta/orden). I13: claves de pagos de cliente y ventas aún viven en memoria de la UI (sin `solicitudes_operacion` persistente). I5/Entrega 2: resuelto para pagos de proveedor y ajustes/reversiones (idempotencia); sigue pendiente el guard de estado de compra a nivel DB.
- I8/P6: venta vinculada a `armado_pc_id` sin flujo.

## Pendientes de decisión
- P1 `CSX`: naturaleza desconocida; se conserva como método legado `sin_clasificar` (solo proveedores, no aplica a clientes).
- P3 R3b reembolso en efectivo de pagos con tarjeta; P4 umbral de autorización; P5 identidad de roles.

## Notas Entrega 1
- Filas históricas de pagos/movimientos conservan `metodo_pago_id`/`fecha_negocio` NULL (inmutables); usar `v_*_contables`.
- `gastos` aún no usa el catálogo (sin servicio/UI; fuera de alcance).
- Fecha de negocio por defecto = día de Bogotá del instante de registro; los servicios aún no permiten fecha manual.
- Reversiones heredan `metodo_pago_id` del original (puede ser NULL en legado); el trigger no exige método en reversiones.

## Notas Entrega 2
- Claves/huella son NULL en filas históricas; el servicio las exige en operaciones nuevas, la BD solo garantiza unicidad y que clave y huella vayan juntas (inserciones SQL directas sin clave siguen permitidas).
- Movimientos de inventario generados por compras/ventas/órdenes no llevan clave (su idempotencia depende de su operación origen).
- API cambiada: `adjust_stock`, `reverse_movement`, `register_supplier_payment`, `reverse_supplier_payment` exigen `idempotency_key`.

## Notas Entrega 3
- Hueco de numeración: existe 0011 sin 0010. Seguro porque 0010 no depende de 0011A ni lo toca; si se añade, se aplicará tras 0011 en bases ya migradas.
- `v_saldos_ordenes` no incluye aún `saldo_favor_aplicado_cop` (requiere ledger de 0010).

## Notas Entrega 4
- (Resuelto en Entrega 5) El reembolso pendiente se salda con compensaciones.
- Cancelación comercial sin devolución (servicio prestado, deuda por valor retenido) y extinción de deuda (condonación/castigo) no existen aún (Entrega 6). Una devolución con `R<T` deja saldo pendiente cobrable como pago normal.
- Reversión de pagos de venta: se exige naturaleza/origen/evidencia, pero sin `actores` ni autorizador (declarativo hasta Entrega 6). No hay aún bloqueo por operaciones posteriores dependientes del pago (no existen compensaciones); R6/R13 llegan con la 5/6. Pagos históricos conservan estos campos NULL.
- La devolución de ventas ligadas a `armado_pc_id` (I8/P6) no tiene tratamiento especial: no hay flujo de venta de armados.
- Devoluciones de ventas históricas sin `costo_unitario_historico_cop`: el movimiento usa el costo actual del producto y la pérdida se reporta NULL (no se estima).
- Autorizador/solicitante/ejecutor son texto declarativo; se valida solo que autorizador ≠ ejecutor.

## Corregido: datos obsoletos al cambiar de producto (2026-10-31)
- **Síntoma:** al elegir otro producto en el diálogo de línea de venta o de compra, descripción y precio/costo seguían mostrando los del producto anterior; se podía guardar `product_id` de un producto con descripción/precio de otro.
- **Causa raíz:** `SaleLineDialog._suggest` y `PurchaseLineDialog._suggest_description` rellenaban solo campos *vacíos*; tras la primera selección ya no se actualizaban (y en compras el costo no tenía ninguna señal). El guardado leía los widgets sin verificar que correspondieran al producto seleccionado.
- **Corrección:** `ui/product_defaults.py` (`ProductFieldBinding`): cambiar de producto restablece siempre descripción y precio/costo al valor del nuevo producto (limpia si se elige «no inventariable»); lo editado después es manual y se respeta; `sync_for_save` reaplica los valores si la selección no coincide con el producto cuyos valores se aplicaron. Editar una línea existente conserva sus valores históricos.
- **No reproducible / no afectados:** cotizaciones (`ProposalLineDialog` no tiene selector de producto; conserva `product_id` de la línea al editar su texto, por diseño histórico) y ajustes/movimientos de inventario (el producto es fijo y se recarga con `get_product` en cada apertura). No hay validación de servicio que compare descripción/precio con el producto: la descripción es histórica y editable por diseño.
- Pruebas de regresión: `tests/test_product_selection_ui.py` (11). 8 fallaban antes de la corrección.

## Notas Entrega 5
- Identidad: ejecutor, autorizador y quien registra son texto declarativo (se valida solo que autorizador ≠ ejecutor/registrante); la tabla `actores` llega en la Entrega 6.
- Reversión financiera real de un pago con reembolsos ya entregados (`exceso_reembolsado_cop > 0`): se registra siempre y bloquea nuevas entregas y compensaciones, pero **no** anula automáticamente los compromisos pendientes ni reconoce/cobra la deuda (N0, F, H): Entrega 6. El operador puede anular el compromiso manualmente con autorizador.
- La corrección de registro erróneo se rechaza si deja `C > P` o `C + G > D` (R6); el bloqueo por crédito ya usado o deuda condonada llega con la 6.
- Eventos `corregida` existen en la tabla pero no hay servicio/UI; los `ajuste` del ledger están bloqueados por trigger. Uso de saldo a favor en órdenes: no habilitado (Fase 2).
- Regla de oro estricta: no se crea un reembolso nuevo mientras otro de la misma venta esté `preparada` o `en_investigacion` (sin excepción autorizada todavía).
- `compensaciones_cancelacion.cancelacion_id` es opcional: la compensación se calcula a nivel de venta (R2/R3 usan toda la posición), no por devolución individual.
- Vouchers deterministas `RC-AAAA-######`; la reimpresión física no existe aún (no hay impresión).
- No hay panel automático de «entregas pendientes de confirmar» al iniciar: se consulta con `v_compensaciones_pendientes` / `CompensationService.pending_deliveries()` y el diálogo «Reembolsos y crédito» de cada venta.

## Notas Entrega 6
- **Identidad declarativa** (ID6): el directorio no autentica; cualquiera puede elegir cualquier actor. La UI lo advierte. Los servicios aún aceptan texto libre (origen `legado`) por compatibilidad programática; la UI solo usa el directorio y pide registrar actores si está vacío.
- Límite de autorización `NULL` = pendiente: el actor no puede autorizar importes hasta que el propietario lo fije (ID2/ID3). No hay excepción para una sola persona: autorizador y ejecutor deben ser distintos.
- Filas anteriores a la 0013 conservan su texto con `origen_identidad` NULL (se muestra como `legado`); no se reescriben.
- Reversión financiera real: anula solo compromisos **sin preparar** (más recientes primero, hasta que quepan en P). Los `preparada`/`en_investigacion` nunca se auto-anulan (Informe3 §2.5 prevalece sobre Nota §2.6 para ese caso) y quedan bloqueados para entrega por R3; se ven en `compromisos_sin_respaldo_cop`.
- H solo cubre la deuda que no cabe en un pago normal de la venta (Nota §5.4); el resto se cobra como pago de venta. PA2 (comisiones del banco) no se modela.
- `saldo_favor_aplicado_cop` en `v_saldos_ordenes` vale 0: el uso de saldo a favor en órdenes sigue deshabilitado (Fase 2); el trigger de pago de orden no suma `U`.
- Contabilidad de condonación/castigo (A3/A4/PA4): se registran como hechos separados no-caja; su tratamiento contable lo define el contador, no el código.

## Pendientes de cierre de la Fase 1 (actualizado tras los pendientes P1-P3)
Resueltos: panel de entregas pendientes, reversión de reembolsos entregados y evento `corregida`, cancelación comercial (guarda + asistente), arqueo y entregas del día, `solicitudes_operacion`, huella en pagos de cliente.
Siguen abiertos:
1. Validación visual del propietario de los bloques P1-P2 y de las pantallas nuevas (Pendientes, Arqueo de caja, Cancelar venta…, correcciones de entrega).
2. Solicitudes persistentes aún NO integradas en: pagos y reversiones de proveedor, ajustes y reversiones de inventario, creación de ventas y reversión de pagos de cliente (conservan su idempotencia por tabla de las entregas 2-5).
3. Los pagos de venta/orden no registran quién los solicitó (`solicitado_por` = «No indicado»): no hay selector de actor en esos diálogos.
4. Criterios §3.8 #12-#16: dependen de autenticación (ID5, fase posterior).
5. Arqueo: no es una foto histórica (pendiente/anulado se evalúan hoy) y no guarda conteos físicos (decisión del propietario).
6. R13-C: no existe la alternativa «anular parcialmente la extinción» en la misma operación (se rechaza y se anula antes por el flujo existente).

## Notas de los pendientes P1-P3
- Una investigación abierta sobre una entrega ya registrada no cambia los saldos (sigue contando como entregada) pero bloquea nuevos reembolsos de la venta.
- Reintentar una solicitud pendiente reejecuta el servicio con la carga guardada y la MISMA clave; si la operación ya existía, devuelve el registro original.
- Solicitudes `pendiente` con detalle «Rechazada: …» son rechazos definitivos con rollback completo; el panel las lista para reintentar o abandonar.
