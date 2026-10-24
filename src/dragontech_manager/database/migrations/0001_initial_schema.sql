-- DragonTech Manager: esquema base. Importes COP son INTEGER; tiempos terminan en Z.
CREATE TABLE clientes (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL CHECK (length(trim(nombre)) > 0),
    telefono TEXT,
    whatsapp TEXT,
    correo TEXT,
    notas TEXT NOT NULL DEFAULT '',
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc),
    actualizado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', actualizado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', actualizado_en_utc) = actualizado_en_utc),
    archivado_en_utc TEXT CHECK (archivado_en_utc IS NULL OR (strftime('%Y-%m-%dT%H:%M:%SZ', archivado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', archivado_en_utc) = archivado_en_utc))
);

CREATE INDEX idx_clientes_nombre ON clientes(nombre COLLATE NOCASE);
CREATE INDEX idx_clientes_telefono ON clientes(telefono) WHERE telefono IS NOT NULL;

CREATE TABLE equipos (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE CHECK (
        length(codigo) = 14 AND codigo GLOB 'EQ-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]'
    ),
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (length(trim(tipo)) > 0),
    marca TEXT NOT NULL DEFAULT '',
    modelo TEXT NOT NULL DEFAULT '',
    serial TEXT,
    especificaciones TEXT NOT NULL DEFAULT '',
    accesorios_recibidos TEXT NOT NULL DEFAULT '',
    estado_fisico TEXT NOT NULL DEFAULT '',
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc),
    archivado_en_utc TEXT CHECK (archivado_en_utc IS NULL OR (strftime('%Y-%m-%dT%H:%M:%SZ', archivado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', archivado_en_utc) = archivado_en_utc))
);

CREATE INDEX idx_equipos_cliente ON equipos(cliente_id);
CREATE INDEX idx_equipos_serial ON equipos(serial) WHERE serial IS NOT NULL AND serial <> '';

CREATE TABLE ordenes_servicio (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE CHECK (
        length(codigo) = 14 AND codigo GLOB 'OS-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]'
    ),
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    equipo_id INTEGER NOT NULL REFERENCES equipos(id) ON DELETE RESTRICT,
    recibido_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', recibido_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', recibido_en_utc) = recibido_en_utc),
    fecha_entrega TEXT CHECK (fecha_entrega IS NULL OR (date(fecha_entrega) IS NOT NULL AND date(fecha_entrega) = fecha_entrega)),
    problema_reportado TEXT NOT NULL CHECK (length(trim(problema_reportado)) > 0),
    diagnostico TEXT NOT NULL DEFAULT '',
    trabajo_realizado TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'recibida' CHECK (estado IN ('recibida', 'diagnostico', 'espera_aprobacion', 'en_proceso', 'lista', 'entregada', 'cancelada')),
    tecnico TEXT NOT NULL DEFAULT '',
    importe_inicial_cop INTEGER NOT NULL CHECK (typeof(importe_inicial_cop) = 'integer' AND importe_inicial_cop >= 0),
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc),
    actualizado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', actualizado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', actualizado_en_utc) = actualizado_en_utc)
);

CREATE INDEX idx_orden_estado_fecha ON ordenes_servicio(estado, recibido_en_utc);
CREATE INDEX idx_orden_cliente_fecha ON ordenes_servicio(cliente_id, recibido_en_utc);
CREATE INDEX idx_orden_equipo_fecha ON ordenes_servicio(equipo_id, recibido_en_utc);

CREATE TABLE servicios_adicionales (
    id INTEGER PRIMARY KEY,
    orden_id INTEGER NOT NULL REFERENCES ordenes_servicio(id) ON DELETE RESTRICT,
    descripcion TEXT NOT NULL CHECK (length(trim(descripcion)) > 0),
    importe_propuesto_cop INTEGER NOT NULL CHECK (typeof(importe_propuesto_cop) = 'integer' AND importe_propuesto_cop > 0),
    propuesto_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', propuesto_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', propuesto_en_utc) = propuesto_en_utc)
);

CREATE INDEX idx_adicionales_orden ON servicios_adicionales(orden_id);

CREATE TABLE decisiones_adicional (
    id INTEGER PRIMARY KEY,
    servicio_adicional_id INTEGER NOT NULL REFERENCES servicios_adicionales(id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK (decision IN ('aprobado', 'rechazado')),
    decidido_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', decidido_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', decidido_en_utc) = decidido_en_utc),
    evidencia TEXT NOT NULL CHECK (length(trim(evidencia)) > 0)
);

CREATE INDEX idx_decisiones_adicional_reciente ON decisiones_adicional(servicio_adicional_id, decidido_en_utc DESC, id DESC);
CREATE TRIGGER decisiones_adicional_sin_edicion
BEFORE UPDATE ON decisiones_adicional
BEGIN
    SELECT RAISE(ABORT, 'Las decisiones registradas son inmutables; agregue un nuevo evento');
END;
CREATE TRIGGER decisiones_adicional_sin_borrado
BEFORE DELETE ON decisiones_adicional
BEGIN
    SELECT RAISE(ABORT, 'No se borran decisiones históricas');
END;

CREATE TRIGGER decisiones_adicional_no_reduce_deuda_pagada
BEFORE INSERT ON decisiones_adicional WHEN NEW.decision = 'rechazado'
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM servicios_adicionales s
        JOIN decisiones_adicional previa ON previa.servicio_adicional_id = s.id
        WHERE s.id = NEW.servicio_adicional_id
          AND previa.id = (SELECT d.id FROM decisiones_adicional d
                           WHERE d.servicio_adicional_id = s.id
                           ORDER BY d.decidido_en_utc DESC, d.id DESC LIMIT 1)
          AND previa.decision = 'aprobado'
          AND COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                        FROM pagos_clientes p WHERE p.orden_id = s.orden_id), 0)
              > (SELECT importe_inicial_cop + COALESCE(SUM(
                    CASE WHEN ultima.decision = 'aprobado' AND ad.id <> s.id
                         THEN ad.importe_propuesto_cop ELSE 0 END), 0)
                 FROM ordenes_servicio o
                 LEFT JOIN servicios_adicionales ad ON ad.orden_id = o.id
                 LEFT JOIN decisiones_adicional ultima ON ultima.servicio_adicional_id = ad.id
                    AND ultima.id = (SELECT d.id FROM decisiones_adicional d2
                                     JOIN decisiones_adicional d ON d.id = d2.id
                                     WHERE d2.servicio_adicional_id = ad.id
                                     ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
                 WHERE o.id = s.orden_id)
    ) THEN RAISE(ABORT, 'Revierta el excedente pagado antes de rechazar el adicional') END;
END;

CREATE TABLE productos (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE CHECK (length(trim(sku)) > 0),
    nombre TEXT NOT NULL CHECK (length(trim(nombre)) > 0),
    descripcion TEXT NOT NULL DEFAULT '',
    costo_actual_cop INTEGER NOT NULL DEFAULT 0 CHECK (typeof(costo_actual_cop) = 'integer' AND costo_actual_cop >= 0),
    precio_actual_cop INTEGER NOT NULL DEFAULT 0 CHECK (typeof(precio_actual_cop) = 'integer' AND precio_actual_cop >= 0),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    umbral_reposicion INTEGER CHECK (umbral_reposicion IS NULL OR (typeof(umbral_reposicion) = 'integer' AND umbral_reposicion >= 0)),
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc)
);

CREATE INDEX idx_productos_nombre ON productos(nombre COLLATE NOCASE);

CREATE TABLE orden_repuestos (
    id INTEGER PRIMARY KEY,
    orden_id INTEGER NOT NULL REFERENCES ordenes_servicio(id) ON DELETE RESTRICT,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
    servicio_adicional_id INTEGER REFERENCES servicios_adicionales(id) ON DELETE RESTRICT,
    cantidad INTEGER NOT NULL CHECK (typeof(cantidad) = 'integer' AND cantidad > 0),
    costo_unitario_cop INTEGER NOT NULL CHECK (typeof(costo_unitario_cop) = 'integer' AND costo_unitario_cop >= 0),
    precio_unitario_cop INTEGER NOT NULL CHECK (typeof(precio_unitario_cop) = 'integer' AND precio_unitario_cop >= 0),
    asignado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', asignado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', asignado_en_utc) = asignado_en_utc)
);

CREATE INDEX idx_orden_repuestos_orden ON orden_repuestos(orden_id);
CREATE INDEX idx_orden_repuestos_producto ON orden_repuestos(producto_id);

CREATE TRIGGER orden_repuesto_adicional_aprobado
BEFORE INSERT ON orden_repuestos WHEN NEW.servicio_adicional_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM servicios_adicionales s
        JOIN ordenes_servicio o ON o.id = s.orden_id
        JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
        WHERE s.id = NEW.servicio_adicional_id AND s.orden_id = NEW.orden_id
          AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                      WHERE d2.servicio_adicional_id = s.id
                      ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
          AND d.decision = 'aprobado'
    ) THEN RAISE(ABORT, 'El repuesto requiere un adicional aprobado de la misma orden') END;
END;

CREATE TRIGGER adicional_con_repuesto_no_rechazar
BEFORE INSERT ON decisiones_adicional WHEN NEW.decision = 'rechazado'
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM decisiones_adicional previa
        WHERE previa.servicio_adicional_id = NEW.servicio_adicional_id
          AND previa.id = (SELECT d.id FROM decisiones_adicional d
                           WHERE d.servicio_adicional_id = NEW.servicio_adicional_id
                           ORDER BY d.decidido_en_utc DESC, d.id DESC LIMIT 1)
          AND previa.decision = 'aprobado'
    ) AND EXISTS (
        SELECT 1 FROM orden_repuestos WHERE servicio_adicional_id = NEW.servicio_adicional_id
    ) THEN RAISE(ABORT, 'No rechace un adicional después de asignar repuestos') END;
END;

CREATE TABLE cotizaciones (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    creada_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creada_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creada_en_utc) = creada_en_utc),
    vence_el TEXT CHECK (vence_el IS NULL OR (date(vence_el) IS NOT NULL AND date(vence_el) = vence_el)),
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'enviada', 'aceptada', 'rechazada', 'vencida', 'convertida', 'cancelada')),
    notas TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_cotizaciones_cliente_fecha ON cotizaciones(cliente_id, creada_en_utc);
CREATE INDEX idx_cotizaciones_estado_fecha ON cotizaciones(estado, creada_en_utc);

CREATE TABLE cotizacion_detalles (
    id INTEGER PRIMARY KEY,
    cotizacion_id INTEGER NOT NULL REFERENCES cotizaciones(id) ON DELETE RESTRICT,
    descripcion TEXT NOT NULL CHECK (length(trim(descripcion)) > 0),
    cantidad INTEGER NOT NULL CHECK (typeof(cantidad) = 'integer' AND cantidad > 0),
    precio_unitario_cop INTEGER NOT NULL CHECK (typeof(precio_unitario_cop) = 'integer' AND precio_unitario_cop >= 0),
    costo_unitario_historico_cop INTEGER CHECK (costo_unitario_historico_cop IS NULL OR (typeof(costo_unitario_historico_cop) = 'integer' AND costo_unitario_historico_cop >= 0)),
    producto_id INTEGER REFERENCES productos(id) ON DELETE RESTRICT
);

CREATE INDEX idx_cotizacion_detalles_padre ON cotizacion_detalles(cotizacion_id);

CREATE TABLE armados_pc (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    estado TEXT NOT NULL DEFAULT 'planificado' CHECK (estado IN ('planificado', 'espera_componentes', 'ensamblando', 'pruebas', 'listo', 'entregado', 'cancelado')),
    fecha_inicio_utc TEXT CHECK (fecha_inicio_utc IS NULL OR (strftime('%Y-%m-%dT%H:%M:%SZ', fecha_inicio_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', fecha_inicio_utc) = fecha_inicio_utc)),
    fecha_entrega TEXT CHECK (fecha_entrega IS NULL OR (date(fecha_entrega) IS NOT NULL AND date(fecha_entrega) = fecha_entrega)),
    mano_obra_cop INTEGER NOT NULL DEFAULT 0 CHECK (typeof(mano_obra_cop) = 'integer' AND mano_obra_cop >= 0),
    notas_ensamblaje TEXT NOT NULL DEFAULT '',
    pruebas TEXT NOT NULL DEFAULT '',
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc)
);

CREATE INDEX idx_armados_cliente_estado ON armados_pc(cliente_id, estado);

CREATE TABLE ventas (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    cotizacion_id INTEGER UNIQUE REFERENCES cotizaciones(id) ON DELETE RESTRICT,
    armado_pc_id INTEGER UNIQUE REFERENCES armados_pc(id) ON DELETE RESTRICT,
    fecha_venta TEXT NOT NULL CHECK (date(fecha_venta) IS NOT NULL AND date(fecha_venta) = fecha_venta),
    estado TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'parcial', 'completada', 'cancelada')),
    notas TEXT NOT NULL DEFAULT '',
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc)
);

CREATE INDEX idx_ventas_cliente_fecha ON ventas(cliente_id, fecha_venta);
CREATE INDEX idx_ventas_estado_fecha ON ventas(estado, fecha_venta);

CREATE TABLE armado_componentes (
    id INTEGER PRIMARY KEY,
    armado_id INTEGER NOT NULL REFERENCES armados_pc(id) ON DELETE RESTRICT,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
    cantidad INTEGER NOT NULL CHECK (typeof(cantidad) = 'integer' AND cantidad > 0),
    costo_unitario_historico_cop INTEGER NOT NULL CHECK (typeof(costo_unitario_historico_cop) = 'integer' AND costo_unitario_historico_cop >= 0),
    precio_unitario_cobrado_cop INTEGER NOT NULL CHECK (typeof(precio_unitario_cobrado_cop) = 'integer' AND precio_unitario_cobrado_cop >= 0),
    numero_serie TEXT,
    notas TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_armado_componentes_armado ON armado_componentes(armado_id);
CREATE INDEX idx_armado_componentes_producto ON armado_componentes(producto_id);

CREATE TABLE venta_detalles (
    id INTEGER PRIMARY KEY,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE RESTRICT,
    descripcion TEXT NOT NULL CHECK (length(trim(descripcion)) > 0),
    cantidad INTEGER NOT NULL CHECK (typeof(cantidad) = 'integer' AND cantidad > 0),
    precio_unitario_cop INTEGER NOT NULL CHECK (typeof(precio_unitario_cop) = 'integer' AND precio_unitario_cop >= 0),
    costo_unitario_historico_cop INTEGER CHECK (costo_unitario_historico_cop IS NULL OR (typeof(costo_unitario_historico_cop) = 'integer' AND costo_unitario_historico_cop >= 0)),
    producto_id INTEGER REFERENCES productos(id) ON DELETE RESTRICT
);

CREATE INDEX idx_venta_detalles_padre ON venta_detalles(venta_id);
CREATE INDEX idx_venta_detalles_producto ON venta_detalles(producto_id) WHERE producto_id IS NOT NULL;

CREATE TABLE pagos_clientes (
    id INTEGER PRIMARY KEY,
    orden_id INTEGER REFERENCES ordenes_servicio(id) ON DELETE RESTRICT,
    venta_id INTEGER REFERENCES ventas(id) ON DELETE RESTRICT,
    importe_cop INTEGER NOT NULL CHECK (typeof(importe_cop) = 'integer' AND importe_cop > 0),
    tipo TEXT NOT NULL CHECK (tipo IN ('recibo', 'reversion')),
    metodo TEXT NOT NULL CHECK (length(trim(metodo)) > 0),
    referencia TEXT NOT NULL DEFAULT '',
    registrado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) = registrado_en_utc),
    reversa_pago_id INTEGER UNIQUE REFERENCES pagos_clientes(id) ON DELETE RESTRICT,
    motivo TEXT NOT NULL DEFAULT '',
    CHECK ((orden_id IS NOT NULL) <> (venta_id IS NOT NULL)),
    CHECK ((tipo = 'recibo' AND reversa_pago_id IS NULL) OR
           (tipo = 'reversion' AND reversa_pago_id IS NOT NULL AND length(trim(motivo)) > 0))
);

CREATE INDEX idx_pagos_orden_fecha ON pagos_clientes(orden_id, registrado_en_utc) WHERE orden_id IS NOT NULL;
CREATE INDEX idx_pagos_venta_fecha ON pagos_clientes(venta_id, registrado_en_utc) WHERE venta_id IS NOT NULL;

CREATE TRIGGER pagos_clientes_no_sobrepagar_orden
BEFORE INSERT ON pagos_clientes WHEN NEW.tipo = 'recibo' AND NEW.orden_id IS NOT NULL
BEGIN
    SELECT CASE WHEN
        COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                  FROM pagos_clientes p WHERE p.orden_id = NEW.orden_id), 0) + NEW.importe_cop
        > (SELECT o.importe_inicial_cop + COALESCE(SUM(
              CASE WHEN d.decision = 'aprobado' THEN s.importe_propuesto_cop ELSE 0 END), 0)
           FROM ordenes_servicio o
           LEFT JOIN servicios_adicionales s ON s.orden_id = o.id
           LEFT JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
             AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                         WHERE d2.servicio_adicional_id = s.id
                         ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
           WHERE o.id = NEW.orden_id)
    THEN RAISE(ABORT, 'El pago supera el importe acordado de la orden') END;
END;

CREATE TRIGGER pagos_clientes_no_sobrepagar_venta
BEFORE INSERT ON pagos_clientes WHEN NEW.tipo = 'recibo' AND NEW.venta_id IS NOT NULL
BEGIN
    SELECT CASE WHEN
        COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                  FROM pagos_clientes p WHERE p.venta_id = NEW.venta_id), 0) + NEW.importe_cop
        > COALESCE((SELECT SUM(cantidad * precio_unitario_cop)
                    FROM venta_detalles WHERE venta_id = NEW.venta_id), 0)
    THEN RAISE(ABORT, 'El pago supera el importe acordado de la venta') END;
END;

CREATE TRIGGER pagos_clientes_validar_reversion
BEFORE INSERT ON pagos_clientes WHEN NEW.tipo = 'reversion'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM pagos_clientes original
        WHERE original.id = NEW.reversa_pago_id
          AND original.tipo = 'recibo'
          AND original.importe_cop = NEW.importe_cop
          AND original.orden_id IS NEW.orden_id
          AND original.venta_id IS NEW.venta_id
    ) THEN RAISE(ABORT, 'La reversión debe coincidir con un recibo y su destino') END;
END;

CREATE TRIGGER pagos_clientes_inmutables_update
BEFORE UPDATE ON pagos_clientes
BEGIN
    SELECT RAISE(ABORT, 'Los pagos son inmutables; registre una reversión');
END;
CREATE TRIGGER pagos_clientes_inmutables_delete
BEFORE DELETE ON pagos_clientes
BEGIN
    SELECT RAISE(ABORT, 'No se borran pagos históricos');
END;

CREATE TABLE reservas_inventario (
    id INTEGER PRIMARY KEY,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
    orden_repuesto_id INTEGER UNIQUE REFERENCES orden_repuestos(id) ON DELETE RESTRICT,
    armado_componente_id INTEGER UNIQUE REFERENCES armado_componentes(id) ON DELETE RESTRICT,
    venta_detalle_id INTEGER UNIQUE REFERENCES venta_detalles(id) ON DELETE RESTRICT,
    cantidad INTEGER NOT NULL CHECK (typeof(cantidad) = 'integer' AND cantidad > 0),
    estado TEXT NOT NULL DEFAULT 'reservada' CHECK (estado IN ('reservada', 'liberada', 'consumida')),
    creada_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creada_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creada_en_utc) = creada_en_utc),
    actualizada_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', actualizada_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', actualizada_en_utc) = actualizada_en_utc),
    CHECK ((orden_repuesto_id IS NOT NULL) + (armado_componente_id IS NOT NULL) + (venta_detalle_id IS NOT NULL) = 1)
);

CREATE INDEX idx_reservas_producto_estado ON reservas_inventario(producto_id, estado);

CREATE TRIGGER reservas_validar_origen
BEFORE INSERT ON reservas_inventario
BEGIN
    SELECT CASE WHEN NEW.cantidad > (
        COALESCE((SELECT SUM(cantidad_delta) FROM movimientos_inventario
                  WHERE producto_id = NEW.producto_id), 0)
        - COALESCE((SELECT SUM(cantidad) FROM reservas_inventario
                    WHERE producto_id = NEW.producto_id AND estado = 'reservada'), 0)
    ) THEN RAISE(ABORT, 'No hay existencia disponible suficiente para reservar') END;
    SELECT CASE WHEN NEW.orden_repuesto_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM orden_repuestos WHERE id = NEW.orden_repuesto_id
          AND producto_id = NEW.producto_id AND cantidad = NEW.cantidad
    ) THEN RAISE(ABORT, 'La reserva no coincide con el repuesto de la orden') END;
    SELECT CASE WHEN NEW.armado_componente_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM armado_componentes WHERE id = NEW.armado_componente_id
          AND producto_id = NEW.producto_id AND cantidad = NEW.cantidad
    ) THEN RAISE(ABORT, 'La reserva no coincide con el componente del armado') END;
    SELECT CASE WHEN NEW.venta_detalle_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM venta_detalles WHERE id = NEW.venta_detalle_id
          AND producto_id = NEW.producto_id AND cantidad = NEW.cantidad
    ) THEN RAISE(ABORT, 'La reserva no coincide con el detalle de venta') END;
END;

CREATE TABLE compras (
    id INTEGER PRIMARY KEY,
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id) ON DELETE RESTRICT,
    referencia TEXT NOT NULL DEFAULT '',
    fecha_compra TEXT NOT NULL CHECK (date(fecha_compra) IS NOT NULL AND date(fecha_compra) = fecha_compra),
    fecha_recepcion TEXT CHECK (fecha_recepcion IS NULL OR (date(fecha_recepcion) IS NOT NULL AND date(fecha_recepcion) = fecha_recepcion)),
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'pendiente', 'recibida', 'cancelada')),
    notas TEXT NOT NULL DEFAULT '',
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc)
);

CREATE INDEX idx_compras_proveedor_fecha ON compras(proveedor_id, fecha_compra);
CREATE INDEX idx_compras_estado_fecha ON compras(estado, fecha_compra);

CREATE TABLE compra_detalles (
    id INTEGER PRIMARY KEY,
    compra_id INTEGER NOT NULL REFERENCES compras(id) ON DELETE RESTRICT,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
    cantidad INTEGER NOT NULL CHECK (typeof(cantidad) = 'integer' AND cantidad > 0),
    costo_unitario_historico_cop INTEGER NOT NULL CHECK (typeof(costo_unitario_historico_cop) = 'integer' AND costo_unitario_historico_cop >= 0)
);

CREATE INDEX idx_compra_detalles_compra ON compra_detalles(compra_id);
CREATE INDEX idx_compra_detalles_producto ON compra_detalles(producto_id);

CREATE TABLE proveedores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL CHECK (length(trim(nombre)) > 0),
    identificacion_fiscal TEXT,
    telefono TEXT,
    correo TEXT,
    notas TEXT NOT NULL DEFAULT '',
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc)
);

CREATE INDEX idx_proveedores_nombre ON proveedores(nombre COLLATE NOCASE);

CREATE TABLE pagos_proveedores (
    id INTEGER PRIMARY KEY,
    compra_id INTEGER NOT NULL REFERENCES compras(id) ON DELETE RESTRICT,
    importe_cop INTEGER NOT NULL CHECK (typeof(importe_cop) = 'integer' AND importe_cop > 0),
    tipo TEXT NOT NULL CHECK (tipo IN ('pago', 'reversion')),
    metodo TEXT NOT NULL CHECK (length(trim(metodo)) > 0),
    referencia TEXT NOT NULL DEFAULT '',
    registrado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', registrado_en_utc) = registrado_en_utc),
    reversa_pago_id INTEGER UNIQUE REFERENCES pagos_proveedores(id) ON DELETE RESTRICT,
    motivo TEXT NOT NULL DEFAULT '',
    CHECK ((tipo = 'pago' AND reversa_pago_id IS NULL) OR
           (tipo = 'reversion' AND reversa_pago_id IS NOT NULL AND length(trim(motivo)) > 0))
);

CREATE INDEX idx_pagos_proveedores_compra_fecha ON pagos_proveedores(compra_id, registrado_en_utc);

CREATE TRIGGER pagos_proveedores_no_superar_total
BEFORE INSERT ON pagos_proveedores WHEN NEW.tipo = 'pago'
BEGIN
    SELECT CASE WHEN
        COALESCE((SELECT SUM(CASE WHEN tipo = 'pago' THEN importe_cop ELSE -importe_cop END)
                  FROM pagos_proveedores WHERE compra_id = NEW.compra_id), 0) + NEW.importe_cop
        > COALESCE((SELECT SUM(d.cantidad * d.costo_unitario_historico_cop)
                    FROM compra_detalles d WHERE d.compra_id = NEW.compra_id), 0)
    THEN RAISE(ABORT, 'El pago supera el total documentado de la compra') END;
END;

CREATE TRIGGER compra_detalle_no_editar_con_pagos
BEFORE UPDATE ON compra_detalles WHEN EXISTS (
    SELECT 1 FROM pagos_proveedores p WHERE p.compra_id = OLD.compra_id
)
BEGIN
    SELECT RAISE(ABORT, 'No edite detalles de compra después de registrar pagos');
END;
CREATE TRIGGER compra_detalle_no_borrar_con_pagos
BEFORE DELETE ON compra_detalles WHEN EXISTS (
    SELECT 1 FROM pagos_proveedores p WHERE p.compra_id = OLD.compra_id
)
BEGIN
    SELECT RAISE(ABORT, 'No borre detalles de compra después de registrar pagos');
END;

CREATE TRIGGER pagos_proveedores_validar_reversion
BEFORE INSERT ON pagos_proveedores WHEN NEW.tipo = 'reversion'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM pagos_proveedores original
        WHERE original.id = NEW.reversa_pago_id
          AND original.tipo = 'pago'
          AND original.compra_id = NEW.compra_id
          AND original.importe_cop = NEW.importe_cop
    ) THEN RAISE(ABORT, 'La reversión debe coincidir con el pago y su compra') END;
END;

CREATE TRIGGER pagos_proveedores_inmutables_update
BEFORE UPDATE ON pagos_proveedores
BEGIN
    SELECT RAISE(ABORT, 'Los pagos a proveedores son inmutables; registre una reversión');
END;
CREATE TRIGGER pagos_proveedores_inmutables_delete
BEFORE DELETE ON pagos_proveedores
BEGIN
    SELECT RAISE(ABORT, 'No se borran pagos históricos a proveedores');
END;

CREATE TABLE gastos (
    id INTEGER PRIMARY KEY,
    fecha_gasto TEXT NOT NULL CHECK (date(fecha_gasto) IS NOT NULL AND date(fecha_gasto) = fecha_gasto),
    categoria TEXT NOT NULL CHECK (length(trim(categoria)) > 0),
    descripcion TEXT NOT NULL CHECK (length(trim(descripcion)) > 0),
    importe_cop INTEGER NOT NULL CHECK (typeof(importe_cop) = 'integer' AND importe_cop > 0),
    tipo TEXT NOT NULL DEFAULT 'egreso' CHECK (tipo IN ('egreso', 'reversion')),
    metodo TEXT NOT NULL CHECK (length(trim(metodo)) > 0),
    referencia TEXT NOT NULL DEFAULT '',
    reversa_gasto_id INTEGER UNIQUE REFERENCES gastos(id) ON DELETE RESTRICT,
    motivo TEXT NOT NULL DEFAULT '',
    notas TEXT NOT NULL DEFAULT '',
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc),
    CHECK ((tipo = 'egreso' AND reversa_gasto_id IS NULL) OR
           (tipo = 'reversion' AND reversa_gasto_id IS NOT NULL AND length(trim(motivo)) > 0))
);

CREATE INDEX idx_gastos_fecha_categoria ON gastos(fecha_gasto, categoria);

CREATE TRIGGER gastos_validar_reversion
BEFORE INSERT ON gastos WHEN NEW.tipo = 'reversion'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM gastos original
        WHERE original.id = NEW.reversa_gasto_id AND original.tipo = 'egreso'
          AND original.importe_cop = NEW.importe_cop
          AND original.categoria = NEW.categoria
    ) THEN RAISE(ABORT, 'La reversión debe coincidir con un egreso registrado') END;
END;

CREATE TABLE movimientos_inventario (
    id INTEGER PRIMARY KEY,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE RESTRICT,
    cantidad_delta INTEGER NOT NULL CHECK (typeof(cantidad_delta) = 'integer' AND cantidad_delta <> 0),
    costo_unitario_historico_cop INTEGER NOT NULL CHECK (typeof(costo_unitario_historico_cop) = 'integer' AND costo_unitario_historico_cop >= 0),
    tipo TEXT NOT NULL CHECK (tipo IN ('compra', 'venta', 'orden', 'armado', 'ajuste', 'reversion')),
    compra_detalle_id INTEGER REFERENCES compra_detalles(id) ON DELETE RESTRICT,
    venta_detalle_id INTEGER REFERENCES venta_detalles(id) ON DELETE RESTRICT,
    orden_repuesto_id INTEGER REFERENCES orden_repuestos(id) ON DELETE RESTRICT,
    armado_componente_id INTEGER REFERENCES armado_componentes(id) ON DELETE RESTRICT,
    reversa_movimiento_id INTEGER UNIQUE REFERENCES movimientos_inventario(id) ON DELETE RESTRICT,
    creado_en_utc TEXT NOT NULL CHECK (strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) IS NOT NULL AND strftime('%Y-%m-%dT%H:%M:%SZ', creado_en_utc) = creado_en_utc),
    motivo TEXT NOT NULL DEFAULT '',
    CHECK ((compra_detalle_id IS NOT NULL) + (venta_detalle_id IS NOT NULL) +
           (orden_repuesto_id IS NOT NULL) + (armado_componente_id IS NOT NULL) <= 1),
    CHECK (
        (tipo IN ('compra', 'venta', 'orden', 'armado') AND
         (compra_detalle_id IS NOT NULL OR venta_detalle_id IS NOT NULL OR
          orden_repuesto_id IS NOT NULL OR armado_componente_id IS NOT NULL) AND
         reversa_movimiento_id IS NULL)
        OR (tipo = 'ajuste' AND compra_detalle_id IS NULL AND venta_detalle_id IS NULL AND
            orden_repuesto_id IS NULL AND armado_componente_id IS NULL AND
            reversa_movimiento_id IS NULL AND length(trim(motivo)) > 0)
        OR (tipo = 'reversion' AND compra_detalle_id IS NULL AND venta_detalle_id IS NULL AND
            orden_repuesto_id IS NULL AND armado_componente_id IS NULL AND
            reversa_movimiento_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_movimiento_compra_detalle ON movimientos_inventario(compra_detalle_id) WHERE compra_detalle_id IS NOT NULL;
CREATE UNIQUE INDEX uq_movimiento_venta_detalle ON movimientos_inventario(venta_detalle_id) WHERE venta_detalle_id IS NOT NULL;
CREATE UNIQUE INDEX uq_movimiento_orden_repuesto ON movimientos_inventario(orden_repuesto_id) WHERE orden_repuesto_id IS NOT NULL;
CREATE UNIQUE INDEX uq_movimiento_armado_componente ON movimientos_inventario(armado_componente_id) WHERE armado_componente_id IS NOT NULL;
CREATE INDEX idx_movimientos_producto_fecha ON movimientos_inventario(producto_id, creado_en_utc);

CREATE TRIGGER movimientos_validar_reversion
BEFORE INSERT ON movimientos_inventario WHEN NEW.tipo = 'reversion'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM movimientos_inventario original
        WHERE original.id = NEW.reversa_movimiento_id
          AND original.tipo <> 'reversion'
          AND original.producto_id = NEW.producto_id
          AND original.cantidad_delta = -NEW.cantidad_delta
          AND original.costo_unitario_historico_cop = NEW.costo_unitario_historico_cop
    ) THEN RAISE(ABORT, 'La reversión debe compensar un movimiento del mismo producto') END;
END;

CREATE TRIGGER movimientos_validar_producto_compra
BEFORE INSERT ON movimientos_inventario WHEN NEW.compra_detalle_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.tipo <> 'compra' OR NEW.cantidad_delta <= 0 OR NOT EXISTS (
        SELECT 1 FROM compra_detalles d JOIN compras c ON c.id = d.compra_id
        WHERE d.id = NEW.compra_detalle_id AND d.producto_id = NEW.producto_id
          AND c.estado = 'recibida' AND NEW.cantidad_delta = d.cantidad
          AND NEW.costo_unitario_historico_cop = d.costo_unitario_historico_cop
    ) THEN RAISE(ABORT, 'Movimiento de compra incompatible con su detalle recibido') END;
END;
CREATE TRIGGER movimientos_validar_producto_venta
BEFORE INSERT ON movimientos_inventario WHEN NEW.venta_detalle_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.tipo <> 'venta' OR NEW.cantidad_delta >= 0 OR NOT EXISTS (
        SELECT 1 FROM venta_detalles WHERE id = NEW.venta_detalle_id AND producto_id = NEW.producto_id
          AND COALESCE(costo_unitario_historico_cop, 0) = NEW.costo_unitario_historico_cop
    ) THEN RAISE(ABORT, 'Movimiento de venta incompatible con su detalle') END;
END;
CREATE TRIGGER movimientos_validar_producto_orden
BEFORE INSERT ON movimientos_inventario WHEN NEW.orden_repuesto_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.tipo <> 'orden' OR NEW.cantidad_delta >= 0 OR NOT EXISTS (
        SELECT 1 FROM orden_repuestos WHERE id = NEW.orden_repuesto_id AND producto_id = NEW.producto_id
          AND costo_unitario_cop = NEW.costo_unitario_historico_cop
    ) THEN RAISE(ABORT, 'Movimiento de orden incompatible con su repuesto') END;
END;
CREATE TRIGGER movimientos_validar_producto_armado
BEFORE INSERT ON movimientos_inventario WHEN NEW.armado_componente_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.tipo <> 'armado' OR NEW.cantidad_delta >= 0 OR NOT EXISTS (
        SELECT 1 FROM armado_componentes WHERE id = NEW.armado_componente_id AND producto_id = NEW.producto_id
          AND costo_unitario_historico_cop = NEW.costo_unitario_historico_cop
    ) THEN RAISE(ABORT, 'Movimiento de armado incompatible con su componente') END;
END;

CREATE TRIGGER movimientos_no_exceder_reserva
BEFORE INSERT ON movimientos_inventario
WHEN NEW.tipo IN ('venta', 'orden', 'armado')
BEGIN
    SELECT CASE WHEN -NEW.cantidad_delta > COALESCE((
        SELECT SUM(cantidad_delta) FROM movimientos_inventario WHERE producto_id = NEW.producto_id
    ), 0) THEN RAISE(ABORT, 'La salida supera la existencia física') END;
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM reservas_inventario r
        WHERE r.producto_id = NEW.producto_id AND r.estado = 'reservada'
          AND ((NEW.venta_detalle_id IS NOT NULL AND r.venta_detalle_id = NEW.venta_detalle_id)
            OR (NEW.orden_repuesto_id IS NOT NULL AND r.orden_repuesto_id = NEW.orden_repuesto_id)
            OR (NEW.armado_componente_id IS NOT NULL AND r.armado_componente_id = NEW.armado_componente_id))
          AND r.cantidad = -NEW.cantidad_delta
    ) THEN RAISE(ABORT, 'La salida física requiere una reserva coincidente') END;
END;

CREATE TRIGGER movimientos_consumir_reserva
AFTER INSERT ON movimientos_inventario WHEN NEW.tipo IN ('venta', 'orden', 'armado')
BEGIN
    UPDATE reservas_inventario
       SET estado = 'consumida', actualizada_en_utc = NEW.creado_en_utc
     WHERE estado = 'reservada' AND producto_id = NEW.producto_id
       AND ((NEW.venta_detalle_id IS NOT NULL AND venta_detalle_id = NEW.venta_detalle_id)
         OR (NEW.orden_repuesto_id IS NOT NULL AND orden_repuesto_id = NEW.orden_repuesto_id)
         OR (NEW.armado_componente_id IS NOT NULL AND armado_componente_id = NEW.armado_componente_id));
END;

CREATE TRIGGER movimientos_inmutables_update
BEFORE UPDATE ON movimientos_inventario
BEGIN
    SELECT RAISE(ABORT, 'Los movimientos de inventario son inmutables');
END;
CREATE TRIGGER movimientos_inmutables_delete
BEFORE DELETE ON movimientos_inventario
BEGIN
    SELECT RAISE(ABORT, 'No se borran movimientos de inventario');
END;

CREATE TABLE secuencias (
    entidad TEXT NOT NULL CHECK (entidad IN ('equipo', 'orden_servicio')),
    anio INTEGER NOT NULL CHECK (typeof(anio) = 'integer' AND anio BETWEEN 1 AND 9999),
    siguiente_ordinal INTEGER NOT NULL CHECK (typeof(siguiente_ordinal) = 'integer' AND siguiente_ordinal BETWEEN 1 AND 1000000),
    PRIMARY KEY (entidad, anio)
);

CREATE VIEW v_saldos_ordenes AS
SELECT o.id AS orden_id,
       o.importe_inicial_cop + COALESCE((
           SELECT SUM(s.importe_propuesto_cop)
           FROM servicios_adicionales s
           JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
           WHERE s.orden_id = o.id
             AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                         WHERE d2.servicio_adicional_id = s.id
                         ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
             AND d.decision = 'aprobado'
       ), 0) AS importe_acordado_cop,
       COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                 FROM pagos_clientes p WHERE p.orden_id = o.id), 0) AS pagado_neto_cop,
       o.importe_inicial_cop + COALESCE((
           SELECT SUM(s.importe_propuesto_cop)
           FROM servicios_adicionales s
           JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
           WHERE s.orden_id = o.id
             AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                         WHERE d2.servicio_adicional_id = s.id
                         ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
             AND d.decision = 'aprobado'
       ), 0) - COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                         FROM pagos_clientes p WHERE p.orden_id = o.id), 0) AS saldo_pendiente_cop
FROM ordenes_servicio o;

CREATE VIEW v_saldos_ventas AS
SELECT v.id AS venta_id,
       COALESCE((SELECT SUM(d.cantidad * d.precio_unitario_cop)
                 FROM venta_detalles d WHERE d.venta_id = v.id), 0) AS importe_acordado_cop,
       COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                 FROM pagos_clientes p WHERE p.venta_id = v.id), 0) AS pagado_neto_cop,
       COALESCE((SELECT SUM(d.cantidad * d.precio_unitario_cop)
                 FROM venta_detalles d WHERE d.venta_id = v.id), 0)
       - COALESCE((SELECT SUM(CASE WHEN p.tipo = 'recibo' THEN p.importe_cop ELSE -p.importe_cop END)
                   FROM pagos_clientes p WHERE p.venta_id = v.id), 0) AS saldo_pendiente_cop
FROM ventas v;

CREATE VIEW v_saldos_compras AS
SELECT c.id AS compra_id,
       COALESCE((SELECT SUM(d.cantidad * d.costo_unitario_historico_cop)
                 FROM compra_detalles d WHERE d.compra_id = c.id), 0) AS importe_compra_cop,
       COALESCE((SELECT SUM(CASE WHEN p.tipo = 'pago' THEN p.importe_cop ELSE -p.importe_cop END)
                 FROM pagos_proveedores p WHERE p.compra_id = c.id), 0) AS pagado_neto_cop,
       COALESCE((SELECT SUM(d.cantidad * d.costo_unitario_historico_cop)
                 FROM compra_detalles d WHERE d.compra_id = c.id), 0)
       - COALESCE((SELECT SUM(CASE WHEN p.tipo = 'pago' THEN p.importe_cop ELSE -p.importe_cop END)
                   FROM pagos_proveedores p WHERE p.compra_id = c.id), 0) AS saldo_pendiente_cop
FROM compras c;

CREATE VIEW v_existencias AS
SELECT p.id AS producto_id,
       COALESCE((SELECT SUM(m.cantidad_delta) FROM movimientos_inventario m WHERE m.producto_id = p.id), 0) AS existencia,
       COALESCE((SELECT SUM(r.cantidad) FROM reservas_inventario r
                 WHERE r.producto_id = p.id AND r.estado = 'reservada'), 0) AS reservado,
       COALESCE((SELECT SUM(m.cantidad_delta) FROM movimientos_inventario m WHERE m.producto_id = p.id), 0)
       - COALESCE((SELECT SUM(r.cantidad) FROM reservas_inventario r
                   WHERE r.producto_id = p.id AND r.estado = 'reservada'), 0) AS disponible
FROM productos p;

CREATE VIEW v_gastos_netos AS
SELECT id, fecha_gasto, categoria, descripcion,
       CASE WHEN tipo = 'egreso' THEN importe_cop ELSE -importe_cop END AS importe_neto_cop,
       reversa_gasto_id
FROM gastos;

CREATE TRIGGER detalles_cotizacion_cerrada_sin_edicion
BEFORE UPDATE ON cotizacion_detalles WHEN EXISTS (
    SELECT 1 FROM cotizaciones c WHERE c.id = OLD.cotizacion_id AND c.estado IN ('aceptada', 'convertida')
)
BEGIN
    SELECT RAISE(ABORT, 'No edite detalles de una cotización aceptada o convertida');
END;
CREATE TRIGGER detalles_cotizacion_cerrada_sin_borrado
BEFORE DELETE ON cotizacion_detalles WHEN EXISTS (
    SELECT 1 FROM cotizaciones c WHERE c.id = OLD.cotizacion_id AND c.estado IN ('aceptada', 'convertida')
)
BEGIN
    SELECT RAISE(ABORT, 'No borre detalles de una cotización aceptada o convertida');
END;

CREATE TRIGGER detalles_venta_protegidos_update
BEFORE UPDATE ON venta_detalles WHEN
    EXISTS (SELECT 1 FROM pagos_clientes p WHERE p.venta_id = OLD.venta_id)
    OR EXISTS (SELECT 1 FROM movimientos_inventario m WHERE m.venta_detalle_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'No edite una línea de venta con pagos o movimientos asociados');
END;
CREATE TRIGGER detalles_venta_protegidos_delete
BEFORE DELETE ON venta_detalles WHEN
    EXISTS (SELECT 1 FROM pagos_clientes p WHERE p.venta_id = OLD.venta_id)
    OR EXISTS (SELECT 1 FROM movimientos_inventario m WHERE m.venta_detalle_id = OLD.id)
BEGIN
    SELECT RAISE(ABORT, 'No borre una línea de venta con pagos o movimientos asociados');
END;

CREATE TRIGGER repuesto_con_salida_sin_edicion
BEFORE UPDATE ON orden_repuestos WHEN EXISTS (
    SELECT 1 FROM movimientos_inventario m WHERE m.orden_repuesto_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'No edite repuestos con una salida de inventario registrada');
END;
CREATE TRIGGER repuesto_con_salida_sin_borrado
BEFORE DELETE ON orden_repuestos WHEN EXISTS (
    SELECT 1 FROM movimientos_inventario m WHERE m.orden_repuesto_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'No borre repuestos con una salida de inventario registrada');
END;

CREATE TRIGGER componente_con_salida_sin_edicion
BEFORE UPDATE ON armado_componentes WHEN EXISTS (
    SELECT 1 FROM movimientos_inventario m WHERE m.armado_componente_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'No edite componentes con una salida de inventario registrada');
END;
CREATE TRIGGER componente_con_salida_sin_borrado
BEFORE DELETE ON armado_componentes WHEN EXISTS (
    SELECT 1 FROM movimientos_inventario m WHERE m.armado_componente_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'No borre componentes con una salida de inventario registrada');
END;

CREATE TRIGGER compra_recibida_sin_edicion
BEFORE UPDATE ON compra_detalles WHEN EXISTS (
    SELECT 1 FROM movimientos_inventario m WHERE m.compra_detalle_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'No edite una compra con recepción de inventario registrada');
END;
CREATE TRIGGER compra_recibida_sin_borrado
BEFORE DELETE ON compra_detalles WHEN EXISTS (
    SELECT 1 FROM movimientos_inventario m WHERE m.compra_detalle_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'No borre una compra con recepción de inventario registrada');
END;

CREATE TRIGGER gastos_sin_edicion
BEFORE UPDATE ON gastos
BEGIN
    SELECT RAISE(ABORT, 'Los gastos registrados no se editan en esta versión');
END;
CREATE TRIGGER gastos_sin_borrado
BEFORE DELETE ON gastos
BEGIN
    SELECT RAISE(ABORT, 'No se borran gastos históricos');
END;

CREATE TRIGGER orden_no_reducir_deuda_pagada
BEFORE UPDATE OF importe_inicial_cop ON ordenes_servicio
BEGIN
    SELECT CASE WHEN
        NEW.importe_inicial_cop + COALESCE((
            SELECT SUM(s.importe_propuesto_cop)
            FROM servicios_adicionales s
            JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
            WHERE s.orden_id = OLD.id AND d.decision = 'aprobado'
              AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                          WHERE d2.servicio_adicional_id = s.id
                          ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
        ), 0) < COALESCE((
            SELECT SUM(CASE WHEN tipo = 'recibo' THEN importe_cop ELSE -importe_cop END)
            FROM pagos_clientes WHERE orden_id = OLD.id
        ), 0)
    THEN RAISE(ABORT, 'El nuevo importe dejaría pagos por encima de lo acordado') END;
END;

CREATE TRIGGER adicional_decidido_sin_edicion
BEFORE UPDATE ON servicios_adicionales WHEN EXISTS (
    SELECT 1 FROM decisiones_adicional WHERE servicio_adicional_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'No edite una propuesta después de registrar una decisión');
END;
CREATE TRIGGER adicional_decidido_sin_borrado
BEFORE DELETE ON servicios_adicionales WHEN EXISTS (
    SELECT 1 FROM decisiones_adicional WHERE servicio_adicional_id = OLD.id
)
BEGIN
    SELECT RAISE(ABORT, 'No borre una propuesta con decisiones históricas');
END;

CREATE TRIGGER cotizacion_aceptada_no_reabrir
BEFORE UPDATE OF estado ON cotizaciones WHEN OLD.estado IN ('aceptada', 'convertida') AND NEW.estado <> OLD.estado
BEGIN
    SELECT RAISE(ABORT, 'No reabra una cotización aceptada o convertida');
END;
CREATE TRIGGER detalle_cotizacion_aceptada_no_agregar
BEFORE INSERT ON cotizacion_detalles WHEN EXISTS (
    SELECT 1 FROM cotizaciones WHERE id = NEW.cotizacion_id AND estado IN ('aceptada', 'convertida')
)
BEGIN
    SELECT RAISE(ABORT, 'No agregue detalles a una cotización aceptada o convertida');
END;

CREATE TRIGGER detalle_venta_pagada_no_agregar
BEFORE INSERT ON venta_detalles WHEN EXISTS (
    SELECT 1 FROM pagos_clientes WHERE venta_id = NEW.venta_id
)
BEGIN
    SELECT RAISE(ABORT, 'No agregue líneas a una venta después de recibir pagos');
END;

CREATE TRIGGER reserva_solo_transicion_final
BEFORE UPDATE ON reservas_inventario
WHEN OLD.estado <> 'reservada' OR NEW.estado NOT IN ('liberada', 'consumida')
  OR NEW.id <> OLD.id OR NEW.producto_id <> OLD.producto_id
  OR NEW.orden_repuesto_id IS NOT OLD.orden_repuesto_id
  OR NEW.armado_componente_id IS NOT OLD.armado_componente_id
  OR NEW.venta_detalle_id IS NOT OLD.venta_detalle_id
  OR NEW.cantidad <> OLD.cantidad OR NEW.creada_en_utc <> OLD.creada_en_utc
BEGIN
    SELECT RAISE(ABORT, 'La reserva solo puede pasar una vez a liberada o consumida');
END;
CREATE TRIGGER reservas_sin_borrado
BEFORE DELETE ON reservas_inventario
BEGIN
    SELECT RAISE(ABORT, 'No se borran reservas; márquelas liberadas o consumidas');
END;
