-- Fase 1, Entrega 6 (B): parte B pendiente del 0011 original. Depende de 0012 (compensaciones,
-- ledger) y 0013 (extinciones, recuperaciones, actores). No modifica filas.
--   * v_historial_financiero_venta: una fila por hecho económico. La suma de efecto_residuo_cop
--     es F = H + Q - N0 (Nota de corrección: usa reembolsos ENTREGADOS, no comprometidos) y la
--     de efecto_caja_cop es el efectivo neto movido (P + H - C_e).
--   * v_cartera_ventas: deuda pendiente por venta, separada de la caja.
--   * v_saldos_ordenes: añade saldo_favor_aplicado_cop. El ledger ya admite orden_id pero el
--     uso de saldo a favor en órdenes sigue deshabilitado (Informe2 §6.5, P7): hoy vale 0.

CREATE VIEW v_historial_financiero_venta AS
SELECT v.id AS venta_id, v.creado_en_utc AS instante_utc, v.fecha_venta AS fecha_negocio,
       'venta' AS evento, v.id AS referencia_id, 'Venta ' || v.codigo AS descripcion,
       -COALESCE((SELECT SUM(d.cantidad * d.precio_unitario_cop) FROM venta_detalles d WHERE d.venta_id = v.id), 0) AS efecto_residuo_cop,
       0 AS efecto_caja_cop, 'no_caja' AS naturaleza, '' AS responsable, 'sistema' AS origen_identidad
FROM ventas v
UNION ALL
SELECT p.venta_id, p.registrado_en_utc, COALESCE(p.fecha_negocio, date(p.registrado_en_utc, '-5 hours')),
       CASE WHEN p.tipo = 'recibo' THEN 'pago' ELSE 'reversion_pago' END, p.id,
       CASE WHEN p.tipo = 'recibo' THEN 'Pago recibido (' || p.metodo || ')'
            ELSE 'Reversión de pago #' || p.reversa_pago_id || ' (' || COALESCE(p.naturaleza_reversion, 'legado') || ')' END,
       CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END,
       CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END,
       'caja', COALESCE(p.ejecutor_nombre, ''), COALESCE(p.origen_identidad, 'legado')
FROM pagos_clientes p WHERE p.venta_id IS NOT NULL
UNION ALL
SELECT c.venta_id, c.ejecutado_en_utc, c.fecha_negocio, 'devolucion', c.id, 'Devolución reconocida: ' || c.motivo,
       COALESCE((SELECT SUM(l.importe_reconocido_cop) FROM cancelacion_venta_lineas l WHERE l.cancelacion_id = c.id), 0),
       0, 'no_caja', c.responsable_ejecucion, COALESCE(c.origen_identidad, 'legado')
FROM cancelaciones_venta c
UNION ALL
SELECT k.venta_id, k.registrado_en_utc, k.fecha_negocio, 'compromiso_reembolso', k.id,
       'Compromiso de reembolso (sin efecto hasta la entrega)', 0, 0, 'no_caja', k.responsable_ejecucion, COALESCE(k.origen_identidad, 'legado')
FROM compensaciones_cancelacion k WHERE k.tipo = 'reembolso'
UNION ALL
SELECT k.venta_id, e.registrado_en_utc, date(e.ocurrido_en_utc, '-5 hours'), 'anulacion_compromiso', e.id,
       'Anulación del compromiso #' || k.id, 0, 0, 'no_caja', e.registrado_por, COALESCE(e.origen_identidad, 'legado')
FROM eventos_compensacion e JOIN compensaciones_cancelacion k ON k.id = e.compensacion_id WHERE e.tipo = 'anulada'
UNION ALL
SELECT k.venta_id, e.ocurrido_en_utc, date(e.ocurrido_en_utc, '-5 hours'), 'entrega_reembolso', e.id,
       'Entrega de reembolso ' || COALESCE(e.voucher_codigo, '') || ' (' || e.medio || ')',
       -k.importe_cop, -k.importe_cop, 'caja', e.registrado_por, COALESCE(e.origen_identidad, 'legado')
FROM eventos_compensacion e JOIN compensaciones_cancelacion k ON k.id = e.compensacion_id WHERE e.tipo = 'entregada'
UNION ALL
SELECT k.venta_id, k.registrado_en_utc, k.fecha_negocio, 'credito_generado', k.id,
       'Saldo a favor generado', -k.importe_cop, 0, 'no_caja', k.responsable_ejecucion, COALESCE(k.origen_identidad, 'legado')
FROM compensaciones_cancelacion k WHERE k.tipo = 'credito'
UNION ALL
SELECT m.venta_id, m.registrado_en_utc, m.fecha_negocio, 'credito_aplicado', m.id,
       'Saldo a favor aplicado', -m.importe_cop, 0, 'no_caja', m.registrado_por, COALESCE(m.origen_identidad, 'legado')
FROM movimientos_saldo_favor m WHERE m.tipo = 'utilizacion' AND m.venta_id IS NOT NULL
UNION ALL
SELECT x.venta_id, x.registrado_en_utc, x.fecha_negocio,
       CASE x.tipo WHEN 'condonacion' THEN 'condonacion' ELSE 'castigo' END, x.id,
       CASE x.tipo WHEN 'condonacion' THEN 'Condonación de deuda: ' ELSE 'Castigo de deuda: ' END || x.motivo,
       x.importe_cop, 0, 'no_caja', x.ejecutor_nombre, 'directorio'
FROM extinciones_deuda_venta x
UNION ALL
SELECT x.venta_id, a.anulada_en_utc, a.fecha_negocio, 'anulacion_extincion', a.id,
       'Anulación de extinción #' || x.id || ': ' || a.motivo, -a.importe_anulado_cop, 0, 'no_caja', a.ejecutor_nombre, 'directorio'
FROM anulaciones_extincion_deuda a JOIN extinciones_deuda_venta x ON x.id = a.extincion_id
UNION ALL
SELECT h.venta_id, h.registrado_en_utc, h.fecha_negocio, 'recuperacion_deuda', h.id,
       'Recuperación de deuda (' || m.nombre || '): ' || h.motivo, h.importe_cop, h.importe_cop, 'caja', h.ejecutor_nombre, 'directorio'
FROM recuperaciones_deuda_venta h JOIN metodos_pago m ON m.id = h.metodo_pago_id;

CREATE VIEW v_cartera_ventas AS
SELECT s.venta_id, v.codigo AS venta_codigo, v.cliente_id, c.nombre AS cliente_nombre,
       v.fecha_venta, CAST(julianday(date('now', '-5 hours')) - julianday(v.fecha_venta) AS INTEGER) AS antiguedad_dias,
       s.deuda_pendiente_cop, s.estado_liquidacion, s.estado_comercial
FROM v_saldos_ventas s JOIN ventas v ON v.id = s.venta_id JOIN clientes c ON c.id = v.cliente_id
WHERE s.deuda_pendiente_cop > 0;

DROP VIEW v_saldos_ordenes;
CREATE VIEW v_saldos_ordenes AS
SELECT i.orden_id,
       i.importe_acordado_cop,
       COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                 FROM pagos_clientes p WHERE p.orden_id = i.orden_id), 0) AS pagado_neto_cop,
       i.importe_acordado_cop
         - COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                     FROM pagos_clientes p WHERE p.orden_id = i.orden_id), 0)
         - COALESCE((SELECT -SUM(m.importe_cop) FROM movimientos_saldo_favor m
                     WHERE m.orden_id = i.orden_id AND m.tipo = 'utilizacion'), 0) AS saldo_pendiente_cop,
       COALESCE((SELECT -SUM(m.importe_cop) FROM movimientos_saldo_favor m
                 WHERE m.orden_id = i.orden_id AND m.tipo = 'utilizacion'), 0) AS saldo_favor_aplicado_cop
FROM v_ordenes_importes i;
