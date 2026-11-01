-- Fase 1, Entrega 2: idempotencia de pagos/reversiones de proveedor y de
-- ajustes/reversiones de inventario. Las columnas quedan NULL en filas históricas
-- (inmutables). El servicio exige clave y huella en operaciones nuevas; la base
-- garantiza unicidad de la clave y que clave y huella viajen juntas.

ALTER TABLE pagos_proveedores ADD COLUMN clave_idempotencia TEXT
    CHECK (clave_idempotencia IS NULL OR length(trim(clave_idempotencia)) BETWEEN 1 AND 120);
ALTER TABLE pagos_proveedores ADD COLUMN huella_solicitud TEXT
    CHECK (huella_solicitud IS NULL OR length(huella_solicitud) = 64);
ALTER TABLE movimientos_inventario ADD COLUMN clave_idempotencia TEXT
    CHECK (clave_idempotencia IS NULL OR length(trim(clave_idempotencia)) BETWEEN 1 AND 120);
ALTER TABLE movimientos_inventario ADD COLUMN huella_solicitud TEXT
    CHECK (huella_solicitud IS NULL OR length(huella_solicitud) = 64);

CREATE UNIQUE INDEX uq_pagos_proveedores_clave_idempotencia
    ON pagos_proveedores(clave_idempotencia) WHERE clave_idempotencia IS NOT NULL;
CREATE UNIQUE INDEX uq_movimientos_clave_idempotencia
    ON movimientos_inventario(clave_idempotencia) WHERE clave_idempotencia IS NOT NULL;

CREATE TRIGGER pagos_proveedores_clave_con_huella
BEFORE INSERT ON pagos_proveedores
WHEN (NEW.clave_idempotencia IS NULL) <> (NEW.huella_solicitud IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'La clave de idempotencia y la huella deben registrarse juntas');
END;

CREATE TRIGGER movimientos_clave_con_huella
BEFORE INSERT ON movimientos_inventario
WHEN (NEW.clave_idempotencia IS NULL) <> (NEW.huella_solicitud IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'La clave de idempotencia y la huella deben registrarse juntas');
END;
