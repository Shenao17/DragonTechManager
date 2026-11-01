# BUSINESS_RULES

Fuente autoritativa: Informe2, Informe3 y Nota de corrección (carpeta `docs/`). Este resumen no los sustituye.

- Dinero en COP enteros. Nunca borrar ni editar registros financieros; se corrige con reversión/evento compensatorio.
- Fecha de negocio = día calendario de Bogotá (UTC-5); `*_en_utc` es el instante técnico. No se reescribe historia.
- Métodos de pago: catálogo único; textos legados se resuelven por alias; `CSX` legado sin clasificar (P1).
- Invariantes R1–R8 (Informe2 §2.3), R9–R14 (Informe3). `C_c` comprometido vs `C_e` entregado: la deuda real usa `C_e` (Nota de corrección). R3 se aplica al emitir, no retroactivamente.
- Cancelación total con saldo pendiente: extinción explícita (cobro, condonación, castigo), nunca movimientos ficticios (Informe3 §1).
- Reembolsos físicos: compromiso y entrega separados, confirmación append-only (Informe3 §2).
- Entrega de órdenes: sin regla de saldo mínimo (Fase 2).
