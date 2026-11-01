-- Fase 1, Entrega 4 (parte A de 0010 del diseño): devoluciones y cancelaciones de
-- ventas. Registra hechos append-only (cabecera + líneas), reintegra al inventario
-- solo lo apto, y deriva el estado de la venta; no hay compensaciones, saldo a favor
-- ni extinción de deuda (Entregas posteriores crearán tablas nuevas que referencian
-- estas, sin modificar esta migración). Invariantes: R1 (cantidades acumuladas) y R4
-- (un pago nuevo no supera lo vendido menos lo devuelto reconocido).

CREATE TABLE cancelaciones_venta (
    id INTEGER PRIMARY KEY,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE RESTRICT,
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
    solicitante TEXT NOT NULL CHECK (length(trim(solicitante)) > 0),
    solicitante_tipo TEXT NOT NULL CHECK (solicitante_tipo IN ('cliente', 'interno')),
    solicitado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', solicitado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', solicitado_en_utc) = solicitado_en_utc),
    responsable_ejecucion TEXT NOT NULL CHECK (length(trim(responsable_ejecucion)) > 0),
    ejecutado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', ejecutado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', ejecutado_en_utc) = ejecutado_en_utc),
    autorizador TEXT NOT NULL DEFAULT '',
    autorizado_en_utc TEXT CHECK (autorizado_en_utc IS NULL OR (strftime('%Y-%m-%dT%H:%M:%SZ', autorizado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', autorizado_en_utc) = autorizado_en_utc)),
    referencia_autorizacion TEXT NOT NULL DEFAULT '',
    fecha_negocio TEXT NOT NULL CHECK (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio),
    clave_idempotencia TEXT NOT NULL UNIQUE CHECK (length(trim(clave_idempotencia)) BETWEEN 1 AND 120),
    huella_solicitud TEXT NOT NULL CHECK (length(huella_solicitud) = 64),
    -- Autorización completa o ausente; el autorizador nunca es quien ejecuta (Informe2 §4.3).
    CHECK ((trim(autorizador) = '' AND autorizado_en_utc IS NULL AND trim(referencia_autorizacion) = '')
        OR (trim(autorizador) <> '' AND autorizado_en_utc IS NOT NULL AND length(trim(referencia_autorizacion)) > 0
            AND lower(trim(autorizador)) <> lower(trim(responsable_ejecucion)))),
    CHECK (fecha_negocio <= date(ejecutado_en_utc, '-5 hours'))
);

CREATE INDEX idx_cancelaciones_venta ON cancelaciones_venta(venta_id, ejecutado_en_utc);

CREATE TABLE cancelacion_venta_lineas (
    id INTEGER PRIMARY KEY,
    cancelacion_id INTEGER NOT NULL REFERENCES cancelaciones_venta(id) ON DELETE RESTRICT,
    venta_detalle_id INTEGER NOT NULL REFERENCES venta_detalles(id) ON DELETE RESTRICT,
    cantidad_devuelta INTEGER NOT NULL CHECK (typeof(cantidad_devuelta) = 'integer' AND cantidad_devuelta > 0),
    cantidad_reintegrada INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(cantidad_reintegrada) = 'integer' AND cantidad_reintegrada >= 0 AND cantidad_reintegrada <= cantidad_devuelta),
    condicion_no_apta TEXT CHECK (condicion_no_apta IS NULL OR condicion_no_apta IN ('danado', 'incompleto', 'no_apto', 'otro')),
    motivo_no_reintegro TEXT NOT NULL DEFAULT '',
    importe_reconocido_cop INTEGER NOT NULL CHECK (typeof(importe_reconocido_cop) = 'integer' AND importe_reconocido_cop >= 0),
    motivo_ajuste_valor TEXT NOT NULL DEFAULT '',
    UNIQUE (cancelacion_id, venta_detalle_id)
);

CREATE INDEX idx_cancelacion_lineas_detalle ON cancelacion_venta_lineas(venta_detalle_id);

ALTER TABLE movimientos_inventario ADD COLUMN devolucion_venta_linea_id INTEGER
    REFERENCES cancelacion_venta_lineas(id) ON DELETE RESTRICT;
CREATE UNIQUE INDEX uq_movimientos_devolucion_linea
    ON movimientos_inventario(devolucion_venta_linea_id) WHERE devolucion_venta_linea_id IS NOT NULL;

CREATE TRIGGER cancelaciones_venta_inmutables_update
BEFORE UPDATE ON cancelaciones_venta
BEGIN
    SELECT RAISE(ABORT, 'Las devoluciones registradas son inmutables');
END;
CREATE TRIGGER cancelaciones_venta_inmutables_delete
BEFORE DELETE ON cancelaciones_venta
BEGIN
    SELECT RAISE(ABORT, 'No se borran devoluciones registradas');
END;
CREATE TRIGGER cancelacion_lineas_inmutables_update
BEFORE UPDATE ON cancelacion_venta_lineas
BEGIN
    SELECT RAISE(ABORT, 'Las líneas de devolución son inmutables');
END;
CREATE TRIGGER cancelacion_lineas_inmutables_delete
BEFORE DELETE ON cancelacion_venta_lineas
BEGIN
    SELECT RAISE(ABORT, 'No se borran líneas de devolución');
END;

-- R1 y reglas de condición/valor por línea.
CREATE TRIGGER cancelacion_lineas_validar
BEFORE INSERT ON cancelacion_venta_lineas
BEGIN
    SELECT RAISE(ABORT, 'La línea no pertenece a la venta de la devolución')
    WHERE NOT EXISTS (
        SELECT 1 FROM venta_detalles d JOIN cancelaciones_venta c ON c.venta_id = d.venta_id
        WHERE d.id = NEW.venta_detalle_id AND c.id = NEW.cancelacion_id);
    SELECT RAISE(ABORT, 'La cantidad devuelta supera lo vendido y aún no devuelto')
    WHERE COALESCE((SELECT SUM(l.cantidad_devuelta) FROM cancelacion_venta_lineas l
                    WHERE l.venta_detalle_id = NEW.venta_detalle_id), 0) + NEW.cantidad_devuelta
          > (SELECT d.cantidad FROM venta_detalles d WHERE d.id = NEW.venta_detalle_id);
    SELECT RAISE(ABORT, 'El valor reconocido no puede superar el precio de lo devuelto')
    WHERE NEW.importe_reconocido_cop
          > NEW.cantidad_devuelta * (SELECT d.precio_unitario_cop FROM venta_detalles d WHERE d.id = NEW.venta_detalle_id);
    SELECT RAISE(ABORT, 'Solo se reintegra inventario de líneas con producto')
    WHERE NEW.cantidad_reintegrada > 0
      AND (SELECT d.producto_id FROM venta_detalles d WHERE d.id = NEW.venta_detalle_id) IS NULL;
    SELECT RAISE(ABORT, 'Las unidades no reintegradas requieren condición y motivo')
    WHERE NEW.cantidad_reintegrada < NEW.cantidad_devuelta
      AND (SELECT d.producto_id FROM venta_detalles d WHERE d.id = NEW.venta_detalle_id) IS NOT NULL
      AND (NEW.condicion_no_apta IS NULL OR length(trim(NEW.motivo_no_reintegro)) = 0);
    SELECT RAISE(ABORT, 'Un valor reconocido menor al precio requiere motivo y autorización')
    WHERE NEW.importe_reconocido_cop
          < NEW.cantidad_devuelta * (SELECT d.precio_unitario_cop FROM venta_detalles d WHERE d.id = NEW.venta_detalle_id)
      AND (length(trim(NEW.motivo_ajuste_valor)) = 0
           OR (SELECT trim(c.autorizador) FROM cancelaciones_venta c WHERE c.id = NEW.cancelacion_id) = '');
END;

-- Un movimiento por línea, solo por lo reintegrado (Informe2 §5.3). Lo no apto no
-- altera existencias: la pérdida se reporta en v_devoluciones_no_reintegradas.
CREATE TRIGGER cancelacion_lineas_reintegrar_inventario
AFTER INSERT ON cancelacion_venta_lineas WHEN NEW.cantidad_reintegrada > 0
BEGIN
    INSERT INTO movimientos_inventario
        (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo, creado_en_utc,
         motivo, fecha_negocio, devolucion_venta_linea_id)
    SELECT d.producto_id, NEW.cantidad_reintegrada,
           COALESCE(d.costo_unitario_historico_cop, p.costo_actual_cop), 'ajuste',
           c.ejecutado_en_utc, 'Devolución de venta ' || v.codigo, c.fecha_negocio, NEW.id
    FROM venta_detalles d
    JOIN cancelaciones_venta c ON c.id = NEW.cancelacion_id
    JOIN ventas v ON v.id = d.venta_id
    JOIN productos p ON p.id = d.producto_id
    WHERE d.id = NEW.venta_detalle_id;
END;

-- I9: el mecanismo genérico no revierte entradas por devolución.
CREATE TRIGGER movimientos_no_revertir_devolucion
BEFORE INSERT ON movimientos_inventario WHEN NEW.tipo = 'reversion'
BEGIN
    SELECT RAISE(ABORT, 'Un movimiento de devolución no se revierte por el mecanismo genérico')
    WHERE EXISTS (SELECT 1 FROM movimientos_inventario o
                  WHERE o.id = NEW.reversa_movimiento_id AND o.devolucion_venta_linea_id IS NOT NULL);
END;

-- R4 / I3: un recibo nuevo no supera lo vendido menos lo devuelto reconocido.
DROP TRIGGER pagos_clientes_no_sobrepagar_venta;
CREATE TRIGGER pagos_clientes_no_sobrepagar_venta
BEFORE INSERT ON pagos_clientes WHEN NEW.tipo = 'recibo' AND NEW.venta_id IS NOT NULL
BEGIN
    SELECT CASE WHEN
        COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                  FROM pagos_clientes p WHERE p.venta_id = NEW.venta_id), 0) + NEW.importe_cop
        > COALESCE((SELECT SUM(cantidad * precio_unitario_cop)
                    FROM venta_detalles WHERE venta_id = NEW.venta_id), 0)
          - COALESCE((SELECT SUM(l.importe_reconocido_cop)
                      FROM cancelacion_venta_lineas l
                      JOIN cancelaciones_venta c ON c.id = l.cancelacion_id
                      WHERE c.venta_id = NEW.venta_id), 0)
    THEN RAISE(ABORT, 'El pago supera el importe acordado de la venta') END;
END;

-- Reversión de pagos de venta: se distingue el registro erróneo (el dinero nunca
-- ingresó) de la reversión financiera real (ingresó y fue revertido), Nota de
-- corrección §2.6. El pago original nunca se modifica.
ALTER TABLE pagos_clientes ADD COLUMN naturaleza_reversion TEXT
    CHECK (naturaleza_reversion IS NULL OR naturaleza_reversion IN ('correccion_registro_erroneo', 'reversion_financiera_real'));
ALTER TABLE pagos_clientes ADD COLUMN origen_evento TEXT
    CHECK (origen_evento IS NULL OR origen_evento IN ('banco', 'operador', 'conciliacion', 'otro'));
ALTER TABLE pagos_clientes ADD COLUMN evidencia_reversion TEXT;

CREATE TRIGGER pagos_clientes_reversion_clasificada
BEFORE INSERT ON pagos_clientes WHEN NEW.tipo = 'reversion' AND NEW.venta_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'La reversión de un pago de venta requiere naturaleza, origen y evidencia')
    WHERE NEW.naturaleza_reversion IS NULL OR NEW.origen_evento IS NULL
       OR NEW.evidencia_reversion IS NULL OR length(trim(NEW.evidencia_reversion)) = 0;
END;

-- Saldos de venta: parten de lo vendido menos lo devuelto reconocido. Con R = 0
-- reproducen exactamente la vista anterior. Sin compensaciones (C = G = U = 0),
-- el sobrepago es P - (T - R); la 0012+ lo descontará de compensaciones.
DROP VIEW v_saldos_ventas;
CREATE VIEW v_saldos_ventas AS
WITH base AS (
    SELECT v.id AS venta_id, v.estado AS estado_almacenado,
           COALESCE((SELECT SUM(d.cantidad * d.precio_unitario_cop)
                     FROM venta_detalles d WHERE d.venta_id = v.id), 0) AS t,
           COALESCE((SELECT SUM(l.importe_reconocido_cop)
                     FROM cancelacion_venta_lineas l
                     JOIN cancelaciones_venta c ON c.id = l.cancelacion_id
                     WHERE c.venta_id = v.id), 0) AS r,
           COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                     FROM pagos_clientes p WHERE p.venta_id = v.id), 0) AS p,
           COALESCE((SELECT SUM(d.cantidad) FROM venta_detalles d WHERE d.venta_id = v.id), 0) AS u_vendidas,
           COALESCE((SELECT SUM(l.cantidad_devuelta)
                     FROM cancelacion_venta_lineas l
                     JOIN cancelaciones_venta c ON c.id = l.cancelacion_id
                     WHERE c.venta_id = v.id), 0) AS u_devueltas
    FROM ventas v
)
SELECT venta_id,
       t AS importe_acordado_cop,
       r AS devuelto_reconocido_cop,
       t - r AS importe_neto_cop,
       p AS pagado_neto_cop,
       MAX(0, t - r - p) AS saldo_pendiente_cop,
       MAX(0, p - (t - r)) AS sobrepago_pendiente_cop,
       u_vendidas AS unidades_vendidas,
       u_devueltas AS unidades_devueltas,
       CASE WHEN u_devueltas = 0 THEN 'ninguna'
            WHEN u_devueltas >= u_vendidas THEN 'total'
            ELSE 'parcial' END AS estado_devolucion,
       CASE WHEN estado_almacenado = 'cancelada' THEN 'cancelada'
            WHEN u_vendidas > 0 AND u_devueltas >= u_vendidas AND p = t - r THEN 'cancelada'
            WHEN p > t - r THEN 'reembolso_pendiente'
            WHEN t - r - p = 0 THEN 'completada'
            WHEN p > 0 THEN 'parcial'
            ELSE 'abierta' END AS estado_cobro
FROM base;

-- Pérdida operativa por unidades devueltas no aptas (Informe2 §5.5). El costo
-- desconocido se informa como NULL; no se estima.
CREATE VIEW v_devoluciones_no_reintegradas AS
SELECT c.venta_id, v.codigo AS venta_codigo, c.id AS cancelacion_id, l.id AS linea_id,
       d.producto_id, p.sku AS producto_sku,
       l.cantidad_devuelta, l.cantidad_reintegrada,
       l.cantidad_devuelta - l.cantidad_reintegrada AS cantidad_no_apta,
       l.condicion_no_apta AS condicion, l.motivo_no_reintegro AS motivo,
       d.costo_unitario_historico_cop * (l.cantidad_devuelta - l.cantidad_reintegrada) AS costo_perdida_cop,
       c.autorizador, c.fecha_negocio
FROM cancelacion_venta_lineas l
JOIN cancelaciones_venta c ON c.id = l.cancelacion_id
JOIN ventas v ON v.id = c.venta_id
JOIN venta_detalles d ON d.id = l.venta_detalle_id
LEFT JOIN productos p ON p.id = d.producto_id
WHERE d.producto_id IS NOT NULL AND l.cantidad_devuelta > l.cantidad_reintegrada;
