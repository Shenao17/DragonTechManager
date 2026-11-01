-- Fase 1 (pendientes, bloque 1): evento `corregida` y reversión de un reembolso entregado
-- (Informe3 §2.2-2.3, B4; Nota R13-C). Dos correcciones, siempre con evento nuevo, autorizador
-- y motivo; el hecho `entregada` nunca se borra ni se edita:
--   * 'datos': corrige medio, referencia externa, fecha efectiva o receptor de la entrega.
--   * 'entrega_no_ocurrida': deja constancia de que la entrega registrada no ocurrió. Exige una
--     investigación abierta y evidencia, libera el compromiso (deja de contar en C y C_e) y se
--     RECHAZA si dejaría H + Q por encima de la deuda (R13-C; decisión del propietario).
-- Una investigación ahora puede abrirse también sobre una entrega ya registrada.

ALTER TABLE eventos_compensacion ADD COLUMN correccion_tipo TEXT
    CHECK (correccion_tipo IS NULL OR correccion_tipo IN ('datos', 'entrega_no_ocurrida'));
ALTER TABLE eventos_compensacion ADD COLUMN ocurrido_corregido_en_utc TEXT
    CHECK (ocurrido_corregido_en_utc IS NULL OR (strftime('%Y-%m-%dT%H:%M:%SZ', ocurrido_corregido_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', ocurrido_corregido_en_utc) = ocurrido_corregido_en_utc));
ALTER TABLE eventos_compensacion ADD COLUMN receptor TEXT;
ALTER TABLE eventos_compensacion ADD COLUMN evidencia TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX uq_compensacion_liberada ON eventos_compensacion(compensacion_id)
    WHERE tipo = 'corregida' AND correccion_tipo = 'entrega_no_ocurrida';

-- Estado efectivo: la liberación cuenta como anulada para los saldos (v_ventas_posicion no cambia);
-- `en_investigacion` es además una marca, para que una entrega registrada bajo investigación siga
-- contando como entregada mientras se resuelve.
DROP VIEW v_compensaciones_pendientes;
DROP VIEW v_compensaciones_estado;
CREATE VIEW v_compensaciones_estado AS
SELECT c.id AS compensacion_id, c.venta_id, c.tipo, c.importe_cop,
       CASE WHEN c.tipo = 'credito' THEN 'acreditada'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'anulada')
              OR EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'corregida' AND e.correccion_tipo = 'entrega_no_ocurrida') THEN 'anulada'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'corregida') THEN 'corregida'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'entregada') THEN 'entregada'
            WHEN (SELECT e.tipo FROM eventos_compensacion e WHERE e.compensacion_id = c.id ORDER BY e.id DESC LIMIT 1) = 'en_investigacion' THEN 'en_investigacion'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'preparada') THEN 'preparada'
            ELSE 'comprometida' END AS estado,
       CASE WHEN c.tipo = 'reembolso'
             AND (SELECT e.tipo FROM eventos_compensacion e WHERE e.compensacion_id = c.id ORDER BY e.id DESC LIMIT 1) = 'en_investigacion'
            THEN 1 ELSE 0 END AS en_investigacion,
       EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'corregida' AND e.correccion_tipo = 'entrega_no_ocurrida') AS liberada
FROM compensaciones_cancelacion c;

CREATE VIEW v_compensaciones_pendientes AS
SELECT e.compensacion_id, e.venta_id, v.codigo AS venta_codigo, e.importe_cop, e.estado, e.en_investigacion,
       c.registrado_en_utc AS comprometida_en_utc,
       CAST(julianday(date('now', '-5 hours')) - julianday(c.fecha_negocio) AS INTEGER) AS antiguedad_dias,
       m.nombre AS metodo_nombre,
       (SELECT x.voucher_codigo FROM eventos_compensacion x
        WHERE x.compensacion_id = e.compensacion_id AND x.tipo = 'preparada') AS voucher_codigo
FROM v_compensaciones_estado e
JOIN compensaciones_cancelacion c ON c.id = e.compensacion_id
JOIN ventas v ON v.id = e.venta_id
LEFT JOIN metodos_pago m ON m.id = c.metodo_pago_id
WHERE e.tipo = 'reembolso' AND (e.estado IN ('comprometida', 'preparada', 'en_investigacion') OR e.en_investigacion = 1);

CREATE VIEW v_investigaciones_compensacion AS
SELECT e.compensacion_id, e.venta_id, v.codigo AS venta_codigo, e.importe_cop, e.estado,
       i.registrado_en_utc AS abierta_en_utc, i.registrado_por AS abierta_por, i.motivo,
       CAST(julianday(date('now', '-5 hours')) - julianday(date(i.registrado_en_utc, '-5 hours')) AS INTEGER) AS dias_abierta
FROM v_compensaciones_estado e
JOIN ventas v ON v.id = e.venta_id
JOIN eventos_compensacion i ON i.id = (SELECT MAX(x.id) FROM eventos_compensacion x WHERE x.compensacion_id = e.compensacion_id)
WHERE e.en_investigacion = 1 AND i.tipo = 'en_investigacion';

-- Regla de oro: una entrega bajo investigación (incluida una ya registrada) bloquea nuevos reembolsos.
DROP TRIGGER compensaciones_validar;
CREATE TRIGGER compensaciones_validar
BEFORE INSERT ON compensaciones_cancelacion
BEGIN
    SELECT RAISE(ABORT, 'La compensación solo aplica a una venta con devolución registrada')
    WHERE (SELECT u_devueltas FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) IS NOT NULL
      AND (SELECT u_devueltas FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) = 0;
    SELECT RAISE(ABORT, 'La devolución indicada no pertenece a la venta')
    WHERE NEW.cancelacion_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM cancelaciones_venta c WHERE c.id = NEW.cancelacion_id AND c.venta_id = NEW.venta_id);
    SELECT RAISE(ABORT, 'La compensación supera el sobrepago pendiente de la venta')
    WHERE (SELECT c_comprometido + g FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) + NEW.importe_cop
          > MAX(0, (SELECT d FROM v_ventas_posicion WHERE venta_id = NEW.venta_id));
    SELECT RAISE(ABORT, 'El reembolso supera el dinero neto recibido en la venta')
    WHERE NEW.tipo = 'reembolso'
      AND (SELECT c_comprometido FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) + NEW.importe_cop
          > (SELECT p FROM v_ventas_posicion WHERE venta_id = NEW.venta_id);
    SELECT RAISE(ABORT, 'Hay una entrega de reembolso preparada o en investigación para esta venta')
    WHERE NEW.tipo = 'reembolso'
      AND EXISTS (SELECT 1 FROM v_compensaciones_estado e
                  WHERE e.venta_id = NEW.venta_id AND (e.estado IN ('preparada', 'en_investigacion') OR e.en_investigacion = 1));
    SELECT RAISE(ABORT, 'El método de reembolso no está activo o no aplica a clientes')
    WHERE NEW.tipo = 'reembolso'
      AND NOT EXISTS (SELECT 1 FROM metodos_pago m WHERE m.id = NEW.metodo_pago_id AND m.activo = 1 AND m.aplica_cliente = 1);
    SELECT RAISE(ABORT, 'El crédito que sustituye efectivo requiere consentimiento explícito del cliente')
    WHERE NEW.tipo = 'credito' AND NEW.consentimiento_cliente = 0
      AND NEW.importe_cop > (SELECT u FROM v_ventas_posicion WHERE venta_id = NEW.venta_id);
END;

DROP TRIGGER eventos_compensacion_validar;
CREATE TRIGGER eventos_compensacion_validar
BEFORE INSERT ON eventos_compensacion
BEGIN
    SELECT RAISE(ABORT, 'Solo los reembolsos tienen eventos de entrega')
    WHERE NOT EXISTS (SELECT 1 FROM compensaciones_cancelacion c WHERE c.id = NEW.compensacion_id AND c.tipo = 'reembolso');
    SELECT RAISE(ABORT, 'La compensación ya fue entregada o anulada')
    WHERE NEW.tipo IN ('preparada', 'entregada', 'anulada')
      AND EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo IN ('entregada', 'anulada'));
    SELECT RAISE(ABORT, 'La preparación requiere voucher y medio')
    WHERE NEW.tipo = 'preparada' AND (NEW.voucher_codigo IS NULL OR length(trim(NEW.voucher_codigo)) = 0 OR NEW.medio IS NULL);
    SELECT RAISE(ABORT, 'La entrega requiere medio, voucher e importe iguales al compromiso')
    WHERE NEW.tipo = 'entregada'
      AND (NEW.medio IS NULL OR NEW.voucher_codigo IS NULL
           OR NEW.importe_cop IS NOT (SELECT importe_cop FROM compensaciones_cancelacion WHERE id = NEW.compensacion_id));
    SELECT RAISE(ABORT, 'El voucher de la entrega no coincide con el preparado')
    WHERE NEW.tipo = 'entregada'
      AND EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id
                  AND e.tipo = 'preparada' AND e.voucher_codigo <> NEW.voucher_codigo);
    SELECT RAISE(ABORT, 'Transferencias y tarjetas requieren referencia externa')
    WHERE NEW.tipo = 'entregada' AND NEW.medio IN ('transferencia', 'tarjeta')
      AND (NEW.referencia_externa IS NULL OR length(trim(NEW.referencia_externa)) = 0);
    SELECT RAISE(ABORT, 'La entrega supera el dinero neto recibido en la venta')
    WHERE NEW.tipo = 'entregada'
      AND (SELECT v.c_entregado FROM v_ventas_posicion v JOIN compensaciones_cancelacion c ON c.venta_id = v.venta_id WHERE c.id = NEW.compensacion_id)
          + NEW.importe_cop
          > (SELECT v.p FROM v_ventas_posicion v JOIN compensaciones_cancelacion c ON c.venta_id = v.venta_id WHERE c.id = NEW.compensacion_id);
    SELECT RAISE(ABORT, 'Anular, investigar o corregir requiere motivo, y anular o corregir además autorizador y referencia')
    WHERE (NEW.tipo IN ('anulada', 'en_investigacion', 'corregida') AND length(trim(NEW.motivo)) = 0)
       OR (NEW.tipo IN ('anulada', 'corregida') AND COALESCE(NEW.origen_identidad, '') <> 'sistema'
           AND (trim(NEW.autorizador) = '' OR length(trim(NEW.referencia_autorizacion)) = 0));
    SELECT RAISE(ABORT, 'La anulación automática solo aplica a compromisos sin preparar')
    WHERE NEW.origen_identidad = 'sistema' AND NEW.tipo = 'anulada'
      AND EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo IN ('preparada', 'en_investigacion'));
    -- Investigación: sobre una entrega preparada o ya registrada, una sola abierta a la vez.
    SELECT RAISE(ABORT, 'Solo se investiga una entrega preparada o ya registrada')
    WHERE NEW.tipo = 'en_investigacion'
      AND NOT EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo IN ('preparada', 'entregada'));
    SELECT RAISE(ABORT, 'La compensación ya está anulada o liberada')
    WHERE NEW.tipo = 'en_investigacion'
      AND EXISTS (SELECT 1 FROM v_compensaciones_estado e WHERE e.compensacion_id = NEW.compensacion_id AND e.estado = 'anulada');
    SELECT RAISE(ABORT, 'Ya hay una investigación abierta para esta compensación')
    WHERE NEW.tipo = 'en_investigacion'
      AND (SELECT e.tipo FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id ORDER BY e.id DESC LIMIT 1) = 'en_investigacion';
    -- Corrección.
    SELECT RAISE(ABORT, 'La corrección debe indicar su tipo: datos o entrega no ocurrida')
    WHERE NEW.tipo = 'corregida' AND NEW.correccion_tipo IS NULL;
    SELECT RAISE(ABORT, 'Solo se corrige una entrega ya registrada y no liberada')
    WHERE NEW.tipo = 'corregida'
      AND (NOT EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo = 'entregada')
           OR EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo = 'corregida' AND e.correccion_tipo = 'entrega_no_ocurrida'));
    SELECT RAISE(ABORT, 'La corrección de datos debe cambiar medio, referencia, fecha efectiva o receptor')
    WHERE NEW.tipo = 'corregida' AND NEW.correccion_tipo = 'datos'
      AND NEW.medio IS NULL AND NEW.referencia_externa IS NULL AND NEW.ocurrido_corregido_en_utc IS NULL AND NEW.receptor IS NULL;
    SELECT RAISE(ABORT, 'La fecha efectiva corregida no puede ser futura')
    WHERE NEW.tipo = 'corregida' AND NEW.ocurrido_corregido_en_utc IS NOT NULL AND NEW.ocurrido_corregido_en_utc > NEW.registrado_en_utc;
    SELECT RAISE(ABORT, 'Esa referencia externa ya respalda otra entrega')
    WHERE NEW.tipo = 'corregida' AND NEW.referencia_externa IS NOT NULL
      AND EXISTS (SELECT 1 FROM eventos_compensacion e
                  WHERE e.compensacion_id <> NEW.compensacion_id AND e.tipo IN ('entregada', 'corregida')
                    AND e.referencia_externa = NEW.referencia_externa
                    AND COALESCE(e.medio, '') = COALESCE(NEW.medio, (SELECT x.medio FROM eventos_compensacion x WHERE x.compensacion_id = NEW.compensacion_id AND x.tipo = 'entregada'), ''));
    SELECT RAISE(ABORT, 'Declarar que la entrega no ocurrió exige una investigación abierta y evidencia')
    WHERE NEW.tipo = 'corregida' AND NEW.correccion_tipo = 'entrega_no_ocurrida'
      AND (length(trim(NEW.evidencia)) = 0
           OR COALESCE((SELECT e.tipo FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id ORDER BY e.id DESC LIMIT 1), '') <> 'en_investigacion');
    -- R13-C: liberar un reembolso entregado baja C_e y N0; Q (y H) no pueden quedar sobre la deuda.
    SELECT RAISE(ABORT, 'La corrección dejaría condonaciones o recuperaciones por encima de la deuda; anula antes la extinción excedente')
    WHERE NEW.tipo = 'corregida' AND NEW.correccion_tipo = 'entrega_no_ocurrida'
      AND (SELECT pos.h + pos.q FROM v_ventas_posicion pos JOIN compensaciones_cancelacion c ON c.venta_id = pos.venta_id WHERE c.id = NEW.compensacion_id)
          > MAX(0, (SELECT pos.n0 FROM v_ventas_posicion pos JOIN compensaciones_cancelacion c ON c.venta_id = pos.venta_id WHERE c.id = NEW.compensacion_id)
                   - (SELECT importe_cop FROM compensaciones_cancelacion WHERE id = NEW.compensacion_id));
END;
