ALTER TABLE cotizaciones
    ADD COLUMN condiciones TEXT NOT NULL DEFAULT '';

CREATE TABLE historial_cotizaciones (
    id INTEGER PRIMARY KEY,
    cotizacion_id INTEGER NOT NULL REFERENCES cotizaciones(id) ON DELETE RESTRICT,
    evento TEXT NOT NULL CHECK (evento IN ('historial_inicial', 'creada', 'editada', 'estado_cambiado')),
    estado_anterior TEXT CHECK (estado_anterior IS NULL OR estado_anterior IN ('borrador', 'enviada', 'aceptada', 'rechazada', 'vencida', 'convertida', 'cancelada')),
    estado_nuevo TEXT NOT NULL CHECK (estado_nuevo IN ('borrador', 'enviada', 'aceptada', 'rechazada', 'vencida', 'convertida', 'cancelada')),
    detalle TEXT NOT NULL DEFAULT '',
    creado_en_utc TEXT NOT NULL CHECK (
        strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL
        AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc
    )
);

CREATE INDEX idx_historial_cotizacion_fecha
    ON historial_cotizaciones(cotizacion_id, creado_en_utc, id);

INSERT INTO historial_cotizaciones
    (cotizacion_id, evento, estado_anterior, estado_nuevo, detalle, creado_en_utc)
SELECT id, 'historial_inicial', NULL, estado,
       'Propuesta preexistente al habilitar el historial; los eventos anteriores no están disponibles.',
       creada_en_utc
FROM cotizaciones;

CREATE TRIGGER historial_cotizaciones_sin_edicion
BEFORE UPDATE ON historial_cotizaciones
BEGIN
    SELECT RAISE(ABORT, 'El historial de cotizaciones es inmutable');
END;

CREATE TRIGGER historial_cotizaciones_sin_borrado
BEFORE DELETE ON historial_cotizaciones
BEGIN
    SELECT RAISE(ABORT, 'No se borra el historial de cotizaciones');
END;
