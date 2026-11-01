-- Fase 1, Entrega 6 (A): directorio de actores, extinción de deuda (condonación/castigo),
-- recuperaciones H y reversión financiera real. Aprobado por el propietario: A1-A6, B1-B7,
-- ID1-ID6 y PA1-PA6 tal como están recomendadas (Informe3 §7, Nota de corrección §9).
-- Identidad DECLARATIVA (Informe3 §3): el directorio reduce errores y permite segregación por
-- id, pero no autentica a nadie. Las filas anteriores conservan su texto (origen 'legado').
--   N0 = C_e + G - D;  F = H + Q - N0;  H <= MAX(0, N0 - saldo pagable);  Q <= MAX(0, N0 - H).
-- Las vistas v_ventas_posicion y v_saldos_ventas se recrean ampliadas (mismas columnas previas).

CREATE TABLE actores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL CHECK (length(trim(nombre)) > 0),
    documento TEXT,
    rol_operativo TEXT NOT NULL CHECK (rol_operativo IN ('vendedor', 'tecnico', 'cajero', 'supervisor', 'propietario', 'contador', 'otro')),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    puede_autorizar INTEGER NOT NULL DEFAULT 0 CHECK (puede_autorizar IN (0, 1)),
    limite_autorizacion_cop INTEGER CHECK (limite_autorizacion_cop IS NULL OR (typeof(limite_autorizacion_cop) = 'integer' AND limite_autorizacion_cop >= 0)),
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc),
    actualizado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', actualizado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', actualizado_en_utc) = actualizado_en_utc),
    notas TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX uq_actores_nombre ON actores(lower(trim(nombre)));
CREATE TRIGGER actores_sin_borrado BEFORE DELETE ON actores
BEGIN SELECT RAISE(ABORT, 'Los actores no se borran; se desactivan'); END;
CREATE TRIGGER actores_creado_estable BEFORE UPDATE OF creado_en_utc ON actores
BEGIN SELECT RAISE(ABORT, 'La fecha de creación de un actor no se modifica'); END;

-- Columnas de actor en las operaciones anteriores (NULL en filas históricas = origen legado).
ALTER TABLE cancelaciones_venta ADD COLUMN solicitante_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE cancelaciones_venta ADD COLUMN ejecutor_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE cancelaciones_venta ADD COLUMN autorizador_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE cancelaciones_venta ADD COLUMN origen_identidad TEXT CHECK (origen_identidad IS NULL OR origen_identidad IN ('directorio', 'legado', 'sistema'));
ALTER TABLE compensaciones_cancelacion ADD COLUMN ejecutor_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE compensaciones_cancelacion ADD COLUMN autorizador_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE compensaciones_cancelacion ADD COLUMN origen_identidad TEXT CHECK (origen_identidad IS NULL OR origen_identidad IN ('directorio', 'legado', 'sistema'));
ALTER TABLE eventos_compensacion ADD COLUMN registrado_por_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE eventos_compensacion ADD COLUMN autorizador_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE eventos_compensacion ADD COLUMN origen_identidad TEXT CHECK (origen_identidad IS NULL OR origen_identidad IN ('directorio', 'legado', 'sistema'));
ALTER TABLE movimientos_saldo_favor ADD COLUMN registrado_por_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE movimientos_saldo_favor ADD COLUMN origen_identidad TEXT CHECK (origen_identidad IS NULL OR origen_identidad IN ('directorio', 'legado', 'sistema'));
ALTER TABLE pagos_clientes ADD COLUMN ejecutor_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE pagos_clientes ADD COLUMN autorizador_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT;
ALTER TABLE pagos_clientes ADD COLUMN origen_identidad TEXT CHECK (origen_identidad IS NULL OR origen_identidad IN ('directorio', 'legado', 'sistema'));
ALTER TABLE cancelaciones_venta ADD COLUMN medio_autorizacion TEXT CHECK (medio_autorizacion IS NULL OR medio_autorizacion IN ('presencial', 'telefono', 'whatsapp', 'correo', 'documento_firmado', 'otro'));
ALTER TABLE compensaciones_cancelacion ADD COLUMN medio_autorizacion TEXT CHECK (medio_autorizacion IS NULL OR medio_autorizacion IN ('presencial', 'telefono', 'whatsapp', 'correo', 'documento_firmado', 'otro'));
ALTER TABLE pagos_clientes ADD COLUMN medio_autorizacion TEXT CHECK (medio_autorizacion IS NULL OR medio_autorizacion IN ('presencial', 'telefono', 'whatsapp', 'correo', 'documento_firmado', 'otro'));
ALTER TABLE pagos_clientes ADD COLUMN ejecutor_nombre TEXT;
ALTER TABLE pagos_clientes ADD COLUMN autorizador_nombre TEXT;

CREATE TRIGGER cancelaciones_venta_actores
BEFORE INSERT ON cancelaciones_venta
WHEN NEW.ejecutor_id IS NOT NULL OR NEW.autorizador_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'El responsable no existe o está inactivo en el directorio de actores')
    WHERE NEW.ejecutor_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.ejecutor_id AND a.activo = 1);
    SELECT RAISE(ABORT, 'El autorizador no existe, está inactivo o no tiene permiso para autorizar')
    WHERE NEW.autorizador_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id AND a.activo = 1 AND a.puede_autorizar = 1);
    SELECT RAISE(ABORT, 'El autorizador debe ser distinto de quien ejecuta la operación')
    WHERE NEW.autorizador_id IS NOT NULL AND NEW.autorizador_id = NEW.ejecutor_id;
    SELECT RAISE(ABORT, 'Una operación con origen en el directorio requiere el actor responsable')
    WHERE NEW.origen_identidad = 'directorio' AND NEW.ejecutor_id IS NULL;
END;
CREATE TRIGGER compensaciones_actores
BEFORE INSERT ON compensaciones_cancelacion
WHEN NEW.ejecutor_id IS NOT NULL OR NEW.autorizador_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'El responsable no existe o está inactivo en el directorio de actores')
    WHERE NEW.ejecutor_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.ejecutor_id AND a.activo = 1);
    SELECT RAISE(ABORT, 'El autorizador no existe, está inactivo o no tiene permiso para autorizar')
    WHERE NEW.autorizador_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id AND a.activo = 1 AND a.puede_autorizar = 1);
    SELECT RAISE(ABORT, 'El autorizador debe ser distinto de quien ejecuta la operación')
    WHERE NEW.autorizador_id IS NOT NULL AND NEW.autorizador_id = NEW.ejecutor_id;
    SELECT RAISE(ABORT, 'El importe supera el límite de autorización del autorizador (o el actor no tiene límite definido)')
    WHERE NEW.autorizador_id IS NOT NULL AND (NEW.importe_cop) > 0
      AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id
                      AND a.limite_autorizacion_cop IS NOT NULL AND a.limite_autorizacion_cop >= (NEW.importe_cop));
    SELECT RAISE(ABORT, 'Una operación con origen en el directorio requiere el actor responsable')
    WHERE NEW.origen_identidad = 'directorio' AND NEW.ejecutor_id IS NULL;
END;
CREATE TRIGGER eventos_compensacion_actores
BEFORE INSERT ON eventos_compensacion
WHEN NEW.registrado_por_id IS NOT NULL OR NEW.autorizador_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'El responsable no existe o está inactivo en el directorio de actores')
    WHERE NEW.registrado_por_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.registrado_por_id AND a.activo = 1);
    SELECT RAISE(ABORT, 'El autorizador no existe, está inactivo o no tiene permiso para autorizar')
    WHERE NEW.autorizador_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id AND a.activo = 1 AND a.puede_autorizar = 1);
    SELECT RAISE(ABORT, 'El autorizador debe ser distinto de quien ejecuta la operación')
    WHERE NEW.autorizador_id IS NOT NULL AND NEW.autorizador_id = NEW.registrado_por_id;
    SELECT RAISE(ABORT, 'El importe supera el límite de autorización del autorizador (o el actor no tiene límite definido)')
    WHERE NEW.autorizador_id IS NOT NULL AND ((SELECT c.importe_cop FROM compensaciones_cancelacion c WHERE c.id = NEW.compensacion_id)) > 0
      AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id
                      AND a.limite_autorizacion_cop IS NOT NULL AND a.limite_autorizacion_cop >= ((SELECT c.importe_cop FROM compensaciones_cancelacion c WHERE c.id = NEW.compensacion_id)));
    SELECT RAISE(ABORT, 'Una operación con origen en el directorio requiere el actor responsable')
    WHERE NEW.origen_identidad = 'directorio' AND NEW.registrado_por_id IS NULL;
END;
CREATE TRIGGER saldo_favor_actores
BEFORE INSERT ON movimientos_saldo_favor
WHEN NEW.registrado_por_id IS NOT NULL OR NEW.origen_identidad = 'directorio'
BEGIN
    SELECT RAISE(ABORT, 'El responsable no existe o está inactivo en el directorio de actores')
    WHERE NEW.registrado_por_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.registrado_por_id AND a.activo = 1);
    SELECT RAISE(ABORT, 'Una operación con origen en el directorio requiere el actor responsable')
    WHERE NEW.origen_identidad = 'directorio' AND NEW.registrado_por_id IS NULL;
END;
CREATE TRIGGER pagos_clientes_actores
BEFORE INSERT ON pagos_clientes
WHEN NEW.ejecutor_id IS NOT NULL OR NEW.autorizador_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'El responsable no existe o está inactivo en el directorio de actores')
    WHERE NEW.ejecutor_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.ejecutor_id AND a.activo = 1);
    SELECT RAISE(ABORT, 'El autorizador no existe, está inactivo o no tiene permiso para autorizar')
    WHERE NEW.autorizador_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id AND a.activo = 1 AND a.puede_autorizar = 1);
    SELECT RAISE(ABORT, 'El autorizador debe ser distinto de quien ejecuta la operación')
    WHERE NEW.autorizador_id IS NOT NULL AND NEW.autorizador_id = NEW.ejecutor_id;
    SELECT RAISE(ABORT, 'El importe supera el límite de autorización del autorizador (o el actor no tiene límite definido)')
    WHERE NEW.autorizador_id IS NOT NULL AND (NEW.importe_cop) > 0
      AND NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id
                      AND a.limite_autorizacion_cop IS NOT NULL AND a.limite_autorizacion_cop >= (NEW.importe_cop));
    SELECT RAISE(ABORT, 'Una operación con origen en el directorio requiere el actor responsable')
    WHERE NEW.origen_identidad = 'directorio' AND NEW.ejecutor_id IS NULL;
END;

-- ---------------------------------------------------------------------------
-- Extinción de deuda (no mueve caja), anulaciones y recuperaciones H (sí mueven caja
-- pero no son pagos de venta: no aumentan P y no disparan R4).
-- ---------------------------------------------------------------------------
CREATE TABLE extinciones_deuda_venta (
    id INTEGER PRIMARY KEY,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE RESTRICT,
    cancelacion_id INTEGER REFERENCES cancelaciones_venta(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN ('condonacion', 'castigo')),
    importe_cop INTEGER NOT NULL CHECK (typeof(importe_cop) = 'integer' AND importe_cop > 0),
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
    evidencia_cobro TEXT NOT NULL DEFAULT '',
    referencia_autorizacion TEXT NOT NULL CHECK (length(trim(referencia_autorizacion)) > 0),
    medio_autorizacion TEXT NOT NULL CHECK (medio_autorizacion IN ('presencial', 'telefono', 'whatsapp', 'correo', 'documento_firmado', 'otro')),
    autorizador_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    autorizador_nombre TEXT NOT NULL CHECK (length(trim(autorizador_nombre)) > 0),
    autorizado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', autorizado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', autorizado_en_utc) = autorizado_en_utc),
    ejecutor_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    ejecutor_nombre TEXT NOT NULL CHECK (length(trim(ejecutor_nombre)) > 0),
    fecha_negocio TEXT NOT NULL CHECK (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio),
    registrado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) = registrado_en_utc),
    clave_idempotencia TEXT NOT NULL UNIQUE CHECK (length(trim(clave_idempotencia)) BETWEEN 1 AND 120),
    huella_solicitud TEXT NOT NULL CHECK (length(huella_solicitud) = 64),
    CHECK (autorizador_id <> ejecutor_id),
    CHECK (tipo <> 'castigo' OR length(trim(evidencia_cobro)) > 0),
    CHECK (fecha_negocio <= date(registrado_en_utc, '-5 hours'))
);
CREATE INDEX idx_extinciones_venta ON extinciones_deuda_venta(venta_id);

CREATE TABLE anulaciones_extincion_deuda (
    id INTEGER PRIMARY KEY,
    extincion_id INTEGER NOT NULL REFERENCES extinciones_deuda_venta(id) ON DELETE RESTRICT,
    importe_anulado_cop INTEGER NOT NULL CHECK (typeof(importe_anulado_cop) = 'integer' AND importe_anulado_cop > 0),
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
    referencia_autorizacion TEXT NOT NULL CHECK (length(trim(referencia_autorizacion)) > 0),
    medio_autorizacion TEXT NOT NULL CHECK (medio_autorizacion IN ('presencial', 'telefono', 'whatsapp', 'correo', 'documento_firmado', 'otro')),
    autorizador_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    autorizador_nombre TEXT NOT NULL CHECK (length(trim(autorizador_nombre)) > 0),
    ejecutor_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    ejecutor_nombre TEXT NOT NULL CHECK (length(trim(ejecutor_nombre)) > 0),
    fecha_negocio TEXT NOT NULL CHECK (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio),
    anulada_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', anulada_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', anulada_en_utc) = anulada_en_utc),
    clave_idempotencia TEXT NOT NULL UNIQUE CHECK (length(trim(clave_idempotencia)) BETWEEN 1 AND 120),
    huella_solicitud TEXT NOT NULL CHECK (length(huella_solicitud) = 64),
    CHECK (autorizador_id <> ejecutor_id)
);
CREATE INDEX idx_anulaciones_extincion ON anulaciones_extincion_deuda(extincion_id);

CREATE TABLE recuperaciones_deuda_venta (
    id INTEGER PRIMARY KEY,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE RESTRICT,
    importe_cop INTEGER NOT NULL CHECK (typeof(importe_cop) = 'integer' AND importe_cop > 0),
    metodo_pago_id INTEGER NOT NULL REFERENCES metodos_pago(id) ON DELETE RESTRICT,
    referencia TEXT NOT NULL DEFAULT '',
    motivo TEXT NOT NULL CHECK (length(trim(motivo)) > 0),
    referencia_autorizacion TEXT NOT NULL CHECK (length(trim(referencia_autorizacion)) > 0),
    medio_autorizacion TEXT NOT NULL CHECK (medio_autorizacion IN ('presencial', 'telefono', 'whatsapp', 'correo', 'documento_firmado', 'otro')),
    autorizador_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    autorizador_nombre TEXT NOT NULL CHECK (length(trim(autorizador_nombre)) > 0),
    ejecutor_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    ejecutor_nombre TEXT NOT NULL CHECK (length(trim(ejecutor_nombre)) > 0),
    fecha_negocio TEXT NOT NULL CHECK (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio),
    registrado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) = registrado_en_utc),
    clave_idempotencia TEXT NOT NULL UNIQUE CHECK (length(trim(clave_idempotencia)) BETWEEN 1 AND 120),
    huella_solicitud TEXT NOT NULL CHECK (length(huella_solicitud) = 64),
    CHECK (autorizador_id <> ejecutor_id),
    CHECK (fecha_negocio <= date(registrado_en_utc, '-5 hours'))
);
CREATE INDEX idx_recuperaciones_venta ON recuperaciones_deuda_venta(venta_id);

CREATE TRIGGER extinciones_inmutables_update BEFORE UPDATE ON extinciones_deuda_venta
BEGIN SELECT RAISE(ABORT, 'Las extinciones de deuda son inmutables; registre una anulación'); END;
CREATE TRIGGER extinciones_inmutables_delete BEFORE DELETE ON extinciones_deuda_venta
BEGIN SELECT RAISE(ABORT, 'No se borran extinciones de deuda'); END;
CREATE TRIGGER anulaciones_extincion_inmutables_update BEFORE UPDATE ON anulaciones_extincion_deuda
BEGIN SELECT RAISE(ABORT, 'Las anulaciones de extinción son inmutables'); END;
CREATE TRIGGER anulaciones_extincion_inmutables_delete BEFORE DELETE ON anulaciones_extincion_deuda
BEGIN SELECT RAISE(ABORT, 'No se borran anulaciones de extinción'); END;
CREATE TRIGGER recuperaciones_inmutables_update BEFORE UPDATE ON recuperaciones_deuda_venta
BEGIN SELECT RAISE(ABORT, 'Las recuperaciones de deuda son inmutables'); END;
CREATE TRIGGER recuperaciones_inmutables_delete BEFORE DELETE ON recuperaciones_deuda_venta
BEGIN SELECT RAISE(ABORT, 'No se borran recuperaciones de deuda'); END;

-- ---------------------------------------------------------------------------
-- Vistas: posición única ampliada (N0, H, Q) y saldos. Se recrean con las columnas previas.
-- ---------------------------------------------------------------------------
DROP VIEW v_saldos_ventas;
DROP VIEW v_ventas_posicion;
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
                     JOIN cancelaciones_venta c ON c.id = l.cancelacion_id WHERE c.venta_id = v.id), 0) AS u_devueltas,
           COALESCE((SELECT SUM(x.importe_cop) FROM extinciones_deuda_venta x WHERE x.venta_id = v.id AND x.tipo = 'condonacion'), 0)
             - COALESCE((SELECT SUM(a.importe_anulado_cop) FROM anulaciones_extincion_deuda a
                         JOIN extinciones_deuda_venta x ON x.id = a.extincion_id
                         WHERE x.venta_id = v.id AND x.tipo = 'condonacion'), 0) AS k,
           COALESCE((SELECT SUM(x.importe_cop) FROM extinciones_deuda_venta x WHERE x.venta_id = v.id AND x.tipo = 'castigo'), 0)
             - COALESCE((SELECT SUM(a.importe_anulado_cop) FROM anulaciones_extincion_deuda a
                         JOIN extinciones_deuda_venta x ON x.id = a.extincion_id
                         WHERE x.venta_id = v.id AND x.tipo = 'castigo'), 0) AS w,
           COALESCE((SELECT SUM(h.importe_cop) FROM recuperaciones_deuda_venta h WHERE h.venta_id = v.id), 0) AS h
    FROM ventas v
), pos AS (
    SELECT *, p + u - (t - r) AS d, k + w AS q FROM base
), liq AS (
    SELECT *, c_entregado + g - d AS n0 FROM pos
)
SELECT *,
       MAX(0, MIN(t - r - p - u, n0 - h - q)) AS pagable
FROM liq;

CREATE VIEW v_saldos_ventas AS
SELECT venta_id,
       t AS importe_acordado_cop,
       r AS devuelto_reconocido_cop,
       t - r AS importe_neto_cop,
       p AS pagado_neto_cop,
       u AS saldo_favor_aplicado_cop,
       pagable AS saldo_pendiente_cop,
       c_comprometido AS reembolsos_comprometidos_cop,
       c_entregado AS reembolsos_entregados_cop,
       c_comprometido - c_entregado AS reembolso_por_entregar_cop,
       g AS credito_generado_cop,
       MAX(0, d - (c_comprometido + g)) AS sobrepago_pendiente_cop,
       MAX(0, c_entregado - p) AS exceso_reembolsado_cop,
       MAX(0, c_comprometido - p) AS compromisos_sin_respaldo_cop,
       u_vendidas AS unidades_vendidas,
       u_devueltas AS unidades_devueltas,
       CASE WHEN u_devueltas = 0 THEN 'ninguna'
            WHEN u_devueltas >= u_vendidas THEN 'total'
            ELSE 'parcial' END AS estado_devolucion,
       MAX(0, n0) AS deuda_bruta_cop,
       h AS recuperado_cop,
       k AS condonado_cop,
       w AS castigado_cop,
       MAX(0, n0 - h - q) AS deuda_pendiente_cop,
       h + q - n0 AS residuo_liquidacion_cop,
       CASE WHEN h + q - n0 > 0 THEN 'pendiente_reembolso'
            WHEN c_comprometido > c_entregado THEN 'pendiente_reembolso'
            WHEN n0 - h - q > 0 THEN CASE WHEN p + u + h > 0 THEN 'cobro_parcial' ELSE 'pendiente_cobro' END
            WHEN q > 0 AND w = 0 THEN 'condonada'
            WHEN q > 0 AND k = 0 THEN 'castigada'
            ELSE 'liquidada' END AS estado_liquidacion,
       CASE WHEN u_vendidas > 0 AND u_devueltas >= u_vendidas THEN
                 CASE WHEN n0 - h - q > 0 THEN
                           CASE WHEN c_entregado > p THEN 'cancelada_con_deuda_por_reversion' ELSE 'cancelada_con_deuda' END
                      WHEN h + q - n0 > 0 OR c_comprometido > c_entregado THEN 'cancelada_con_reembolso_pendiente'
                      ELSE 'cancelada_liquidada' END
            ELSE 'abierta' END AS estado_comercial,
       CASE WHEN estado_almacenado = 'cancelada' THEN 'cancelada'
            WHEN d - (c_comprometido + g) > 0 OR c_comprometido > c_entregado THEN 'reembolso_pendiente'
            WHEN n0 - h - q > 0 AND pagable = 0 THEN 'deuda_pendiente'
            WHEN u_vendidas > 0 AND u_devueltas >= u_vendidas AND n0 - h - q <= 0 THEN 'cancelada'
            WHEN pagable = 0 THEN 'completada'
            WHEN p + u > 0 THEN 'parcial'
            ELSE 'abierta' END AS estado_cobro
FROM v_ventas_posicion;

-- ---------------------------------------------------------------------------
-- Triggers de extinción y recuperación (R9, R14, PA3) y de pagos / crédito (R4 + R9).
-- ---------------------------------------------------------------------------
CREATE TRIGGER extinciones_validar
BEFORE INSERT ON extinciones_deuda_venta
BEGIN
    SELECT RAISE(ABORT, 'El ejecutor no existe o está inactivo en el directorio de actores')
    WHERE NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.ejecutor_id AND a.activo = 1);
    SELECT RAISE(ABORT, 'El autorizador no existe, está inactivo o no tiene permiso para autorizar')
    WHERE NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id AND a.activo = 1 AND a.puede_autorizar = 1);
    SELECT RAISE(ABORT, 'El importe supera el límite de autorización del autorizador (o el actor no tiene límite definido)')
    WHERE NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id
                      AND a.limite_autorizacion_cop IS NOT NULL AND a.limite_autorizacion_cop >= NEW.importe_cop);
    SELECT RAISE(ABORT, 'La devolución indicada no pertenece a la venta')
    WHERE NEW.cancelacion_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM cancelaciones_venta c WHERE c.id = NEW.cancelacion_id AND c.venta_id = NEW.venta_id);
    SELECT RAISE(ABORT, 'La extinción supera la deuda pendiente de la venta')
    WHERE NEW.importe_cop > COALESCE((SELECT MAX(0, n0 - h - q) FROM v_ventas_posicion WHERE venta_id = NEW.venta_id), 0);
END;

CREATE TRIGGER anulaciones_extincion_validar
BEFORE INSERT ON anulaciones_extincion_deuda
BEGIN
    SELECT RAISE(ABORT, 'El ejecutor no existe o está inactivo en el directorio de actores')
    WHERE NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.ejecutor_id AND a.activo = 1);
    SELECT RAISE(ABORT, 'El autorizador no existe, está inactivo o no tiene permiso para autorizar')
    WHERE NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id AND a.activo = 1 AND a.puede_autorizar = 1);
    SELECT RAISE(ABORT, 'La anulación supera lo extinguido y aún no anulado')
    WHERE NEW.importe_anulado_cop
          > (SELECT x.importe_cop FROM extinciones_deuda_venta x WHERE x.id = NEW.extincion_id)
            - COALESCE((SELECT SUM(a.importe_anulado_cop) FROM anulaciones_extincion_deuda a WHERE a.extincion_id = NEW.extincion_id), 0);
END;

CREATE TRIGGER recuperaciones_validar
BEFORE INSERT ON recuperaciones_deuda_venta
BEGIN
    SELECT RAISE(ABORT, 'El ejecutor no existe o está inactivo en el directorio de actores')
    WHERE NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.ejecutor_id AND a.activo = 1);
    SELECT RAISE(ABORT, 'El autorizador no existe, está inactivo o no tiene permiso para autorizar')
    WHERE NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id AND a.activo = 1 AND a.puede_autorizar = 1);
    SELECT RAISE(ABORT, 'El importe supera el límite de autorización del autorizador (o el actor no tiene límite definido)')
    WHERE NOT EXISTS (SELECT 1 FROM actores a WHERE a.id = NEW.autorizador_id
                      AND a.limite_autorizacion_cop IS NOT NULL AND a.limite_autorizacion_cop >= NEW.importe_cop);
    SELECT RAISE(ABORT, 'El método de cobro no está activo o no aplica a clientes')
    WHERE NOT EXISTS (SELECT 1 FROM metodos_pago m WHERE m.id = NEW.metodo_pago_id AND m.activo = 1 AND m.aplica_cliente = 1);
    -- H solo cubre la deuda que NO cabe en un pago normal de la venta (Nota §5.4) y H + Q <= deuda bruta.
    SELECT RAISE(ABORT, 'La recuperación solo cubre la deuda que excede el saldo cobrable como pago de venta')
    WHERE (SELECT h FROM v_ventas_posicion WHERE venta_id = NEW.venta_id) + NEW.importe_cop
          > MAX(0, (SELECT n0 - MAX(0, t - r - p - u) FROM v_ventas_posicion WHERE venta_id = NEW.venta_id));
    SELECT RAISE(ABORT, 'La recuperación superaría la deuda pendiente de la venta')
    WHERE NEW.importe_cop > COALESCE((SELECT MAX(0, n0 - h - q) FROM v_ventas_posicion WHERE venta_id = NEW.venta_id), 0);
END;

-- R4 + R9: un pago nuevo no supera el saldo cobrable (que ya descuenta crédito, devoluciones y extinciones).
DROP TRIGGER pagos_clientes_no_sobrepagar_venta;
CREATE TRIGGER pagos_clientes_no_sobrepagar_venta
BEFORE INSERT ON pagos_clientes WHEN NEW.tipo = 'recibo' AND NEW.venta_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.importe_cop > (SELECT pagable FROM v_ventas_posicion WHERE venta_id = NEW.venta_id)
    THEN RAISE(ABORT, 'El pago supera el importe acordado de la venta') END;
END;

-- Mismo cálculo para aplicar saldo a favor (0012 recreado con el saldo cobrable ampliado).
DROP TRIGGER saldo_favor_validar;
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
      AND -NEW.importe_cop > (SELECT pagable FROM v_ventas_posicion WHERE venta_id = NEW.venta_id);
    SELECT RAISE(ABORT, 'El saldo a favor del cliente no puede quedar negativo')
    WHERE COALESCE((SELECT SUM(m.importe_cop) FROM movimientos_saldo_favor m WHERE m.cliente_id = NEW.cliente_id), 0)
          + NEW.importe_cop < 0;
END;

-- Eventos de entrega (0012) con una excepción: la anulación generada por el sistema tras una
-- reversión financiera real no exige autorizador (origen 'sistema'); una entrega 'preparada'
-- NUNCA se anula automáticamente (Informe3 §2.5).
DROP TRIGGER eventos_compensacion_validar;
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
       OR (NEW.tipo IN ('anulada', 'corregida') AND COALESCE(NEW.origen_identidad, '') <> 'sistema'
           AND (trim(NEW.autorizador) = '' OR length(trim(NEW.referencia_autorizacion)) = 0));
    SELECT RAISE(ABORT, 'La anulación automática solo aplica a compromisos sin preparar')
    WHERE NEW.origen_identidad = 'sistema' AND NEW.tipo = 'anulada'
      AND EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo IN ('preparada', 'en_investigacion'));
    SELECT RAISE(ABORT, 'Solo se investiga una entrega preparada')
    WHERE NEW.tipo = 'en_investigacion'
      AND NOT EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo = 'preparada');
    SELECT RAISE(ABORT, 'Solo se corrige una entrega ya registrada')
    WHERE NEW.tipo = 'corregida'
      AND NOT EXISTS (SELECT 1 FROM eventos_compensacion e WHERE e.compensacion_id = NEW.compensacion_id AND e.tipo = 'entregada');
END;

-- Reversión financiera real: se registra siempre (0010) y, aquí, el sistema anula los
-- compromisos SIN preparar que ya no estén respaldados, del más reciente al más antiguo,
-- hasta que C_comprometido quepa en P. Los preparados/en investigación se conservan
-- (el dinero pudo haber salido) y quedan bloqueados para entrega por R3.
CREATE TRIGGER pagos_clientes_reversion_real_anula_pendientes
AFTER INSERT ON pagos_clientes
WHEN NEW.tipo = 'reversion' AND NEW.venta_id IS NOT NULL AND NEW.naturaleza_reversion = 'reversion_financiera_real'
BEGIN
    INSERT INTO eventos_compensacion
        (compensacion_id, tipo, ocurrido_en_utc, registrado_en_utc, registrado_por, motivo,
         clave_idempotencia, huella_solicitud, origen_identidad)
    SELECT c.id, 'anulada', NEW.registrado_en_utc, NEW.registrado_en_utc, 'Sistema',
           'Anulación automática por reversión financiera real del pago ' || NEW.reversa_pago_id,
           'reversion:' || NEW.id || ':anula:' || c.id, printf('%064x', c.id), 'sistema'
    FROM compensaciones_cancelacion c
    JOIN v_compensaciones_estado e ON e.compensacion_id = c.id
    JOIN v_ventas_posicion pos ON pos.venta_id = c.venta_id
    WHERE c.venta_id = NEW.venta_id AND c.tipo = 'reembolso' AND e.estado = 'comprometida'
      AND pos.c_comprometido > pos.p
      AND COALESCE((SELECT SUM(c2.importe_cop) FROM compensaciones_cancelacion c2
                    JOIN v_compensaciones_estado e2 ON e2.compensacion_id = c2.id
                    WHERE c2.venta_id = c.venta_id AND c2.tipo = 'reembolso' AND e2.estado = 'comprometida'
                      AND c2.id > c.id), 0) < pos.c_comprometido - pos.p;
END;
