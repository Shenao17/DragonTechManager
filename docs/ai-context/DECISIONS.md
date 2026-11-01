# DECISIONS

## Aprobadas
- Fase 1 en 4 entregas (0008–0011), empezando por métodos/fecha de negocio.
- Sin reescritura histórica; columnas nuevas NULL + vistas.
- Entrega 1: método `CSX` conservado, solo proveedores, `sin_clasificar`; `Otro` incluido por uso existente en UI de ventas.
- Los servicios aceptan `method` como id de catálogo o nombre/alias; texto desconocido se rechaza (no se crean métodos implícitos).

- Entrega 2 limitada a proveedores e inventario (alcance autorizado); `solicitudes_operacion`, huella en pagos de cliente y `actores` quedan fuera y sin numerar (los números 0010/0011 se mantienen para Entregas 3/4).
- `idempotency_key` obligatorio en la API de servicio; nullable en BD por compatibilidad histórica.

- Entrega 3 = parte A del 0011 (sin dependencia de 0010); la parte B pasará a una migración posterior (Informe3 §4.7 prevé 0012 si 0008–0011 ya se aplicaron). `v_saldos_ordenes` se mantiene sin columnas de crédito hasta 0010.

- Entrega 4: la cancelación total es derivada (todas las unidades devueltas); no se guarda un tipo. R7/R11 (liquidación) se evalúan cuando existan compensaciones (Entrega 5/6), por lo que 0010 no impone C+G=D.
- Entrega 4 incluye `v_devoluciones_no_reintegradas` (depende solo de líneas) y la clasificación de reversión de pagos; los `actores` quedan para la Entrega 6.
- Autorización de valor reconocido menor: autorizador + referencia obligatorios y distintos del ejecutor (Informe2 §4.3); resto de reglas declarativas.
- Numeración provisional: Entrega 5 → 0012, Entrega 6 → 0013, parte B del 0011 → 0014; se recrean vistas/triggers con DROP/CREATE, nunca se edita una migración aplicada.

- Entrega 5 incluye la confirmación de entrega de reembolsos (eventos_compensacion) por indicación expresa; en el roadmap queda fuera de la Entrega 6. `actores`, extinciones de deuda, recuperaciones `H` y anulación automática tras reversión real siguen en la 6.
- Compensación mixta = dos compromisos (reembolso + crédito) creados atómicamente con claves derivadas `<clave>:r`/`:c` y la misma huella de la solicitud.
- Ledger con importes con signo: generación > 0, utilización < 0; saldo = suma. Crédito nace por trigger en la misma transacción (clave derivada determinista `compensacion:<id>:generacion`).
- Voucher determinista `RC-AAAA-<id>`: reintentar o reimprimir devuelve el mismo.

- Entrega 6 (aprobadas por el propietario el 2026-11-01): todas las políticas A1–A6, B1–B7, ID1–ID6, PA1–PA6 como recomendadas; parte B del 0011 = solo `v_historial_financiero_venta` + `saldo_favor_aplicado_cop` (sin historial de órdenes); recuperaciones H en tabla propia `recuperaciones_deuda_venta` (no son pagos de venta).
- Actores: identidad declarativa, límite NULL = pendiente (no ilimitado), autorizador ≠ ejecutor sin excepción; texto libre permitido solo en servicios (origen `legado`).
- F usa reembolsos ENTREGADOS (Nota): el compromiso no tiene efecto de residuo hasta la entrega.

- Pendientes de Fase 1 (aprobadas por el propietario el 2026-11-01): R13-C = **rechazar** la corrección que deje H+Q sobre la deuda (nunca anular en silencio); cancelación comercial **sin concepto nuevo** (devolución + cargo como deuda + guarda `cancellation_status` + asistente); arqueo **solo lo diseñado** (entregas efectivas y pendientes/anuladas; conteo físico solo en pantalla).
- Solicitudes de operación: se registran antes de ejecutar (transacción propia) y se completan en la transacción del negocio. Un rechazo definitivo deja la solicitud `pendiente` con el motivo en `detalle` (se puede reintentar o abandonar); abandonar retira la clave. `carga_util` y `resumen` se añadieron al diseño de Informe2 para poder reintentar tras un reinicio.
- Una entrega «no ocurrida» queda como estado `anulada` + marca `liberada` (los saldos no cambian de vista); la entrega original se conserva.

## Propuestas/pendientes
Ver `KNOWN_ISSUES.md` (P1–P11 en Informe2 §12 e Informe3 §7).
