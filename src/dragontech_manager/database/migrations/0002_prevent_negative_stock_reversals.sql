-- No permitir que revertir una entrada ya consumida cree inventario negativo.
CREATE TRIGGER movimientos_reversion_no_stock_negativo
BEFORE INSERT ON movimientos_inventario
WHEN NEW.tipo = 'reversion' AND NEW.cantidad_delta < 0
BEGIN
    SELECT CASE WHEN
        COALESCE((SELECT SUM(cantidad_delta)
                  FROM movimientos_inventario
                  WHERE producto_id = NEW.producto_id), 0) + NEW.cantidad_delta < 0
    THEN RAISE(ABORT, 'No se puede revertir una entrada por debajo de la existencia disponible') END;
END;
