-- Fase 1, Entrega 1: catálogo de métodos de pago y fecha de negocio.
-- No reescribe filas históricas (los pagos y movimientos son inmutables): las
-- columnas nuevas quedan NULL en lo antiguo y las vistas v_*_contables resuelven
-- el legado. La fecha de negocio es el día local de Bogotá (UTC-5, sin horario
-- de verano); el instante UTC sigue siendo la fecha técnica.

CREATE TABLE metodos_pago (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE CHECK (length(trim(codigo)) > 0 AND codigo = upper(codigo)),
    nombre TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(nombre)) > 0),
    familia TEXT NOT NULL CHECK (familia IN ('efectivo', 'transferencia', 'tarjeta', 'otro', 'sin_clasificar')),
    aplica_cliente INTEGER NOT NULL DEFAULT 1 CHECK (aplica_cliente IN (0, 1)),
    aplica_proveedor INTEGER NOT NULL DEFAULT 1 CHECK (aplica_proveedor IN (0, 1)),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    legado INTEGER NOT NULL DEFAULT 0 CHECK (legado IN (0, 1)),
    orden INTEGER NOT NULL DEFAULT 100 CHECK (typeof(orden) = 'integer'),
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc)
);

CREATE TABLE metodos_pago_alias (
    id INTEGER PRIMARY KEY,
    alias_normalizado TEXT NOT NULL UNIQUE CHECK (length(alias_normalizado) > 0 AND alias_normalizado = lower(trim(alias_normalizado))),
    metodo_pago_id INTEGER NOT NULL REFERENCES metodos_pago(id) ON DELETE RESTRICT
);

CREATE INDEX idx_metodos_pago_alias_metodo ON metodos_pago_alias(metodo_pago_id);

INSERT INTO metodos_pago (codigo, nombre, familia, aplica_cliente, aplica_proveedor, activo, legado, orden, creado_en_utc) VALUES
    ('EFECTIVO',      'Efectivo',      'efectivo',       1, 1, 1, 0, 10, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('TRANSFERENCIA', 'Transferencia', 'transferencia',  1, 1, 1, 0, 20, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('TARJETA',       'Tarjeta',       'tarjeta',        1, 1, 1, 0, 30, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ('OTRO',          'Otro',          'otro',           1, 1, 1, 0, 90, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- CSX aparece en pagos reales a proveedores; su naturaleza no está confirmada (Informe2 P1).
    ('CSX',           'CSX',           'sin_clasificar', 0, 1, 1, 1, 95, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));

INSERT INTO metodos_pago_alias (alias_normalizado, metodo_pago_id)
SELECT a.alias, m.id
FROM (
    SELECT 'efectivo' AS alias, 'EFECTIVO' AS codigo UNION ALL
    SELECT 'transferencia', 'TRANSFERENCIA' UNION ALL
    SELECT 'transferencia bancaria', 'TRANSFERENCIA' UNION ALL
    SELECT 'tarjeta', 'TARJETA' UNION ALL
    SELECT 'tarjeta de débito', 'TARJETA' UNION ALL
    SELECT 'tarjeta de crédito', 'TARJETA' UNION ALL
    SELECT 'otro', 'OTRO' UNION ALL
    SELECT 'csx', 'CSX'
) AS a
JOIN metodos_pago m ON m.codigo = a.codigo;

CREATE TRIGGER metodos_pago_sin_borrado
BEFORE DELETE ON metodos_pago
BEGIN
    SELECT RAISE(ABORT, 'Los métodos de pago no se borran; se desactivan');
END;

CREATE TRIGGER metodos_pago_identidad_estable
BEFORE UPDATE OF codigo, nombre, familia, creado_en_utc ON metodos_pago
BEGIN
    SELECT RAISE(ABORT, 'Código, nombre y familia de un método de pago no se modifican');
END;

CREATE TRIGGER metodos_pago_alias_inmutables_update
BEFORE UPDATE ON metodos_pago_alias
BEGIN
    SELECT RAISE(ABORT, 'Los alias de métodos de pago son inmutables');
END;

CREATE TRIGGER metodos_pago_alias_inmutables_delete
BEFORE DELETE ON metodos_pago_alias
BEGIN
    SELECT RAISE(ABORT, 'Los alias de métodos de pago no se borran');
END;

-- Columnas nuevas (NULL en filas históricas).
ALTER TABLE pagos_clientes ADD COLUMN metodo_pago_id INTEGER REFERENCES metodos_pago(id) ON DELETE RESTRICT;
ALTER TABLE pagos_clientes ADD COLUMN fecha_negocio TEXT CHECK (fecha_negocio IS NULL OR (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio));
ALTER TABLE pagos_proveedores ADD COLUMN metodo_pago_id INTEGER REFERENCES metodos_pago(id) ON DELETE RESTRICT;
ALTER TABLE pagos_proveedores ADD COLUMN fecha_negocio TEXT CHECK (fecha_negocio IS NULL OR (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio));
ALTER TABLE movimientos_inventario ADD COLUMN fecha_negocio TEXT CHECK (fecha_negocio IS NULL OR (date(fecha_negocio) IS NOT NULL AND date(fecha_negocio) = fecha_negocio));

CREATE INDEX idx_pagos_clientes_fecha_negocio ON pagos_clientes(fecha_negocio) WHERE fecha_negocio IS NOT NULL;
CREATE INDEX idx_pagos_clientes_metodo ON pagos_clientes(metodo_pago_id) WHERE metodo_pago_id IS NOT NULL;
CREATE INDEX idx_pagos_proveedores_fecha_negocio ON pagos_proveedores(fecha_negocio) WHERE fecha_negocio IS NOT NULL;
CREATE INDEX idx_pagos_proveedores_metodo ON pagos_proveedores(metodo_pago_id) WHERE metodo_pago_id IS NOT NULL;
CREATE INDEX idx_movimientos_fecha_negocio ON movimientos_inventario(fecha_negocio) WHERE fecha_negocio IS NOT NULL;

-- Filas nuevas: fecha de negocio obligatoria y no posterior al día de Bogotá del registro.
-- Los recibos/pagos exigen un método activo aplicable; las reversiones lo heredan por servicio.
CREATE TRIGGER pagos_clientes_metodo_y_fecha
BEFORE INSERT ON pagos_clientes
BEGIN
    SELECT RAISE(ABORT, 'La fecha de negocio del pago es obligatoria')
    WHERE NEW.fecha_negocio IS NULL;
    SELECT RAISE(ABORT, 'La fecha de negocio no puede ser posterior al día local del registro')
    WHERE NEW.fecha_negocio > date(NEW.registrado_en_utc, '-5 hours');
    SELECT RAISE(ABORT, 'El método de pago es obligatorio, debe estar activo y aplicar a clientes')
    WHERE NEW.tipo = 'recibo'
      AND NOT EXISTS (SELECT 1 FROM metodos_pago
                      WHERE id = NEW.metodo_pago_id AND activo = 1 AND aplica_cliente = 1);
    SELECT RAISE(ABORT, 'El texto del método no coincide con el catálogo')
    WHERE NEW.metodo_pago_id IS NOT NULL
      AND NEW.metodo <> (SELECT nombre FROM metodos_pago WHERE id = NEW.metodo_pago_id);
END;

CREATE TRIGGER pagos_proveedores_metodo_y_fecha
BEFORE INSERT ON pagos_proveedores
BEGIN
    SELECT RAISE(ABORT, 'La fecha de negocio del pago es obligatoria')
    WHERE NEW.fecha_negocio IS NULL;
    SELECT RAISE(ABORT, 'La fecha de negocio no puede ser posterior al día local del registro')
    WHERE NEW.fecha_negocio > date(NEW.registrado_en_utc, '-5 hours');
    SELECT RAISE(ABORT, 'El método de pago es obligatorio, debe estar activo y aplicar a proveedores')
    WHERE NEW.tipo = 'pago'
      AND NOT EXISTS (SELECT 1 FROM metodos_pago
                      WHERE id = NEW.metodo_pago_id AND activo = 1 AND aplica_proveedor = 1);
    SELECT RAISE(ABORT, 'El texto del método no coincide con el catálogo')
    WHERE NEW.metodo_pago_id IS NOT NULL
      AND NEW.metodo <> (SELECT nombre FROM metodos_pago WHERE id = NEW.metodo_pago_id);
END;

CREATE TRIGGER movimientos_fecha_negocio_obligatoria
BEFORE INSERT ON movimientos_inventario
BEGIN
    SELECT RAISE(ABORT, 'La fecha de negocio del movimiento es obligatoria')
    WHERE NEW.fecha_negocio IS NULL;
    SELECT RAISE(ABORT, 'La fecha de negocio no puede ser posterior al día local del registro')
    WHERE NEW.fecha_negocio > date(NEW.creado_en_utc, '-5 hours');
END;

-- Vistas contables: unifican filas nuevas y legado sin reescribir historia.
CREATE VIEW v_pagos_clientes_contables AS
SELECT p.*,
       COALESCE(p.fecha_negocio, date(p.registrado_en_utc, '-5 hours')) AS fecha_negocio_efectiva,
       p.fecha_negocio IS NULL AS fecha_derivada,
       COALESCE(p.metodo_pago_id,
                (SELECT a.metodo_pago_id FROM metodos_pago_alias a
                 WHERE a.alias_normalizado = lower(trim(p.metodo)))) AS metodo_pago_id_efectivo
FROM pagos_clientes p;

CREATE VIEW v_pagos_proveedores_contables AS
SELECT p.*,
       COALESCE(p.fecha_negocio, date(p.registrado_en_utc, '-5 hours')) AS fecha_negocio_efectiva,
       p.fecha_negocio IS NULL AS fecha_derivada,
       COALESCE(p.metodo_pago_id,
                (SELECT a.metodo_pago_id FROM metodos_pago_alias a
                 WHERE a.alias_normalizado = lower(trim(p.metodo)))) AS metodo_pago_id_efectivo
FROM pagos_proveedores p;

CREATE VIEW v_movimientos_contables AS
SELECT m.*,
       COALESCE(m.fecha_negocio, date(m.creado_en_utc, '-5 hours')) AS fecha_negocio_efectiva,
       m.fecha_negocio IS NULL AS fecha_derivada
FROM movimientos_inventario m;
