ALTER TABLE productos
    ADD COLUMN categoria TEXT NOT NULL DEFAULT '';

ALTER TABLE proveedores
    ADD COLUMN direccion TEXT NOT NULL DEFAULT '';

-- Los detalles previos no pueden recuperar un nombre histórico que nunca se guardó.
-- Las filas existentes quedan vacías; los servicios nuevos siempre guardan snapshot.
ALTER TABLE compra_detalles
    ADD COLUMN descripcion_historica TEXT NOT NULL DEFAULT '';

CREATE TRIGGER movimientos_no_stock_negativo
BEFORE INSERT ON movimientos_inventario
WHEN NEW.tipo IN ('ajuste', 'reversion')
BEGIN
    SELECT CASE WHEN
        COALESCE((SELECT SUM(cantidad_delta) FROM movimientos_inventario
                  WHERE producto_id = NEW.producto_id), 0) + NEW.cantidad_delta
        < COALESCE((SELECT SUM(cantidad) FROM reservas_inventario
                    WHERE producto_id = NEW.producto_id AND estado = 'reservada'), 0)
    THEN RAISE(ABORT, 'El movimiento dejaría stock negativo o por debajo de lo reservado') END;
END;

CREATE TRIGGER movimientos_requieren_motivo
BEFORE INSERT ON movimientos_inventario
WHEN length(trim(NEW.motivo)) = 0
BEGIN
    SELECT RAISE(ABORT, 'Todo movimiento de inventario requiere un motivo');
END;

CREATE TRIGGER compras_recibidas_inmutables
BEFORE UPDATE ON compras WHEN OLD.estado = 'recibida'
BEGIN
    SELECT RAISE(ABORT, 'Una compra recibida conserva su historial y no se edita');
END;

CREATE TRIGGER compras_sin_borrado
BEFORE DELETE ON compras
BEGIN
    SELECT RAISE(ABORT, 'No se borran compras históricas');
END;
