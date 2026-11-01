-- Fase 1, Entrega 5: saldo a favor (ledger) y compensaciones de devoluciones
-- (reembolso, crédito o mixta = dos compromisos creados atómicamente). Depende de
-- cancelaciones_venta (0010). Todo es append-only: el estado de una compensación se
-- deriva de sus eventos y el saldo del cliente de la suma del ledger.
--   D = P + U - (T - R);  R2: C + G <= MAX(0, D);  R3: C <= P (al comprometer) y
--   C_entregado <= P (al entregar; no se reevalúa retroactivamente, Nota de corrección);
--   R4: P + U <= T - R en pagos y usos nuevos;  R5: saldo del cliente >= 0;
--   R6: una corrección de registro erróneo no puede dejar compensaciones sin respaldo.
-- Autorizador/registrante son texto declarativo hasta la tabla de actores (Entrega 6).

CREATE TABLE tipos_origen_saldo_favor (
    codigo TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL
);
INSERT INTO tipos_origen_saldo_favor (codigo, descripcion) VALUES
    ('venta', 'Venta directa'),
    ('orden', 'Orden de servicio'),
    ('compensacion_venta', 'Compensación de devolución de venta'),
    ('cancelacion_orden', 'Cancelación de orden (fase posterior)'),
    ('ajuste', 'Ajuste manual autorizado');

CREATE TABLE compensaciones_cancelacion (
    id INTEGER PRIMARY KEY,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE RESTRICT,
    cancelacion_id INTEGER REFERENCES cancelaciones_venta(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN ('reembolso', 'credito')),
    importe_cop INTEGER NOT NULL CHECK (typeof(importe_cop) = 'integer' AND importe_cop > 0),
    metodo_pago_id INTEGER REFERENCES metodos_pago(id) ON DELETE RESTRICT,
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
    responsable_ejecucion TEXT NOT NULL CHECK (length(trim(responsable_ejecucion)) > 0),
    autorizador TEXT NOT NULL CHECK (length(trim(autorizador)) > 0),
    autorizado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', autorizado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', autorizado_en_utc) = autorizado_en_utc),
    referencia_autorizacion TEXT NOT NULL CHECK (length(trim(referencia_autorizacion)) > 0),
    consentimiento_cliente INTEGER NOT NULL DEFAULT 0 CHECK (consentimiento_cliente IN (0, 1)),
    fecha_negocio TEXT NOT NULL CHECK (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio),
    registrado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) = registrado_en_utc),
    clave_idempotencia TEXT NOT NULL UNIQUE CHECK (length(trim(clave_idempotencia)) BETWEEN 1 AND 120),
    huella_solicitud TEXT NOT NULL CHECK (length(huella_solicitud) = 64),
    CHECK (lower(trim(autorizador)) <> lower(trim(responsable_ejecucion))),
    CHECK ((tipo = 'reembolso' AND metodo_pago_id IS NOT NULL) OR (tipo = 'credito' AND metodo_pago_id IS NULL)),
    CHECK (fecha_negocio <= date(registrado_en_utc, '-5 hours'))
);
CREATE INDEX idx_compensaciones_venta ON compensaciones_cancelacion(venta_id);

CREATE TABLE eventos_compensacion (
    id INTEGER PRIMARY KEY,
    compensacion_id INTEGER NOT NULL REFERENCES compensaciones_cancelacion(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN ('preparada', 'entregada', 'anulada', 'en_investigacion', 'corregida')),
    ocurrido_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', ocurrido_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', ocurrido_en_utc) = ocurrido_en_utc),
    registrado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) = registrado_en_utc),
    registrado_por TEXT NOT NULL CHECK (length(trim(registrado_por)) > 0),
    autorizador TEXT NOT NULL DEFAULT '',
    referencia_autorizacion TEXT NOT NULL DEFAULT '',
    voucher_codigo TEXT,
    medio TEXT CHECK (medio IS NULL OR medio IN ('efectivo', 'transferencia', 'tarjeta')),
    referencia_externa TEXT,
    importe_cop INTEGER CHECK (importe_cop IS NULL OR (typeof(importe_cop) = 'integer' AND importe_cop > 0)),
    motivo TEXT NOT NULL DEFAULT '',
    clave_idempotencia TEXT NOT NULL UNIQUE CHECK (length(trim(clave_idempotencia)) BETWEEN 1 AND 120),
    huella_solicitud TEXT NOT NULL CHECK (length(huella_solicitud) = 64),
    CHECK (ocurrido_en_utc <= registrado_en_utc),
    CHECK (trim(autorizador) = '' OR lower(trim(autorizador)) <> lower(trim(registrado_por)))
);
CREATE INDEX idx_eventos_compensacion ON eventos_compensacion(compensacion_id, id);
CREATE UNIQUE INDEX uq_compensacion_preparada ON eventos_compensacion(compensacion_id) WHERE tipo = 'preparada';
CREATE UNIQUE INDEX uq_compensacion_entregada ON eventos_compensacion(compensacion_id) WHERE tipo = 'entregada';
CREATE UNIQUE INDEX uq_compensacion_anulada ON eventos_compensacion(compensacion_id) WHERE tipo = 'anulada';
CREATE UNIQUE INDEX uq_voucher_compensacion ON eventos_compensacion(voucher_codigo) WHERE voucher_codigo IS NOT NULL AND tipo = 'preparada';
CREATE UNIQUE INDEX uq_referencia_externa_entrega ON eventos_compensacion(medio, referencia_externa)
    WHERE referencia_externa IS NOT NULL AND tipo = 'entregada';

CREATE TABLE movimientos_saldo_favor (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN ('generacion', 'utilizacion', 'ajuste')),
    importe_cop INTEGER NOT NULL CHECK (typeof(importe_cop) = 'integer' AND importe_cop <> 0),
    origen_tipo TEXT NOT NULL REFERENCES tipos_origen_saldo_favor(codigo) ON DELETE RESTRICT,
    origen_id INTEGER NOT NULL,
    venta_id INTEGER REFERENCES ventas(id) ON DELETE RESTRICT,
    orden_id INTEGER REFERENCES ordenes_servicio(id) ON DELETE RESTRICT,
    movimiento_corregido_id INTEGER REFERENCES movimientos_saldo_favor(id) ON DELETE RESTRICT,
    fecha_negocio TEXT NOT NULL CHECK (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio),
    registrado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) = registrado_en_utc),
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
    registrado_por TEXT NOT NULL CHECK (length(trim(registrado_por)) > 0),
    autorizador TEXT NOT NULL DEFAULT '',
    clave_idempotencia TEXT NOT NULL UNIQUE CHECK (length(trim(clave_idempotencia)) BETWEEN 1 AND 120),
    huella_solicitud TEXT NOT NULL CHECK (length(huella_solicitud) = 64),
    CHECK ((tipo = 'utilizacion' AND importe_cop < 0 AND ((venta_id IS NOT NULL) <> (orden_id IS NOT NULL)))
        OR (tipo = 'generacion' AND importe_cop > 0 AND venta_id IS NULL AND orden_id IS NULL)
        OR (tipo = 'ajuste' AND movimiento_corregido_id IS NOT NULL))
);
CREATE INDEX idx_saldo_favor_cliente ON movimientos_saldo_favor(cliente_id, id);
CREATE INDEX idx_saldo_favor_venta ON movimientos_saldo_favor(venta_id) WHERE venta_id IS NOT NULL;
CREATE UNIQUE INDEX uq_saldo_favor_generacion_origen
    ON movimientos_saldo_favor(origen_tipo, origen_id) WHERE tipo = 'generacion';

CREATE TRIGGER compensaciones_inmutables_update BEFORE UPDATE ON compensaciones_cancelacion
BEGIN SELECT RAISE(ABORT, 'Las compensaciones son inmutables; registre un evento'); END;
CREATE TRIGGER compensaciones_inmutables_delete BEFORE DELETE ON compensaciones_cancelacion
BEGIN SELECT RAISE(ABORT, 'No se borran compensaciones'); END;
CREATE TRIGGER eventos_compensacion_inmutables_update BEFORE UPDATE ON eventos_compensacion
BEGIN SELECT RAISE(ABORT, 'Los eventos de compensación son inmutables'); END;
CREATE TRIGGER eventos_compensacion_inmutables_delete BEFORE DELETE ON eventos_compensacion
BEGIN SELECT RAISE(ABORT, 'No se borran eventos de compensación'); END;
CREATE TRIGGER saldo_favor_inmutables_update BEFORE UPDATE ON movimientos_saldo_favor
BEGIN SELECT RAISE(ABORT, 'Los movimientos de saldo a favor son inmutables'); END;
CREATE TRIGGER saldo_favor_inmutables_delete BEFORE DELETE ON movimientos_saldo_favor
BEGIN SELECT RAISE(ABORT, 'No se borran movimientos de saldo a favor'); END;

-- Estado efectivo de cada compensación, derivado de sus eventos.
CREATE VIEW v_compensaciones_estado AS
SELECT c.id AS compensacion_id, c.venta_id, c.tipo, c.importe_cop,
       CASE WHEN c.tipo = 'credito' THEN 'acreditada'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'anulada') THEN 'anulada'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'corregida') THEN 'corregida'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'entregada') THEN 'entregada'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'en_investigacion') THEN 'en_investigacion'
            WHEN EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = c.id AND e.tipo = 'preparada') THEN 'preparada'
            ELSE 'comprometida' END AS estado
FROM compensaciones_cancelacion c;

-- Posición financiera única de una venta (todas las reglas leen de aquí).
CREATE VIEW v_ventas_posicion AS
WITH base AS (
    SELECT v.id AS venta_id, v.cliente_id, v.estado AS estado_almacenado,
           COALESCE((SELECT SUM(d.cantidad * d.precio_unitario_cop) FROM venta_detalles d WHERE d.venta_id = v.id), 0) AS t,
           COALESCE((SELECT SUM(l.importe_reconocido_cop) FROM cancelacion_venta_lineas l
                     JOIN cancelaciones_venta c ON c.id = l.cancelacion_id WHERE c.venta_id = v.id), 0) AS r,
           COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                     FROM pagos_clientes p WHERE p.venta_id = v.id), 0) AS p,
           COALESCE((SELECT -SUM(m.importe_cop) FROM movimientos_saldo_favor m
                     WHERE m.venta_id = v.id AND m.tipo = 'utilizacion'), 0) AS u,
           COALESCE((SELECT SUM(e.importe_cop) FROM v_compensaciones_estado e
                     WHERE e.venta_id = v.id AND e.tipo = 'reembolso' AND e.estado <> 'anulada'), 0) AS c_comprometido,
           COALESCE((SELECT SUM(e.importe_cop) FROM v_compensaciones_estado e
                     WHERE e.venta_id = v.id AND e.tipo = 'reembolso' AND e.estado IN ('entregada', 'corregida')), 0) AS c_entregado,
           COALESCE((SELECT SUM(e.importe_cop) FROM v_compensaciones_estado e
                     WHERE e.venta_id = v.id AND e.tipo = 'credito'), 0) AS g,
           COALESCE((SELECT SUM(d.cantidad) FROM venta_detalles d WHERE d.venta_id = v.id), 0) AS u_vendidas,
           COALESCE((SELECT SUM(l.cantidad_devuelta) FROM cancelacion_venta_lineas l
                     JOIN cancelaciones_venta c ON c.id = l.cancelacion_id WHERE c.venta_id = v.id), 0) AS u_devueltas
    FROM ventas v
)
SELECT *, p + u - (t - r) AS d FROM base;

-- Saldos de venta: ahora descuentan saldo a favor aplicado y compensaciones.
DROP VIEW v_saldos_ventas;
CREATE VIEW v_saldos_ventas AS
SELECT venta_id,
       t AS importe_acordado_cop,
       r AS devuelto_reconocido_cop,
       t - r AS importe_neto_cop,
       p AS pagado_neto_cop,
       u AS saldo_favor_aplicado_cop,
       MAX(0, t - r - p - u) AS saldo_pendiente_cop,
       c_comprometido AS reembolsos_comprometidos_cop,
       c_entregado AS reembolsos_entregados_cop,
       c_comprometido - c_entregado AS reembolso_por_entregar_cop,
       g AS credito_generado_cop,
       MAX(0, d - (c_comprometido + g)) AS sobrepago_pendiente_cop,
       MAX(0, c_entregado - p) AS exceso_reembolsado_cop,
       u_vendidas AS unidades_vendidas,
       u_devueltas AS unidades_devueltas,
       CASE WHEN u_devueltas = 0 THEN 'ninguna'
            WHEN u_devueltas >= u_vendidas THEN 'total'
            ELSE 'parcial' END AS estado_devolucion,
       CASE WHEN estado_almacenado = 'cancelada' THEN 'cancelada'
            WHEN d - (c_comprometido + g) > 0 OR c_comprometido > c_entregado THEN 'reembolso_pendiente'
            WHEN u_vendidas > 0 AND u_devueltas >= u_vendidas AND t - r - p - u <= 0 THEN 'cancelada'
            WHEN t - r - p - u <= 0 THEN 'completada'
            WHEN p + u > 0 THEN 'parcial'
            ELSE 'abierta' END AS estado_cobro
FROM v_ventas_posicion;

CREATE VIEW v_saldos_favor AS
SELECT c.id AS cliente_id,
       COALESCE(SUM(CASE WHEN m.tipo = 'generacion' THEN m.importe_cop END), 0) AS generado_cop,
       COALESCE(-SUM(CASE WHEN m.tipo = 'utilizacion' THEN m.importe_cop END), 0) AS utilizado_cop,
       COALESCE(SUM(CASE WHEN m.tipo = 'ajuste' THEN m.importe_cop END), 0) AS ajustes_cop,
       COALESCE(SUM(m.importe_cop), 0) AS saldo_disponible_cop
FROM clientes c LEFT JOIN movimientos_saldo_favor m ON m.cliente_id = c.id
GROUP BY c.id;

CREATE VIEW v_compensaciones_pendientes AS
SELECT e.compensacion_id, e.venta_id, v.codigo AS venta_codigo, e.importe_cop, e.estado,
       c.registrado_en_utc AS comprometida_en_utc,
       (SELECT x.voucher_codigo FROM eventos_compensacion x
        WHERE x.compensacion_id = e.compensacion_id AND x.tipo = 'preparada') AS voucher_codigo
FROM v_compensaciones_estado e
JOIN compensaciones_cancelacion c ON c.id = e.compensacion_id
JOIN ventas v ON v.id = e.venta_id
WHERE e.tipo = 'reembolso' AND e.estado IN ('comprometida', 'preparada', 'en_investigacion');

-- Compromiso: R2, R3, regla de oro (una entrega en curso por venta) y R8.
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
                  WHERE e.venta_id = NEW.venta_id AND e.estado IN ('preparada', 'en_investigacion'));
    SELECT RAISE(ABORT, 'El método de reembolso no está activo o no aplica a clientes')
    WHERE NEW.tipo = 'reembolso'
      AND NOT EXISTS (SELECT 1 FROM metodos_pago m WHERE m.id = NEW.metodo_pago_id AND m.activo = 1 AND m.aplica_cliente = 1);
    SELECT RAISE(ABORT, 'El crédito que sustituye efectivo requiere consentimiento explícito del cliente')
    WHERE NEW.tipo = 'credito' AND NEW.consentimiento_cliente = 0
      AND NEW.importe_cop > (SELECT u FROM v_ventas_posicion WHERE venta_id = NEW.venta_id);
END;

-- R5: el crédito nace una sola vez por compensación, en la misma transacción.
CREATE TRIGGER compensaciones_generar_credito
AFTER INSERT ON compensaciones_cancelacion WHEN NEW.tipo = 'credito'
BEGIN
    INSERT INTO movimientos_saldo_favor
        (cliente_id, tipo, importe_cop, origen_tipo, origen_id, fecha_negocio, registrado_en_utc,
         motivo, registrado_por, autorizador, clave_idempotencia, huella_solicitud)
    SELECT v.cliente_id, 'generacion', NEW.importe_cop, 'compensacion_venta', NEW.id, NEW.fecha_negocio,
           NEW.registrado_en_utc, NEW.motivo, NEW.responsable_ejecucion, NEW.autorizador,
           'compensacion:' || NEW.id || ':generacion', NEW.huella_solicitud
    FROM ventas v WHERE v.id = NEW.venta_id;
END;

CREATE TRIGGER saldo_favor_validar
BEFORE INSERT ON movimientos_saldo_favor
BEGIN
    SELECT RAISE(ABORT, 'Los ajustes de saldo a favor no están habilitados')
    WHERE NEW.tipo = 'ajuste';
    SELECT RAISE(ABORT, 'El saldo a favor solo se genera desde una compensación de crédito de la misma venta y cliente')
    WHERE NEW.tipo = 'generacion'
      AND NOT EXISTS (SELECT 1 FROM compensaciones_cancelacion c JOIN ventas v ON v.id = c.venta_id
                      WHERE NEW.origen_tipo = 'compensacion_venta' AND c.id = NEW.origen_id AND c.tipo = 'credito'
                        AND c.importe_cop = NEW.importe_cop AND v.cliente_id = NEW.cliente_id);
    SELECT RAISE(ABORT, 'El uso de saldo a favor en órdenes no está habilitado en esta fase')
    WHERE NEW.tipo = 'utilizacion' AND NEW.orden_id IS NOT NULL;
    SELECT RAISE(ABORT, 'La venta no existe o no pertenece al cliente del saldo a favor')
    WHERE NEW.tipo = 'utilizacion'
      AND NOT EXISTS (SELECT 1 FROM ventas v WHERE v.id = NEW.venta_id AND v.cliente_id = NEW.cliente_id
                      AND NEW.origen_tipo = 'venta' AND NEW.origen_id = v.id);
    SELECT RAISE(ABORT, 'La aplicación supera el saldo pendiente de la venta')
    WHERE NEW.tipo = 'utilizacion'
      AND -NEW.importe_cop > (SELECT t - r - p - u FROM v_ventas_posicion WHERE venta_id = NEW.venta_id);
    SELECT RAISE(ABORT, 'El saldo a favor del cliente no puede quedar negativo')
    WHERE COALESCE((SELECT SUM(m.importe_cop) FROM movimientos_saldo_favor m WHERE m.cliente_id = NEW.cliente_id), 0)
          + NEW.importe_cop < 0;
END;

-- Eventos de entrega: voucher, doble entrega, R3 al entregar y estados válidos.
CREATE TRIGGER eventos_compensacion_validar
BEFORE INSERT ON eventos_compensacion
BEGIN
    SELECT RAISE(ABORT, 'Solo los reembolsos tienen eventos de entrega')
    WHERE NOT EXISTS (SELECT 1 FROM compensaciones_cancelacion c WHERE c.id = NEW.compensacion_id AND c.tipo = 'reembolso');
    SELECT RAISE(ABORT, 'La compensación ya fue entregada o anulada')
    WHERE NEW.tipo IN ('preparada', 'en_investigacion', 'entregada', 'anulada')
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
    SELECT RAISE(ABORT, 'Anular o investigar requiere motivo y, para anular, autorizador')
    WHERE (NEW.tipo IN ('anulada', 'en_investigacion', 'corregida') AND length(trim(NEW.motivo)) = 0)
       OR (NEW.tipo IN ('anulada', 'corregida') AND (trim(NEW.autorizador) = '' OR length(trim(NEW.referencia_autorizacion)) = 0));
    SELECT RAISE(ABORT, 'Solo se investiga una entrega preparada')
    WHERE NEW.tipo = 'en_investigacion'
      AND NOT EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo = 'preparada');
    SELECT RAISE(ABORT, 'Solo se corrige una entrega ya registrada')
    WHERE NEW.tipo = 'corregida'
      AND NOT EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo = 'entregada');
END;

-- R4 con saldo a favor: un recibo nuevo no supera lo vendido menos lo devuelto y lo aplicado.
DROP TRIGGER pagos_clientes_no_sobrepagar_venta;
CREATE TRIGGER pagos_clientes_no_sobrepagar_venta
BEFORE INSERT ON pagos_clientes WHEN NEW.tipo = 'recibo' AND NEW.venta_id IS NOT NULL
BEGIN
    SELECT CASE WHEN
        (SELECT p + u FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) + NEW.importe_cop
        > (SELECT t - r FROM v_ventas_posicion WHERE venta_id = NEW.venta_id)
    THEN RAISE(ABORT, 'El pago supera el importe acordado de la venta') END;
END;

-- R6: corregir un registro erróneo no puede dejar compensaciones sin respaldo. Una
-- reversión financiera real se registra siempre (Nota de corrección §2.6); sus efectos
-- (exceso reembolsado, entregas no financiadas bloqueadas) se ven en v_saldos_ventas.
CREATE TRIGGER pagos_clientes_revalidar_compensaciones
BEFORE INSERT ON pagos_clientes
WHEN NEW.tipo = 'reversion' AND NEW.venta_id IS NOT NULL AND NEW.naturaleza_reversion = 'correccion_registro_erroneo'
BEGIN
    SELECT RAISE(ABORT, 'La corrección dejaría compensaciones por encima de lo recibido; anúlalas antes')
    WHERE (SELECT c_comprometido FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) > (SELECT p FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) - NEW.importe_cop
       OR (SELECT c_comprometido + g FROM v_ventas_posicion WHERE venta_id = NEW.venta_id)
          > MAX(0, (SELECT d FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) - NEW.importe_cop);
END;
