# Arquitectura inicial

## Objetivo y alcance

La primera versión es una aplicación de escritorio local de un solo computador. Usa Python 3, PySide6 y SQLite. No requiere servidor, servicios externos ni sincronización entre equipos. La interfaz inicial incluye navegación y flujos reales para clientes, equipos y apertura/consulta de órdenes; los demás módulos se muestran como próximamente.

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

La ventana principal mantiene una conexión SQLite compartida durante su vida y muestra las páginas dentro de un `QStackedWidget`. Los diálogos de alta recopilan entradas, pero la validación de negocio y la escritura permanecen en los servicios. Las páginas recargan datos tras una operación exitosa. Los errores de validación o integridad se presentan sin cerrar la aplicación. No se ofrecen transiciones de estado de órdenes porque todavía no existe una política formal.

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
    │       └── 0002_prevent_negative_stock_reversals.sql
    ├── repositories/
    │   ├── customers.py
    │   ├── equipment.py
    │   ├── service_orders.py
    │   ├── dashboard.py
    │   └── _rows.py
    ├── services/
    │   ├── customers.py
    │   ├── equipment.py
    │   ├── service_orders.py
    │   ├── dashboard.py
    │   ├── errors.py
    │   └── _common.py
    └── ui/
        ├── main_window.py   # Navegación y contenedor principal
        ├── pages.py         # Dashboard, registros y estados Próximamente
        ├── dialogs.py       # Formularios de alta e historial
        ├── widgets.py       # Tarjetas, estados vacíos y tablas
        └── theme.py         # Paleta oscura y estilo Qt
tests/
├── test_database.py         # Garantías básicas de conexión
├── test_database_schema.py  # Esquema, migraciones y reglas SQLite
├── test_services.py         # Casos de uso, dashboard y atomicidad
└── test_ui.py               # Construcción, navegación y formularios Qt
docs/
├── architecture.md
└── data-model.md
```

El dominio dedicado se añadirá cuando sea necesario; no se crean directorios llenos de archivos vacíos. La base de usuario no se guarda dentro del repositorio: se usa `QStandardPaths.AppDataLocation`. `tests/test_ui.py` selecciona el backend `offscreen` para probar ventanas sin pantalla física; esto verifica construcción e interacción automatizada, no el aspecto visual en un escritorio real.

## Inicio y persistencia

`app.main()` asigna la identidad de organización/aplicación de Qt, resuelve `AppDataLocation`, crea el directorio si hace falta, abre la base mediante `open_database()` y ejecuta `migrate()`. El primer inicio deja una base vacía con el esquema vigente, sin clientes ficticios. Si el directorio no se puede crear, la ruta no es un archivo regular, o la conexión/migración falla, informa el problema y no elimina ni reinicializa archivos. La ruta efectiva aparece en Información.

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

## Estado de implementación

Las migraciones `0001_initial_schema.sql` y `0002_prevent_negative_stock_reversals.sql` crean el esquema inicial y añaden una protección de inventario. Existen repositorios/servicios y pantallas funcionales iniciales para clientes, equipos y órdenes, junto con un dashboard de conteos reales. Cotizaciones, ventas, armados, inventario y finanzas no tienen flujos operativos en UI. También están pendientes las transiciones de estado formalizadas, backups/restauración, auditoría y verificación visual en escritorios Linux/Windows. No se han añadido dependencias de prueba de UI: se usa PySide6 ya instalada.
