# Informe2 - Diseño Fase 1 (Revisión)

**Proyecto:** DragonTech Manager  
**Fecha:** 2026-10-31  
**Estado:** revisión de diseño. No se implementó ninguna entrega.  
**Base de la revisión:** Informe2 original, esquema v7, 143 pruebas aprobadas y evidencias recopiladas durante la revisión. No se repitieron auditorías ni pruebas.

---

## 0. Resumen ejecutivo

La revisión confirma que la dirección general del Informe2 es correcta, pero corrige seis puntos que podían producir decisiones ambiguas o controles insuficientes:

1. **Invariante financiera:** `C + G + (T − R) ≤ P + U` es la condición correcta de “no ganancia para el cliente”, pero es **necesaria y no suficiente**. Debe:
   - aplicarse solo a compensaciones, nunca como condición para aceptar una devolución;
   - expresarse como `C + G ≤ MAX(0, D)` con `D = P + U − (T − R)`;
   - complementarse con `C ≤ P` para impedir que se pague efectivo por valor que ingresó como saldo a favor;
   - usar el valor **reconocido** de la devolución, no necesariamente el precio de lista;
   - contar compensaciones **comprometidas** (pendientes + confirmadas), no solo las confirmadas;
   - revalidarse ante una reversión de pago, porque es la única operación que reduce `D`.
2. **Idempotencia durable:** una clave UUID en memoria no sobrevive al cierre de la aplicación. Se propone un registro persistente de intenciones (`solicitudes_operacion`) escrito antes de ejecutar, una ejecución atómica única y un esquema de dos fases para efectos externos (entrega de efectivo o transferencia).
3. **Roles:** se separan explícitamente `solicitante`, `responsable_ejecucion` y `autorizador`, con marcas de tiempo y una regla de segregación de funciones. Sin un módulo de usuarios no se puede verificar identidad; queda documentado como pendiente.
4. **Devoluciones no aptas:** se reemplaza el booleano “reintegrar inventario” por cantidad reintegrada + condición + valor reconocido + motivo, con reporte de pérdida y autorización cuando corresponda.
5. **Ledger de saldo a favor:** se rediseña con origen genérico (`origen_tipo`/`origen_id`) y referencias opcionales a venta y orden, de modo que pueda usarse en órdenes de servicio sin reconstruir la tabla.
6. **Inconsistencias adicionales:** se documentan 16 hallazgos comprobados entre SQL, triggers, servicios, vistas y UI, con su disposición (Fase 1, Fase 2 o pendiente de validación).

Además, se demuestra matemáticamente que **las devoluciones parciales válidas no quedan impedidas** por la invariante; lo que la invariante limita es la compensación. El caso que podía parecer un bloqueo es una devolución parcial sin sobrepago, donde no corresponde compensar.

---

## 1. Evidencia utilizada

No se realizaron nuevas auditorías generales. Se usan los hallazgos ya comprobados:

- Esquema real en versión 7; `integrity_check = ok`; sin violaciones de claves foráneas.
- 143 pruebas aprobadas al cierre de Fase 0.
- Datos reales: 1 venta, 3 pagos de cliente, 3 movimientos de inventario, 5 órdenes, 2 compras.
- Métodos de pago existentes: cliente `Efectivo` y `Tarjeta`; proveedor `CSX`, `EFECTIVO`, `TRANSFERENCIA`.
- `ventas`, `venta_detalles` y `pagos_clientes` son inmutables por triggers.
- `pagos_clientes` tiene `clave_idempotencia` única, pero no `huella_solicitud`.
- `pagos_proveedores` y `movimientos_inventario` no tienen idempotencia.
- `movimientos_inventario.tipo` no admite un tipo nuevo sin reconstruir la tabla.
- No existe ledger de saldo a favor, tabla de devoluciones ni catálogo de métodos.
- No existe tabla de usuarios/autenticación.

Cuando una conclusión depende de un dato no verificado, se marca **Pendiente de validación**.

---

## 2. Invariantes financieras: corrección y demostración

### 2.1 Definiciones

Para una venta concreta:

| Símbolo | Significado |
|---|---|
| `T` | Valor total vendido: `Σ cantidad × precio_unitario` de `venta_detalles`. |
| `R` | Valor **reconocido** de lo devuelto: suma de `cancelacion_venta_lineas.importe_reconocido_cop`. Por defecto es el precio completo; puede ser menor por condición del producto, con motivo y autorización. |
| `P` | Dinero neto recibido: recibos menos reversiones en `pagos_clientes` (efectivo, transferencia, tarjeta). No incluye saldo a favor. |
| `U` | Saldo a favor aplicado a esta venta: suma de movimientos `utilizacion` asociados a la venta. |
| `C` | Reembolsos **comprometidos**: compensaciones `reembolso` en estado pendiente o confirmado. Excluye anuladas. |
| `G` | Saldo a favor **generado** por esta venta: compensaciones `credito`. |
| `C_conf` | Reembolsos efectivamente confirmados (entrega realizada). Se usa para reportes de caja, no para el tope. |
| `D` | Posición neta del cliente: `P + U − (T − R)`. Si `D > 0`, el cliente pagó de más; si `D < 0`, aún debe `−D`. |

### 2.2 La regla original: qué es correcta y qué le falta

La regla original:

```text
C + G + (T − R) ≤ P + U
```

es algebraicamente equivalente a:

```text
C + G ≤ D
```

Es la condición de **no ganancia**: el cliente no puede terminar con bienes retenidos más compensaciones por encima de lo que entregó (dinero + saldo a favor). Es correcta como tope de compensación.

Pero es **insuficiente** y puede interpretarse mal:

1. **No incluye `C ≤ P`.** Permite pagar efectivo por valor que ingresó como saldo a favor.
   - Ejemplo: `T=1000`, `P=0`, `U=1000`, `R=1000`. `D=1000`. La regla original permite `C=1000, G=0`: `1000 + 0 + 0 ≤ 0 + 1000`. Sin embargo, sería un reembolso en efectivo sin haber recibido efectivo. Viola la naturaleza del saldo a favor.
2. **No distingue devolución de compensación.** Si se usa como precondición para registrar la devolución, bloquea devoluciones parciales válidas con `D < 0`.
   - Ejemplo: `T=1000`, `P=200`, `R=700`. `D = 200 − 300 = −100`. La devolución es válida: el cliente retiene bienes por 300 y aún debe 100. No hay compensación. La desigualdad no se cumple, pero eso no debe impedir la devolución.
3. **No usa `MAX(0, D)`.** Con `D < 0`, la regla se vuelve una condición imposible para cualquier compensación positiva; es correcto que no haya compensación, pero debe expresarse explícitamente.
4. **No distingue comprometido de confirmado.** Un reembolso pendiente ya reserva dinero y debe contar para el tope; si solo se contara el confirmado, se podría comprometer dos veces el mismo efectivo.
5. **Usa `R` sin definir.** Si el producto devuelto está dañado y se reconoce un valor menor, `R` debe ser el valor reconocido, no el precio de lista.
6. **No cubre la reversión de pagos.** Una reversión reduce `P` y por tanto `D`; puede invalidar una compensación ya registrada.

### 2.3 Invariantes corregidas

Se reemplaza la regla única por este conjunto:

| ID | Invariante | Ámbito |
|---|---|---|
| **R1** | `0 ≤ R ≤ T`. La devolución se permite siempre que queden cantidades vendidas, independientemente de `P`, `U` o `D`. | Devolución |
| **R2** | `C + G ≤ MAX(0, D)`, con `D = P + U − (T − R)`. | Compensación |
| **R3** | `C ≤ P`. Ningún reembolso en efectivo/banco/tarjeta puede superar el dinero neto recibido. | Compensación |
| **R3b** | Recomendado: `C_efectivo ≤ P_efectivo` por familia de método, salvo autorización expresa. | Política de caja |
| **R4** | Un **nuevo** pago o una **nueva** aplicación de saldo a favor no puede hacer que `P + U` supere `T − R`. Es una restricción de flujo, no de estado. | Pagos / crédito |
| **R5** | `G` solo nace de una compensación `credito`, con una generación única por compensación. El saldo del cliente nunca es negativo. | Ledger |
| **R6** | Una reversión de pago debe seguir cumpliendo `C + G ≤ P_nuevo + U − (T − R)` y `C ≤ P_nuevo`. | Reversión |
| **R7** | En una `cancelacion_total`, debe quedar `C + G = D` y `sobrepago_pendiente = 0`. En una devolución parcial se puede dejar pendiente, pero debe mostrarse. | Cierre |
| **R8** | Si `G > U`, la parte de crédito que sustituye efectivo requiere consentimiento explícito del cliente y autorización. | Política |

**Nota sobre R4:** `P + U ≤ T − R` no es una invariante de estado. Después de una devolución es normal que `P + U > T − R`; esa diferencia es precisamente `D`, el sobrepago a compensar. R4 solo impide **nuevos** pagos o aplicaciones de crédito que aumenten el sobrepago.

### 2.4 Propiedades matemáticas

Derivando `D = P + U − T + R`:

| Operación | Efecto sobre `D` | Consecuencia |
|---|---|---|
| Nueva devolución (`R` aumenta) | `+ΔR` | `D` aumenta; una devolución nunca invalida una compensación previa. |
| Nuevo pago (`P` aumenta) | `+ΔP` | Solo se permite mientras `D < 0`; lleva `D` hacia 0 y nunca lo supera (R4). |
| Aplicación de crédito (`U` aumenta) | `+ΔU` | Igual que el pago; no puede crear sobrepago. |
| Reversión de pago (`P` disminuye) | `−ΔP` | Puede invalidar una compensación previa; requiere R6. |
| Ajuste de crédito del cliente | No cambia `U` de la venta | No afecta `D`; afecta el saldo global. |

**Teorema:** antes de cualquier devolución, `D ≤ 0`; el sobrepago solo nace de una devolución. Por tanto, `C + G > 0` exige al menos una devolución registrada. Esto coincide con la regla de negocio: no se compensa lo que no se ha devuelto.

**Corolario:** como `R` solo aumenta, una devolución posterior no puede reducir `D`. El único riesgo de invalidar una compensación es una reversión de pago; de ahí R6.

### 2.5 Escenarios numéricos

Todos los valores están en COP. `C` es comprometido (pendiente o confirmado). “Válido” significa que la operación puede registrarse.

| # | `T` | `P` | `U` | `R` | `D` | `C` | `G` | Resultado | Explicación |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| A | 1000 | 1000 | 0 | 300 | 300 | 300 | 0 | **Válido** | Cliente retiene 700 y recibe 300. Total 1000. |
| B | 1000 | 1000 | 0 | 300 | 300 | 200 | 100 | **Válido** | Mixto: 200 efectivo + 100 crédito. |
| C | 1000 | 1000 | 0 | 300 | 300 | 400 | 0 | **Inválido** | `C > D`: el cliente terminaría con 1100 de valor. |
| D | 1000 | 800 | 0 | 300 | 100 | 100 | 0 | **Válido** | Retiene 700; pagó 800; se devuelve 100. |
| E | 1000 | 0 | 1000 | 1000 | 1000 | 1000 | 0 | **Inválido** | La regla original lo permite, pero `C > P`: reembolso en efectivo sin efectivo recibido. Correcto: `C=0, G=1000`. |
| F | 1000 | 600 | 400 | 1000 | 1000 | 600 | 400 | **Válido** | Devuelve 600 en efectivo y restaura 400 de crédito. |
| F2 | 1000 | 600 | 400 | 1000 | 1000 | 700 | 300 | **Inválido** | `C > P` (700 > 600). |
| G | 1000 | 500 | 0 | 700 | 200 | 200 | 0 | **Válido** | Devolución parcial: retiene 300, pagó 500, se devuelven 200. |
| H | 1000 | 200 | 0 | 700 | −100 | 0 | 0 | **Válido, sin compensación** | Retiene 300, pagó 200, aún debe 100. La devolución es válida; la regla de compensación no se cumple y no debe usarse como precondición de la devolución. |
| I | 1000 | 1000 | 0 | 500 | 500 | 500 | 0 | **Válido** | Dos devoluciones: 300 + 200; compensaciones 300 + 200. Acumulados correctos. |
| J | 1000 | 1000 | 0 | 800 | 800 | 800 | 0 | **Válido** | Retiene 200, pagó 1000, se devuelven 800. |
| J2 | 1000 | 700 | 0 | 800 | 500 | 800 | 0 | **Inválido** | Tras revertir 300 un pago: `C > D` y `C > P`. Se debe bloquear la reversión. |
| K | 1000 | 1000 | 0 | 800 | 800 | 600 | 200 | **Válido** | Reparto 600 efectivo + 200 crédito. |
| K2 | 1000 | 900 | 0 | 800 | 700 | 600 | 200 | **Inválido** | Tras revertir 100: `C + G = 800 > D = 700`, aunque `C ≤ P`. Por eso R6 debe revalidar el tope completo. |
| L | 1000 | 500 | 0 | 400 | −100 | 0 | 0 | **Válido** | Aún debe 100; puede pagar 100 (R4) y `D` pasa a 0. Pagar 200 violaría R4. |
| M | 1000 | 500 | 0 | 300 | −200 | 0 | 0 | **Válido** | Debe 200; aplica `U=200` de su crédito. `D=0`, sin reembolso. |

**Lectura de H (el caso que parecía un bloqueo):** la devolución parcial es válida; lo que no corresponde es compensar. La regla original, aplicada como condición de la devolución, la habría rechazado. La corrección es separar R1 (devolución) de R2 (compensación).

**Lectura de E:** demuestra que la regla original no es suficiente. Pasa la desigualdad, pero viola la naturaleza del saldo a favor. R3 lo impide.

**Lectura de K2:** demuestra que R3 por sí sola no basta ante una reversión; hay que revalidar R2 con el nuevo `P`.

### 2.6 Dónde se aplica cada invariante

| Invariante | Control principal | Control secundario |
|---|---|---|
| R1 | Trigger de cantidad acumulada por `venta_detalle_id` | Validación de servicio |
| R2 | Trigger `BEFORE INSERT` en compensaciones | Vista de saldos |
| R3 | Trigger de compensación contra pagos netos | Validación de servicio |
| R3b | Trigger por familia de método (si se aprueba) | Advertencia en UI |
| R4 | Trigger de pago de venta y de aplicación de crédito | Validación de servicio |
| R5 | Índice único de generación por origen + trigger de saldo ≥ 0 | Servicio de crédito |
| R6 | Trigger de reversión de pago | `SalesService.reverse_payment` |
| R7 | Servicio de cancelación total | Vista `v_saldos_ventas` |
| R8 | Validación de consentimiento en UI/servicio | Autorizador |

---

## 3. Idempotencia durable ante cierre inesperado

### 3.1 Modelo de fallo

Una operación financiera puede fallar en cinco puntos:

| Punto de fallo | Estado en base | Riesgo si no hay diseño |
|---|---|---|
| Antes de escribir | Nada | Ninguno; el usuario reintenta. |
| Después de escribir la intención, antes de ejecutar | Intención `pendiente`, sin efecto de negocio | Duplicación si se genera una clave nueva al reiniciar. |
| Durante la transacción de negocio | Rollback completo | Ninguno; la intención sigue pendiente. |
| Después del commit, antes de responder a la UI | Negocio confirmado | El usuario reintenta y duplica si la clave no se conserva. |
| Después de entregar efectivo/transferencia, antes de confirmar | Compensación pendiente | Doble entrega o pérdida de trazabilidad. |

La clave del diseño: **la transacción de negocio es única y atómica**; lo que sobrevive al cierre es una **intención persistente** con la misma clave, no una clave en memoria.

### 3.2 Registro persistente de intenciones

Propuesta de tabla:

```sql
CREATE TABLE solicitudes_operacion (
    id INTEGER PRIMARY KEY,
    clave_idempotencia TEXT NOT NULL UNIQUE,
    tipo_operacion TEXT NOT NULL,
    huella_solicitud TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('pendiente','completada','abandonada')),
    entidad_tipo TEXT,
    entidad_id INTEGER,
    solicitado_por TEXT NOT NULL,
    creada_en_utc TEXT NOT NULL,
    completada_en_utc TEXT,
    detalle TEXT NOT NULL DEFAULT ''
);
```

- `pendiente`: intención confirmada en base, sin efecto financiero.
- `completada`: la operación de negocio se confirmó en la misma transacción; incluye `entidad_tipo`/`entidad_id`.
- `abandonada`: el usuario decidió no continuar; solo se permite si no hay entidad asociada.

La tabla no sustituye a las tablas de negocio: es el índice de idempotencia y recuperación.

### 3.3 Protocolo de ejecución

```text
1. Registrar intención (transacción propia):
   INSERT ... estado='pendiente'
   - si la clave existe con otra huella  → ConflictError, sin escribir nada
   - si existe 'completada'              → devolver la entidad registrada
   - si existe 'pendiente'               → continuar (reintento tras cierre)
   - si existe 'abandonada'              → ConflictError (clave retirada)

2. Ejecutar el caso de uso en UNA transacción:
   BEGIN IMMEDIATE
     verificar de nuevo el estado de la intención
     insertar cabecera, líneas, compensaciones, inventario y crédito
     UPDATE solicitudes_operacion
        SET estado='completada', entidad_tipo=?, entidad_id=?, completada_en_utc=?
      WHERE clave=? AND estado='pendiente'
   COMMIT

3. Devolver el resultado consultando la entidad, no un JSON duplicado.
```

**Por qué funciona:** si el proceso muere en el paso 2, SQLite revierte todo y la intención queda `pendiente`; al reiniciar, la UI la muestra y el reintento usa la misma clave. Si muere después del commit, la intención está `completada` y el reintento devuelve la entidad sin volver a escribir.

### 3.4 Efectos externos: compensación en dos fases

Un reembolso en efectivo o una transferencia no son atómicos con la base: el dinero puede entregarse antes o después del commit. Para eso se separa:

1. **Compromiso** (`compensaciones_cancelacion`): fila inmutable que reserva el importe. Cuenta para `C` y para el tope R2/R3. Evita comprometer dos veces el mismo dinero.
2. **Confirmación** (`confirmaciones_compensacion`): evento append-only que registra que el dinero se entregó, con fecha, responsable, autorizador y referencia. Es idempotente por `compensacion_id` y por clave.
3. **Anulación** (`confirmaciones_compensacion` tipo `anulada`): solo si no se confirmó; libera el importe. Requiere motivo y autorizador.

```sql
CREATE TABLE confirmaciones_compensacion (
    id INTEGER PRIMARY KEY,
    compensacion_id INTEGER NOT NULL UNIQUE
        REFERENCES compensaciones_cancelacion(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN ('confirmada','anulada')),
    confirmado_en_utc TEXT NOT NULL,
    confirmado_por TEXT NOT NULL,
    autorizador TEXT NOT NULL,
    referencia TEXT NOT NULL DEFAULT '',
    motivo TEXT NOT NULL DEFAULT '',
    clave_idempotencia TEXT NOT NULL UNIQUE
);
```

Estados efectivos:

| Compromiso | Confirmación | Estado efectivo | Cuenta para `C` | Reporte de caja |
|---|---|---|---|---|
| Pendiente | Ninguna | `pendiente` | Sí | No |
| Pendiente | `confirmada` | `confirmada` | Sí | Sí |
| Pendiente | `anulada` | `anulada` | No | No |

**Caso de cierre después de entregar efectivo:** la compensación queda `pendiente`; al reiniciar, la UI la muestra. El usuario confirma con la misma clave; la confirmación es única y no duplica la entrega. Si el efectivo no se entregó, anula.

**Caso de doble clic en confirmar:** la clave única y `compensacion_id UNIQUE` impiden la segunda confirmación.

**Crédito:** la generación es interna y se confirma en la misma transacción; no requiere dos fases. La utilización también es interna.

### 3.5 Recuperación al inicio

1. Consultar `solicitudes_operacion` con estado `pendiente`.
2. Mostrar “operaciones pendientes de confirmar” con tipo, fecha, solicitante y resumen.
3. Si `entidad_id` existe, la operación se completó pero la intención no se actualizó (no debería ocurrir por atomicidad); reconciliar a `completada`.
4. Si no hay entidad, ofrecer **Reintentar** o **Abandonar**. Abandonar solo marca `abandonada`; no borra historia porque no hay efecto financiero.
5. Para compensaciones pendientes, ofrecer **Confirmar entrega** o **Anular**. No auto-anular: el dinero pudo haberse entregado.

### 3.6 Claves y huellas

- La clave se genera **una vez por intención del usuario**, al abrir el formulario, y se persiste con la intención.
- No se deriva de datos personales, importes ni fecha; dos operaciones legítimas iguales deben tener claves distintas.
- La huella es SHA-256 del payload canónico (ordenado, sin campos volátiles).
- Misma clave + misma huella → mismo resultado.
- Misma clave + otra huella → `ConflictError`, cero escrituras.
- Claves distintas + mismo contenido económico → permitido si los topes lo autorizan; la UI serializa para evitar dos intenciones accidentales.
- Filas generadas por el sistema (por ejemplo, crédito de una cancelación) usan clave derivada determinista: `cancelacion:{id}:compensacion:{id}`, con restricción única. Así un reintento interno no duplica.

### 3.7 Durabilidad

- Se depende de la atomicidad de SQLite; no hay escrituras externas dentro de la transacción.
- No se debilita `synchronous`. Si en el futuro se activa WAL, las escrituras financieras deben usar `synchronous=FULL`.
- Los respaldos previos a migración de Fase 0 siguen siendo el punto de restauración.
- Para futuras pasarelas de pago: outbox con estado `pendiente_envio`/`confirmado` y clave de idempotencia del proveedor. **Pendiente de validación** si se integra una pasarela.

### 3.8 UI

- El botón de guardar se deshabilita mientras la operación está en curso.
- Al reabrir, la UI consulta intenciones pendientes antes de permitir una nueva operación igual.
- La clave no se regenera al reintentar; solo al iniciar una intención nueva.
- Los diálogos muestran el estado pendiente/confirmado de cada reembolso.

### 3.9 Pruebas de idempotencia y recuperación

1. Cierre simulado después de registrar la intención y antes de la transacción: al reabrir, la intención está `pendiente` y el reintento produce un solo efecto.
2. Cierre simulado durante la transacción (excepción forzada después de insertar la cabecera): rollback total; no quedan líneas, movimientos ni crédito.
3. Cierre simulado después del commit y antes de responder: el reintento devuelve la entidad y no duplica.
4. Misma clave + otra huella: conflicto y cero escrituras.
5. Dos conexiones simultáneas con la misma clave: una gana; la otra devuelve el resultado.
6. Dos conexiones con claves distintas y el mismo contenido: los topes económicos impiden el exceso.
7. Confirmación de reembolso repetida: una sola confirmación.
8. Anulación después de confirmación: rechazada.
9. Reinicio con compensación pendiente: se muestra; confirmar no duplica; anular libera el tope.

---

## 4. Separación de roles

### 4.1 Definiciones

| Rol | Qué significa | Quién lo ejerce |
|---|---|---|
| **Solicitante** | Quien pide la devolución, cancelación o ajuste. Puede ser el cliente o un colaborador que recibe la solicitud. | Cliente o personal. |
| **Responsable de ejecución** | Quien registra la operación y decide la condición del producto. | Personal autorizado. |
| **Autorizador** | Quien aprueba la compensación económica y las excepciones (no reintegro con reembolso total, valor reconocido menor, ajuste de crédito). | Supervisor o responsable designado. |

No son intercambiables. El solicitante no autoriza; el ejecutor no se autoriza a sí mismo cuando hay compensación.

### 4.2 Campos por entidad

| Entidad | Campos |
|---|---|
| `cancelaciones_venta` | `solicitante`, `solicitante_tipo` (`cliente`/`interno`), `solicitado_en_utc`, `responsable_ejecucion`, `ejecutado_en_utc`, `motivo` |
| `compensaciones_cancelacion` | `responsable_ejecucion` (heredado), `autorizador`, `autorizado_en_utc`, `referencia_autorizacion`, `consentimiento_cliente` (si `G > U`) |
| `confirmaciones_compensacion` | `confirmado_por`, `autorizador`, `confirmado_en_utc`, `referencia` |
| `movimientos_saldo_favor` | `registrado_por`, `autorizador` (para generación/ajuste), `origen_tipo`/`origen_id` |
| `solicitudes_operacion` | `solicitado_por` |

### 4.3 Reglas de segregación

| Operación | Autorizador obligatorio | Debe ser distinto del ejecutor |
|---|---|---|
| Devolución sin compensación | No | — |
| Devolución con reembolso > 0 | Sí | Sí |
| Generación de crédito > 0 | Sí | Sí |
| Uso de crédito | No | — |
| Ajuste de crédito | Sí | Sí |
| Devolución sin reintegro con reembolso total | Sí | Sí |
| Valor reconocido menor al precio | Sí | Sí |
| Anulación de compensación pendiente | Sí | Sí |

**Umbral:** en Fase 1 se recomienda exigir autorizador distinto para **toda** compensación positiva. Un umbral configurable puede llegar después; empezar estricto es más seguro.

### 4.4 Limitación actual

No existe tabla de usuarios ni autenticación. Los campos son **declarativos**: se puede escribir cualquier nombre. Por tanto:

- La segregación se puede validar como “texto no vacío y distinto”, no como identidad real.
- La UI debe pedir los tres campos y mostrar un resumen antes de confirmar.
- **Pendiente de validación:** módulo de usuarios/roles y sesión autenticada. Mientras no exista, el control es organizativo, no criptográfico.
- Si la empresa tiene una sola persona, se debe documentar una excepción autorizada; no simular un autorizador ficticio.

---

## 5. Productos devueltos no aptos para inventario disponible

### 5.1 El problema

El Informe2 original usaba un booleano `reintegrar_inventario`. Eso no distingue entre:

- producto apto para reventa;
- producto dañado por el cliente;
- producto incompleto (faltan accesorios);
- producto no apto por higiene, vencimiento o seguridad;
- producto que el cliente conserva y solo se compensa parcialmente.

Tampoco permite devolver 3 unidades y reintegrar solo 2.

### 5.2 Modelo corregido

En `cancelacion_venta_lineas`:

```sql
cantidad_devuelta      INTEGER NOT NULL CHECK (cantidad_devuelta > 0)
cantidad_reintegrada   INTEGER NOT NULL DEFAULT 0
                       CHECK (cantidad_reintegrada >= 0
                          AND cantidad_reintegrada <= cantidad_devuelta)
condicion_no_apta      TEXT CHECK (condicion_no_apta IN
                         ('danado','incompleto','no_apto','otro'))
motivo_no_reintegro    TEXT NOT NULL DEFAULT ''
importe_reconocido_cop INTEGER NOT NULL CHECK (importe_reconocido_cop >= 0)
motivo_ajuste_valor    TEXT NOT NULL DEFAULT ''
```

Reglas:

- `cantidad_reintegrada` es la cantidad que vuelve a stock disponible.
- La diferencia `cantidad_devuelta − cantidad_reintegrada` es la cantidad no apta.
- Si la diferencia es mayor que cero, `condicion_no_apta` y `motivo_no_reintegro` son obligatorios.
- Si `cantidad_reintegrada > 0`, la línea debe tener `producto_id`.
- `importe_reconocido_cop` es el valor comercial aceptado para la devolución. Por defecto es `cantidad_devuelta × precio_unitario`. Puede ser menor solo con `motivo_ajuste_valor` y autorizador distinto.
- La pérdida de inventario se calcula, no se inventa:
  `costo_perdida_cop = costo_unitario_historico × (cantidad_devuelta − cantidad_reintegrada)`.
  Si el costo histórico es `NULL`, se reporta como “costo no disponible” y no se estima.

### 5.3 Movimiento de inventario

- Se crea **un** movimiento por línea, solo por `cantidad_reintegrada`, con `tipo='ajuste'`, `cantidad_delta > 0` y `devolucion_venta_linea_id`.
- Si `cantidad_reintegrada = 0`, no se crea movimiento.
- El trigger `AFTER INSERT` de la línea crea el movimiento en la misma transacción.
- El índice único por `devolucion_venta_linea_id` impide dos movimientos para la misma línea.
- El movimiento no se puede revertir por el mecanismo genérico.
- La parte no reintegrada **no genera movimiento**: el artículo ya salió del stock al venderse y no vuelve. La pérdida se reporta por costo, sin alterar existencias.

### 5.4 Efecto en la compensación

`R` usa `importe_reconocido_cop`, no el precio de lista. Ejemplos:

**Ejemplo 1 — devolución total, producto dañado, reembolso completo (la empresa asume la pérdida):**

- `T=1000`, `P=1000`, devuelve un artículo de precio 400, dañado, no se reintegra.
- `R=400` (se reconoce el precio completo), `D=1000+0−(1000−400)=400`.
- `C=400`, `G=0`: válido. No hay stock; la pérdida es el costo histórico del artículo.
- Requiere autorizador distinto y motivo.

**Ejemplo 2 — devolución total, producto dañado, se reconoce solo el 50%:**

- Artículo de precio 400, reconocido 200; `R=200`, `D=1000−(1000−200)=200`.
- `C=200`: válido. El cliente absorbe 200 como cargo por condición.
- Requiere `motivo_ajuste_valor` y autorizador.
- La pérdida de inventario sigue siendo el costo histórico completo del artículo no reintegrado.

**Ejemplo 3 — devolución parcial con unidades mixtas:**

- Se devuelven 3 unidades; 2 aptas, 1 dañada.
- `cantidad_devuelta=3`, `cantidad_reintegrada=2`, `condicion_no_apta='danado'`, `motivo_no_reintegro='Pantalla quebrada'`.
- Se crea un movimiento por 2; la pérdida se calcula por 1.
- La compensación se calcula sobre las 3 unidades reconocidas.

**Ejemplo 4 — producto incompleto:**

- Se devuelve un equipo sin cargador; `cantidad_reintegrada=0`, `condicion_no_apta='incompleto'`.
- No vuelve a stock hasta que se complete o se reclasifique; la pérdida se reporta.
- **Pendiente de validación:** si se permite reintegrar como “usado” después de una inspección; en Fase 1 no se hace automáticamente.

### 5.5 Reporte de pérdidas

Vista propuesta `v_devoluciones_no_reintegradas`:

| Columna | Contenido |
|---|---|
| venta, código | Referencia de la venta. |
| línea, producto | Línea devuelta y SKU. |
| cantidad_devuelta | Total devuelto. |
| cantidad_reintegrada | Total que volvió a stock. |
| cantidad_no_apta | Diferencia. |
| condicion | Dañado, incompleto, no apto, otro. |
| motivo | Texto obligatorio. |
| costo_perdida_cop | Costo histórico × cantidad no apta. |
| autorizador | Quien aprobó la excepción. |

No se mezcla con ingresos ni con saldo a favor. Es una vista de pérdida operativa.

### 5.6 Controles

- No reintegrar con reembolso total exige autorización.
- Valor reconocido menor exige motivo y autorización.
- La UI muestra el cálculo antes de confirmar: “se reintegran X, se descartan Y, pérdida estimada Z, se reembolsan C, se abonan G”.
- El ejecutor declara la condición; el autorizador aprueba la excepción.
- **Pendiente de validación:** política comercial para daños causados por el cliente (reembolso total, parcial o ninguno). El modelo soporta las tres; la política debe decidirse.

---

## 6. Extensibilidad del ledger de saldo a favor a órdenes de servicio

### 6.1 Problema del diseño original

El ledger original tenía `venta_id` y una restricción que exigía `venta_id` para toda utilización. Eso impediría usar el mismo saldo en una orden sin reconstruir la tabla o duplicar el ledger.

### 6.2 Diseño corregido

```sql
CREATE TABLE tipos_origen_saldo_favor (
    codigo TEXT PRIMARY KEY,
    descripcion TEXT NOT NULL
);

INSERT INTO tipos_origen_saldo_favor (codigo, descripcion) VALUES
    ('venta', 'Venta directa'),
    ('orden', 'Orden de servicio'),
    ('compensacion_venta', 'Compensación de cancelación de venta'),
    ('cancelacion_orden', 'Cancelación de orden (fase posterior)'),
    ('ajuste', 'Ajuste manual autorizado');

CREATE TABLE movimientos_saldo_favor (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN ('generacion','utilizacion','ajuste')),
    importe_cop INTEGER NOT NULL CHECK (importe_cop <> 0),
    origen_tipo TEXT NOT NULL REFERENCES tipos_origen_saldo_favor(codigo),
    origen_id INTEGER NOT NULL,
    venta_id INTEGER REFERENCES ventas(id),
    orden_id INTEGER REFERENCES ordenes_servicio(id),
    movimiento_corregido_id INTEGER REFERENCES movimientos_saldo_favor(id),
    fecha_negocio TEXT NOT NULL,
    registrado_en_utc TEXT NOT NULL,
    motivo TEXT NOT NULL,
    registrado_por TEXT NOT NULL,
    autorizador TEXT NOT NULL DEFAULT '',
    clave_idempotencia TEXT NOT NULL UNIQUE,
    huella_solicitud TEXT NOT NULL,
    CHECK (
        (tipo='utilizacion' AND ((venta_id IS NOT NULL) <> (orden_id IS NOT NULL)))
        OR (tipo='generacion' AND venta_id IS NULL AND orden_id IS NULL)
        OR (tipo='ajuste' AND movimiento_corregido_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_saldo_favor_generacion_origen
    ON movimientos_saldo_favor(origen_tipo, origen_id)
    WHERE tipo='generacion';
```

### 6.3 Uso en ventas (Fase 1)

- Generación: `origen_tipo='compensacion_venta'`, `origen_id=compensacion_id`.
- Utilización: `origen_tipo='venta'`, `origen_id=venta_id`, `venta_id` poblado.
- El trigger valida que la venta exista, pertenezca al cliente y tenga saldo pendiente suficiente.
- `v_saldos_ventas` descuenta `U` del saldo pendiente.

### 6.4 Uso en órdenes (fase posterior, sin reconstruir el ledger)

- Utilización: `origen_tipo='orden'`, `origen_id=orden_id`, `orden_id` poblado. La columna y la restricción ya existen.
- `CreditService.apply_to_order` inserta el movimiento con la misma lógica de saldo.
- `v_saldos_ordenes` añade `saldo_favor_aplicado_cop` y lo resta del saldo pendiente.
- El trigger de pago de orden se amplía para exigir `P + U ≤ importe_acordado`.
- Generación desde una cancelación de orden: se inserta `cancelacion_orden` en `tipos_origen_saldo_favor` (una fila, sin DDL), se crea la tabla `cancelaciones_orden` en su fase y se extiende el trigger de validación de origen. El ledger no se reconstruye.
- La unicidad de generación por origen ya cubre el futuro: `UNIQUE(origen_tipo, origen_id) WHERE tipo='generacion'`.

**Confirmación:** sí, el ledger es ampliable a órdenes de servicio. Lo único que se añade en la fase de órdenes es una fila en el catálogo de orígenes, la tabla de cancelación de órdenes y la extensión de un trigger; **no** se altera la tabla del ledger ni se reescriben movimientos.

### 6.5 Límite de Fase 1

En Fase 1 solo se habilita el uso en ventas. El uso en órdenes queda diseñado pero no implementado, para no ampliar el alcance aprobado.

---

## 7. Inconsistencias adicionales comprobadas

| ID | Evidencia | Impacto | Disposición |
|---|---|---|---|
| **I1** | `SalesService.register_payment` comprueba `sale["estado"] == "cancelada"`, pero `get_sale` devuelve `v.*` (estado almacenado, siempre `abierta`) y `estado_cobro` derivado. | La guarda de cancelación es ineficaz hoy. | Corregir en Fase 1: comparar `estado_cobro`/`estado_comercial`. |
| **I2** | `v_saldos_ventas.estado_cobro` calcula total − pagos; ignora devoluciones y saldo a favor. | Una venta devuelta puede aparecer “completada” y con saldo incorrecto. | Corregir en Fase 1 (vista nueva). |
| **I3** | `pagos_clientes_no_sobrepagar_venta` compara pagos con el total bruto; no considera devoluciones ni crédito. | Se podría cobrar sobre valor ya devuelto. | Corregir en Fase 1 con trigger de valor neto. |
| **I4** | `pagos_clientes` tiene `clave_idempotencia` pero no `huella_solicitud`; la comparación se hace campo por campo en el servicio. | Verificación frágil y duplicada. | Añadir huella y centralizar en Fase 1. |
| **I5** | `pagos_proveedores` no tiene idempotencia; el trigger `pagos_proveedores_no_superar_total` no verifica el estado de la compra (el servicio sí). | Doble pago por reintento; inserción directa podría pagar una compra cancelada. | Idempotencia en Fase 1; guard de estado a nivel DB recomendado. |
| **I6** | `transition_purchase` solo permite cancelar en `borrador` o `pendiente`; una compra `recibida` es inmutable y no hay flujo de devolución a proveedor. | No se puede corregir una compra recibida. | Fase posterior; documentar. |
| **I7** | `ventas.estado` admite `cancelada` pero nunca se actualiza; `ventas.cotizacion_id` es único y la propuesta queda `convertida`. | Estado almacenado engañoso; no se puede reconvertir la misma propuesta tras cancelar. | Estado derivado en Fase 1; reconversión requiere nueva propuesta (documentar). |
| **I8** | `ventas.armado_pc_id` existe, pero no hay flujo de venta de armado y las líneas pueden no tener `producto_id`. | Cancelación de una venta vinculada a armado sin compensación de inventario definida. | **Pendiente de validación:** bloquear automático o tratar como no reintegrable. |
| **I9** | El guard de Fase 0 solo bloquea movimientos con `venta_detalle_id`, `compra_detalle_id`, `orden_repuesto_id`, `armado_componente_id`; una devolución sería `ajuste` con nueva procedencia. | El mecanismo genérico podría revertir una devolución. | Ampliar guard y trigger en Fase 1. |
| **I10** | `v_saldos_ordenes`, `ServiceOrderRepository.list_orders` y tres triggers recalculan extras; `decisiones_adicional_no_reduce_deuda_pagada` tiene un self-join redundante. | Discrepancias y mantenimiento riesgoso. | Vista única y reescritura en Fase 1. |
| **I11** | No existe catálogo de métodos; `ui/sales.py`, `ui/order_details.py` y `ui/procurement.py` usan listas distintas o texto libre. | Datos inconsistentes y reportes no comparables. | Catálogo en Fase 1. |
| **I12** | No hay `fecha_negocio`; los triggers de inmutabilidad impiden backfill de pagos y movimientos. | Reportes por fecha UTC, no contable. | Columna nullable + vistas derivadas en Fase 1; no reescribir historia. |
| **I13** | Las claves de idempotencia de la UI son `uuid4().hex` en memoria (`PaymentDialog`). | Se pierden al cerrar; un reintento tras reinicio puede duplicar. | Registro persistente de intenciones en Fase 1. |
| **I14** | No hay tabla de usuarios/autenticación. | Roles declarativos; no se puede verificar identidad. | **Pendiente de validación:** módulo de usuarios. |
| **I15** | El trigger de pago de orden no verifica el estado de la orden (el servicio sí); no hay crédito aplicable a órdenes. | Defensa en profundidad incompleta; extensión futura. | Fase 2, con el ledger ya preparado. |
| **I16** | `venta_detalles.costo_unitario_historico_cop` es nullable y `gastos` no tiene servicio. | Pérdida de devolución no calculable en algunos casos; gastos sin flujo. | Reportar “costo no disponible”; gastos, fase posterior. |

**Nota:** I5 e I15 son brechas de defensa en profundidad: el servicio bloquea, pero una inserción directa en SQLite podría saltarse la regla. No se proponen cambios fuera de Fase 1 salvo I5 (idempotencia), que sí está en alcance.

---

## 8. Ajustes al modelo de datos respecto al Informe2 original

### 8.1 Tablas y columnas

| Elemento | Informe2 original | Revisión |
|---|---|---|
| `cancelaciones_venta` | `responsable`, `autorizado_por` | `solicitante`, `solicitante_tipo`, `solicitado_en_utc`, `responsable_ejecucion`, `ejecutado_en_utc`, `motivo` |
| `cancelacion_venta_lineas` | `reintegrar_inventario` booleano | `cantidad_reintegrada`, `condicion_no_apta`, `motivo_no_reintegro`, `importe_reconocido_cop`, `motivo_ajuste_valor` |
| `compensaciones_cancelacion` | `responsable`, `autorizado_por` | + `autorizado_en_utc`, `referencia_autorizacion`, `consentimiento_cliente`; estado efectivo por confirmaciones |
| Confirmaciones | No existían | `confirmaciones_compensacion` (append-only) |
| `movimientos_saldo_favor` | `venta_id`, `cancelacion_id`, `compensacion_id` | `origen_tipo`/`origen_id`, `venta_id`/`orden_id`, `registrado_por`, `autorizador`; catálogo de orígenes |
| Idempotencia | Clave + huella en la misma transacción | + `solicitudes_operacion` persistente y protocolo de recuperación |
| `pagos_clientes` | Sin huella | + `huella_solicitud` |
| `pagos_proveedores` | Sin idempotencia | + `clave_idempotencia`, `huella_solicitud`, `metodo_pago_id`, `fecha_negocio` |
| `movimientos_inventario` | Sin idempotencia | + `clave_idempotencia`, `huella_solicitud`, `fecha_negocio`, `devolucion_venta_linea_id` |

### 8.2 Vistas

- `v_saldos_ventas`: añade `devuelto_cop`, `saldo_favor_aplicado_cop`, `reembolsado_cop`, `credito_generado_cop`, `sobrepago_pendiente_cop`, `estado_devolucion`, `estado_comercial`; corrige `estado_cobro`.
- `v_saldos_ordenes`: proyección de `v_ordenes_importes`; preparada para `saldo_favor_aplicado_cop`.
- `v_ordenes_importes`: fuente única de extras.
- `v_saldos_favor`, `v_movimientos_saldo_favor`, `v_historial_financiero_venta`, `v_devoluciones_no_reintegradas`.

### 8.3 Triggers nuevos o reescritos

- Cantidad devuelta acumulada por línea.
- Tope R2/R3 por compensación.
- Revalidación R6 al revertir pago.
- Generación única de crédito por origen.
- Saldo de crédito no negativo.
- Movimiento de inventario automático por cantidad reintegrada.
- Validación de devolución y bloqueo de reversión genérica.
- Coherencia de condición/valor reconocido.
- Fecha de negocio obligatoria en filas nuevas.
- Reescritura de los tres triggers de extras contra la vista canónica.
- Trigger de idempotencia de generación y utilización.

### 8.4 Servicios y UI

- `SalesService`: cancelación, devolución, historial, guardas corregidas.
- `CreditService`: generación, uso en venta, ajuste; preparado para orden.
- `ReturnsService`: orquestación transaccional.
- `PaymentMethodService`: catálogo y legado.
- `IdempotencyService`: intenciones, huellas, recuperación.
- UI: diálogo de devolución con cantidades/condición/valor reconocido, reparto, roles; página de saldo a favor; métodos unificados; fecha de negocio; aviso de operaciones pendientes.

---

## 9. Impacto en migraciones

Se mantienen cuatro migraciones, con contenido ampliado:

| # | Nombre propuesto | Contenido revisado |
|---|---|---|
| 0008 | `0008_payment_methods_and_business_date.sql` | Catálogo, alias, `metodo_pago_id`, `fecha_negocio`, índices, triggers de fecha. |
| 0009 | `0009_idempotency_and_operation_intents.sql` | Idempotencia de proveedores e inventario; `solicitudes_operacion`; huella en pagos de cliente. |
| 0010 | `0010_sale_returns_credit_and_confirmations.sql` | Cancelaciones, líneas con condición/valor reconocido, compensaciones, confirmaciones, ledger con orígenes, movimientos de devolución, triggers R1–R8, vistas de venta y crédito. |
| 0011 | `0011_canonical_order_totals_and_history.sql` | `v_ordenes_importes`, reemplazo de `v_saldos_ordenes`, `v_historial_financiero_venta`, reescritura de triggers de extras, `v_devoluciones_no_reintegradas`. |

No se reescriben filas históricas. Las columnas nuevas quedan `NULL` en lo antiguo y las vistas resuelven el legado. Las migraciones siguen siendo atómicas por archivo, con respaldo previo de Fase 0 y restauración verificada como estrategia de reversión.

---

## 10. Riesgos y controles

| Riesgo | Control |
|---|---|
| Cliente termina con más valor del que entregó | R2 + R3 + pruebas de escenarios A–M |
| Reembolso en efectivo de valor recibido como crédito | R3 y, si se aprueba, R3b por método |
| Devolución parcial bloqueada por usar la regla de compensación como precondición | Separar R1 (devolución) de R2 (compensación) |
| Compensación invalidada por reversión de pago | R6 revalida el tope completo, no solo `C ≤ P` |
| Doble reembolso tras cierre | Intención persistente + compensación en dos fases + clave única |
| Doble uso de crédito | `BEGIN IMMEDIATE`, saldo leído dentro de la transacción, trigger de saldo ≥ 0, clave única |
| Crédito duplicado | Generación única por `(origen_tipo, origen_id)` |
| Producto dañado vuelve a stock | `cantidad_reintegrada` + condición + trigger + autorización |
| Pérdida no visible | `v_devoluciones_no_reintegradas` y costo histórico |
| Roles simulados | Campos obligatorios y distintos; módulo de usuarios pendiente |
| Extras inconsistentes | Vista única y prueba de equivalencia sobre copia real |
| Métodos legados perdidos | Catálogo + alias + filas legadas con texto exacto |
| Migración fallida | Transacción por archivo + respaldo + restauración |
| Vistas nuevas rompen UI | Conservar columnas y probar esquema/equivalencia |
| Venta vinculada a armado sin inventario definido | Bloquear o exigir tratamiento manual; pendiente de validación |

---

## 11. Pruebas de aceptación necesarias

### 11.1 Invariantes

1. Escenarios A–M de la tabla, cada uno con resultado esperado (válido/inválido).
2. Devolución parcial con `D < 0`: se registra, no se compensa, el saldo pendiente es correcto.
3. Devolución parcial con `D > 0`: compensación hasta `D`, no más.
4. Reembolso en efectivo con `P=0`, `U>0`: rechazado; solo crédito.
5. Reversión de pago que deja `C > P` o `C+G > D`: rechazada, sin cambios.
6. Nueva devolución después de una compensación: no invalida la compensación previa.
7. Cancelación total: `C+G = D` y `sobrepago_pendiente = 0`.
8. Devolución parcial con pendiente: visible y consistente.

### 11.2 Idempotencia durable

9. Cierre simulado antes de la transacción: un solo efecto al reintentar.
10. Cierre simulado durante la transacción: rollback total.
11. Cierre simulado después del commit: el reintento devuelve la entidad.
12. Misma clave/otra huella: conflicto.
13. Dos conexiones con la misma clave: un solo efecto.
14. Confirmación repetida de reembolso: una sola.
15. Anulación después de confirmación: rechazada.
16. Reinicio con intención pendiente: se muestra y se resuelve.

### 11.3 Roles

17. Compensación sin autorizador: rechazada.
18. Autorizador igual al ejecutor: rechazado.
19. Devolución sin compensación: no exige autorizador.
20. Ajuste de crédito sin autorizador: rechazado.

### 11.4 Devoluciones no aptas

21. 3 devueltas, 2 reintegradas: un movimiento por 2, pérdida por 1.
22. 0 reintegradas: ningún movimiento, pérdida registrada.
23. Condición/motivo faltantes: rechazado.
24. Valor reconocido menor sin motivo/autorización: rechazado.
25. Producto sin `producto_id` con cantidad reintegrada > 0: rechazado.

### 11.5 Ledger y órdenes

26. Uso de crédito en venta: saldo y saldo pendiente correctos.
27. Prueba de esquema: el ledger admite `orden_id` y origen `orden`.
28. Simulación de uso en orden (sin UI): el saldo baja y la venta no se altera.
29. Generación única por origen: segunda inserción rechazada.

### 11.6 Inconsistencias adicionales

30. Pago en venta totalmente devuelta: rechazado por estado derivado y por trigger.
31. Cobro sobre valor ya devuelto: rechazado.
32. Extras: los 5 órdenes reales dan el mismo importe antes y después.
33. Métodos legados: `CSX`, `EFECTIVO`, `TRANSFERENCIA`, `Efectivo`, `Tarjeta` visibles y seleccionables.
34. Fecha de negocio nocturna: asignación correcta.
35. Migración sobre copia real: v11, integridad, mismos conteos e importes.
36. Restauración de la copia previa: vuelve a v7.

---

## 12. Decisiones pendientes

| # | Decisión | Información faltante | Recomendación |
|---|---|---|---|
| P1 | Significado de `CSX` | No se conoce si es una pasarela, un banco o una caja. | Conservarlo como método legado; no clasificarlo a ciegas. |
| P2 | Política de daño causado por el cliente | Reglamento comercial. | Soportar reembolso total, parcial o ninguno; exigir autorización. |
| P3 | Reembolso en efectivo de pagos con tarjeta | Política de la empresa. | Aplicar R3b por método salvo autorización. |
| P4 | Umbral de autorización y excepción de una sola persona | Organización del negocio. | Exigir autorizador distinto para toda compensación en Fase 1. |
| P5 | Identidad real de roles | No hay usuarios/autenticación. | Diseñar módulo de usuarios en fase posterior; mientras tanto, campos declarativos. |
| P6 | Venta vinculada a `armado_pc_id` | No se verificó si la venta real usa armado; no hay flujo de venta de armado. | Bloquear cancelación automática o exigir tratamiento manual. |
| P7 | Uso de saldo a favor en órdenes | Fase 2. | Ledger ya preparado; no implementar en Fase 1. |
| P8 | Devolución parcial con sobrepago pendiente | Política de atención. | Permitir con aviso; cancelación total exige liquidar. |
| P9 | Pasarela de pagos externa | No existe integración. | Outbox con idempotencia del proveedor en fase posterior. |
| P10 | Devolución de compras recibidas | No hay flujo. | Fase posterior; documentar que hoy no es posible. |
| P11 | Reintegro de producto incompleto tras inspección | Política de taller. | No automático en Fase 1; ajuste manual posterior. |

---

## 13. Resumen de cambios respecto al Informe2 original

| Tema | Informe2 original | Revisión |
|---|---|---|
| Invariante | `C + G + (T − R) ≤ P + U` | Se conserva como R2, pero con `MAX(0, D)`, `C ≤ P`, R4 de flujo, R6 de reversión, R7 de cierre y R8 de consentimiento. |
| Devoluciones parciales | Podían interpretarse como bloqueadas | Se demuestra que no lo están; se separa devolución de compensación. |
| Idempotencia | Clave + huella en la misma transacción | Registro persistente de intenciones + protocolo de recuperación + dos fases para efectos externos. |
| Roles | `responsable` y `autorizado_por` | `solicitante`, `responsable_ejecucion`, `autorizador`, con tiempos y segregación. |
| Inventario devuelto | Booleano | Cantidad reintegrada + condición + valor reconocido + motivo + pérdida. |
| Ledger | `venta_id` | Origen genérico + `venta_id`/`orden_id`; ampliable a órdenes sin reconstruir. |
| Inconsistencias | Algunas detectadas | 16 hallazgos comprobados con disposición. |
| Migraciones | 0008–0011 | Mismos números, contenido ampliado; sin reescritura histórica. |
| Pruebas | Enumeradas | 36 pruebas de aceptación organizadas por invariante, idempotencia, roles, no reintegro, ledger e inconsistencias. |

---

## 14. Cierre

Este documento es una **revisión de diseño**. No se implementó ninguna entrega, no se modificaron código, SQL, migraciones, datos ni configuración. El único archivo creado es este informe.

La implementación de la Fase 1 requiere autorización expresa y debe comenzar por la Entrega 1 (catálogo de métodos y fecha de negocio), respetando las correcciones aquí establecidas.
