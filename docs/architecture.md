# Arquitectura inicial

## Objetivo y alcance

La primera versión es una aplicación de escritorio local de un solo computador. Usa Python 3, PySide6 y SQLite. No requiere servidor ni sincronización entre equipos. La interfaz incluye flujos reales para clientes, equipos y órdenes; cotizaciones/ventas e inventario se muestran como próximamente.

## Capas y dependencias

```text
Interfaz PySide6  ->  Servicios de aplicación  ->  Repositorios SQL  ->  SQLite
         |                      |                         |
         +----------------------+-------------------------+---- pruebas
```

- **Interfaz (`ui/`)**: ventanas, vistas y presentación de errores. Recoge datos y llama servicios; no ejecuta SQL ni calcula reglas financieras.
- **Acceso a datos (`database/`)**: conexiones, migraciones y utilidades SQL. No decide reglas de presentación.
- **Repositorios (`repositories/`)**: SQL parametrizado sobre tablas reales y conversión uniforme de filas a diccionarios. No valida reglas de negocio ni controla transacciones.
- **Servicios (`services/`)**: valida entradas y coordina repositorios, secuencias y transacciones. Hoy cubren clientes, equipos y órdenes. Publican errores de aplicación (`ValidationError`, `NotFoundError`, `ConflictError`, `DataIntegrityError`) sin exponer errores SQL crudos.
- **Dominio (`domain/`)**: tipos, estados y validaciones compartidas cuando el crecimiento del código lo justifique. Evitar clases ceremoniales sin comportamiento.
- **Pruebas (`tests/`)**: pruebas de servicios y persistencia con SQLite temporal o en memoria; pruebas de interfaz solo para comportamientos que aporten valor.

La dependencia apunta hacia dentro: la UI conoce servicios; los servicios usan repositorios; los repositorios conocen SQLite. El dominio no debe depender de PySide6. Las transacciones se inician y confirman en el límite del caso de uso que requiere atomicidad, nunca repartidas entre widgets.

La ventana principal mantiene una conexión SQLite compartida durante su vida y muestra las páginas dentro de un `QStackedWidget`. Los diálogos recopilan entradas, pero la validación de negocio y la escritura permanecen en los servicios. Los cambios de cliente/equipo refrescan la lista y mantienen búsqueda/selección. El detalle de órdenes obtiene datos del servicio, guarda campos técnicos mediante un servicio y aplica transiciones transaccionales. Los errores de validación o integridad se presentan sin cerrar la aplicación.

Los formularios de varios campos usan un área desplazable para conservar controles y etiquetas legibles en ventanas compactas. Las descripciones de órdenes son multilínea, ajustan el texto al ancho del campo y mantienen espacio vertical suficiente. Las opciones de estado se consultan al servicio para la orden específica y la página explica los bloqueos por trabajo pendiente, aprobación o cierre.

El dashboard usa `DashboardService` y una consulta reciente limitada a ocho órdenes. La consulta devuelve datos de cliente/equipo y fecha; la UI no accede directamente a SQLite. La selección y doble clic abren el detalle real, y las acciones rápidas llaman los formularios existentes de alta.

## Estructura actual

```text
src/
└── dragontech_manager/
    ├── __main__.py          # Permite iniciar con python -m dragontech_manager
    ├── app.py               # Inicialización Qt, ruta de datos, migraciones y ventana
    ├── database/
    │   ├── connection.py
    │   ├── migrations.py
    │   ├── sequences.py
    │   ├── transactions.py
    │   └── migrations/
    │       ├── 0001_initial_schema.sql
    │       ├── 0002_prevent_negative_stock_reversals.sql
    │       └── 0003_service_order_status_history.sql
    ├── repositories/
    │   ├── customers.py
    │   ├── equipment.py
    │   ├── service_orders.py
    │   ├── dashboard.py       # Resumen y ocho órdenes recientes como máximo
    │   └── _rows.py
    ├── services/
    │   ├── customers.py
    │   ├── equipment.py
    │   ├── service_orders.py
    │   ├── dashboard.py
    │   ├── errors.py
    │   ├── updates.py         # Consulta opcional de metadatos de releases
    │   └── _common.py
    └── ui/
        ├── main_window.py   # Navegación y contenedor principal
        ├── pages.py         # Dashboard, registros y estados Próximamente
        ├── dialogs.py       # Formularios de alta e historial
        ├── order_details.py # Detalle técnico, transición e historial
        ├── widgets.py       # Tarjetas, estados vacíos y tablas
        ├── update_worker.py # Consulta de red fuera del hilo de UI
        └── theme.py         # Temas oscuro/claro y preferencia
tests/
├── test_database.py         # Garantías básicas de conexión
├── test_database_schema.py  # Esquema, migraciones y reglas SQLite
├── test_services.py         # Casos de uso, dashboard y atomicidad
├── test_ui.py               # Construcción, navegación, edición y formularios Qt
└── test_updates.py          # Manifiestos simulados sin Internet
docs/
├── architecture.md
└── data-model.md
```

El dominio dedicado se añadirá cuando sea necesario; no se crean directorios llenos de archivos vacíos. La base de usuario no se guarda dentro del repositorio: se usa `QStandardPaths.AppDataLocation`. `tests/test_ui.py` selecciona el backend `offscreen` para probar ventanas sin pantalla física; esto verifica construcción e interacción automatizada, no el aspecto visual en un escritorio real.

## Inicio y persistencia

`app.main()` asigna la identidad de organización/aplicación de Qt, recupera la preferencia de tema con `QSettings`, resuelve `AppDataLocation`, crea el directorio si hace falta, abre la base mediante `open_database()` y ejecuta `migrate()`. El primer inicio deja una base vacía con el esquema vigente, sin clientes ficticios. Si el directorio no se puede crear, la ruta no es un archivo regular, o la conexión/migración falla, informa el problema y no elimina ni reinicializa archivos. Información identifica el almacenamiento como local sin exponer su ruta privada.

Ubicaciones típicas (Qt puede variar según configuración): Linux `~/.local/share/DragonTech/DragonTech Manager/`, Windows `%APPDATA%/DragonTech/DragonTech Manager/`, macOS `~/Library/Application Support/DragonTech/DragonTech Manager/`. El archivo se llama `dragontech_manager.sqlite3`.

## SQLite, transacciones y concurrencia

- `open_database()` activa `PRAGMA foreign_keys = ON`, `busy_timeout` y `sqlite3.Row`.
- Una operación que modifica varias tablas usa una sola transacción. Ejemplos: aprobar extras y actualizar el importe acordado, recibir una compra y crear movimientos, o confirmar una entrega y descontar componentes.
- Se prefiere `BEGIN IMMEDIATE` en operaciones críticas de escritura para reservar el escritor antes de leer secuencias o existencias. SQLite serializa escritores; transacciones cortas limitan bloqueos.
- Las tablas aplican `UNIQUE`, `CHECK`, claves foráneas restrictivas y algunos triggers como última defensa además de validaciones de Python.
- Dinero en COP se almacena como entero. No se almacenan saldos calculados como autoridad ni cantidades monetarias en `REAL`.
- Los cambios financieros y movimientos de inventario se corrigen con registros compensatorios trazables, no borrando historia.

## Identificadores y copias de seguridad

Las claves primarias internas son enteros separados de los códigos impresos. La tabla `secuencias` por entidad/año mantiene el próximo ordinal. `allocate_code()` exige una transacción activa; el servicio que cree el registro debe reservar el código y dar de alta la fila en una transacción `BEGIN IMMEDIATE`. Los índices `UNIQUE` en el código visible rechazan cualquier colisión residual.

Los códigos iniciales son `EQ-AAAA-######` y `OS-AAAA-######`. La política es una sola base activa en un computador. Al restaurar una copia se restaura también la tabla de secuencias. Si se reanuda el trabajo desde una copia antigua, comparar su secuencia con el mayor ordinal ya emitido y avanzar la secuencia antes de crear registros. No combinar dos bases activas editables: eso puede colisionar códigos y requiere una futura herramienta de consolidación.

Las copias deben hacerse con la API de backup de SQLite o después de cerrar la aplicación, no copiando a ciegas una base abierta en modo WAL. Al restaurar una copia antigua, validar `PRAGMA integrity_check`, `PRAGMA foreign_key_check` y migrar antes de abrir la aplicación. Las secuencias viajan en la misma base; revisar su ordinal antes de reanudar desde una copia antigua. La rutina de backup/recuperación se implementará en una etapa propia.

## Migraciones

`database/migrations/NNNN_nombre.sql` contiene cambios SQL ordenados y permanentes. `migrate(connection)` requiere una conexión sin transacción externa, registra versión, nombre, SHA-256 y hora UTC en `schema_migrations`. Cada migración corre bajo `BEGIN IMMEDIATE`; DDL y registro de versión se confirman juntos. Una falla revierte esa migración. El ejecutor valida `PRAGMA integrity_check` y `PRAGMA foreign_key_check`, y rechaza cambios en archivos ya aplicados o versiones faltantes. No se editan migraciones publicadas: se agrega un número nuevo. No hay downgrade automático.

`0003_service_order_status_history.sql` agrega el historial inmutable de estados. Para filas antiguas inserta un evento con el estado vigente y anota explícitamente que las transiciones previas no están disponibles; no atribuye un estado anterior ficticio.

## Estado de implementación

Las migraciones `0001`–`0003` crean el esquema y el historial de estados. Clientes/equipos se pueden crear, buscar y editar. Órdenes se pueden abrir, consultar en detalle, completar técnicamente y mover por la ruta documentada en el modelo de datos; la transición de entrega guarda `fecha_entrega` existente y un evento UTC.

### Tema y preferencias

El tema oscuro sigue siendo el predeterminado. Información permite cambiar entre `dark` y `light`; `QSettings` guarda `appearance/theme` y el cambio se aplica a la sesión actual. Las tablas se recargan después del cambio para actualizar colores derivados del tema. No se persisten rutas privadas ni acentos personalizados.

### Canal de actualizaciones

`__version__` en `dragontech_manager/__init__.py` es la única fuente de versión. `git remote -v` no devuelve un remoto y no hay metadatos de publicación, así que `UPDATE_MANIFEST_URL` está sin configurar. El botón informa este estado y no inicia conexiones. Cuando exista un canal HTTPS configurado, el checker usa timeout de cuatro segundos, limita el manifiesto, exige una versión, hash SHA-256, firma declarada y enlace HTTPS en el mismo host; la UI hace la consulta en un `QThread`. El resultado solo ofrece abrir la página de versión: no descarga ni ejecuta archivos. La firma/hash no se verifican criptográficamente en esta etapa, por lo que la función no es autenticación de artefactos ni un instalador.

Cotizaciones/ventas, armado, pagos, aprobación de servicios adicionales e inventario no tienen flujos UI/servicios. Compras/proveedores y gastos tampoco cuentan con casos de uso. El dashboard solo resume órdenes. Backups/restauración, auditoría general, snapshots versionados de datos maestros, informes exportables y empaquetado permanecen pendientes. Las pruebas de UI usan la instalación existente de PySide6, sin nuevas dependencias.
