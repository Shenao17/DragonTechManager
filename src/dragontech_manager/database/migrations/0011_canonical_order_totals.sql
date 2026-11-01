-- Fase 1, Entrega 3 (parte A de 0011 del diseño): fuente única del importe acordado
-- de una orden. No depende de 0010 (devoluciones/saldo a favor, aún no aplicada) y no
-- modifica filas. El importe acordado es importe_inicial + adicionales cuya ÚLTIMA
-- decisión es 'aprobado'; antes se recalculaba en v_saldos_ordenes, list_orders y tres
-- triggers. Los triggers conservan nombre, evento y mensaje.

CREATE VIEW v_ordenes_importes AS
SELECT o.id AS orden_id,
       o.importe_inicial_cop,
       COALESCE((
           SELECT SUM(s.importe_propuesto_cop)
           FROM servicios_adicionales s
           JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
           WHERE s.orden_id = o.id
             AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                         WHERE d2.servicio_adicional_id = s.id
                         ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
             AND d.decision = 'aprobado'
       ), 0) AS extras_aprobados_cop,
       o.importe_inicial_cop + COALESCE((
           SELECT SUM(s.importe_propuesto_cop)
           FROM servicios_adicionales s
           JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
           WHERE s.orden_id = o.id
             AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                         WHERE d2.servicio_adicional_id = s.id
                         ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
             AND d.decision = 'aprobado'
       ), 0) AS importe_acordado_cop
FROM ordenes_servicio o;

DROP VIEW v_saldos_ordenes;
CREATE VIEW v_saldos_ordenes AS
SELECT i.orden_id,
       i.importe_acordado_cop,
       COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                 FROM pagos_clientes p WHERE p.orden_id = i.orden_id), 0) AS pagado_neto_cop,
       i.importe_acordado_cop
         - COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                     FROM pagos_clientes p WHERE p.orden_id = i.orden_id), 0) AS saldo_pendiente_cop
FROM v_ordenes_importes i;

DROP TRIGGER pagos_clientes_no_sobrepagar_orden;
CREATE TRIGGER pagos_clientes_no_sobrepagar_orden
BEFORE INSERT ON pagos_clientes WHEN NEW.tipo = 'recibo' AND NEW.orden_id IS NOT NULL
BEGIN
    SELECT CASE WHEN
        COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                  FROM pagos_clientes p WHERE p.orden_id = NEW.orden_id), 0) + NEW.importe_cop
        > (SELECT importe_acordado_cop FROM v_ordenes_importes WHERE orden_id = NEW.orden_id)
    THEN RAISE(ABORT, 'El pago supera el importe acordado de la orden') END;
END;

DROP TRIGGER orden_no_reducir_deuda_pagada;
CREATE TRIGGER orden_no_reducir_deuda_pagada
BEFORE UPDATE OF importe_inicial_cop ON ordenes_servicio
BEGIN
    SELECT CASE WHEN
        NEW.importe_inicial_cop
          + (SELECT extras_aprobados_cop FROM v_ordenes_importes WHERE orden_id = OLD.id)
        < COALESCE((
            SELECT SUM(CASE WHEN tipo = 'recibo' THEN importe_cop ELSE -importe_cop END)
            FROM pagos_clientes WHERE orden_id = OLD.id
        ), 0)
    THEN RAISE(ABORT, 'El nuevo importe dejaría pagos por encima de lo acordado') END;
END;

-- Al rechazar un adicional cuya última decisión es 'aprobado', el importe acordado sin
-- él es el actual menos su importe propuesto.
DROP TRIGGER decisiones_adicional_no_reduce_deuda_pagada;
CREATE TRIGGER decisiones_adicional_no_reduce_deuda_pagada
BEFORE INSERT ON decisiones_adicional WHEN NEW.decision = 'rechazado'
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM servicios_adicionales s
        JOIN decisiones_adicional previa ON previa.servicio_adicional_id = s.id
        WHERE s.id = NEW.servicio_adicional_id
          AND previa.id = (SELECT d.id FROM decisiones_adicional d
                           WHERE d.servicio_adicional_id = s.id
                           ORDER BY d.decidido_en_utc DESC, d.id DESC LIMIT 1)
          AND previa.decision = 'aprobado'
          AND COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                        FROM pagos_clientes p WHERE p.orden_id = s.orden_id), 0)
              > (SELECT i.importe_acordado_cop FROM v_ordenes_importes i WHERE i.orden_id = s.orden_id)
                - s.importe_propuesto_cop
    ) THEN RAISE(ABORT, 'Revierta el excedente pagado antes de rechazar el adicional') END;
END;
