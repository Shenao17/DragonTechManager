# Arquitectura inicial

## Objetivo y alcance

La primera versión es una aplicación de escritorio local de un solo computador. Usa Python 3, PySide6 y SQLite. No requiere servidor, servicios externos ni sincronización entre equipos. La interfaz que acompaña a este documento es solo un indicador de que el paquete inicia; no define el diseño visual del producto.

## Capas y dependencias

```text
Interfaz PySide6  ->  Servicios de aplicación  ->  Repositorios SQL  ->  SQLite
         |                      |                         |
         +----------------------+-------------------------+---- pruebas
```

- **Interfaz (`ui/`)**: ventanas, vistas y presentación de errores. Recoge datos y llama servicios; no ejecuta SQL ni calcula reglas financieras.
- **Servicios (`services/`)**: casos de uso y reglas de negocio, como aprobar un adicional, registrar un pago o confirmar una salida de inventario. Coordina operaciones atómicas.
- **Acceso a datos (`database/`)**: conexiones, futuras migraciones y repositorios/consultas SQL. No decide reglas de presentación.
- **Dominio (`domain/`)**: tipos, estados y validaciones compartidas cuando el crecimiento del código lo justifique. Evitar clases ceremoniales sin comportamiento.
- **Pruebas (`tests/`)**: pruebas de servicios y persistencia con SQLite temporal o en memoria; pruebas de interfaz solo para comportamientos que aporten valor.

La dependencia apunta hacia dentro: la UI conoce servicios; los servicios usan repositorios; los repositorios conocen SQLite. El dominio no debe depender de PySide6. Las transacciones se inician y confirman en el límite del caso de uso que requiere atomicidad, nunca repartidas entre widgets.

## Estructura inicial

```text
src/dragontech_manager/
├── __main__.py              # Permite iniciar con python -m dragontech_manager
├── app.py                   # Inicialización Qt y ventana provisional
└── database/
    └── connection.py        # Apertura y configuración común de SQLite
tests/
└── test_database.py         # Garantías básicas de conexión y claves foráneas
docs/
├── architecture.md
└── data-model.md
```

Se crearán subpaquetes `services/`, `repositories/`, `domain/` y módulos de UI por área cuando empiece su implementación. No se crean directorios llenos de archivos vacíos. `data/` queda reservado para la base local; los datos reales se excluyen de Git.

## SQLite, transacciones y concurrencia

- Cada conexión activa `PRAGMA foreign_keys = ON` y un `busy_timeout` acotado.
- Una operación que modifica varias tablas usa una sola transacción. Ejemplos: aprobar extras y actualizar el importe acordado, recibir una compra y crear movimientos, o confirmar una entrega y descontar componentes.
- Se prefiere `BEGIN IMMEDIATE` en operaciones críticas de escritura para reservar el escritor antes de leer secuencias o existencias. SQLite serializa escritores; transacciones cortas limitan bloqueos.
- Las tablas tendrán restricciones `UNIQUE`, `CHECK` y claves foráneas como última defensa además de validaciones de Python.
- Dinero en COP se almacena como entero. No se almacenan saldos calculados como autoridad ni cantidades monetarias en `REAL`.
- Los cambios financieros y movimientos de inventario se corrigen con registros compensatorios trazables, no borrando historia.

## Identificadores y copias de seguridad

Las claves primarias internas son enteros separados de los códigos impresos. Una tabla de secuencias por entidad/año mantiene el próximo ordinal. La generación del código, el incremento de secuencia y el alta del registro ocurren en una transacción `BEGIN IMMEDIATE`; índices `UNIQUE` en el código visible resuelven cualquier colisión residual.

Los códigos iniciales son `EQ-AAAA-######` y `OS-AAAA-######`. La política es una sola base activa en un computador. Al restaurar una copia se restaura también la tabla de secuencias. Si se reanuda el trabajo desde una copia antigua, comparar su secuencia con el mayor ordinal ya emitido y avanzar la secuencia antes de crear registros. No combinar dos bases activas editables: eso puede colisionar códigos y requiere una futura herramienta de consolidación.

Las copias deben hacerse con la API de backup de SQLite o después de cerrar la aplicación, no copiando a ciegas una base abierta en modo WAL. La rutina de backup/recuperación se implementará en una etapa propia.

## Estado de implementación

Actualmente se valida el arranque de Qt y la configuración de conexión SQLite. El esquema de negocio, migraciones, repositorios y servicios están pendientes; este documento es diseño, no una promesa de que las tablas ya existan.
