CREATE TABLE historial_estados_orden (
    id INTEGER PRIMARY KEY,
    orden_id INTEGER NOT NULL REFERENCES ordenes_servicio(id) ON DELETE RESTRICT,
    estado_anterior TEXT CHECK (
        estado_anterior IS NULL OR estado_anterior IN (
            'recibida', 'diagnostico', 'espera_aprobacion', 'en_proceso',
            'lista', 'entregada', 'cancelada'
        )
    ),
    estado_nuevo TEXT NOT NULL CHECK (estado_nuevo IN (
        'recibida', 'diagnostico', 'espera_aprobacion', 'en_proceso',
        'lista', 'entregada', 'cancelada'
    )),
    cambiado_en_utc TEXT NOT NULL CHECK (
        strftime('%Y-%m-%dT%H:%M:%SZ', cambiado_en_utc) IS NOT NULL AND
        strftime('%Y-%m-%dT%H:%M:%SZ', cambiado_en_utc) = cambiado_en_utc
    ),
    motivo TEXT NOT NULL DEFAULT '',
    CHECK (estado_anterior IS NULL OR estado_anterior <> estado_nuevo)
);

CREATE INDEX idx_historial_estados_orden
    ON historial_estados_orden(orden_id, cambiado_en_utc, id);

-- El estado actual se conserva como punto de partida, sin fingir que conocemos
-- transiciones ocurridas antes de que existiera este historial.
INSERT INTO historial_estados_orden
    (orden_id, estado_anterior, estado_nuevo, cambiado_en_utc, motivo)
SELECT id, NULL, estado, actualizado_en_utc,
       'Estado vigente al activar el historial; transiciones anteriores no disponibles.'
FROM ordenes_servicio;

CREATE TRIGGER historial_estados_orden_inmutable_update
BEFORE UPDATE ON historial_estados_orden
BEGIN
    SELECT RAISE(ABORT, 'El historial de estados es inmutable');
END;

CREATE TRIGGER historial_estados_orden_inmutable_delete
BEFORE DELETE ON historial_estados_orden
BEGIN
    SELECT RAISE(ABORT, 'El historial de estados no se borra');
END;
