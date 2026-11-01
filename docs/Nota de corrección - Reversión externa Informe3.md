# Nota de corrección — Reversión externa posterior a un reembolso

**Referencia:** `Informe3 - Cierre de decisiones Fase 1.md`, sección 1.8, ejemplo 4.  
**Alcance:** revisión exclusiva de ese escenario. No es una auditoría general.  
**Efecto:** esta nota corrige la lectura matemática de R3, R9, R11, R12 y R13 para el caso de reversión externa. No modifica el Informe3 ni ningún otro documento, código, SQL, migración o dato.

---

## 1. El escenario y el resultado actual

Ejemplo 4 del Informe3:

- `T = 1000`, `P = 1000`, devolución total `R = 1000`.
- Reembolso entregado `C = 1000`, `G = 0`, `Q = 0`.
- Antes de la reversión: `D = 1000`, `F = 0` (el cliente pagó 1000 y devolvió todo; el sobrepago es 1000).
- El banco revierte el pago original: `P` baja a `0`.
- Después: `D = 0`, `C = 1000`, `F = −1000`.

Hay un error aritmético en el ejemplo original: antes de la reversión `D = 1000`, no `0`; después de la reversión `D = 0`. La conclusión de que el cliente debe 1000 no cambia.

El Informe3 concluye correctamente que el cliente debe 1000. El problema es que las invariantes R3, R9, R11 y R13, leídas literalmente, no permiten ese estado ni su resolución. R12 sí lo describe, pero no lo hace accionable.

---

## 2. Compatibilidad de las invariantes

| Invariante | Lectura literal | Ejemplo 4 después de la reversión | ¿Compatible? |
|---|---|---|---|
| **R3** | `C ≤ P` | `1000 ≤ 0` es falso. | **No** como invariante de estado. |
| **R9** | `0 ≤ Q ≤ MAX(0, −D)` | `D = 0`, luego `Q ≤ 0`: no se puede condonar ni castigar. | **No**. |
| **R11** | Si `D ≥ 0`, `C + G = D` y `Q = 0` | `1000 ≠ 0`. | **No**. |
| **R12** | `F = D − (C + G) + Q` | `F = −1000`: deuda pendiente. | **Sí**, pero solo si `C` es el reembolso entregado. |
| **R13** | Revalidar `Q ≤ MAX(0, −D_nuevo)` y `F` | `Q = 0`, pasa; pero la razón es distinta. | **Incompleta/mal dirigida**. |

### 2.1 R3: no es una invariante de estado, es una regla de emisión

R3 se cumple al comprometer y entregar el reembolso: `C = 1000 ≤ P = 1000`. Deja de cumplirse cuando un tercero reduce `P` después del hecho. No se puede impedir que el banco revierta, y no se debe “corregir” borrando el reembolso.

**Corrección:** R3 debe aplicarse **antes** de comprometer o entregar un nuevo reembolso, no retroactivamente sobre uno ya entregado. Si una reversión externa deja `C_e > P`, la diferencia es una deuda real, no una violación que se resuelva con un movimiento ficticio.

### 2.2 R9: la base de la deuda no es `−D`

R9 usa `MAX(0, −D)`, que solo mide la deuda de precio de venta. En el ejemplo 4, `D = 0`, pero el cliente debe 1000 porque recibió un reembolso que el banco dejó sin financiación. La base correcta es el **beneficio neto recibido por el cliente**:

```text
N0 = C_e + G − D
```

donde `C_e` son los reembolsos **entregados** (no los meramente comprometidos). `N0 > 0` es deuda; `N0 < 0` es sobrepago pendiente de reembolso.

En el ejemplo 4: `N0 = 1000 + 0 − 0 = 1000`.

**Corrección:** `0 ≤ Q ≤ MAX(0, N0 − H)`, donde `H` son las recuperaciones de deuda. Para el caso sin recuperación, `Q ≤ 1000`.

### 2.3 R11: el cierre no depende del signo de `D`

R11 dice que con `D ≥ 0` debe cumplirse `C + G = D`. Eso presupone que el reembolso no puede exceder `D`, lo cual es cierto solo si no hay reversión externa. Después de la reversión, `D = 0` y `C_e = 1000`: el estado es válido económicamente, pero R11 lo rechaza.

**Corrección:** el cierre se expresa con el residuo `F`:

```text
F = H + Q − N0
```

- `F = 0`: liquidada.
- `F < 0`: deuda pendiente `−F`.
- `F > 0`: reembolso pendiente `F` si `N0 < 0`; si `N0 > 0`, es una extinción excesiva inválida.
- `Q > 0` solo si `N0 > 0`.
- En cancelación total, además debe cumplirse `C_p = 0` (no hay reembolsos comprometidos pendientes de entregar).

### 2.4 R12: compatible, pero distingue compromiso de entrega

La fórmula original:

```text
F = D − (C + G) + Q
```

es algebraicamente equivalente a `F = Q − N0` **si `C = C_e` y `H = 0`**. Con recuperación `H`, se amplía a:

```text
F = H + Q − N0
```

El problema es que el Informe3 define `C` como reembolsos **comprometidos** (pendientes + entregados). Para medir deuda real hay que usar `C_e` (entregados). Si se usa `C` comprometido, `F = 0` puede ocultar un reembolso pendiente de entrega. Por eso se separan:

- `C_c`: comprometido, para el tope de autorización.
- `C_e`: entregado, para la deuda y la caja.
- `C_p = C_c − C_e`: pendiente de entrega.

R12 sigue siendo válida; solo debe usar `C_e`.

### 2.5 R13: la reversión de pago no reduce la deuda, la aumenta

R13 afirma que una reversión de pago puede hacer que `Q` quede por encima de la nueva deuda. La desigualdad es correcta, pero la premisa no se cumple en una reversión de **pago**:

- La reversión reduce `P`.
- `D = P + U − (T − R)` disminuye.
- `MAX(0, −D)` aumenta.
- `N0 = C_e + G − D` también aumenta.

Si `Q` era válido antes (`Q ≤ deuda_anterior`), sigue siendo válido después (`Q ≤ deuda_nueva`), porque la deuda aumentó. El riesgo real es otro:

1. **Reversión de pago:** puede dejar `C_e > P`; eso viola R3 y crea deuda por reembolso no financiado.
2. **Reversión de un reembolso:** reduce `C_e`, reduce `N0` y **sí** puede dejar `Q > N0`; ahí debe revalidarse y, si hace falta, anular parcialmente la extinción.

**Corrección:** dividir R13 en R13-P (reversión de pago) y R13-C (reversión de reembolso).

### 2.6 Corrección de registro erróneo vs reversión financiera real

No son el mismo hecho y no pueden compartir el mismo tipo de evento:

| Evento | Qué significa | ¿El dinero entró realmente? | Efecto en `P` | Requisito |
|---|---|---|---|---|
| `correccion_registro_erroneo` | Se registró un ingreso que nunca existió: duplicado, importe equivocado, prueba, error de digitación. | **No.** Se demuestra con extracto, comprobante o conciliación. | Baja `P` en el importe mal registrado. | Evidencia de que el dinero nunca ingresó; recálculo de saldos; bloqueo si hay operaciones posteriores incompatibles. |
| `reversion_financiera_real` | El dinero sí ingresó y luego fue revertido por el banco, un contracargo o una devolución real. | **Sí**, y luego salió o fue retirado. | Baja `P` por el importe revertido. | Registro siempre, automático o manual; deuda `N0`/`F` si `C_e > P`; anulación de `C_p`; bloqueo de nuevas entregas no financiadas. |

Reglas comunes:

- El pago original **nunca se elimina ni se modifica**. Ambos eventos son append-only y se relacionan con `pago_cliente_id`.
- La **procedencia** se registra en un campo separado: `origen_evento = banco | operador | conciliacion | otro`. La procedencia no determina la naturaleza contable; la determinan los hechos: si el dinero nunca ingresó, es corrección; si ingresó y luego se revirtió, es reversión real.
- Una reversión real introducida manualmente por un operador tiene el mismo tratamiento contable que una recibida automáticamente del banco. Cambia la procedencia y la evidencia, no la naturaleza.
- Ambos eventos recalculan `P`, `D`, `N0`, `F`, `Q`, `H` y las vistas de saldos.

**Procedimiento de corrección de registro erróneo:**

1. Aportar evidencia de que el dinero nunca ingresó (extracto sin el abono, duplicado identificado, comprobante anulado).
2. Registrar `correccion_registro_erroneo` con importe, motivo, evidencia, actor, autorizador y clave idempotente.
3. Recalcular `P` y todos los saldos; no se borra ni se edita el pago original.
4. Detectar operaciones posteriores que dependan del `P` erróneo: reembolsos comprometidos o entregados, crédito usado, pagos aplicados, deuda condonada.
5. Si hay operaciones incompatibles, **bloquear** hasta resolverlas: anular compromisos pendientes, reversar lo que corresponda o escalar el caso. Si `C_e > P` tras la corrección, no se crea deuda automáticamente: es una operación posterior incompatible y debe resolverse antes de cerrar. Si no se puede deshacer, se escala como incidente y se trata como deuda real con autorización, no como corrección silenciosa.

**Procedimiento de reversión financiera real:**

1. Registrar el evento, venga del banco o de un operador, con referencia bancaria, fecha efectiva, fecha de registro, actor y evidencia.
2. Mantener el pago original intacto.
3. Reducir `P`; recalcular `D`, `N0`, `F`.
4. Si `C_e > P`, reconocer la deuda por `N0` y `F`.
5. Anular los compromisos `C_p` que ya no estén financiados y bloquear nuevas entregas no financiadas.
6. No invalidar `Q` retroactivamente por una reversión de pago. Solo una reversión de reembolso activa R13-C y exige revalidar `Q`.

---

## 3. Modelo mínimo corregido

Sin crear movimientos ficticios, se precisan las magnitudes siguientes (tres nuevas: `C_e`, `H` y `N0`):

| Magnitud | Definición | Uso |
|---|---|---|
| `C_c` | Reembolsos comprometidos (pendientes + entregados). | Tope de autorización. |
| `C_e` | Reembolsos entregados. | Deuda real y caja. |
| `C_p` | `C_c − C_e`. | Reembolsos pendientes de entrega. |
| `H` | Recuperaciones de deuda por reversión (dinero real que entra); se usa especialmente para la parte que no cabe en un pago de venta. | Reduce la deuda; no es pago de venta. |
| `Q` | Condonaciones y castigos netos de anulaciones. | Extingue deuda sin caja. |
| `N0` | `C_e + G − D`. | Beneficio neto recibido; base de la deuda bruta. |
| `F` | `H + Q − N0`. | Residuo: `F < 0` deuda, `F > 0` reembolso pendiente (solo si `N0 < 0`), `F = 0` liquidada. |

Restricciones:

```text
0 ≤ H ≤ MAX(0, N0)
0 ≤ Q ≤ MAX(0, N0 − H)
H + Q ≤ MAX(0, N0)
Si N0 ≤ 0: H = 0 y Q = 0
```

La deuda bruta es `MAX(0, N0)`; la deuda pendiente es `MAX(0, N0 − H − Q) = MAX(0, −F)` cuando `N0 > 0`. El componente de **reembolso no financiado** es `V = MAX(0, C_e − P)`, siempre que exista un evento de reversión externa registrado. `V` no sustituye a `N0`: es una desagregación para reportes. Una reversión también puede aumentar la deuda de venta cuando `P` cae por debajo de `T − R`; en ese caso `V = 0` y el aumento queda recogido en `N0` (ver ejemplo C).

---

## 4. Ajustes a las invariantes

| Invariante | Ajuste propuesto |
|---|---|
| **R3** | Aplicar en la emisión: antes de comprometer, `C_c + nuevo ≤ P`; antes de entregar, `C_e + nuevo ≤ P`. No reevaluar retroactivamente. Si una reversión externa deja `C_e > P`, la diferencia `V = C_e − P` se reconoce como deuda respaldada por el evento de reversión. Los reembolsos pendientes `C_p` se anulan; no se entregan. |
| **R9** | `0 ≤ Q ≤ MAX(0, N0 − H)`, con `H ≤ MAX(0, N0)`. Sustituye a `MAX(0, −D)`. |
| **R11** | En cancelación total: `C_p = 0` y `F = 0` para `cancelada_liquidada`. Si `F < 0`, `cancelada_con_deuda` (subtipo `por_reversion` si `V > 0`). Si `F > 0` y `N0 < 0`, `cancelada_con_reembolso_pendiente`; si `F > 0` y `N0 > 0`, es una extinción excesiva inválida. `Q > 0` solo si `N0 > 0`. |
| **R12** | `F = D − (C_e + G) + H + Q = H + Q − N0`. Si se usa `C_c` en lugar de `C_e`, el resultado es un residual de compromiso, no de liquidación. |
| **R13-P** | Reversión de pago: `P` baja, `N0` sube. Interna: bloquear si `C_e > P_nuevo`; si `C_c > P_nuevo`, anular `C_p` hasta que quepa. Externa: registrar, permitir el exceso como deuda `V`, anular `C_p` y bloquear nuevos reembolsos. `Q` no se invalida por esta vía. |
| **R13-C** | Reversión o anulación de reembolso: `C_e` baja, `N0` baja. Revalidar `Q ≤ MAX(0, N0 − H)`. Si `Q` excede, anular parcialmente la extinción o rechazar la reversión. |

### 4.1 Compatibilidad con las decisiones incorporadas

| Invariante | Corrección de registro erróneo | Reversión financiera real | ¿Compatible? |
|---|---|---|---|
| **R3** | Recalcula `P`; si deja `C_e > P`, hay operación posterior incompatible y se bloquea. No se crea deuda automáticamente. | Puede dejar `C_e > P`; se reconoce deuda `N0`/`F`, se anula `C_p` y se bloquean nuevas entregas no financiadas. | **Sí.** R3 sigue siendo regla de emisión, no invariante retroactiva. |
| **R9** | No crea deuda nueva; si el recálculo revela deuda por operaciones posteriores, se bloquea hasta resolver. | `P` baja, `N0` sube; el tope de `Q` aumenta y `Q` previo no se invalida. | **Sí.** La base es `N0`, no `−D`. |
| **R11** | Recalcula `F`; no se marca liquidada si hay incompatibilidades o `C_p > 0`. | `F < 0` si queda deuda; se cancela `C_p`; la venta queda `cancelada_con_deuda` hasta extinguir. | **Sí.** El cierre usa `F = H + Q − N0`. |
| **R12** | Recalcula `P`, `N0` y `F`; no se usa para crear deuda. | Recalcula `P`, `N0` y `F`; la deuda surge de `C_e > P`. | **Sí.** La fórmula usa `C_e` y `H`. |
| **R13-P** | No es una reversión de pago; no se aplica R13-P. Si `C_e > P`, se bloquea. | Aumenta `N0`; no invalida `Q`; exige cancelar `C_p` y bloquear nuevas entregas no financiadas. | **Sí.** R13-P aplica solo a reversión real de pago. |

---

## 5. Cómo se registra la deuda

La deuda **no se registra como un pago**. Se registra el hecho real que la origina y se deriva el saldo:

1. **Evento append-only relacionado con el pago original** (el pago nunca se elimina ni se modifica):
   - `correccion_registro_erroneo`: solo con evidencia de que el dinero nunca ingresó. Recalcula `P` y todos los saldos. Si hay operaciones posteriores incompatibles, se bloquea hasta resolverlas; no se usa para crear deuda por reversión.
   - `reversion_financiera_real`: se registra siempre, venga del banco o de un operador. Reduce `P`; si `C_e > P`, reconoce la deuda por `N0` y `F`; anula `C_p` no financiado y bloquea nuevas entregas no financiadas.
   - Campos: pago original, venta, importe, tipo de evento, `origen_evento` (`banco`, `operador`, `conciliacion`, `otro`), referencia, motivo, fecha efectiva, fecha de registro, actor, autorizador, evidencia, clave de idempotencia y huella.
   - Importe positivo; el signo lo aplica la vista al restar de `P`.
2. **Cálculo derivado:** `N0 = C_e + G − D`; `F = H + Q − N0`; deuda pendiente `= MAX(0, N0 − H − Q)`.
3. **Estado:** `cancelada_con_deuda` si la venta está totalmente devuelta y `F < 0`; el subtipo `_por_reversion` se usa cuando `V > 0`. Si `V = 0`, la deuda es de venta incrementada por la reversión, no un reembolso no financiado. Si no es cancelación total, `con_deuda`.
4. **Cobro:** si la deuda cabe en `T − R`, se cobra como pago normal de venta (R4 lo permite). La parte que excede `T − R`, o la deuda que existe cuando `T − R = 0`, se registra como `H` en una tabla de recuperaciones (o en un pago con concepto específico). `H` es dinero real que entra, pero **no aumenta `P`** y no debe disparar R4. Se reporta como “recuperación de reversión”, no como pago de venta.
5. **Condonación/castigo:** `Q` se registra en `extinciones_deuda_venta` con origen `reversion` y referencia al evento. Es no-caja. `H` y `Q` deben imputarse a un componente (venta o reversión) para los reportes; la suma de imputaciones no puede superar `N0`.
6. **Nada de movimientos ficticios:** no se crea un `pago_cliente` negativo, no se usa un `recibo` para condonar, no se genera crédito `G` para “pagar” la deuda y no se borra el reembolso.

**La procedencia no define la naturaleza:** un operador puede registrar una reversión real y el banco puede informar una corrección de registro. Lo que decide es si el dinero ingresó y salió, no quién lo informó. `origen_evento` se conserva para auditoría, pero no cambia el tratamiento contable.

**Por qué `H` separado de `P`:** si el cobro de la deuda se registrara como pago normal, `P` subiría por encima de `T − R` y R4 lo bloquearía. Además, inflaría el historial de pagos de la venta con dinero que no corresponde al precio. `H` conserva ambas cosas: la caja real y la naturaleza de recuperación.

---

## 6. ¿La deuda puede cobrarse, condonarse o castigarse con las reglas actuales?

| Acción | Regla actual | Resultado en el ejemplo 4 |
|---|---|---|
| **Cobrar** | R4: `P + U ≤ T − R` para un nuevo pago. | **No como pago de venta.** `T − R = 0`; cualquier pago nuevo viola R4. Se requiere `H`. |
| **Condonar** | R9: `Q ≤ MAX(0, −D)`. | **No.** `D = 0`; `Q ≤ 0`. |
| **Castigar** | R9, mismo tope. | **No.** Misma razón. |
| **Ver la deuda** | R12: `F = D − (C + G) + Q`. | **Sí.** `F = −1000`; se ve, pero no se puede resolver. |
| **Cerrar la venta** | R11: con `D ≥ 0`, `C + G = D`. | **No.** `1000 ≠ 0`. |

**Conclusión:** con las reglas actuales la deuda es visible, pero no accionable. No se puede cobrar por R4, no se puede condonar ni castigar por R9, y no se puede cerrar por R11. Hacen falta los ajustes de la sección 4.

**Matiz:** si `T − R > 0`, la parte de deuda que quepa en `T − R` puede cobrarse con un pago normal; solo el exceso requiere `H`. En el ejemplo 4, `T − R = 0`, por eso todo el cobro requiere `H`. El ejemplo C ilustra un caso donde el pago normal de 600 es suficiente.

---

## 7. Ejemplos numéricos

### Ejemplo A — reversión total, tres formas de resolver

- `T = 1000`, `P = 1000`, `R = 1000`, `C_e = 1000`, `G = 0`.
- Antes: `D = 1000`, `N0 = 0`, `F = 0`.
- El banco revierte 1000: `P = 0`, `D = 0`, `N0 = 1000`, `F = −1000`.
- Deuda: 1000. `V = C_e − P = 1000`.

| Resolución | `H` | `Q` | `F` | Caja | Efecto |
|---|---:|---:|---:|---:|---|
| Cobrar todo | 1000 | 0 | 0 | `+1000` | Deuda extinguida por recuperación. |
| Condonar todo | 0 | 1000 | 0 | 0 | Deuda extinguida sin caja; reporte de condonación. |
| Castigar todo | 0 | 1000 | 0 | 0 | Igual, pero con evidencia de incobrabilidad. |
| Mixto | 300 | 700 | 0 | `+300` | Recuperación parcial y condonación parcial. |
| Exceso | 300 | 800 | `+100` | `+300` | **Inválido:** `H + Q = 1100 > N0 = 1000`. |

`P` permanece en 0 en todos los casos; el cobro se registra como `H`, no como pago de venta. Así no se viola R4 y el historial de la venta no se infla.

### Ejemplo B — reversión parcial

- `T = 1000`, `P = 1000`, `R = 1000`, `C_e = 1000`.
- El banco revierte 400: `P = 600`, `D = 600`, `N0 = 1000 − 600 = 400`, `F = −400`.
- `V = C_e − P = 400`.
- Cobrar `H = 400` → `F = 0`. Condonar `Q = 400` → `F = 0`.
- Si se cobran 500: `H > N0`; rechazado por exceso.

### Ejemplo C — deuda de venta más reversión

- `T = 1000`, `P = 200`, `R = 400`; `T − R = 600`; `D = 200 − 600 = −400`.
- `C_e = 0`, `G = 0`; `N0 = 0 − (−400) = 400`.
- El banco revierte los 200: `P = 0`, `D = −600`, `N0 = 600`.
- Deuda total: 600 = 400 de precio pendiente + 200 de pago revertido.
- Como `T − R = 600`, un pago normal de 600 es válido (R4 lo permite) y deja `P = 600`, `D = 0`, `N0 = 0`, `F = 0`. Es la opción recomendada para no separar artificialmente la deuda de venta.
- Alternativas: `H = 600` (mantiene `P = 0` y registra todo como recuperación) o condonar `Q = 600`; mixto `H = 200, Q = 400` también es válido.

### Ejemplo D — reversión con reembolso pendiente

- `T = 1000`, `P = 1000`, `R = 1000`.
- `C_c = 1000`, pero solo `C_e = 500` entregados; `C_p = 500` pendientes.
- El banco revierte 1000: `P = 0`, `D = 0`, `N0 = 500`, `F = −500`.
- Los 500 pendientes **no se entregan**: se anulan. La deuda es 500.
- Si se entregaran los 500 pendientes: `C_e = 1000`, `N0 = 1000`, deuda 1000; el sistema debe bloquearlo.

Esto muestra por qué R12 debe usar `C_e` y no `C_c`: con `C_c = 1000`, la fórmula original daría `F = −1000` aun antes de entregar los 500 pendientes, exagerando la deuda.

### Ejemplo E — reversión de un reembolso (R13-C)

- `T = 1000`, `P = 0` (ya revertido), `R = 1000`, `C_e = 1000`, `Q = 500`.
- `N0 = 1000`, `F = 500 − 1000 = −500`: deuda 500.
- Se revierte el reembolso completo: `C_e = 0`, `N0 = 0`.
- Ahora `Q = 500 > N0 = 0`: **inválido**. Hay que anular 500 de la condonación; `Q` vuelve a 0 y `F = 0`.
- Si solo se revierte 400 del reembolso: `C_e = 600`, `N0 = 600`, `Q = 500`, `F = −100`: deuda 100; válido.

Este es el caso en el que R13 original sí era necesario, pero aplicado a `C_e`, no a `P`.

### Ejemplo F — sobrepago normal, sin reversión

- `T = 1000`, `P = 1000`, `R = 300`; `D = 300`.
- `C_e = 200`, `G = 0`; `N0 = 200 − 300 = −100`.
- `F = −N0 = 100`: reembolso pendiente de 100.
- Se entrega otro reembolso de 100: `C_e = 300`, `N0 = 0`, `F = 0`.
- `Q = 0` y `H = 0` porque no hay deuda.

### Ejemplo G — corrección de registro erróneo

- `T = 1000`, `R = 1000`; el cliente pagó 1000 una sola vez.
- El operador registró el pago dos veces: `P = 2000`; `D = 2000`, `C_e = 0`, `N0 = −2000`, `F = 2000` (sobrepago pendiente).
- Se demuestra el duplicado con el extracto y se registra `correccion_registro_erroneo` por 1000.
- El pago original no se borra; el evento se enlaza a él. `P` vuelve a 1000; `D = 1000`; `N0 = 0`; `F = 0`.
- Si antes de la corrección se hubiera entregado un reembolso de 1500: `C_e = 1500`, `P = 1000`, `N0 = 500`, `F = −500`; `C_e > P`. La corrección se **bloquea** por operación posterior incompatible. Hay que recuperar 500, revertir la parte que corresponda o escalar el caso; no se crea deuda automáticamente por una corrección.

### Ejemplo H — reversión real informada por banco o por operador

- `T = 1000`, `P = 1000`, `R = 1000`, `C_e = 1000`.
- El banco notifica un contracargo de 1000: se registra `reversion_financiera_real` con `origen_evento = banco`.
- `P = 0`, `D = 0`, `N0 = 1000`, `F = −1000`; deuda 1000; el pago original permanece intacto.
- Si el operador introduce manualmente la misma reversión, con `origen_evento = operador` y la misma evidencia, el resultado contable es idéntico: `P = 0`, `N0 = 1000`, `F = −1000`.
- Si la reversión es parcial de 400: `P = 600`, `D = 600`, `N0 = 400`, `F = −400`.
- La diferencia entre banco y operador es de procedencia y evidencia, no de naturaleza contable.

---

## 8. Pruebas de aceptación

1. **Reversión total después de reembolso total:** `P = 0`, `C_e = 1000`, `N0 = 1000`, `F = −1000`; estado `cancelada_con_deuda_por_reversion`; no se crea pago negativo.
2. **R3 no retroactiva:** el reembolso histórico no se revierte ni se borra; solo se bloquean nuevos reembolsos.
3. **R9:** `Q = 1000` se acepta; `Q = 1001` se rechaza.
4. **R9 con recuperación:** `H = 300`, `Q = 700` se acepta; `H = 300`, `Q = 800` se rechaza.
5. **R11:** con `Q = 0` la venta queda con deuda; con `Q = 1000` queda liquidada; con `C_p > 0` no se marca liquidada.
6. **R12:** `F = −1000` antes de cobrar; `F = 0` después de `H = 1000`; `F = −600` después de `Q = 400`.
7. **R13-P interna:** una reversión interna que deje `C_e > P_nuevo` se bloquea.
8. **R13-P externa:** se registra el evento, se permite `C_e > P_nuevo`, se crea la deuda `V` y se bloquean nuevos reembolsos.
9. **R13-C:** una reversión de reembolso que deje `Q > N0` se rechaza o exige anulación parcial de `Q`.
10. **Cobro `H`:** reduce la deuda, no aumenta `P`, no dispara R4 y es idempotente.
11. **Condonación/castigo `Q`:** reduce la deuda, no mueve caja y aparece en reportes separados.
12. **Exceso:** `H + Q > N0` se rechaza; no se acepta sobre-extinción.
13. **Reembolso pendiente:** tras la reversión, `C_p` se anula y no se entrega; si se intenta entregar, se bloquea y se alerta.
14. **Idempotencia:** dos notificaciones del mismo banco con la misma referencia no duplican la reversión; dos cobros con la misma clave no duplican `H`.
15. **Reportes:** `deuda_total`, `deuda_por_reversion`, `recuperado`, `condonado`, `castigado` y `F` reconcilian; la caja solo incluye `H`, no `Q`.
16. **Sin movimientos ficticios:** no existe `pago_cliente` negativo, no se usa `recibo` para condonar, no se crea `G` para pagar la deuda y no se borra el reembolso.
17. **Deuda dentro de `T − R`:** si `T − R > 0`, la parte de deuda de venta se cobra con pago normal; `H` solo se usa para el exceso o cuando `T − R = 0`.
18. **Corrección sin evidencia:** `correccion_registro_erroneo` sin prueba de que el dinero nunca ingresó se rechaza.
19. **Pago original intacto:** la corrección no elimina ni modifica el pago original; solo agrega un evento append-only enlazado.
20. **Recálculo:** la corrección actualiza `P`, `D`, `N0`, `F` y las vistas; los saldos no quedan con el valor erróneo.
21. **Corrección incompatible:** si después del pago erróneo hay reembolsos, crédito usado o deuda condonada, la corrección se bloquea hasta resolverlos.
22. **Reversión real manual:** un operador puede registrar una `reversion_financiera_real`; el resultado contable es el mismo que si viniera del banco.
23. **Reversión real automática:** una notificación del banco se registra como `reversion_financiera_real` sin intervención manual y con la misma contabilidad.
24. **Procedencia:** `origen_evento` queda registrado; cambiar de banco a operador no cambia `N0`, `F` ni la naturaleza contable.
25. **Deuda por reversión real:** `C_e > P` genera deuda por `N0`/`F`; no se crea un pago negativo ni se borra el reembolso.
26. **Pendientes no financiados:** tras la reversión, `C_p` se anula y no se permiten nuevas entregas no financiadas.
27. **Q y R13:** una reversión de pago no invalida `Q`; una reversión de reembolso que deje `Q > N0` activa R13-C y exige anulación parcial o rechazo.

---

## 9. Decisiones que requieren aprobación

| # | Decisión | Recomendación |
|---|---|---|
| PA1 | ¿Se cobra la deuda por reversión o se absorbe como pérdida? | Intentar cobro; si no es viable, condonar o castigar con autorización. |
| PA2 | ¿Se cobran comisiones del banco por contracargo? | No modelarlas en esta corrección; decidir aparte. |
| PA3 | ¿Quién autoriza `H` y `Q`? | Autorizador distinto del ejecutor, con límites. |
| PA4 | ¿Tratamiento contable del castigo? | Definir con contador; no asumirlo. |
| PA5 | ¿Se permite deuda por reversión después de cancelación total? | Sí, como estado `cancelada_con_deuda_por_reversion` hasta resolver. |
| PA6 | ¿Se permite reversión parcial? | Sí; el modelo la soporta con `V` y `H` parciales. |

---

## 10. Resumen de la corrección

| Punto | Informe3 | Corrección |
|---|---|---|
| R3 | `C ≤ P` como invariante de estado. | Regla de emisión; exceso por reversión externa se reconoce como deuda `V`. |
| R9 | `Q ≤ MAX(0, −D)`. | `Q ≤ MAX(0, N0 − H)`, con `N0 = C_e + G − D`. |
| R11 | Cierre según signo de `D`. | Cierre según `F = H + Q − N0` y `C_p = 0`. |
| R12 | `F = D − (C + G) + Q`. | `F = D − (C_e + G) + H + Q`; usar entregados, no comprometidos. |
| R13 | Reversión de pago podría invalidar `Q`. | R13-P: la reversión de pago aumenta la deuda; el riesgo es `C_e > P`. R13-C: la reversión de reembolso reduce `N0` y sí puede invalidar `Q`. |
| Deuda | Se ve en `F`, sin operación de cobro. | Evento de reversión + `H` (cobro) + `Q` (condonación/castigo). |
| Movimientos | No había camino para resolverla. | Sin movimientos ficticios: reversión real, recuperación real, extinción no-caja. |
| Tipos de evento | No distinguía corrección de reversión. | `correccion_registro_erroneo` solo con evidencia de que el dinero nunca ingresó; `reversion_financiera_real` siempre se registra. |
| Pago original | No estaba regulado. | Nunca se elimina ni modifica; el evento es append-only y se enlaza a él. |
| Procedencia | No estaba separada de la naturaleza. | `origen_evento` (banco, operador, conciliación, otro) se registra, pero no define la naturaleza contable. |
| Reembolsos pendientes | No se anulaban automáticamente. | `C_p` no financiado se anula y se bloquean nuevas entregas no financiadas. |

**Conclusión:** el ejemplo 4 es económicamente correcto, pero las invariantes R3, R9 y R11 no lo soportan y R13 está mal dirigida. La corrección mínima es separar compromiso de entrega (`C_c`/`C_e`), medir la deuda con `N0`, añadir recuperaciones `H`, y expresar el cierre con `F`. Además, se separa la corrección de registro erróneo de la reversión financiera real, se conserva el pago original y se registra la procedencia sin confundirla con la naturaleza contable. Con eso, la deuda puede cobrarse, condonarse o castigarse sin crear pagos ficticios, y el resto de las invariantes del Informe2/Informe3 se conserva.
