"""v_ordenes_importes como fuente única del importe acordado de órdenes (Entrega 3)."""

import sqlite3
import unittest

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.repositories.service_orders import ServiceOrderRepository

UTC = "2026-10-24T15:30:00Z"

# Fórmula previa a 0011, copiada de v_saldos_ordenes (0001) como referencia de equivalencia.
LEGACY = """
SELECT o.id,
       o.importe_inicial_cop + COALESCE((
           SELECT SUM(s.importe_propuesto_cop)
           FROM servicios_adicionales s
           JOIN decisiones_adicional d ON d.servicio_adicional_id = s.id
           WHERE s.orden_id = o.id
             AND d.id = (SELECT d2.id FROM decisiones_adicional d2
                         WHERE d2.servicio_adicional_id = s.id
                         ORDER BY d2.decidido_en_utc DESC, d2.id DESC LIMIT 1)
             AND d.decision = 'aprobado'), 0)
FROM ordenes_servicio o ORDER BY o.id"""


class OrderTotalsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.c = open_database(":memory:")
        self.addCleanup(self.c.close)
        migrate(self.c)
        self.c.execute("INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('C', ?, ?)", (UTC, UTC))
        self.c.execute("INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc) VALUES ('EQ-2026-000001', 1, 'PC', ?)", (UTC,))
        for n, initial in enumerate((10_000, 20_000, 0, 5_000, 7_000), 1):
            self.c.execute(
                """INSERT INTO ordenes_servicio (codigo, cliente_id, equipo_id, recibido_en_utc,
                   problema_reportado, importe_inicial_cop, creado_en_utc, actualizado_en_utc)
                   VALUES (?, 1, 1, ?, 'x', ?, ?, ?)""", (f"OS-2026-{n:06d}", UTC, initial, UTC, UTC))
        extras = [(1, 3_000), (1, 4_000), (2, 6_000), (2, 1_000), (3, 9_000), (4, 2_000)]
        for order, amount in extras:
            self.c.execute("INSERT INTO servicios_adicionales (orden_id, descripcion, importe_propuesto_cop, propuesto_en_utc) VALUES (?, 'e', ?, ?)", (order, amount, UTC))
        decisions = [  # (adicional, decision, instante): incluye re-decisiones y pendientes
            (1, "aprobado", "2026-10-24T16:00:00Z"), (2, "rechazado", "2026-10-24T16:00:00Z"),
            (3, "aprobado", "2026-10-24T16:00:00Z"), (3, "rechazado", "2026-10-24T17:00:00Z"),
            (4, "rechazado", "2026-10-24T16:00:00Z"), (4, "aprobado", "2026-10-24T18:00:00Z"),
            (5, "aprobado", "2026-10-24T16:00:00Z"),  # adicional 6 queda pendiente; orden 5 sin extras
        ]
        for extra, decision, at in decisions:
            self.c.execute("INSERT INTO decisiones_adicional (servicio_adicional_id, decision, decidido_en_utc, evidencia) VALUES (?, ?, ?, 'ok')", (extra, decision, at))
        self.c.execute("INSERT INTO pagos_clientes (orden_id, importe_cop, tipo, metodo, metodo_pago_id, registrado_en_utc, fecha_negocio) VALUES (1, 5000, 'recibo', 'Efectivo', 1, ?, '2026-10-24')", (UTC,))
        self.c.commit()

    def test_view_matches_previous_formula_for_every_order(self) -> None:
        legacy = [tuple(r) for r in self.c.execute(LEGACY)]
        new = [tuple(r) for r in self.c.execute("SELECT orden_id, importe_acordado_cop FROM v_ordenes_importes ORDER BY orden_id")]
        saldos = [tuple(r) for r in self.c.execute("SELECT orden_id, importe_acordado_cop FROM v_saldos_ordenes ORDER BY orden_id")]
        self.assertEqual(legacy, new)
        self.assertEqual(legacy, saldos)
        self.assertEqual([r[1] for r in legacy], [13_000, 21_000, 9_000, 5_000, 7_000])

    def test_balances_and_list_orders_use_the_same_amounts(self) -> None:
        row = self.c.execute("SELECT * FROM v_saldos_ordenes WHERE orden_id = 1").fetchone()
        self.assertEqual((row["pagado_neto_cop"], row["saldo_pendiente_cop"]), (5_000, 8_000))
        listed = {o["id"]: o["importe_acordado_cop"] for o in
                  ServiceOrderRepository(self.c).list_orders(state=None, customer_id=None, equipment_id=None, limit=50, offset=0)}
        self.assertEqual(listed, {1: 13_000, 2: 21_000, 3: 9_000, 4: 5_000, 5: 7_000})

    def test_triggers_keep_their_rules_using_the_shared_view(self) -> None:
        pay = "INSERT INTO pagos_clientes (orden_id, importe_cop, tipo, metodo, metodo_pago_id, registrado_en_utc, fecha_negocio) VALUES (1, ?, 'recibo', 'Efectivo', 1, ?, '2026-10-24')"
        with self.assertRaisesRegex(sqlite3.IntegrityError, "supera el importe acordado"):
            self.c.execute(pay, (8_001, UTC))
        self.c.execute(pay, (8_000, UTC))  # exactamente el saldo
        with self.assertRaisesRegex(sqlite3.IntegrityError, "dejaría pagos por encima"):
            self.c.execute("UPDATE ordenes_servicio SET importe_inicial_cop = 9_999 WHERE id = 1")
        self.c.execute("UPDATE ordenes_servicio SET importe_inicial_cop = 10_000 WHERE id = 1")
        # rechazar el adicional aprobado 1 (3.000) dejaría 13.000 pagados sobre 10.000
        with self.assertRaisesRegex(sqlite3.IntegrityError, "Revierta el excedente"):
            self.c.execute("INSERT INTO decisiones_adicional (servicio_adicional_id, decision, decidido_en_utc, evidencia) VALUES (1, 'rechazado', '2026-10-25T10:00:00Z', 'x')")
        # orden 2 (adicional 4 aprobado, sin pagos): rechazar sí se permite
        self.c.execute("INSERT INTO decisiones_adicional (servicio_adicional_id, decision, decidido_en_utc, evidencia) VALUES (4, 'rechazado', '2026-10-25T10:00:00Z', 'x')")
        self.assertEqual(self.c.execute("SELECT importe_acordado_cop FROM v_ordenes_importes WHERE orden_id = 2").fetchone()[0], 20_000)

    def test_migration_is_idempotent_and_integrity_holds(self) -> None:
        self.assertEqual(migrate(self.c), 12)
        self.assertEqual(self.c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(self.c.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
