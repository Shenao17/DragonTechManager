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
- Un reembolso pendiente (`estado_cobro='reembolso_pendiente'`) no se puede saldar todavía: compensaciones y saldo a favor son la Entrega 5. Hoy solo se ve el sobrepago.
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
