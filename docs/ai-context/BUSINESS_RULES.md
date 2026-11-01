# BUSINESS_RULES

Fuente autoritativa: Informe2, Informe3 y Nota de corrección (carpeta `docs/`). Este resumen no los sustituye.

- Dinero en COP enteros. Nunca borrar ni editar registros financieros; se corrige con reversión/evento compensatorio.
- Fecha de negocio = día calendario de Bogotá (UTC-5); `*_en_utc` es el instante técnico. No se reescribe historia.
- Métodos de pago: catálogo único; textos legados se resuelven por alias; `CSX` legado sin clasificar (P1).
- Invariantes R1–R8 (Informe2 §2.3), R9–R14 (Informe3). `C_c` comprometido vs `C_e` entregado: la deuda real usa `C_e` (Nota de corrección). R3 se aplica al emitir, no retroactivamente.
- Devolución total = todas las unidades devueltas (derivado). Valor reconocido `R` ≤ precio; menor exige motivo + autorizador distinto. Solo lo apto vuelve a stock; lo no apto es pérdida (costo histórico) y no altera existencias. Reversión de pago: `correccion_registro_erroneo` (dinero nunca ingresó) ≠ `reversion_financiera_real`; el pago original no se toca.
- Compensación: `D = P + U − (T − R)`; `C + G ≤ MAX(0, D)`; reembolso `C ≤ P`; crédito que sustituye efectivo exige consentimiento (R8); autorizador distinto del ejecutor. Entrega ≠ compromiso: el estado sale de eventos; nunca se auto-anula una entrega preparada. Un pago o uso de crédito nuevo nunca supera `T − R − U` (R4). El saldo a favor del cliente nunca es negativo (R5).
- Deuda: `N0 = C_e + G − D`; `F = H + Q − N0`; `Q ≤ MAX(0, N0 − H)`; `H` solo para deuda que no cabe en un pago normal. Condonación/castigo no mueven caja ni son pagos; el castigo exige evidencia de cobro; toda extinción y recuperación exige autorizador distinto, con límite definido, referencia y medio. Una anulación restaura la deuda sin borrar el hecho original. Reversión financiera real: se registra siempre, anula compromisos sin preparar y bloquea entregas no financiadas.
- Entrega ≠ registro: una entrega registrada solo se corrige con eventos nuevos y autorizador; «no ocurrió» exige investigación abierta y evidencia, libera el compromiso y se rechaza si deja H+Q sobre la deuda (R13-C). Cancelar una venta = devolverla; lo retenido es un cargo (deuda) que se cobra, condona o castiga; nunca se cierra como cancelada sin devolución total y sin saldos pendientes.
- Cancelación total con saldo pendiente: extinción explícita (cobro, condonación, castigo), nunca movimientos ficticios (Informe3 §1).
- Reembolsos físicos: compromiso y entrega separados, confirmación append-only (Informe3 §2).
- Entrega de órdenes: sin regla de saldo mínimo (Fase 2).
