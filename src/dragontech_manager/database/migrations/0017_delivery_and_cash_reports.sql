-- Fase 1 (pendientes, bloque 2): reportes de entregas del día y arqueo de caja (Informe3 §2.7, C5).
-- Alcance aprobado por el propietario: solo lo diseñado. No hay conteo físico persistido: la
-- diferencia contra el conteo se calcula en pantalla. Respetan las correcciones de entrega
-- (0016): medio, referencia, fecha efectiva y receptor vigentes salen de la última corrección de
-- datos; una entrega liberada («no ocurrió») no cuenta.

CREATE VIEW v_entregas_efectivas AS
SELECT e.id AS evento_id, k.id AS compensacion_id, k.venta_id, v.codigo AS venta_codigo, k.importe_cop,
       COALESCE((SELECT c.medio FROM eventos_compensacion c WHERE c.compensacion_id = k.id AND c.tipo = 'corregida'
                   AND c.correccion_tipo = 'datos' AND c.medio IS NOT NULL ORDER BY c.id DESC LIMIT 1), e.medio) AS medio,
       COALESCE((SELECT c.referencia_externa FROM eventos_compensacion c WHERE c.compensacion_id = k.id AND c.tipo = 'corregida'
                   AND c.correccion_tipo = 'datos' AND c.referencia_externa IS NOT NULL ORDER BY c.id DESC LIMIT 1), e.referencia_externa) AS referencia_externa,
       COALESCE((SELECT c.ocurrido_corregido_en_utc FROM eventos_compensacion c WHERE c.compensacion_id = k.id AND c.tipo = 'corregida'
                   AND c.correccion_tipo = 'datos' AND c.ocurrido_corregido_en_utc IS NOT NULL ORDER BY c.id DESC LIMIT 1), e.ocurrido_en_utc) AS ocurrido_efectivo_utc,
       COALESCE((SELECT c.receptor FROM eventos_compensacion c WHERE c.compensacion_id = k.id AND c.tipo = 'corregida'
                   AND c.correccion_tipo = 'datos' AND c.receptor IS NOT NULL ORDER BY c.id DESC LIMIT 1), e.receptor) AS receptor,
       e.registrado_en_utc, e.voucher_codigo, e.registrado_por,
       EXISTS (SELECT 1 FROM eventos_compensacion c WHERE c.compensacion_id = k.id AND c.tipo = 'corregida'
                 AND c.correccion_tipo = 'entrega_no_ocurrida') AS liberada
FROM eventos_compensacion e
JOIN compensaciones_cancelacion k ON k.id = e.compensacion_id
JOIN ventas v ON v.id = k.venta_id
WHERE e.tipo = 'entregada';

-- Entregas del día por fecha efectiva y por fecha de registro, separadas (la entrega puede preceder al registro).
CREATE VIEW v_entregas_del_dia AS
SELECT 'fecha_efectiva' AS criterio, date(ocurrido_efectivo_utc, '-5 hours') AS fecha, medio,
       COUNT(*) AS entregas, SUM(importe_cop) AS importe_cop
FROM v_entregas_efectivas WHERE liberada = 0 GROUP BY 2, 3
UNION ALL
SELECT 'fecha_registro', date(registrado_en_utc, '-5 hours'), medio, COUNT(*), SUM(importe_cop)
FROM v_entregas_efectivas WHERE liberada = 0 GROUP BY 2, 3;

-- Arqueo de efectivo por día de negocio. «Entregado» usa la fecha efectiva de la entrega;
-- «comprometido», «pendiente» y «anulado» se agrupan por el día del compromiso y el estado se
-- evalúa HOY (no es una foto histórica). Solo reembolsos cuyo método es de la familia efectivo.
CREATE VIEW v_arqueo_caja AS
WITH dias AS (
    SELECT date(ocurrido_efectivo_utc, '-5 hours') AS fecha FROM v_entregas_efectivas
    UNION SELECT k.fecha_negocio FROM compensaciones_cancelacion k WHERE k.tipo = 'reembolso'
)
SELECT d.fecha,
       COALESCE((SELECT SUM(x.importe_cop) FROM v_entregas_efectivas x
                 WHERE x.liberada = 0 AND x.medio = 'efectivo' AND date(x.ocurrido_efectivo_utc, '-5 hours') = d.fecha), 0) AS entregado_efectivo_cop,
       COALESCE((SELECT SUM(x.importe_cop) FROM v_entregas_efectivas x
                 WHERE x.liberada = 0 AND x.medio <> 'efectivo' AND date(x.ocurrido_efectivo_utc, '-5 hours') = d.fecha), 0) AS entregado_otros_medios_cop,
       COALESCE((SELECT SUM(k.importe_cop) FROM compensaciones_cancelacion k JOIN metodos_pago m ON m.id = k.metodo_pago_id
                 WHERE k.tipo = 'reembolso' AND m.familia = 'efectivo' AND k.fecha_negocio = d.fecha), 0) AS comprometido_efectivo_cop,
       COALESCE((SELECT SUM(k.importe_cop) FROM compensaciones_cancelacion k JOIN metodos_pago m ON m.id = k.metodo_pago_id
                 JOIN v_compensaciones_estado s ON s.compensacion_id = k.id
                 WHERE k.tipo = 'reembolso' AND m.familia = 'efectivo' AND k.fecha_negocio = d.fecha
                   AND s.estado IN ('comprometida', 'preparada', 'en_investigacion')), 0) AS pendiente_efectivo_cop,
       COALESCE((SELECT SUM(k.importe_cop) FROM compensaciones_cancelacion k JOIN metodos_pago m ON m.id = k.metodo_pago_id
                 JOIN v_compensaciones_estado s ON s.compensacion_id = k.id
                 WHERE k.tipo = 'reembolso' AND m.familia = 'efectivo' AND k.fecha_negocio = d.fecha
                   AND s.estado = 'anulada'), 0) AS anulado_efectivo_cop
FROM dias d;
