-- Idempotencia de ventas y pagos: las claves las genera el cliente de la operación
-- y permiten devolver el resultado original cuando se reintenta la misma solicitud.
ALTER TABLE ventas ADD COLUMN clave_idempotencia TEXT;
ALTER TABLE ventas ADD COLUMN huella_solicitud TEXT;
CREATE UNIQUE INDEX uq_ventas_clave_idempotencia
    ON ventas(clave_idempotencia) WHERE clave_idempotencia IS NOT NULL;

ALTER TABLE pagos_clientes ADD COLUMN clave_idempotencia TEXT;
CREATE UNIQUE INDEX uq_pagos_clientes_clave_idempotencia
    ON pagos_clientes(clave_idempotencia) WHERE clave_idempotencia IS NOT NULL;

DROP VIEW v_saldos_ventas;
CREATE VIEW v_saldos_ventas AS
SELECT v.id AS venta_id,
       COALESCE((SELECT SUM(d.cantidad * d.precio_unitario_cop)
                 FROM venta_detalles d WHERE d.venta_id = v.id), 0) AS importe_acordado_cop,
       COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                 FROM pagos_clientes p WHERE p.venta_id = v.id), 0) AS pagado_neto_cop,
       COALESCE((SELECT SUM(d.cantidad * d.precio_unitario_cop)
                 FROM venta_detalles d WHERE d.venta_id = v.id), 0)
       - COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                   FROM pagos_clientes p WHERE p.venta_id = v.id), 0) AS saldo_pendiente_cop,
       CASE WHEN v.estado = 'cancelada' THEN 'cancelada'
            WHEN COALESCE((SELECT SUM(d.cantidad * d.precio_unitario_cop)
                           FROM venta_detalles d WHERE d.venta_id = v.id), 0)
                 - COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                             FROM pagos_clientes p WHERE p.venta_id = v.id), 0) = 0
                THEN 'completada'
            WHEN COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                           FROM pagos_clientes p WHERE p.venta_id = v.id), 0) > 0
                THEN 'parcial'
            ELSE 'abierta' END AS estado_cobro
FROM ventas v;

-- Vincula cada línea convertida a su concepto de propuesta para verificar
-- snapshots y evitar conceptos omitidos o duplicados.
ALTER TABLE venta_detalles ADD COLUMN cotizacion_detalle_id INTEGER
    REFERENCES cotizacion_detalles(id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX uq_venta_detalle_cotizacion_linea
    ON venta_detalles(cotizacion_detalle_id) WHERE cotizacion_detalle_id IS NOT NULL;

DROP TRIGGER cotizacion_aceptada_no_reabrir;
CREATE TRIGGER cotizacion_aceptada_no_reabrir
BEFORE UPDATE OF estado ON cotizaciones WHEN
    (OLD.estado = 'convertida' AND NEW.estado <> 'convertida')
    OR (OLD.estado = 'aceptada' AND NEW.estado NOT IN ('aceptada', 'convertida'))
    OR (OLD.estado NOT IN ('aceptada', 'convertida') AND NEW.estado = 'convertida')
BEGIN
    SELECT RAISE(ABORT, 'Una propuesta aceptada solo puede convertirse mediante una venta; una convertida no se reabre');
END;

CREATE TRIGGER cotizacion_convertida_requiere_venta
BEFORE UPDATE OF estado ON cotizaciones WHEN NEW.estado = 'convertida'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM ventas v WHERE v.cotizacion_id = NEW.id AND v.cliente_id = NEW.cliente_id
    ) THEN RAISE(ABORT, 'La propuesta requiere una venta asociada para convertirse') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM venta_detalles d JOIN ventas v ON v.id = d.venta_id
        WHERE v.cotizacion_id = NEW.id
    ) <> (
        SELECT COUNT(*) FROM cotizacion_detalles WHERE cotizacion_id = NEW.id
    ) THEN RAISE(ABORT, 'La venta debe conservar todos los conceptos de la propuesta') END;
END;

CREATE TRIGGER venta_propuesta_debe_estar_aceptada
BEFORE INSERT ON ventas WHEN NEW.cotizacion_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM cotizaciones c
        WHERE c.id = NEW.cotizacion_id AND c.cliente_id = NEW.cliente_id AND c.estado = 'aceptada'
    ) THEN RAISE(ABORT, 'Solo se convierte una propuesta aceptada del mismo cliente') END;
END;

CREATE TRIGGER detalle_venta_concepto_propuesta_coincide
BEFORE INSERT ON venta_detalles WHEN NEW.cotizacion_detalle_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM cotizacion_detalles qd JOIN ventas v ON v.id = NEW.venta_id
        WHERE qd.id = NEW.cotizacion_detalle_id AND qd.cotizacion_id = v.cotizacion_id
          AND qd.descripcion = NEW.descripcion AND qd.cantidad = NEW.cantidad
          AND qd.precio_unitario_cop = NEW.precio_unitario_cop
          AND qd.producto_id IS NEW.producto_id
    ) THEN RAISE(ABORT, 'La línea de venta debe conservar el concepto aceptado') END;
END;

CREATE TRIGGER venta_no_agregar_conceptos_tras_conversion
BEFORE INSERT ON venta_detalles WHEN EXISTS (
    SELECT 1 FROM ventas WHERE id = NEW.venta_id AND cotizacion_id IS NOT NULL
)
AND NEW.cotizacion_detalle_id IS NULL
BEGIN
    SELECT RAISE(ABORT, 'La venta convertida conserva exactamente las líneas de su propuesta');
END;

CREATE TRIGGER ventas_no_borrar
BEFORE DELETE ON ventas
BEGIN
    SELECT RAISE(ABORT, 'No se borran ventas históricas');
END;

CREATE TRIGGER ventas_no_editar_cabecera
BEFORE UPDATE ON ventas
BEGIN
    SELECT RAISE(ABORT, 'La cabecera de una venta confirmada es inmutable');
END;

CREATE TRIGGER detalles_venta_no_editar
BEFORE UPDATE ON venta_detalles
BEGIN
    SELECT RAISE(ABORT, 'Los conceptos de venta confirmados son inmutables');
END;

CREATE TRIGGER detalles_venta_no_borrar
BEFORE DELETE ON venta_detalles
BEGIN
    SELECT RAISE(ABORT, 'No se borran conceptos de ventas históricas');
END;
