# DECISIONS

## Aprobadas
- Fase 1 en 4 entregas (0008–0011), empezando por métodos/fecha de negocio.
- Sin reescritura histórica; columnas nuevas NULL + vistas.
- Entrega 1: método `CSX` conservado, solo proveedores, `sin_clasificar`; `Otro` incluido por uso existente en UI de ventas.
- Los servicios aceptan `method` como id de catálogo o nombre/alias; texto desconocido se rechaza (no se crean métodos implícitos).

- Entrega 2 limitada a proveedores e inventario (alcance autorizado); `solicitudes_operacion`, huella en pagos de cliente y `actores` quedan fuera y sin numerar (los números 0010/0011 se mantienen para Entregas 3/4).
- `idempotency_key` obligatorio en la API de servicio; nullable en BD por compatibilidad histórica.

## Propuestas/pendientes
Ver `KNOWN_ISSUES.md` (P1–P11 en Informe2 §12 e Informe3 §7).
