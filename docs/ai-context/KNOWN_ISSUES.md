# KNOWN_ISSUES

## Abiertos (de Informe2 §7; corrección prevista en entregas 2–4)
- I1–I3: guarda de venta cancelada ineficaz; `v_saldos_ventas` ignora devoluciones/crédito.
- I4/I5/I13: idempotencia en memoria (UUID de la UI); sin idempotencia en pagos a proveedor ni movimientos.
- I9: guard de reversión de inventario no cubre procedencias nuevas (devolución).
- I10: extras de órdenes calculados en 3 sitios.
- I8/P6: venta vinculada a `armado_pc_id` sin flujo.

## Pendientes de decisión
- P1 `CSX`: naturaleza desconocida; se conserva como método legado `sin_clasificar` (solo proveedores, no aplica a clientes).
- P3 R3b reembolso en efectivo de pagos con tarjeta; P4 umbral de autorización; P5 identidad de roles.

## Notas Entrega 1
- Filas históricas de pagos/movimientos conservan `metodo_pago_id`/`fecha_negocio` NULL (inmutables); usar `v_*_contables`.
- `gastos` aún no usa el catálogo (sin servicio/UI; fuera de alcance).
- Fecha de negocio por defecto = día de Bogotá del instante de registro; los servicios aún no permiten fecha manual.
- Reversiones heredan `metodo_pago_id` del original (puede ser NULL en legado); el trigger no exige método en reversiones.
