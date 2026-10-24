"""Integridad del esquema y garantías cubiertas por SQLite."""

import sqlite3
import shutil
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import MigrationError, check_integrity, migrate
from dragontech_manager.database.sequences import allocate_code

UTC = "2026-10-24T15:30:00Z"


class DatabaseSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.assertEqual(migrate(self.connection), 2)
        self.connection.execute(
            "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES (?, ?, ?)",
            ("Cliente de prueba", UTC, UTC),
        )
        self.connection.execute(
            "INSERT INTO productos (sku, nombre, creado_en_utc) VALUES (?, ?, ?)",
            ("SKU-TEST", "Producto de prueba", UTC),
        )
        self.connection.execute(
            """INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc)
               VALUES ('EQ-2026-000001', 1, 'Portátil', ?)""",
            (UTC,),
        )
        self.connection.execute(
            """INSERT INTO ordenes_servicio
               (codigo, cliente_id, equipo_id, recibido_en_utc, problema_reportado,
                importe_inicial_cop, creado_en_utc, actualizado_en_utc)
               VALUES ('OS-2026-000001', 1, 1, ?, 'No enciende', 10000, ?, ?)""",
            (UTC, UTC, UTC),
        )
        self.connection.commit()

    def test_initial_schema_and_migration_are_idempotent(self) -> None:
        expected = {
            "clientes", "equipos", "ordenes_servicio", "servicios_adicionales",
            "decisiones_adicional", "pagos_clientes", "cotizaciones",
            "cotizacion_detalles", "ventas", "venta_detalles", "armados_pc",
            "armado_componentes", "productos", "reservas_inventario",
            "movimientos_inventario", "proveedores", "compras", "compra_detalles",
            "pagos_proveedores", "gastos", "secuencias", "schema_migrations",
        }
        actual = {
            row[0] for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(expected <= actual)
        self.assertEqual(migrate(self.connection), 2)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
            2,
        )

    def test_foreign_keys_restrict_orphan_records_and_integrity_check_passes(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc) VALUES (?, 999, 'PC', ?)",
                ("EQ-2026-000002", UTC),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM clientes WHERE id = 1")
        check_integrity(self.connection)

    def test_visible_codes_are_unique_and_format_checked(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc) VALUES (?, 1, 'PC', ?)",
                ("EQ-2026-000001", UTC),
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc) VALUES (?, 1, 'PC', ?)",
                ("equipo-1", UTC),
            )

    def test_timestamps_and_money_values_have_storage_constraints(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO gastos
                   (fecha_gasto, categoria, descripcion, importe_cop, metodo, creado_en_utc)
                   VALUES ('2026-10-24', 'operativo', 'Prueba', 10.5, 'efectivo', ?)""", (UTC,)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc)
                   VALUES ('Fecha inválida', 'not-a-dateZ', ?)""", (UTC,)
            )

    def test_sequence_allocation_is_transactional_and_separate_from_internal_id(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        self.assertEqual(allocate_code(self.connection, "equipo", 2027), "EQ-2027-000001")
        self.connection.rollback()

        with self.assertRaises(RuntimeError):
            allocate_code(self.connection, "equipo", 2027)

        self.connection.execute("BEGIN IMMEDIATE")
        code = allocate_code(self.connection, "equipo", 2027)
        cursor = self.connection.execute(
            "INSERT INTO equipos (codigo, cliente_id, tipo, creado_en_utc) VALUES (?, 1, 'PC', ?)",
            (code, UTC),
        )
        self.connection.commit()
        self.assertEqual(code, "EQ-2027-000001")
        self.assertNotEqual(cursor.lastrowid, code)
        self.connection.execute("BEGIN IMMEDIATE")
        self.assertEqual(allocate_code(self.connection, "orden_servicio", 2027), "OS-2027-000001")
        self.connection.rollback()

    def test_customer_payments_xor_destination_reversal_and_balance(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO pagos_clientes
                   (orden_id, importe_cop, tipo, metodo, registrado_en_utc)
                   VALUES (NULL, 100, 'recibo', 'efectivo', ?)""", (UTC,)
            )
        self.connection.execute(
            """INSERT INTO pagos_clientes
               (orden_id, importe_cop, tipo, metodo, registrado_en_utc)
               VALUES (1, 6000, 'recibo', 'efectivo', ?)""", (UTC,)
        )
        self.connection.execute(
            "INSERT INTO ventas (codigo, cliente_id, fecha_venta, creado_en_utc) VALUES ('V-REVERSAL-TEST', 1, '2026-10-24', ?)",
            (UTC,),
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT saldo_pendiente_cop FROM v_saldos_ordenes WHERE orden_id = 1"
            ).fetchone()[0],
            4000,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO pagos_clientes
                   (orden_id, importe_cop, tipo, metodo, registrado_en_utc)
                   VALUES (1, 4001, 'recibo', 'efectivo', ?)""", (UTC,)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("UPDATE ordenes_servicio SET importe_inicial_cop = 5000 WHERE id = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO pagos_clientes
                   (orden_id, importe_cop, tipo, metodo, registrado_en_utc,
                    reversa_pago_id, motivo)
                   VALUES (1, 5999, 'reversion', 'ajuste', ?, 1, 'Corrección')""", (UTC,)
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO pagos_clientes
                   (venta_id, importe_cop, tipo, metodo, registrado_en_utc,
                    reversa_pago_id, motivo)
                   VALUES (1, 6000, 'reversion', 'ajuste', ?, 1, 'Destino incorrecto')""", (UTC,)
            )
        self.connection.execute(
            """INSERT INTO pagos_clientes
               (orden_id, importe_cop, tipo, metodo, registrado_en_utc,
                reversa_pago_id, motivo)
               VALUES (1, 6000, 'reversion', 'ajuste', ?, 1, 'Corrección')""", (UTC,)
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT pagado_neto_cop FROM v_saldos_ordenes WHERE orden_id = 1"
            ).fetchone()[0],
            0,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("DELETE FROM pagos_clientes WHERE id = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO pagos_clientes
                   (orden_id, importe_cop, tipo, metodo, registrado_en_utc,
                    reversa_pago_id, motivo)
                   VALUES (1, 6000, 'reversion', 'ajuste', ?, 1, 'Doble reversión')""", (UTC,)
            )

    def test_additional_service_uses_latest_decision_and_requires_approval_for_part(self) -> None:
        self.connection.execute(
            "INSERT INTO servicios_adicionales (orden_id, descripcion, importe_propuesto_cop, propuesto_en_utc) VALUES (1, 'Repuesto', 2500, ?)",
            (UTC,),
        )
        self.connection.execute(
            "INSERT INTO decisiones_adicional (servicio_adicional_id, decision, decidido_en_utc, evidencia) VALUES (1, 'rechazado', ?, 'No aprobado')",
            (UTC,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO orden_repuestos
                   (orden_id, producto_id, servicio_adicional_id, cantidad,
                    costo_unitario_cop, precio_unitario_cop, asignado_en_utc)
                   VALUES (1, 1, 1, 1, 1000, 2500, ?)""", (UTC,)
            )
        self.connection.execute(
            "INSERT INTO decisiones_adicional (servicio_adicional_id, decision, decidido_en_utc, evidencia) VALUES (1, 'aprobado', ?, 'Aprobado por el cliente')",
            (UTC,),
        )
        self.connection.execute(
            """INSERT INTO orden_repuestos
               (orden_id, producto_id, servicio_adicional_id, cantidad,
                costo_unitario_cop, precio_unitario_cop, asignado_en_utc)
               VALUES (1, 1, 1, 1, 1000, 2500, ?)""", (UTC,)
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT importe_acordado_cop FROM v_saldos_ordenes WHERE orden_id = 1"
            ).fetchone()[0],
            12500,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("UPDATE decisiones_adicional SET decision = 'rechazado' WHERE id = 2")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO decisiones_adicional (servicio_adicional_id, decision, decidido_en_utc, evidencia) VALUES (1, 'rechazado', ?, 'Retiro')",
                (UTC,),
            )

    def test_rejecting_an_approved_additional_cannot_make_payments_exceed_agreement(self) -> None:
        self.connection.execute(
            "INSERT INTO servicios_adicionales (orden_id, descripcion, importe_propuesto_cop, propuesto_en_utc) VALUES (1, 'Trabajo adicional', 2500, ?)",
            (UTC,),
        )
        self.connection.execute(
            "INSERT INTO decisiones_adicional (servicio_adicional_id, decision, decidido_en_utc, evidencia) VALUES (1, 'aprobado', ?, 'Aprobado')",
            (UTC,),
        )
        self.connection.execute(
            """INSERT INTO pagos_clientes
               (orden_id, importe_cop, tipo, metodo, registrado_en_utc)
               VALUES (1, 12500, 'recibo', 'transferencia', ?)""", (UTC,)
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO decisiones_adicional (servicio_adicional_id, decision, decidido_en_utc, evidencia) VALUES (1, 'rechazado', ?, 'Cambio')",
                (UTC,),
            )

    def test_purchase_partial_payments_are_distinct_from_purchase_value_and_expenses(self) -> None:
        self.connection.execute(
            "INSERT INTO proveedores (nombre, creado_en_utc) VALUES ('Proveedor de prueba', ?)",
            (UTC,),
        )
        self.connection.execute(
            "INSERT INTO compras (proveedor_id, fecha_compra, estado, creado_en_utc) VALUES (1, '2026-10-24', 'pendiente', ?)",
            (UTC,),
        )
        self.connection.execute(
            "INSERT INTO compra_detalles (compra_id, producto_id, cantidad, costo_unitario_historico_cop) VALUES (1, 1, 2, 5000)"
        )
        self.connection.execute(
            """INSERT INTO pagos_proveedores (compra_id, importe_cop, tipo, metodo, registrado_en_utc)
               VALUES (1, 4000, 'pago', 'transferencia', ?)""", (UTC,)
        )
        self.connection.execute(
            """INSERT INTO pagos_proveedores (compra_id, importe_cop, tipo, metodo, registrado_en_utc)
               VALUES (1, 1000, 'pago', 'efectivo', ?)""", (UTC,)
        )
        row = self.connection.execute(
            "SELECT importe_compra_cop, pagado_neto_cop, saldo_pendiente_cop FROM v_saldos_compras"
        ).fetchone()
        self.assertEqual(tuple(row), (10000, 5000, 5000))
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO pagos_proveedores (compra_id, importe_cop, tipo, metodo, registrado_en_utc)
                   VALUES (1, 6001, 'pago', 'transferencia', ?)""", (UTC,)
            )
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM gastos").fetchone()[0], 0)

    def test_expense_reversal_is_traceable_and_does_not_delete_the_original(self) -> None:
        self.connection.execute(
            """INSERT INTO gastos
               (fecha_gasto, categoria, descripcion, importe_cop, metodo, creado_en_utc)
               VALUES ('2026-10-24', 'operativo', 'Insumos de prueba', 3000, 'efectivo', ?)""", (UTC,)
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO gastos
                   (fecha_gasto, categoria, descripcion, importe_cop, tipo, metodo,
                    reversa_gasto_id, motivo, creado_en_utc)
                   VALUES ('2026-10-24', 'operativo', 'Reversión incorrecta', 2000,
                           'reversion', 'ajuste', 1, 'Corrección', ?)""", (UTC,)
            )
        self.connection.execute(
            """INSERT INTO gastos
               (fecha_gasto, categoria, descripcion, importe_cop, tipo, metodo,
                reversa_gasto_id, motivo, creado_en_utc)
               VALUES ('2026-10-24', 'operativo', 'Reversión', 3000,
                       'reversion', 'ajuste', 1, 'Registro duplicado', ?)""", (UTC,)
        )
        self.assertEqual(self.connection.execute("SELECT SUM(importe_neto_cop) FROM v_gastos_netos").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM gastos").fetchone()[0], 2)

    def test_sale_total_and_customer_payment_have_separate_records(self) -> None:
        self.connection.execute(
            "INSERT INTO ventas (codigo, cliente_id, fecha_venta, creado_en_utc) VALUES ('V-TEST-1', 1, '2026-10-24', ?)",
            (UTC,),
        )
        self.connection.execute(
            """INSERT INTO venta_detalles
               (venta_id, descripcion, cantidad, precio_unitario_cop, costo_unitario_historico_cop)
               VALUES (1, 'Servicio de prueba', 1, 7000, 2500)"""
        )
        self.connection.execute(
            """INSERT INTO pagos_clientes
               (venta_id, importe_cop, tipo, metodo, registrado_en_utc)
               VALUES (1, 2000, 'recibo', 'transferencia', ?)""", (UTC,)
        )
        self.assertEqual(
            tuple(self.connection.execute(
                "SELECT importe_acordado_cop, pagado_neto_cop, saldo_pendiente_cop FROM v_saldos_ventas"
            ).fetchone()),
            (7000, 2000, 5000),
        )

    def test_inventory_reservations_are_not_stock_movements_and_duplicate_exit_is_blocked(self) -> None:
        self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo, creado_en_utc, motivo)
               VALUES (1, 5, 1000, 'ajuste', ?, 'Conteo inicial de prueba')""", (UTC,)
        )
        self.connection.execute("INSERT INTO armados_pc (codigo, cliente_id, creado_en_utc) VALUES ('ARM-1', 1, ?)", (UTC,))
        self.connection.execute(
            "INSERT INTO armado_componentes (armado_id, producto_id, cantidad, costo_unitario_historico_cop, precio_unitario_cobrado_cop) VALUES (1, 1, 2, 1000, 2000)"
        )
        self.connection.execute(
            """INSERT INTO reservas_inventario
               (producto_id, armado_componente_id, cantidad, creada_en_utc, actualizada_en_utc)
               VALUES (1, 1, 2, ?, ?)""", (UTC, UTC)
        )
        self.assertEqual(tuple(self.connection.execute("SELECT existencia, reservado FROM v_existencias").fetchone()), (5, 2))
        self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                armado_componente_id, creado_en_utc)
               VALUES (1, -2, 1000, 'armado', 1, ?)""", (UTC,)
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO movimientos_inventario
                   (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                    armado_componente_id, creado_en_utc)
                   VALUES (1, -2, 1000, 'armado', 1, ?)""", (UTC,)
            )
        self.assertEqual(tuple(self.connection.execute("SELECT existencia, reservado, disponible FROM v_existencias").fetchone()), (3, 0, 3))
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO reservas_inventario
                   (producto_id, armado_componente_id, cantidad, creada_en_utc, actualizada_en_utc)
                   VALUES (1, 1, 4, ?, ?)""", (UTC, UTC)
            )

    def test_reversing_consumed_purchase_stock_cannot_create_negative_inventory(self) -> None:
        self.connection.execute("INSERT INTO proveedores (nombre, creado_en_utc) VALUES ('Proveedor', ?)", (UTC,))
        self.connection.execute(
            "INSERT INTO compras (proveedor_id, fecha_compra, estado, creado_en_utc) VALUES (1, '2026-10-24', 'recibida', ?)",
            (UTC,),
        )
        self.connection.execute(
            "INSERT INTO compra_detalles (compra_id, producto_id, cantidad, costo_unitario_historico_cop) VALUES (1, 1, 5, 1000)"
        )
        self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                compra_detalle_id, creado_en_utc)
               VALUES (1, 5, 1000, 'compra', 1, ?)""", (UTC,)
        )
        self.connection.execute(
            "INSERT INTO ventas (codigo, cliente_id, fecha_venta, creado_en_utc) VALUES ('V-INV-1', 1, '2026-10-24', ?)",
            (UTC,),
        )
        self.connection.execute(
            """INSERT INTO venta_detalles
               (venta_id, descripcion, cantidad, precio_unitario_cop,
                costo_unitario_historico_cop, producto_id)
               VALUES (1, 'Producto', 5, 2000, 1000, 1)"""
        )
        self.connection.execute(
            """INSERT INTO reservas_inventario
               (producto_id, venta_detalle_id, cantidad, creada_en_utc, actualizada_en_utc)
               VALUES (1, 1, 5, ?, ?)""", (UTC, UTC)
        )
        self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                venta_detalle_id, creado_en_utc)
               VALUES (1, -5, 1000, 'venta', 1, ?)""", (UTC,)
        )
        self.assertEqual(
            self.connection.execute("SELECT existencia FROM v_existencias WHERE producto_id = 1").fetchone()[0],
            0,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                """INSERT INTO movimientos_inventario
                   (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                    reversa_movimiento_id, creado_en_utc)
                   VALUES (1, -5, 1000, 'reversion', 1, ?)""", (UTC,)
            )
        # Primero se compensa la salida; después se puede corregir la recepción.
        self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                reversa_movimiento_id, creado_en_utc)
               VALUES (1, 5, 1000, 'reversion', 2, ?)""", (UTC,)
        )
        self.connection.execute(
            """INSERT INTO movimientos_inventario
               (producto_id, cantidad_delta, costo_unitario_historico_cop, tipo,
                reversa_movimiento_id, creado_en_utc)
               VALUES (1, -5, 1000, 'reversion', 1, ?)""", (UTC,)
        )
        self.assertEqual(
            self.connection.execute("SELECT existencia FROM v_existencias WHERE producto_id = 1").fetchone()[0],
            0,
        )

    def test_failed_migration_rolls_back_ddl_and_version_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            migration_dir = Path(temp_dir)
            (migration_dir / "0001_broken.sql").write_text(
                "CREATE TABLE transient_table (id INTEGER PRIMARY KEY);\n"
                "INSERT INTO missing_table VALUES (1);\n",
                encoding="utf-8",
            )
            with closing(open_database(":memory:")) as connection:
                with self.assertRaises(sqlite3.OperationalError):
                    migrate(connection, migration_dir)
                self.assertIsNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'transient_table'"
                    ).fetchone()
                )
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 0)

    def test_migration_checksum_detects_edits_to_applied_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            migration_dir = Path(temp_dir)
            migration = migration_dir / "0001_small.sql"
            migration.write_text("CREATE TABLE sample (id INTEGER PRIMARY KEY);\n", encoding="utf-8")
            with closing(open_database(":memory:")) as connection:
                self.assertEqual(migrate(connection, migration_dir), 1)
                migration.write_text("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT);\n", encoding="utf-8")
                with self.assertRaises(MigrationError):
                    migrate(connection, migration_dir)

    def test_version_two_upgrades_a_version_one_database_without_rebuilding_it(self) -> None:
        project_migrations = Path(__file__).parents[1] / "src/dragontech_manager/database/migrations"
        with tempfile.TemporaryDirectory() as temp_dir:
            version_one_dir = Path(temp_dir)
            shutil.copyfile(
                project_migrations / "0001_initial_schema.sql",
                version_one_dir / "0001_initial_schema.sql",
            )
            with closing(open_database(":memory:")) as connection:
                self.assertEqual(migrate(connection, version_one_dir), 1)
                connection.execute(
                    "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('Preservado', ?, ?)",
                    (UTC, UTC),
                )
                connection.commit()
                self.assertEqual(migrate(connection, project_migrations), 2)
                self.assertEqual(
                    connection.execute("SELECT nombre FROM clientes").fetchone()[0],
                    "Preservado",
                )
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name = 'movimientos_reversion_no_stock_negativo'"
                    ).fetchone()
                )

    def test_migration_refuses_to_run_inside_a_caller_transaction(self) -> None:
        with closing(open_database(":memory:")) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(MigrationError):
                migrate(connection)
            connection.rollback()
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
                ).fetchone()
            )


if __name__ == "__main__":
    unittest.main()
