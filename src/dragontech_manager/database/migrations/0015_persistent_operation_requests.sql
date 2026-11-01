-- Fase 1 (pendientes, bloque 3): solicitudes de operación persistentes (Informe2 §3.2-3.5) e
-- idempotencia persistente completa en pagos de cliente (huella, Informe2 I4). La intención
-- se registra en su propia transacción ANTES de ejecutar y se completa en la misma
-- transacción del negocio; sobrevive a un cierre inesperado. No reescribe filas históricas.

CREATE TABLE solicitudes_operacion (
    id INTEGER PRIMARY KEY,
    clave_idempotencia TEXT NOT NULL UNIQUE CHECK (length(trim(clave_idempotencia)) BETWEEN 1 AND 120),
    tipo_operacion TEXT NOT NULL CHECK (length(trim(tipo_operacion)) > 0),
    huella_solicitud TEXT NOT NULL CHECK (length(huella_solicitud) = 64),
    estado TEXT NOT NULL CHECK (estado IN ('pendiente', 'completada', 'abandonada')),
    entidad_tipo TEXT,
    entidad_id INTEGER,
    solicitado_por TEXT NOT NULL CHECK (length(trim(solicitado_por)) > 0),
    creada_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creada_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creada_en_utc) = creada_en_utc),
    completada_en_utc TEXT CHECK (completada_en_utc IS NULL OR (strftime('%Y-%m-%dT%H:%M:%SZ', completada_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', completada_en_utc) = completada_en_utc)),
    detalle TEXT NOT NULL DEFAULT '',
    -- Resumen legible y carga útil canónica (JSON) para poder reintentar tras un reinicio.
    resumen TEXT NOT NULL DEFAULT '',
    carga_util TEXT NOT NULL DEFAULT '{}',
    CHECK ((estado = 'completada' AND entidad_tipo IS NOT NULL AND entidad_id IS NOT NULL AND completada_en_utc IS NOT NULL)
        OR (estado = 'pendiente' AND entidad_tipo IS NULL AND entidad_id IS NULL AND completada_en_utc IS NULL)
        OR (estado = 'abandonada' AND entidad_tipo IS NULL AND entidad_id IS NULL))
);
CREATE INDEX idx_solicitudes_estado ON solicitudes_operacion(estado, creada_en_utc);

CREATE TRIGGER solicitudes_operacion_sin_borrado BEFORE DELETE ON solicitudes_operacion
BEGIN SELECT RAISE(ABORT, 'Las solicitudes de operación no se borran'); END;

-- Solo una solicitud pendiente cambia, y solo de estado/entidad/detalle.
CREATE TRIGGER solicitudes_operacion_transicion BEFORE UPDATE ON solicitudes_operacion
BEGIN
    SELECT RAISE(ABORT, 'Una solicitud completada o abandonada ya no admite cambios')
    WHERE OLD.estado <> 'pendiente';
    SELECT RAISE(ABORT, 'Clave, tipo, huella, solicitante y carga de una solicitud son inmutables')
    WHERE NEW.clave_idempotencia <> OLD.clave_idempotencia OR NEW.tipo_operacion <> OLD.tipo_operacion
       OR NEW.huella_solicitud <> OLD.huella_solicitud OR NEW.solicitado_por <> OLD.solicitado_por
       OR NEW.creada_en_utc <> OLD.creada_en_utc OR NEW.carga_util <> OLD.carga_util OR NEW.resumen <> OLD.resumen;
END;

ALTER TABLE pagos_clientes ADD COLUMN huella_solicitud TEXT
    CHECK (huella_solicitud IS NULL OR length(huella_solicitud) = 64);

-- Los recibos nuevos con clave llevan huella (los históricos con clave sin huella se respetan).
CREATE TRIGGER pagos_clientes_clave_con_huella
BEFORE INSERT ON pagos_clientes
WHEN NEW.huella_solicitud IS NOT NULL AND NEW.clave_idempotencia IS NULL
BEGIN
    SELECT RAISE(ABORT, 'La huella de la solicitud requiere su clave de idempotencia');
END;
