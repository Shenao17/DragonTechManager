# Informe3 - Cierre de decisiones Fase 1

**Proyecto:** DragonTech Manager  
**Referencia:** `Informe2 - Diseño Fase 1 (Revisión).md`  
**Fecha:** 2026-10-31  
**Alcance:** cierre de tres decisiones puntuales de la Fase 1. Trabajo exclusivamente de análisis y diseño. No se implementó nada.

---

## 0. Propósito, coherencia y resumen

Este documento complementa el Informe2; no lo reemplaza ni lo modifica. Cierra tres puntos que quedaron abiertos:

1. Cancelación total con saldo pendiente.
2. Reembolsos físicos y confirmación de entrega.
3. Identidad y autorización mientras no exista autenticación.

Se mantienen las definiciones e invariantes del Informe2:

| Símbolo | Significado |
|---|---|
| `T` | Total vendido. |
| `R` | Valor reconocido de lo devuelto. |
| `P` | Dinero neto recibido (recibos menos reversiones). |
| `U` | Saldo a favor aplicado a la venta. |
| `C` | Reembolsos comprometidos (pendientes o entregados; excluye anulados). |
| `G` | Saldo a favor generado por la venta. |
| `D` | `P + U − (T − R)`. Posición neta antes de compensar. |

Las invariantes R1–R8 del Informe2 siguen vigentes. Este documento añade R9–R14 para la extinción de deuda, la liquidación y la segregación de funciones, y precisa la diferencia entre **compromiso** y **entrega** de un reembolso.

### 0.1 Decisiones propuestas

| ID | Decisión | Estado |
|---|---|---|
| **D1** | Una cancelación total no puede quedar “liquidada” con deuda. Debe cobrarse, condonarse, castigarse o quedar explícitamente como `cancelada_con_deuda`. | Recomendada; requiere aprobación de política. |
| **D2** | La deuda se extingue con eventos explícitos `condonacion` o `castigo`, nunca con pagos ficticios, pagos negativos, crédito artificial ni borrado de filas. | Recomendada. |
| **D3** | Condonación y castigo son distintos: la primera es una renuncia comercial; el segundo es el reconocimiento de un crédito incobrable tras gestiones. Ambos son no-caja. | Recomendada; tratamiento contable pendiente. |
| **D4** | Todo reembolso tiene dos momentos: compromiso (reserva) y entrega (salida real de dinero). La entrega se registra con un evento append-only idempotente. | Recomendada. |
| **D5** | Antes de entregar efectivo se prepara un comprobante con código único. La preparación se persiste antes de imprimir; la entrega se confirma después, incluso tras un cierre inesperado. | Recomendada. |
| **D6** | Sin autenticación, la identidad es **declarativa**. Se usa un directorio de actores y controles operativos; no se simula seguridad. | Recomendada. |
| **D7** | La migración futura a usuarios conserva los actores y los nombres históricos; no reescribe operaciones pasadas. | Recomendada. |

### 0.2 Lo que este documento no hace

- No modifica código, SQL, migraciones, base de datos, configuración ni workflows.
- No implementa funcionalidades.
- No altera el Informe2 ni ningún documento anterior.
- No amplía el alcance aprobado de la Fase 1.
- No asume decisiones del propietario del negocio: las marca como pendientes.

---

## 1. Cancelación total con saldo pendiente

### 1.1 Precisión indispensable: qué significa “cancelación total”

En el Informe2, `cancelacion_total` significa que **todas las cantidades vendidas fueron devueltas**. No significa que la operación haya quedado liquidada económicamente. Hay que separar tres conceptos:

| Concepto | Definición | Efecto económico |
|---|---|---|
| **Devolución total (cantidad)** | Todas las unidades de todas las líneas fueron devueltas. | Extingue la obligación de pagar por los bienes devueltos, pero el valor reconocido `R` puede ser menor que `T`. |
| **Cancelación comercial** | La empresa decide anular la venta aunque no todos los bienes se devuelvan (servicio ya prestado, producto retenido, cliente conserva parte). | No es una devolución total. El valor retenido debe cobrarse, condonarse o tratarse explícitamente. |
| **Liquidación total** | No queda saldo por cobrar ni por devolver. | `C + G = D` si `D > 0`; `Q = −D` si `D < 0`. |

**Conclusión analítica:** si todas las unidades se devuelven y se reconoce el precio completo (`R = T`), entonces `D = P + U ≥ 0`. Nunca hay deuda. Para que exista deuda con devolución total debe ocurrir que `R < T`, es decir, que la empresa retenga un valor por condición, daño, faltantes o cargo acordado. Si no hay devolución total, la deuda puede provenir de los bienes o servicios retenidos.

Esto evita una confusión frecuente: “cancelar” no es lo mismo que “devolver todo”. Una cancelación comercial sin devolución total no puede cerrarse como si todo hubiera vuelto.

### 1.2 Mapa de casos

| Caso | ¿Devolución total? | `D` | ¿Hay deuda? | Tratamiento |
|---|---|---|---|---|
| A | Sí, `R = T` | `P + U ≥ 0` | No | Reembolsar `D` si `D > 0`; nada si `D = 0`. |
| B | Sí, `R < T` | Puede ser negativo | Sí, si `P + U < T − R` | Cobrar, condonar, castigar o mixto. |
| C | No; cliente retiene bienes | Depende del valor retenido | Sí, si lo retenido supera lo pagado | Devolución parcial, no cancelación total; o cancelación con deuda explícita. |
| D | No; servicio ya prestado | Depende del valor del servicio | Sí, si no está pagado | No reversar el servicio; cobrar, condonar o castigar. |
| E | Sí, pero luego hay contracargo o reversión externa | Puede volverse negativo | Sí | Registrar la reversión, bloquear nuevos reembolsos y tratar la deuda. |

### 1.3 Por qué no se puede extinguir la deuda con movimientos ficticios

La deuda no es un pago. Simularla con un movimiento de caja o de crédito produce errores en cascada:

| Solución ficticia | Por qué es incorrecta |
|---|---|
| Insertar un `pago_cliente` con el importe condonado | `pagos_clientes` solo admite `recibo` y `reversion`, con `importe_cop > 0`. Un “pago” condonado infla `P`, los reportes de caja y el historial; además es inmutable y no se puede corregir. |
| Insertar un pago negativo | Viola `importe_cop > 0` y la inmutabilidad. |
| Crear saldo a favor `G` y aplicarlo a la misma deuda | Es circular: la empresa crea una obligación artificial para “pagarse” a sí misma. Solo es legítimo aplicar crédito **preexistente** de otra operación. |
| Rebajar el precio de la venta o borrar líneas | `ventas`, `venta_detalles` y `pagos_clientes` son inmutables por triggers. Reescribir historia impide auditar y puede alterar impuestos. |
| Marcar la venta como `cancelada` y dejar la deuda invisible | El estado almacenado no extingue la obligación; solo oculta el saldo. |

La extinción debe ser un **hecho económico explícito**, con tipo, importe, motivo, autorizador, fecha de negocio e idempotencia. Ese hecho no mueve caja: mueve la posición del cliente.

### 1.4 Operaciones de extinción

Se proponen tres vías legítimas y una mixta:

1. **Cobro:** el cliente paga. Es un `pago_cliente` real, permitido solo hasta `T − R` (invariante R4 del Informe2). No requiere operación especial.
2. **Condonación:** la empresa renuncia voluntariamente a cobrar, total o parcialmente. Es una decisión comercial. Reduce la deuda sin caja.
3. **Castigo:** la empresa reconoce que el crédito es incobrable después de gestiones de cobro. También reduce la deuda sin caja, pero tiene semántica, evidencia y autorización distintas.
4. **Mixto:** parte se cobra, parte se condona y parte se castiga. La suma de las tres no puede superar la deuda.

**Aplicación de saldo a favor preexistente:** si el cliente tiene crédito de otra operación, puede aplicarse a la deuda como `U`. Es una operación legítima del ledger, no una condonación. No se puede crear crédito nuevo para este fin.

**Recomendación:** la condonación y el castigo no deberían usarse para “cuadrar” una cancelación. Si el cliente acepta pagar, se cobra; si no puede, se documenta la condonación o el castigo. La diferencia debe ser visible, no absorbida en silencio.

**Sobre el “saldo condonado” y la “pérdida comercial”:** no se propone un tercer movimiento genérico porque agrupa cosas distintas. La pérdida económica de una cancelación se descompone en:

1. **Condonación o castigo de la deuda:** reduce la cuenta por cobrar; no es saldo a favor del cliente ni movimiento de caja.
2. **Pérdida de inventario:** costo histórico de las unidades devueltas que no se reintegran; se mide al costo, no al precio de venta.
3. **Menor ingreso:** si se reconoce `R < T`, la empresa deja de ingresar la diferencia; no es un movimiento adicional, es el efecto del valor reconocido.

Se reportan por separado para no duplicar. Si el propietario quiere una categoría contable llamada “pérdida comercial”, se mapea a la suma de (1) y (2) con la firma del contador, pero no se usa como sustituto de los eventos ni se registra como pago.

### 1.5 Modelo propuesto

Se añaden dos tablas append-only. La primera registra la extinción; la segunda, su eventual anulación.

```sql
CREATE TABLE extinciones_deuda_venta (
    id INTEGER PRIMARY KEY,
    venta_id INTEGER NOT NULL REFERENCES ventas(id) ON DELETE RESTRICT,
    cancelacion_id INTEGER REFERENCES cancelaciones_venta(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN ('condonacion', 'castigo')),
    importe_cop INTEGER NOT NULL CHECK (importe_cop > 0),
    motivo TEXT NOT NULL,
    referencia_autorizacion TEXT NOT NULL,
    autorizador_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    autorizado_en_utc TEXT NOT NULL,
    ejecutor_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    fecha_negocio TEXT NOT NULL,
    registrado_en_utc TEXT NOT NULL,
    clave_idempotencia TEXT NOT NULL UNIQUE,
    huella_solicitud TEXT NOT NULL
);

CREATE TABLE anulaciones_extincion_deuda (
    id INTEGER PRIMARY KEY,
    extincion_id INTEGER NOT NULL
        REFERENCES extinciones_deuda_venta(id) ON DELETE RESTRICT,
    importe_anulado_cop INTEGER NOT NULL CHECK (importe_anulado_cop > 0),
    motivo TEXT NOT NULL,
    referencia_autorizacion TEXT NOT NULL,
    autorizador_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    anulada_en_utc TEXT NOT NULL,
    clave_idempotencia TEXT NOT NULL UNIQUE
);
```

Reglas:

- Las filas de `extinciones_deuda_venta` no se editan ni se borran.
- Una extinción solo se corrige con una anulación append-only, autorizada y motivada.
- La anulación puede ser total o parcial; la suma de anulaciones no puede superar el importe de la extinción. Esto permite ajustar una condonación cuando una reversión de pago aumenta la deuda, sin borrar el hecho original.
- La anulación no borra el hecho histórico: reduce su efecto y restaura la deuda en la parte anulada.
- `cancelacion_id` es opcional porque una deuda puede existir sin cancelación formal (venta impaga). Si existe, debe pertenecer a la misma venta.
- El importe se expresa en COP entero, como el resto del sistema.
- `fecha_negocio` es la fecha contable; `registrado_en_utc` es la fecha técnica. No se confunden.

La tabla `actores` se define en la sección 3. Si se decide no crear el directorio en Fase 1, los campos `*_id` se sustituyen por texto y se documenta la pérdida de trazabilidad; no se recomienda.

### 1.6 Invariantes nuevas

| ID | Invariante | Ámbito |
|---|---|---|
| **R9** | `0 ≤ Q ≤ MAX(0, −D)`, con `Q = Σ extinciones − Σ anulaciones` (condonado + castigado, neto de anulaciones). La extinción no puede superar la deuda bruta. | Extinción |
| **R10** | `K` y `W` no modifican `P`, `U`, `C`, `G` ni inventario; no generan movimiento de caja. | Extinción |
| **R11** | En cancelación total: si `D ≥ 0`, `C + G = D` y `Q = 0`; si `D < 0`, `Q = −D` y `C = G = 0`. | Cierre |
| **R12** | Residuo de liquidación: `F = D − (C + G) + Q`. `F > 0` = reembolso pendiente; `F < 0` = deuda pendiente; `F = 0` = liquidada. | Cierre |
| **R13** | Una reversión de pago posterior debe revalidar `Q ≤ MAX(0, −D_nuevo)` y `F`; si la deuda aumenta, la extinción previa no puede quedar por encima de la nueva deuda. | Reversión |
| **R14** | Toda extinción `Q > 0` exige autorizador distinto del ejecutor, motivo y referencia de autorización. El castigo exige además evidencia de gestión de cobro. | Control |

**Nota sobre R9:** si la deuda es 400 y se condonan 400, `Q = 400`; si luego se anula la condonación total o parcialmente, `Q` baja y la deuda reaparece en la parte anulada. La anulación no puede dejar `Q` negativo ni superar la extinción original.

**Nota sobre R13:** una reversión de pago reduce `P`, por tanto reduce `D` y aumenta la deuda. Si ya había una condonación, esta puede quedar por encima de la nueva deuda. El sistema debe rechazar la reversión interna. Si es externa e inevitable, debe registrar la reversión, dejar la venta en revisión y anular parcialmente la extinción excedente con autorización; si no se puede determinar el importe, no se ajusta nada y se bloquean nuevas operaciones. No se debe “ajustar” borrando la condonación.

### 1.7 Efecto en vistas e historial

`v_saldos_ventas` debe ampliarse con:

| Columna | Fórmula |
|---|---|
| `devuelto_reconocido_cop` | `R`. |
| `condonado_cop` | `K` neto de anulaciones. |
| `castigado_cop` | `W` neto de anulaciones. |
| `deuda_bruta_cop` | `MAX(0, −D)`. |
| `deuda_pendiente_cop` | `MAX(0, −D − Q)`. |
| `sobrepago_pendiente_cop` | `MAX(0, D − (C + G))`. |
| `residuo_liquidacion_cop` | `D − (C + G) + Q`. |
| `estado_liquidacion` | `pendiente_cobro`, `cobro_parcial`, `pendiente_reembolso`, `condonada`, `castigada`, `liquidada`. |
| `estado_comercial` | `abierta`, `cancelada_con_deuda`, `cancelada_liquidada`, `cancelada_con_reembolso_pendiente`. |

`v_historial_financiero_venta` debe incluir los eventos de extinción con una convención de signos clara. Se propone:

- `efecto_residuo_cop`: cuánto cambia `F`. Positivo mejora la posición del cliente; negativo la empeora.
- `efecto_caja_cop`: salida o entrada real de dinero. Condonación y castigo siempre 0.
- `naturaleza`: `caja`, `no_caja`, `inventario`.

| Evento | `efecto_residuo_cop` | `efecto_caja_cop` |
|---|---:|---:|
| Venta | `−T` | 0 |
| Pago | `+P` | `+P` |
| Reversión de pago | `−P` | `−P` |
| Devolución reconocida | `+R` | 0 |
| Compromiso de reembolso | `−C` | 0 |
| Entrega de reembolso | 0 (ya contado en `C`) | `−C_entregado` |
| Crédito generado | `−G` | 0 |
| Crédito aplicado | `+U` | 0 |
| Condonación | `+K` | 0 |
| Castigo | `+W` | 0 |
| Anulación de extinción | `−Q_anulado` | 0 |

La suma de `efecto_residuo_cop` debe coincidir con `F`. La suma de `efecto_caja_cop` debe coincidir con el efectivo neto realmente movido. Así se evita que una condonación “aparezca” como pago en los reportes de caja.

**Reportes separados:**

- Caja: solo `efecto_caja_cop`.
- Cartera: `deuda_pendiente_cop`, con antigüedad y responsable.
- Pérdidas: condonaciones, castigos y pérdida de inventario por devoluciones no reintegradas, cada una en su columna. No se suman como si fueran lo mismo.
- Estado comercial: derivado de `F` y de las cantidades devueltas, nunca de `ventas.estado`.

### 1.8 Ejemplos numéricos

Todos los valores en COP. Se usa `K` para condonación y `W` para castigo.

#### Ejemplo 1 — devolución total con daño y deuda condonada

- Venta: `T = 1000`.
- Pagos: `P = 200`; saldo a favor aplicado: `U = 0`.
- Se devuelven todas las unidades, pero el producto está dañado y se reconoce `R = 400` (40 % del valor).
- `D = 200 + 0 − (1000 − 400) = −400`. Deuda bruta: 400.

| Alternativa | Operación | Resultado | Caja | `F` |
|---|---|---|---:|---:|
| A | Cobrar 400 | `P` pasa a 600; `D = 0` | `+400` | 0 |
| B | Condonar 400 | `K = 400`; `Q = 400` | 0 | 0 |
| C | Castigar 400 | `W = 400`; `Q = 400` | 0 | 0 |
| D | Cobrar 150 y condonar 250 | `P = 350`; `D = −250`; `K = 250` | `+150` | 0 |

En B y C la venta queda `cancelada_liquidada`, pero por razones distintas: B es una renuncia comercial; C es un crédito incobrable. En D la venta queda liquidada con cobro parcial y condonación.

La pérdida de inventario es independiente: si el artículo dañado costó 250, la pérdida de inventario es 250 y no se suma a la condonación como si fuera caja. El reporte debe mostrar ambas por separado.

#### Ejemplo 2 — devolución total sin deuda y con reembolso

- `T = 1000`, `P = 1000`, `U = 0`.
- Se devuelve todo y se reconoce `R = 1000`.
- `D = 1000 − 0 = 1000`.
- `C = 1000`, `G = 0`, `Q = 0`; `F = 1000 − 1000 + 0 = 0`.
- Se entrega 1000 en efectivo o transferencia. No hay condonación.

Este caso demuestra que la deuda no aparece por “cancelar”, sino por reconocer un valor menor al precio o retener bienes.

#### Ejemplo 3 — cancelación comercial sin devolución total

- `T = 1000` (10 unidades de 100).
- `P = 100`; el cliente conserva 3 unidades (valor 300) y devuelve 7 (valor 700).
- `R = 700`; `D = 100 − (1000 − 700) = −200`. Deuda por los bienes retenidos: 200.

Opciones:

1. **Recomendada:** no cancelar la venta completa; registrar devolución parcial de 7 unidades y dejar activas las 3 retenidas. La deuda de 200 sigue siendo cobrable.
2. Cancelar comercialmente y cobrar 200: `P = 300`, `D = 0`.
3. Cancelar y condonar 200: `K = 200`, `F = 0`.
4. Cancelar y castigar 200: `W = 200`, `F = 0`.

Lo que no se puede hacer es marcar la venta como cancelada y dejar las 3 unidades retenidas sin cargo, sin condonación ni castigo: sería una entrega gratuita no documentada.

#### Ejemplo 4 — deuda por reversión externa después de un reembolso

- `T = 1000`, `P = 1000`, devolución total `R = 1000`, reembolso `C = 1000` ya entregado.
- `D = 0`, `F = 0`.
- El banco revierte el pago original por contracargo: `P` baja a 0.
- Ahora `D = 0 − (1000 − 1000) = 0`; pero `C = 1000` ya salió. `F = 0 − 1000 + 0 = −1000`.
- El cliente recibió 1000 de reembolso y además recuperó 1000 por el contracargo: debe 1000.

La reversión debió bloquearse por R6 si era interna. Si es externa e inevitable, se registra como `reversion_externa`, se bloquean nuevos reembolsos y se trata la deuda con cobro, condonación o castigo. No se borra el reembolso.

#### Ejemplo 5 — deuda pagada con saldo a favor preexistente

- Venta B: `T = 500`, `P = 0`, devolución total con `R = 200`; `D = −300`.
- El cliente tiene crédito de 200 proveniente de la venta A.
- Se aplica `U = 200` a la venta B: `D = 0 + 200 − 300 = −100`.
- Deuda pendiente: 100. Se cobra o se condona.
- No se creó crédito nuevo; se usó crédito existente. Si se condonan 100, `Q = 100`, `F = 0`.

#### Ejemplo 6 — condonación excesiva

- `D = −300`; se intenta condonar 400.
- R9: `Q = 400 > 300`; rechazado. La deuda máxima es 300.
- Si se condona 300 y luego se anula la condonación, `Q = 0` y la deuda vuelve a 300. La anulación es un evento nuevo, no un borrado.

### 1.9 Controles y riesgos

| Riesgo | Control |
|---|---|
| Condonar dos veces la misma deuda | R9 + suma de extinciones no anuladas + clave idempotente. |
| Condonar sin autorización | R14 + trigger + servicio; autorizador distinto del ejecutor. |
| Deuda olvidada tras cancelar | `estado_comercial = cancelada_con_deuda` y reporte de cartera. |
| Condonación usada para ocultar un faltante de caja | Condonación no mueve caja; el arqueo sigue mostrando el faltante. |
| Pérdida de inventario contada como condonación | Reportes separados por naturaleza; conciliación. |
| Reversión posterior que deja `Q` por encima de la deuda | R13; rechazo o registro de exceso con revisión. |
| Condonación sin aprobación del propietario | Límites por actor y decisión pendiente A2. |
| Castigo sin evidencia de cobro | R14 y decisión pendiente A4. |

### 1.10 Pruebas de aceptación

1. Devolución total con `R = T` y `P = T`: no hay deuda; se reembolsa `D` y `F = 0`.
2. Devolución total con `R < T` y `P + U < T − R`: se detecta deuda y se ofrece cobro, condonación, castigo o mixto.
3. Condonación de la deuda exacta: `Q = −D`, `F = 0`, caja sin cambios.
4. Condonación mayor que la deuda: rechazada por R9.
5. Castigo de la deuda exacta: `Q = −D`, `F = 0`, caja sin cambios; exige evidencia.
6. Condonación sin autorizador o con autorizador igual al ejecutor: rechazada.
7. Anulación de condonación: la deuda reaparece; no se borra la fila original.
8. Pago parcial antes de condonar: `P` sube, `D` sube, `Q` baja; `F = 0`.
9. Aplicación de saldo a favor preexistente: reduce la deuda sin crear crédito nuevo.
10. Intento de crear un “pago” por condonación: rechazado por el modelo de pagos.
11. Cancelación comercial sin devolución total: no se permite cerrar sin cargo, condonación o castigo.
12. Reversión externa después de reembolso: se registra deuda, no se borra el reembolso y se bloquean nuevos reembolsos.
13. Historial: la suma de `efecto_residuo_cop` coincide con `F`; la de caja coincide con el efectivo neto.
14. Reporte de cartera y reporte de caja muestran importes distintos y reconciliables.

### 1.11 Decisiones pendientes de aprobación

| # | Decisión | Información faltante | Recomendación |
|---|---|---|---|
| A1 | ¿Se permite cerrar una cancelación con deuda? | Política comercial. | Permitir solo como estado transitorio `cancelada_con_deuda`, con plan de cobro; no como liquidada. |
| A2 | ¿Quién puede condonar y hasta qué importe? | Organización y límites. | Propietario o supervisor con límite; autorizador distinto del ejecutor. |
| A3 | Tratamiento contable de la condonación | Régimen contable/tributario. | Definir si reduce ingreso o se registra como gasto; no asumirlo. |
| A4 | Política de castigo | Procedimiento de cobro y soportes. | Exigir intentos documentados y aprobación del propietario. |
| A5 | ¿Se puede condonar el cargo por daño? | Política de daños. | Sí, con autorización y motivo; no automático. |
| A6 | ¿Se permite deuda después de cancelar si el cliente conserva bienes? | Política de ventas. | Preferir devolución parcial; si se cancela, exigir cargo explícito. |

---

## 2. Reembolsos físicos y confirmación

### 2.1 Compromiso, entrega y confirmación no son lo mismo

El Informe2 ya separaba el **compromiso** de la **confirmación**. Esta revisión precisa tres momentos:

| Momento | Qué significa | Efecto financiero | Efecto de caja |
|---|---|---|---|
| **Compromiso** | La empresa reconoce que debe reembolsar un importe y lo reserva. | Aumenta `C` (compensación comprometida) y consume el tope R2/R3. | Ninguno. |
| **Entrega** | El dinero sale físicamente: efectivo, transferencia o reverso en tarjeta. | No cambia `C`; cambia el estado a `entregada` y el reporte de caja. | Salida real. |
| **Confirmación** | Se registra en el sistema que la entrega ocurrió, con fecha efectiva y evidencia. | Formaliza el evento de entrega; es append-only. | No mueve caja por sí sola; documenta la que ya ocurrió. |

**La confirmación no es la entrega.** El dinero puede entregarse antes de que el sistema lo confirme. Si se tratara la confirmación como la entrega, un cierre inesperado haría creer que no se entregó nada y provocaría una segunda entrega. El diseño debe asumir que **la entrega física puede preceder al registro**.

### 2.2 Modelo propuesto

Se mantiene `compensaciones_cancelacion` como compromiso inmutable. Se generaliza la tabla de confirmaciones del Informe2 a una tabla de **eventos de compensación**:

```sql
CREATE TABLE eventos_compensacion (
    id INTEGER PRIMARY KEY,
    compensacion_id INTEGER NOT NULL
        REFERENCES compensaciones_cancelacion(id) ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN (
        'preparada',
        'entregada',
        'anulada',
        'en_investigacion',
        'corregida'
    )),
    ocurrido_en_utc TEXT NOT NULL,
    registrado_en_utc TEXT NOT NULL,
    registrado_por_id INTEGER NOT NULL REFERENCES actores(id) ON DELETE RESTRICT,
    autorizador_id INTEGER REFERENCES actores(id) ON DELETE RESTRICT,
    referencia_autorizacion TEXT NOT NULL DEFAULT '',
    voucher_codigo TEXT,
    medio TEXT CHECK (medio IN ('efectivo', 'transferencia', 'tarjeta', 'credito')),
    referencia_externa TEXT,
    importe_cop INTEGER CHECK (importe_cop IS NULL OR importe_cop > 0),
    motivo TEXT NOT NULL DEFAULT '',
    clave_idempotencia TEXT NOT NULL UNIQUE,
    huella_solicitud TEXT NOT NULL
);

CREATE UNIQUE INDEX uq_compensacion_entregada
    ON eventos_compensacion(compensacion_id)
    WHERE tipo = 'entregada';

CREATE UNIQUE INDEX uq_compensacion_anulada
    ON eventos_compensacion(compensacion_id)
    WHERE tipo = 'anulada';

CREATE UNIQUE INDEX uq_voucher_compensacion
    ON eventos_compensacion(voucher_codigo)
    WHERE voucher_codigo IS NOT NULL;

CREATE UNIQUE INDEX uq_referencia_externa_compensacion
    ON eventos_compensacion(medio, referencia_externa)
    WHERE referencia_externa IS NOT NULL
      AND tipo = 'entregada';
```

**Coherencia con el Informe2:** el Informe2 proponía `confirmaciones_compensacion` con dos tipos (`confirmada`, `anulada`). Esta revisión la generaliza a `eventos_compensacion` para cubrir preparación, entrega, anulación, investigación y corrección. Es un cambio de nombre y de alcance, no una contradicción: la confirmación pasa a ser el evento `entregada`.

Reglas de integridad:

- `preparada` exige `voucher_codigo`, `medio` y `registrado_por_id`; no exige `importe_cop` porque el importe está en el compromiso.
- `entregada` exige `voucher_codigo`, `medio`, `importe_cop` igual al importe del compromiso y `ocurrido_en_utc`.
- `anulada` solo se permite si no existe un evento `entregada` para la misma compensación.
- `corregida` solo se permite si existe un evento `entregada`; exige autorizador y motivo.
- `en_investigacion` se permite cuando hay duda sobre una entrega; bloquea nuevas entregas y nuevas compensaciones para la misma venta hasta resolverse.
- No se borra ni se edita ningún evento. Las correcciones son eventos nuevos.
- Una compensación no puede tener dos entregas. Si se necesita entregar en partes, se crean dos compromisos separados desde el inicio.

### 2.3 Estados efectivos

El estado se deriva de los eventos:

| Estado | Eventos presentes | ¿Cuenta para `C`? | ¿Caja? | ¿Permite nueva entrega? |
|---|---|---|---:|---|
| `comprometida` | Ninguno | Sí | No | Sí, tras preparar. |
| `preparada` | `preparada` | Sí | No | Sí, una sola vez. |
| `entregada` | `preparada` + `entregada`, o solo `entregada` | Sí | Sí | No. |
| `anulada` | `anulada`, sin `entregada` | No | No | No; se crea otro compromiso si hace falta. |
| `en_investigacion` | `preparada` + `en_investigacion` | Sí | No | No hasta resolver. |
| `corregida` | `entregada` + `corregida` | Según la corrección | Según la corrección | No; requiere un nuevo compromiso si corresponde. |

**Alcance de la corrección:** `corregida` no cambia el importe ni sustituye una entrega por otra. Solo corrige datos de la entrega ya registrada (fecha, referencia, receptor o medio) o deja constancia de que la entrega registrada no ocurrió. Si la corrección implica que no hubo entrega, debe pasar primero por `en_investigacion`, exigir evidencia y autorización, y liberar el compromiso con un evento explícito; nunca se borra `entregada`. Si el importe cambia, se anula el compromiso (si aún no se entregó) o se crea uno nuevo; no se edita el existente.

**Regla de oro:** mientras exista un compromiso `preparada` o `en_investigacion` para una venta, la UI no debe permitir crear otro reembolso para esa misma venta sin una autorización de excepción. El tope económico R2/R3 no basta para evitar una doble entrega del mismo compromiso; se necesita el control por estado y por voucher.

### 2.4 Flujo normal

```text
1. Autorizar la compensación (autorizador distinto del ejecutor).
2. Insertar el compromiso en compensaciones_cancelacion.
   - Clave de idempotencia persistida en solicitudes_operacion.
3. Preparar la entrega:
   - Insertar evento 'preparada' con voucher único.
   - Imprimir el voucher con código, importe, venta, cliente y fecha.
4. Entregar el dinero contra el voucher:
   - Efectivo: contar el dinero, recibir firma y documento del receptor.
   - Transferencia: ejecutarla y anotar la referencia bancaria.
   - Tarjeta: ejecutar el reverso y anotar la referencia de la terminal.
5. Insertar evento 'entregada' con:
   - fecha efectiva (ocurrido_en_utc),
   - fecha de registro (registrado_en_utc),
   - quién entregó y quién recibió,
   - voucher, medio y referencia externa.
6. Si algo falla antes del paso 5, el compromiso queda 'preparada';
   el voucher es la evidencia física para confirmar después.
```

**Orden crítico:** el compromiso se confirma en base **antes** de imprimir el voucher. Así no puede existir un voucher de una operación que no está registrada. Si la impresora falla después del commit, se reimprime el mismo voucher; no se crea otro.

### 2.5 Puntos de fallo y recuperación

| Punto de fallo | Estado en base | ¿Se entregó dinero? | Acción al reiniciar |
|---|---|---|---|
| Antes del compromiso | Nada | No (política: no entregar sin registro) | Repetir la operación con la misma clave. |
| Después del compromiso, antes de preparar | `comprometida` | No | Preparar y entregar cuando corresponda. |
| Después de preparar, antes de entregar | `preparada` | No | Entregar una sola vez o anular con autorización. |
| Durante la entrega, antes de confirmar | `preparada` | **Sí, posiblemente** | Verificar voucher y arqueo; confirmar con fecha efectiva o pasar a investigación. |
| Después de confirmar, antes de responder a la UI | `entregada` | Sí | El reintento devuelve la compensación; no duplica. |

**Caso crítico: la aplicación se cierra después de entregar el efectivo pero antes de confirmar.** Al reiniciar, la compensación sigue `preparada`. La UI muestra un panel de “entregas pendientes de confirmar” con el voucher y el importe. El operador debe:

1. Verificar si el voucher está firmado o si el efectivo falta del cajón.
2. Si se entregó: confirmar con la fecha efectiva y la referencia; el evento `entregada` se inserta una sola vez.
3. Si no se entregó: anular con autorización y motivo; el compromiso libera el tope.
4. Si no se puede determinar: marcar `en_investigacion`; no entregar de nuevo hasta resolver.

**Nunca auto-anular una entrega preparada.** El sistema no sabe si el dinero ya salió. Auto-anular permitiría una segunda entrega y perdería el rastro.

### 2.6 Prevención de doble entrega

La prevención es una combinación de base de datos y operación:

| Control | Qué impide | Limitación |
|---|---|---|
| Índice único `(compensacion_id) WHERE tipo='entregada'` | Dos confirmaciones de la misma compensación. | No impide dos entregas físicas si nadie confirma la primera. |
| Voucher único impreso antes de entregar | Reutilizar el mismo comprobante para dos entregas. | Requiere que el voucher se imprima y se use. |
| Estado `preparada` visible al reiniciar | Olvidar una entrega en curso. | Depende de que el operador revise el panel. |
| Bloqueo de nuevas compensaciones para la misma venta mientras haya `preparada` o `en_investigacion` | Crear un segundo reembolso “por si acaso”. | Puede requerir excepción autorizada para casos legítimos. |
| Tope R2/R3 | Comprometer más de lo que corresponde. | No distingue dos entregas del mismo importe si el tope aún permite más. |
| Arqueo de caja al cierre | Detectar efectivo faltante o sobrante. | Es posterior al hecho; no evita la primera entrega. |
| Doble control en importes altos | Una sola persona no prepara y entrega. | Difícil en negocios de una sola persona. |

**Ejemplo de doble entrega evitada:** `D = 600`. Se comprometen 300 con voucher V-001 y se entregan sin confirmar. Al reiniciar, el operador ve la entrega pendiente. Si intenta crear otra compensación de 300, el sistema la bloquea porque hay una `preparada` para la misma venta. Si confirma V-001, el estado pasa a `entregada` y el tope queda en 300; una segunda compensación de 300 podría ser legítima solo si se autoriza y ya no hay entrega pendiente. El voucher V-001 no se puede reutilizar.

**Ejemplo de entrega legítima en dos partes:** en lugar de una compensación de 600 entregada en dos veces, se crean dos compromisos de 300, cada uno con su voucher y su evento `entregada`. Así el sistema no necesita un estado de “entrega parcial” y cada salida queda trazada.

### 2.7 Idempotencia y trazabilidad

- **Creación del compromiso:** clave en `solicitudes_operacion`; misma clave y misma huella devuelven el mismo compromiso; misma clave y otra huella producen conflicto.
- **Preparación:** clave única; reintentar devuelve el mismo voucher. Si el voucher ya existe, no se genera otro.
- **Entrega:** clave única + índice único por compensación; reintentar devuelve el evento existente.
- **Anulación:** clave única; solo si no hay entrega; reintentar devuelve la anulación existente.
- **Corrección:** clave única; exige autorizador y motivo; no borra la entrega original.
- **Transferencia:** `(medio, referencia_externa)` único para evitar registrar dos veces la misma transferencia.
- **Tarjeta:** misma regla; la referencia de la terminal es la evidencia.
- **Crédito:** no tiene entrega física; se genera en la misma transacción del compromiso y no usa `eventos_compensacion` de tipo `entregada`.

**Trazabilidad mínima por entrega:**

| Dato | Por qué |
|---|---|
| `compensacion_id` | Une compromiso, entrega y venta. |
| `voucher_codigo` | Prueba física única. |
| `importe_cop` | Coincide con el compromiso; detecta alteraciones. |
| `medio` | Efectivo, transferencia, tarjeta. |
| `referencia_externa` | Banco o terminal. |
| `ocurrido_en_utc` | Fecha real de entrega. |
| `registrado_en_utc` | Fecha de registro; puede ser posterior. |
| `registrado_por_id` | Quién registró. |
| `autorizador_id` | Quién aprobó la entrega o la excepción. |
| `motivo` | Explica anulaciones, investigaciones y correcciones. |

**Reportes:**

- `v_compensaciones_pendientes`: compromisos sin entrega ni anulación, con antigüedad y voucher.
- `v_entregas_del_dia`: entregas por fecha efectiva y por fecha de registro, separadas.
- `v_arqueo_caja`: efectivo entregado, pendiente y anulado; diferencia contra el conteo físico.
- `v_investigaciones_compensacion`: casos en investigación, con responsable y fecha límite.

**Limitación:** sin autenticación, la trazabilidad prueba lo que el sistema registró, no quién estuvo físicamente frente a la pantalla. El voucher firmado y el arqueo son las pruebas operativas reales. Se desarrolla en la sección 3.

### 2.8 Ejemplos operativos y numéricos

#### Ejemplo 1 — efectivo entregado y aplicación cerrada antes de confirmar

- Venta `T = 1000`, `P = 1000`, devolución `R = 300`; `D = 300`.
- Se compromete `C = 300` en efectivo, voucher `V-2026-001`.
- El cajero entrega 300 y el cliente firma el voucher.
- La aplicación se cierra antes de pulsar “confirmar”.
- Al reiniciar: compensación `preparada`, voucher `V-2026-001`.
- El operador confirma con fecha efectiva 10:15 y registro 10:22; se inserta `entregada`.
- `C = 300`, caja `−300` una sola vez. `F = 0`.
- Si intenta confirmar de nuevo: el índice único y la clave devuelven el evento existente; no hay segunda salida.

#### Ejemplo 2 — transferencia pendiente de verificación

- `D = 500`. Se compromete una transferencia de 500, voucher `V-2026-002`.
- Se prepara y se ordena la transferencia; el banco aún no confirma.
- La aplicación se cierra. Al reiniciar, estado `preparada`.
- El operador verifica el extracto: referencia `BCO-99881`.
- Confirma con `referencia_externa = 'BCO-99881'`; el índice único impide usar la misma referencia en otra entrega.
- Si el banco rechaza la transferencia, se anula con evidencia y el tope se libera. No se marca `entregada`.

#### Ejemplo 3 — entrega incierta

- `D = 400`. Compromiso preparado, voucher `V-2026-003`.
- Al reiniciar no hay voucher firmado, pero falta dinero del cajón.
- El operador no puede determinar si se entregó.
- Se marca `en_investigacion`; no se anula y no se entrega de nuevo.
- Se revisa el arqueo, se contacta al cliente y se revisan cámaras/comprobantes.
- Si se confirma la entrega: evento `entregada` con evidencia y autorización.
- Si se confirma que no hubo entrega: anulación con autorización y ajuste de caja por el faltante (que es un problema de caja, no un reembolso).

#### Ejemplo 4 — dos entregas legítimas

- `D = 600`. Se crean dos compromisos: `C1 = 300`, `C2 = 300`.
- Cada uno tiene voucher y evento `entregada` independiente.
- `C = 600`; caja `−600`; `F = 0`.
- No se usa un estado de entrega parcial: cada salida es una operación completa.

#### Ejemplo 5 — intento de duplicar tras reinicio

- `D = 300`; compromiso `C1 = 300` ya entregado, pero la UI no se actualizó.
- El usuario intenta crear `C2 = 300`.
- R2/R3: `C1 + C2 = 600 > D = 300`; rechazado.
- Aunque el tope fallara por un error de cálculo, la regla de “no nueva compensación con entrega pendiente” y el estado `entregada` bloquean la operación.
- Si `D = 600` y `C1 = 300` entregado, `C2 = 300` es legítimo; el voucher distinto y la referencia distinta lo distinguen. El sistema no puede confundirlos.

### 2.9 Riesgos y controles

| Riesgo | Control |
|---|---|
| Doble entrega de efectivo | Voucher único + índice único de entrega + bloqueo por estado + arqueo. |
| Entrega sin compromiso registrado | Política: no se entrega sin voucher del sistema; excepción documentada como incidente. |
| Entrega olvidada | Panel de pendientes al inicio + reporte diario + antigüedad. |
| Confirmación falsa | Voucher firmado, referencia bancaria, arqueo y revisión del propietario; sin autenticación no hay prueba criptográfica. |
| Anulación de una entrega ya hecha | Prohibida si existe `entregada`; solo corrección autorizada. |
| Transferencia duplicada | Índice único por referencia externa. |
| Reverso de tarjeta duplicado | Referencia de terminal única + confirmación del banco. |
| Pérdida de trazabilidad por cierre | `ocurrido_en_utc` y `registrado_en_utc` separados; voucher físico. |
| Corrección que borra historia | Eventos append-only; `corregida` no elimina `entregada`. |
| Importe alterado | `importe_cop` de la entrega debe igualar el compromiso; trigger/servicio. |

### 2.10 Pruebas de aceptación

1. Compromiso sin preparar: no hay voucher, no hay caja, `C` cuenta.
2. Preparar: se crea voucher único; reintentar devuelve el mismo.
3. Entregar: se crea un solo evento `entregada`; `C` no cambia; caja sale una vez.
4. Confirmar dos veces: no se duplica.
5. Cerrar después del compromiso y antes de preparar: al reiniciar se puede preparar una sola vez.
6. Cerrar después de preparar y antes de entregar: al reiniciar se puede entregar o anular.
7. Cerrar después de entregar y antes de confirmar: al reiniciar se confirma con fecha efectiva; no se entrega de nuevo.
8. Cerrar después de confirmar: el reintento devuelve la entrega existente.
9. Anular una compensación preparada: libera el tope; no permite si ya hay entrega.
10. Anular una compensación entregada: rechazada; solo corrección autorizada.
11. Marcar `en_investigacion`: bloquea nuevas entregas y nuevas compensaciones para la venta.
12. Transferencia con referencia repetida: rechazada.
13. Dos compromisos para la misma venta con vouchers distintos: permitidos si el tope lo permite.
14. Intento de segunda entrega del mismo compromiso: rechazado.
15. Arqueo: la suma de entregas del día coincide con la salida de caja registrada.
16. Historial: `C` incluye compromisos pendientes y entregados; `C_conf` solo entregados; los reportes no se confunden.
17. Compensación con importe distinto al compromiso: rechazada.
18. Corrección de entrega: no borra la original; requiere autorizador y motivo.

### 2.11 Decisiones pendientes de aprobación

| # | Decisión | Información faltante | Recomendación |
|---|---|---|---|
| B1 | ¿Se permite entregar sin registro en el sistema? | Operación real y tolerancia al riesgo. | No; solo excepción documentada como incidente con autorización posterior. |
| B2 | ¿Se permiten entregas parciales de un mismo compromiso? | Política de caja. | No; dividir en compromisos separados. |
| B3 | ¿Quién puede preparar y quién entregar? | Tamaño del equipo. | Misma persona en negocios pequeños; doble control sobre umbral. |
| B4 | ¿Se permite corregir una entrega confirmada? | Política de errores. | Solo con autorización, evidencia y evento de corrección; nunca borrar. |
| B5 | ¿Qué evidencia se conserva? | Espacio y obligaciones. | Voucher firmado, comprobante bancario o referencia de terminal; retención a definir. |
| B6 | ¿Se acepta el estado `en_investigacion`? | Operación. | Sí; es preferible a anular o duplicar. |
| B7 | Umbral para doble control | Monto y riesgo. | Definir con el propietario; empezar bajo. |

---

## 3. Identidad y autorización sin autenticación

### 3.1 Punto de partida real

Hoy no existe tabla de usuarios, inicio de sesión, contraseñas, sesiones ni control de acceso. Los campos de responsable y autorizador son texto libre. Por tanto:

- **No hay identidad verificada.** Cualquiera frente al equipo puede escribir cualquier nombre.
- **No hay no repudio.** El sistema no puede probar quién autorizó.
- **No hay permisos reales.** Quien tenga acceso al archivo SQLite puede leer o modificar datos.
- **Los triggers pueden validar reglas de datos**, pero no pueden saber quién está sentado frente al teclado.

Este documento **no inventa** una seguridad que no existe. Propone un esquema declarativo, con controles operativos reales y una ruta de migración a autenticación.

### 3.2 Directorio de actores

Se propone una tabla `actores` que funciona como **directorio**, no como autenticación:

```sql
CREATE TABLE actores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    documento TEXT,
    rol_operativo TEXT NOT NULL CHECK (rol_operativo IN (
        'vendedor', 'tecnico', 'cajero', 'supervisor', 'propietario', 'contador', 'otro'
    )),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    puede_autorizar INTEGER NOT NULL DEFAULT 0 CHECK (puede_autorizar IN (0, 1)),
    limite_autorizacion_cop INTEGER,
    creado_en_utc TEXT NOT NULL,
    actualizado_en_utc TEXT NOT NULL,
    notas TEXT NOT NULL DEFAULT ''
);
```

Características:

- No tiene contraseña ni PIN. No es un mecanismo de autenticación.
- El propietario mantiene el directorio y decide quién está activo y quién puede autorizar.
- Solo los actores activos aparecen en los selectores de la UI.
- `limite_autorizacion_cop` permite un tope por actor; `NULL` significa sin límite definido (debe tratarse como pendiente, no como ilimitado).
- Los actores no se borran: se desactivan. Los históricos siguen visibles.

**Por qué un directorio y no texto libre:** reduce errores de tipeo, permite reglas de segregación por ID, facilita reportes y prepara la migración a usuarios. No aumenta la seguridad por sí solo, pero hace verificable la consistencia de los datos.

### 3.3 Campos por operación

Todas las operaciones sensibles deben registrar:

| Campo | Contenido |
|---|---|
| `solicitante_id` | Actor que pide la operación, o `NULL` si es el cliente. |
| `solicitante_tipo` | `cliente` o `interno`. |
| `solicitante_nombre_snapshot` | Nombre tal como se registró; no se actualiza si luego cambia. |
| `ejecutor_id` | Actor que registra la operación. |
| `ejecutor_nombre_snapshot` | Nombre histórico. |
| `autorizador_id` | Actor que aprueba; obligatorio cuando corresponde. |
| `autorizador_nombre_snapshot` | Nombre histórico. |
| `autorizado_en_utc` | Fecha de aprobación. |
| `referencia_autorizacion` | Documento, mensaje, voucher o radicado que prueba la aprobación. |
| `medio_autorizacion` | `presencial`, `telefono`, `whatsapp`, `correo`, `documento_firmado`, `otro`. |
| `origen_identidad` | `directorio`, `legado`, `sistema` (para filas generadas automáticamente). |

**Snapshots:** cada operación guarda el nombre y rol del actor en el momento. Si mañana el actor cambia de nombre o se desactiva, el historial no se reescribe. Es la misma lógica de inmutabilidad que ya usa el sistema para ventas y pagos.

**Operaciones legadas:** las filas anteriores al directorio conservan el texto original, con `actor_id NULL` y `origen_identidad = 'legado'`. No se inventan IDs ni se corrigen nombres hacia atrás.

### 3.4 Reglas de segregación

| Operación | Autorizador obligatorio | Autorizador ≠ ejecutor | Autorizador ≠ solicitante |
|---|---|---|---|
| Devolución sin compensación | No | — | — |
| Devolución con reembolso > 0 | Sí | Sí | Recomendado |
| Generación de crédito > 0 | Sí | Sí | Recomendado |
| Uso de crédito | No | — | — |
| Ajuste de crédito | Sí | Sí | Sí |
| Condonación de deuda | Sí | Sí | Sí |
| Castigo de deuda | Sí | Sí | Sí |
| Devolución sin reintegro con reembolso total | Sí | Sí | Sí |
| Valor reconocido menor al precio | Sí | Sí | Sí |
| Anulación de entrega preparada | Sí | Sí | Recomendado |
| Corrección de entrega confirmada | Sí | Sí | Sí |

**Implementación en base:** un trigger puede verificar que `autorizador_id` no sea nulo, que sea distinto de `ejecutor_id`, que el actor esté activo y que `puede_autorizar = 1`. También puede comparar el importe con `limite_autorizacion_cop`. Lo que **no** puede verificar es que la persona frente al teclado sea ese actor.

**Implementación en servicio:** validar lo mismo antes de escribir, con mensajes claros. La base es la última defensa; el servicio evita intentos inválidos y explica el motivo.

### 3.5 Controles operativos realistas para la primera versión

Sin autenticación, los controles deben ser organizativos, documentales y de conciliación. Estos son realistas y verificables:

| # | Control | Qué riesgo reduce | Limitación |
|---|---|---|---|
| C1 | El propietario mantiene el directorio de actores y revisa altas/bajas mensualmente. | Actores inexistentes o inactivos. | No impide que alguien seleccione otro nombre. |
| C2 | Los actores se seleccionan de una lista; no se escribe texto libre en operaciones nuevas. | Errores y suplantación trivial por tipeo. | La lista es visible para cualquiera. |
| C3 | Toda autorización exige `referencia_autorizacion` (mensaje, correo, voucher firmado, radicado). | Autorizaciones inventadas. | La referencia puede falsificarse; se contrasta con el soporte. |
| C4 | Voucher impreso y firmado para cada reembolso en efectivo. | Doble entrega y confirmaciones falsas. | Requiere disciplina y archivo. |
| C5 | Arqueo de caja diario por el propietario o un supervisor, contra el reporte del sistema. | Faltantes y entregas no registradas. | Es posterior; detecta, no previene. |
| C6 | Revisión de operaciones pendientes al iniciar la aplicación; no se permite un nuevo reembolso de la misma venta sin resolver la pendiente. | Doble entrega tras cierre. | Depende de que se revise el panel. |
| C7 | Revisión semanal de condonaciones, castigos y ajustes de crédito. | Uso indebido de extinciones. | Muestra el evento, no la identidad real. |
| C8 | Equipo con cuenta de sistema operativo propia y bloqueo de pantalla; la base no se comparte por red. | Acceso casual o remoto. | No protege contra acceso físico al archivo. |
| C9 | Respaldos periódicos y conservación de vouchers/comprobantes. | Pérdida de evidencia. | No evita fraude; permite reconstruir. |
| C10 | Doble control para importes altos: una persona prepara, otra entrega o autoriza. | Colusión o error de una sola persona. | Difícil si hay una sola persona; requiere excepción. |
| C11 | Registro de incidentes para entregas sin sistema, anulaciones tardías y diferencias de caja. | Pérdida de trazabilidad. | Es manual; debe revisarse. |
| C12 | Exportación mensual del historial financiero y de los eventos de compensación. | Alteración posterior del archivo. | No es inmutable fuera del sistema. |

**Regla de transparencia:** la UI debe mostrar una advertencia clara de que la identidad es declarativa y de que la autorización no está verificada criptográficamente. No se debe presentar como “seguro” lo que es solo un registro de nombres.

### 3.6 Limitaciones explícitas

| Limitación | Consecuencia | Mitigación |
|---|---|---|
| Cualquiera puede seleccionar cualquier actor. | Suplantación trivial. | Directorio + revisión + evidencia física; no hay solución técnica sin autenticación. |
| No hay contraseñas ni sesiones. | No se puede atribuir una acción a una persona. | Voucher firmado, arqueo, revisión del propietario. |
| No hay permisos por rol reales. | Un actor no autorizado podría intentar autorizar. | `puede_autorizar` y límites en base; sigue siendo declarativo. |
| SQLite es un archivo local. | Quien tenga acceso puede modificarlo. | Cuenta de sistema operativo, respaldos, control físico. |
| Los triggers no conocen la sesión. | No pueden validar identidad. | Validan datos y segregación por ID; la identidad queda fuera. |
| No hay no repudio. | No se puede probar quién firmó. | Documento físico firmado; no es criptográfico. |
| La autorización puede ser posterior. | Se puede “aprobar” después de ejecutar. | `autorizado_en_utc` y referencia; política de que la aprobación precede a la entrega. |

**Conclusión:** la primera versión puede ser **consistente y auditable**, pero no **segura contra suplantación**. Es importante decirlo sin ambigüedad. Si el negocio necesita seguridad real, debe priorizar el módulo de usuarios.

### 3.7 Migración a autenticación multiusuario

Cuando se implemente autenticación, la migración debe preservar la historia. Propuesta por etapas:

1. **Usuarios:** crear `usuarios` con `usuario`, `hash_contraseña`, `mfa_habilitado`, `activo`, `actor_id` único y roles. No se reutiliza el nombre como clave.
2. **Mapeo:** vincular cada `actor` con un `usuario`. Los actores sin usuario quedan como `legado`: visibles en historia, no seleccionables para operaciones nuevas.
3. **Sesiones:** agregar `sesiones` y `auditoria_accesos`; el sistema toma el actor de la sesión, no de un selector.
4. **Campos:** conservar `actor_id` y los snapshots; agregar `usuario_id` y `rol_en_momento`. Las operaciones nuevas usan ambos; las viejas conservan `actor_id`.
5. **Permisos:** roles (vendedor, cajero, técnico, supervisor, propietario, contador), permisos por operación y límites. La autorización se hace desde la sesión del autorizador.
6. **Aprobaciones:** tabla `aprobaciones` con `solicitud_id`, `usuario_id`, `importe`, `vigencia`, `estado` y `token`; el autorizador aprueba desde su sesión. Un usuario no puede aprobar su propia solicitud.
7. **MFA:** obligatorio para autorizadores y para operaciones por encima del umbral.
8. **Auditoría:** registro append-only con usuario, sesión, IP/equipo si aplica, antes/después y hash de integridad.
9. **Backfill:** no se reescriben nombres ni fechas. Se marca `origen_identidad = 'legado'` y se conserva el texto original.
10. **Pruebas:** conteos, integridad referencial, historia visible, prohibición de autoaprobación, expiración de sesión y bloqueo por intentos.

**Qué se migra:** la relación actor–usuario, los permisos y los límites. **Qué no se migra:** los nombres históricos, los importes, las fechas ni las decisiones pasadas. **Qué se agrega:** `usuario_id`, sesión, MFA, aprobaciones y auditoría de accesos.

**Orden recomendado:** primero el directorio de actores en Fase 1; después autenticación en una fase posterior. Así la Fase 1 no se bloquea y la migración futura encuentra datos ordenados.

### 3.8 Pruebas de aceptación

1. No se puede guardar una operación sin ejecutor.
2. No se puede guardar una compensación, condonación o castigo sin autorizador.
3. Autorizador igual al ejecutor: rechazado.
4. Autorizador inactivo o sin `puede_autorizar`: rechazado.
5. Importe superior al límite del autorizador: rechazado.
6. Falta `referencia_autorizacion`: rechazado.
7. Actor inactivo no aparece en el selector de operaciones nuevas.
8. Operación histórica de un actor desactivado sigue visible con su nombre.
9. Cambio de nombre de un actor no altera el snapshot histórico.
10. Operación legada sin actor muestra `origen_identidad = 'legado'`.
11. La UI advierte que la identidad es declarativa.
12. Después de la migración: sin sesión no se opera.
13. El usuario de la sesión no puede ser cambiado desde la UI.
14. Autoaprobación: rechazada.
15. Actor legado sin usuario no puede autorizar operaciones nuevas.
16. La auditoría registra usuario, fecha, operación y referencia.

### 3.9 Decisiones pendientes de aprobación

| # | Decisión | Información faltante | Recomendación |
|---|---|---|---|
| ID1 | ¿Quiénes son los actores y qué roles tienen? | Organización real. | Crear el directorio antes de operar la Fase 1. |
| ID2 | ¿Quién puede autorizar y con qué límites? | Política de riesgo. | Propietario y supervisor con límites; revisar mensualmente. |
| ID3 | ¿Qué excepción se aplica si hay una sola persona? | Tamaño del negocio. | Documentar autoautorización excepcional con evidencia reforzada o autorizador externo (contador/asesor). |
| ID4 | ¿Qué evidencia de autorización se conserva? | Obligaciones y espacio. | Voucher firmado, mensaje o correo; retención mínima a definir. |
| ID5 | ¿Se implementa autenticación ahora o después? | Prioridades y presupuesto. | Después de la Fase 1; el directorio deja el terreno preparado. |
| ID6 | ¿Se acepta que la identidad sea declarativa? | Tolerancia al riesgo. | Sí, con controles operativos y advertencia explícita; no presentarlo como seguridad. |

---

## 4. Impacto técnico consolidado

### 4.1 Tablas nuevas

| Tabla | Propósito | Fase |
|---|---|---|
| `actores` | Directorio declarativo de solicitantes, ejecutores y autorizadores. | 1 |
| `extinciones_deuda_venta` | Condonaciones y castigos append-only. | 1 |
| `anulaciones_extincion_deuda` | Anulación append-only de una extinción. | 1 |
| `eventos_compensacion` | Preparación, entrega, anulación, investigación y corrección. | 1 |
| `documentos_operacion` (opcional) | Referencias y hashes de vouchers/comprobantes. | 1 o posterior |

### 4.2 Columnas nuevas

- `cancelaciones_venta`: `solicitante_id`, `solicitante_tipo`, `solicitante_nombre_snapshot`, `ejecutor_id`, `ejecutor_nombre_snapshot`, `autorizador_id`, `autorizador_nombre_snapshot`, `autorizado_en_utc`, `referencia_autorizacion`, `medio_autorizacion`, `origen_identidad`.
- `compensaciones_cancelacion`: mismos campos de actor y autorización; `voucher_codigo` puede vivir en el evento de preparación.
- `movimientos_saldo_favor`: `actor_id`, `autorizador_id`, snapshots y `origen_identidad`.
- `extinciones_deuda_venta`: actores y autorización.
- `eventos_compensacion`: actores, voucher, medio, referencia externa e importe.

No se reescriben filas históricas. Las columnas nuevas quedan `NULL` en lo antiguo y las vistas resuelven el legado.

### 4.3 Vistas

| Vista | Contenido |
|---|---|
| `v_saldos_ventas` | `D`, `Q`, `F`, deuda bruta/pendiente, sobrepago, estado de liquidación y estado comercial. |
| `v_historial_financiero_venta` | Eventos con `efecto_residuo_cop`, `efecto_caja_cop` y naturaleza. |
| `v_compensaciones_pendientes` | Compromisos sin entrega ni anulación, con antigüedad y voucher. |
| `v_entregas_del_dia` | Entregas por fecha efectiva y por fecha de registro. |
| `v_arqueo_caja` | Efectivo comprometido, entregado, anulado y diferencia. |
| `v_investigaciones_compensacion` | Casos en investigación y responsable. |
| `v_condonaciones_castigos` | Extinciones por tipo, actor, autorizador y fecha. |
| `v_devoluciones_no_reintegradas` | Pérdida de inventario por devoluciones no aptas (Informe2). |

### 4.4 Triggers

- R9: tope de extinción contra la deuda bruta.
- R10: prohibición de efectos de caja/inventario en condonación y castigo.
- R11/R12: coherencia de cierre y residuo.
- R13: revalidación ante reversión de pago.
- R14: autorizador distinto, activo, con permiso y dentro del límite.
- Estado de eventos: `anulada` solo sin `entregada`; `corregida` solo con `entregada`; una sola `entregada` por compensación.
- Voucher único y referencia externa única.
- `importe_cop` de entrega igual al compromiso.
- Prohibición de borrar o editar eventos y extinciones.

### 4.5 Servicios

| Servicio | Responsabilidad |
|---|---|
| `ActorService` | Directorio, activación, permisos y snapshots. |
| `AuthorizationService` | Reglas de segregación, límites y referencias. |
| `DebtService` | Condonar, castigar, anular y consultar deuda. |
| `RefundDeliveryService` | Preparar, entregar, anular, investigar y corregir. |
| `SalesService` | Integrar devolución, deuda y estado comercial. |
| `CreditService` | Generar, aplicar y ajustar saldo a favor. |
| `IdempotencyService` | Intenciones, huellas y recuperación. |

### 4.6 UI

- Diálogo de cancelación con resumen de deuda y elección explícita: cobrar, condonar, castigar o mixto.
- Diálogo de reembolso con preparación, voucher, entrega y confirmación separadas.
- Panel de inicio con operaciones pendientes y entregas preparadas.
- Selector de actores con advertencia de identidad declarativa.
- Diálogo de autorización con referencia y motivo.
- Reportes de cartera, caja, condonaciones, castigos y pérdida de inventario.
- Bloqueo de nuevas operaciones mientras haya una entrega pendiente de la misma venta, salvo excepción autorizada.

### 4.7 Migraciones

Las tablas y columnas de este informe se incorporan a las migraciones planificadas del Informe2, sin cambiar su número:

| Migración | Contenido adicional |
|---|---|
| `0009_idempotency_and_operation_intents.sql` | `actores`; campos de actor en `solicitudes_operacion`. |
| `0010_sale_returns_credit_and_confirmations.sql` | `extinciones_deuda_venta`, `anulaciones_extincion_deuda`, `eventos_compensacion`, triggers R9–R14, vistas de deuda y entrega. |
| `0011_canonical_order_totals_and_history.sql` | Vistas de historial y reportes que consumen los eventos nuevos. |

Si en el futuro las migraciones 0008–0011 ya estuvieran aplicadas en un entorno, se añadiría una `0012` con el mismo contenido. Como la Fase 1 no está implementada, no se requiere una migración extra ahora. No se reescriben filas históricas ni se eliminan columnas.

---

## 5. Matriz consolidada de riesgos

| Riesgo | Probabilidad | Impacto | Control |
|---|---|---|---|
| Deuda condonada dos veces | Media | Alto | R9, suma de extinciones, clave idempotente. |
| Pago ficticio para “cuadrar” deuda | Media | Alto | Prohibición de tipos, CHECK, triggers, revisión. |
| Condonación sin autorización | Media | Alto | R14, trigger, límite, revisión semanal. |
| Deuda olvidada tras cancelar | Alta | Medio | Estado `cancelada_con_deuda`, cartera, alertas. |
| Doble entrega de efectivo | Media | Alto | Voucher único, índice único, estado, arqueo. |
| Entrega no registrada | Media | Alto | Panel de pendientes, voucher firmado, incidentes. |
| Confirmación falsa | Media | Alto | Evidencia física, arqueo, revisión; sin autenticación no se elimina. |
| Transferencia duplicada | Baja | Alto | Referencia externa única. |
| Anulación de entrega ya hecha | Baja | Alto | Trigger: `anulada` solo sin `entregada`. |
| Suplantación de actor | Alta | Medio | Directorio, advertencia, revisión; seguridad real pendiente. |
| Autorización posterior | Media | Medio | `autorizado_en_utc`, referencia, política. |
| Migración rompe historia | Baja | Alto | Aditiva, snapshots, pruebas sobre copia real. |
| Pérdida de inventario contada dos veces | Media | Medio | Reportes separados y conciliación. |
| Reversión posterior invalida condonación | Baja | Alto | R13, revisión, deuda pendiente. |
| Negocio de una sola persona | Alta | Medio | Excepción documentada; autorizador externo si es posible. |

---

## 6. Pruebas de aceptación consolidadas

Las pruebas de las secciones 1.10, 2.10 y 3.8 se suman a las 36 del Informe2. Para el cierre de Fase 1 se consideran obligatorias estas categorías:

| Categoría | Pruebas mínimas |
|---|---|
| Deuda y extinción | 14 pruebas de la sección 1.10. |
| Entrega de reembolsos | 18 pruebas de la sección 2.10. |
| Identidad y autorización | 16 pruebas de la sección 3.8. |
| Regresión | Las 36 del Informe2 siguen aprobando. |
| Migración | Copia real → v11, integridad, conteos, importes y restauración. |
| Caja | Arqueo contra entregas; condonaciones y castigos no aparecen como caja. |
| Historia | Suma de efectos de residuo = `F`; suma de caja = efectivo neto. |

**Criterio de aceptación global:** ninguna operación puede dejar `F` distinto de cero sin un estado explícito (`pendiente_reembolso`, `cancelada_con_deuda`, `en_investigacion`). Ninguna entrega puede registrarse dos veces. Ninguna condonación puede superar la deuda. Ninguna autorización puede tener autorizador igual al ejecutor.

---

## 7. Decisiones que requieren aprobación del propietario

| # | Decisión | Por qué no se asume | Recomendación |
|---|---|---|---|
| **A1** | ¿Se permite que una cancelación total quede con deuda? | Es política comercial y de cartera. | Permitir solo como estado transitorio con plan de cobro; no como liquidada. |
| **A2** | ¿Quién condona y hasta qué importe? | Depende de la organización y el riesgo. | Propietario/supervisor con límites; autorizador distinto. |
| **A3** | Tratamiento contable de la condonación | Depende del régimen contable/tributario. | Definir con contador; no asumir. |
| **A4** | Política y evidencia de castigo | Depende del procedimiento de cobro. | Exigir gestiones documentadas y aprobación. |
| **A5** | ¿Se condona el cargo por daño? | Es política de daños. | Sí, con autorización y motivo; no automático. |
| **A6** | ¿Se permite deuda si el cliente conserva bienes tras cancelar? | Política de ventas. | Preferir devolución parcial; si se cancela, exigir cargo explícito. |
| **B1** | ¿Se entrega dinero sin registro en el sistema? | Es política operativa. | No; excepción documentada como incidente. |
| **B2** | ¿Entregas parciales de un compromiso? | Afecta el modelo y la caja. | No; dividir en compromisos. |
| **B3** | ¿Quién prepara y quién entrega? | Depende del equipo. | Misma persona si es pequeño; doble control sobre umbral. |
| **B4** | ¿Se corrige una entrega confirmada? | Política de errores. | Solo con autorización, evidencia y evento nuevo. |
| **B5** | Evidencia y retención de vouchers | Obligaciones y espacio. | Voucher firmado/comprobante; retención a definir. |
| **B6** | ¿Se acepta el estado `en_investigacion`? | Operación y tolerancia a la incertidumbre. | Sí; es preferible a anular o duplicar. |
| **B7** | Umbral de doble control | Monto y riesgo. | Definir con el propietario; empezar bajo. |
| **ID1** | Actores, roles y autorizadores | Organización real. | Crear el directorio antes de operar. |
| **ID2** | Límites de autorización | Política de riesgo. | Límites por actor; revisión mensual. |
| **ID3** | Excepción para una sola persona | Tamaño del negocio. | Documentar autoautorización excepcional o autorizador externo. |
| **ID4** | Evidencia de autorización | Obligaciones. | Voucher, mensaje o correo; retención mínima. |
| **ID5** | ¿Autenticación ahora o después? | Prioridades y presupuesto. | Después de Fase 1; directorio ahora. |
| **ID6** | ¿Se acepta identidad declarativa? | Tolerancia al riesgo. | Sí, con advertencia y controles; no llamarlo seguridad. |

---

## 8. Resumen de cambios respecto al Informe2

| Tema | Informe2 | Informe3 |
|---|---|---|
| Cancelación total | Preveía cierre con `C + G = D`; no desarrollaba deuda. | Añade R9–R14, extinciones de deuda, estado `cancelada_con_deuda` y tratamiento de condonación/castigo. |
| Deuda | No había operación explícita. | `extinciones_deuda_venta` + `anulaciones_extincion_deuda`; nunca pagos ficticios. |
| Reembolsos | Compromiso + confirmación en dos fases. | Precisión de tres momentos: compromiso, entrega y confirmación; preparación con voucher; investigación; recuperación tras cierre. |
| Confirmaciones | `confirmaciones_compensacion` con `confirmada`/`anulada`. | Generalizada a `eventos_compensacion` con `preparada`, `entregada`, `anulada`, `en_investigacion`, `corregida`. |
| Prevención de doble entrega | Clave única y confirmación. | Añade voucher único, índice único de entrega, bloqueo por estado, arqueo y revisión de pendientes. |
| Identidad | Roles declarativos en texto. | Directorio `actores`, snapshots, reglas de segregación, controles operativos y ruta de migración a autenticación. |
| Autorización | Campos y reglas. | Referencia, medio, límites, autorizador distinto y advertencia de identidad no verificada. |
| Vistas | Saldos e historial. | Añade deuda, condonaciones, castigos, entregas, arqueo, investigaciones y cartera. |
| Pruebas | 36. | Se suman 48 pruebas específicas (14 + 18 + 16) y regresión. |
| Migraciones | 0008–0011. | Mismos números, contenido ampliado; sin reescritura histórica. |

### 8.1 Cierre

Este documento es una **revisión de diseño**. No se implementó ninguna funcionalidad. No se modificaron código, SQL, migraciones, base de datos, configuración ni workflows. No se alteró el Informe2 ni ningún documento anterior. El único archivo creado es este informe.

Las decisiones A1–A6, B1–B7 e ID1–ID6 requieren aprobación del propietario antes de implementarse. La Fase 1 puede comenzar por las migraciones y servicios que no dependen de esas decisiones (directorio de actores, idempotencia, eventos), pero la implementación completa requiere cerrar las políticas indicadas.
