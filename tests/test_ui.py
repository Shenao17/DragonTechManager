"""Verificaciones pequeñas de integración PySide6, ejecutables sin pantalla."""

import os
from pathlib import Path
import tempfile
import unittest

# El runner puede definir DISPLAY aunque no haya un servidor accesible. Estas
# pruebas de widgets no verifican el compositor y siempre deben ser headless.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QHeaderView

from dragontech_manager.app import create_main_window, initialize_database
from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.equipment import EquipmentService
from dragontech_manager.services.service_orders import ServiceOrderService
from dragontech_manager.ui.dialogs import CustomerDialog, EquipmentDialog, ServiceOrderDialog
from dragontech_manager.ui.theme import apply_theme


class DesktopUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setOrganizationName("DragonTech")
        cls.app.setApplicationName("DragonTech Manager Tests")
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.connection = open_database(":memory:")
        self.addCleanup(self.connection.close)
        self.schema_version = migrate(self.connection)

    def test_main_window_builds_navigation_and_proximate_modules(self) -> None:
        window = create_main_window(
            self.connection,
            database_path=":memory:",
            schema_version=self.schema_version,
        )
        self.addCleanup(window.close)
        window.show()
        self.app.processEvents()
        self.assertEqual(window.windowTitle(), "DragonTech Manager")
        self.assertEqual(
            set(window.pages),
            {"dashboard", "customers", "equipment", "orders", "sales", "inventory", "information"},
        )
        self.assertEqual(window._current_key, "dashboard")
        window._navigate("sales")
        self.assertEqual(window.section_title.text(), "Cotizaciones y ventas")
        self.assertFalse(window.action_button.isVisible())

    def test_customer_form_creates_through_service_and_refreshes_page(self) -> None:
        window = create_main_window(
            self.connection,
            database_path=":memory:",
            schema_version=self.schema_version,
        )
        self.addCleanup(window.close)
        window._navigate("customers")

        def enter_and_save() -> None:
            dialogs = [item for item in QApplication.topLevelWidgets() if isinstance(item, CustomerDialog)]
            self.assertEqual(len(dialogs), 1)
            dialog = dialogs[0]
            dialog.name.setText("Cliente de interfaz")
            dialog.phone.setText("3000000000")
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, enter_and_save)
        window.action_button.click()
        page = window.pages["customers"]
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 1)
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 0).text(), "Cliente de interfaz")

    def test_equipment_and_order_forms_use_existing_services_and_generated_codes(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente UI")
        window = create_main_window(
            self.connection,
            database_path=":memory:",
            schema_version=self.schema_version,
        )
        self.addCleanup(window.close)
        window._navigate("equipment")

        def save_equipment() -> None:
            dialog = next(
                item for item in QApplication.topLevelWidgets() if isinstance(item, EquipmentDialog)
            )
            dialog.equipment_type.setText("Portátil")
            dialog.brand.setText("Marca UI")
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, save_equipment)
        window.action_button.click()
        equipment = self.connection.execute("SELECT * FROM equipos").fetchone()
        self.assertIsNotNone(equipment)
        self.assertTrue(equipment["codigo"].startswith("EQ-"))

        window._navigate("orders")

        def save_order() -> None:
            dialog = next(
                item for item in QApplication.topLevelWidgets() if isinstance(item, ServiceOrderDialog)
            )
            dialog.problem.setPlainText("No enciende")
            dialog.amount.setText("185000")
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, save_order)
        window.action_button.click()
        order = self.connection.execute("SELECT * FROM ordenes_servicio").fetchone()
        self.assertEqual(order["cliente_id"], customer["id"])
        self.assertEqual(order["equipo_id"], equipment["id"])
        self.assertTrue(order["codigo"].startswith("OS-"))
        self.assertEqual(order["importe_inicial_cop"], 185000)

    def test_database_initialization_migrates_without_clearing_existing_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "profile" / "dragontech.sqlite3"
            connection, version = initialize_database(database_path)
            self.assertEqual(version, 2)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            connection.execute(
                "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('Registro de prueba', '2026-10-24T15:30:00Z', '2026-10-24T15:30:00Z')"
            )
            connection.commit()
            connection.close()

            reopened, reopened_version = initialize_database(database_path)
            try:
                self.assertEqual(reopened_version, 2)
                self.assertEqual(reopened.execute("SELECT nombre FROM clientes").fetchone()[0], "Registro de prueba")
                self.assertEqual(reopened.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 1)
            finally:
                reopened.close()

    def test_registry_tables_resize_scroll_and_preserve_full_cell_values(self) -> None:
        customers = CustomerService(self.connection)
        customer = customers.create_customer(
            "Cliente con nombre largo para comprobar lectura completa",
            phone="3001234567",
            email="contacto.cliente.extenso@example.com",
            notes="Notas adicionales que deben seguir disponibles aunque la celda se elida",
        )
        equipment = EquipmentService(self.connection).register_equipment(
            customer["id"],
            "Portátil de alto rendimiento",
            brand="Marca de prueba",
            model="Modelo empresarial edición avanzada",
            serial="SERIAL-DE-PRUEBA-123456",
        )
        equipment_service = EquipmentService(self.connection)
        order_service = ServiceOrderService(self.connection)
        order_service.open_service_order(
            customer["id"], equipment["id"], "Revisar funcionamiento", initial_amount_cop=185000
        )
        for index in range(25):
            extra_customer = customers.create_customer(f"Cliente de tabla {index:02d}")
            equipment_service.register_equipment(
                extra_customer["id"], "Equipo de prueba", brand="DragonTech", model=f"Modelo {index:02d}"
            )
            order_service.open_service_order(
                customer["id"], equipment["id"], f"Visita de prueba {index:02d}"
            )
        window = create_main_window(
            self.connection,
            database_path=":memory:",
            schema_version=self.schema_version,
        )
        self.addCleanup(window.close)

        window.resize(1440, 920)
        window.show()
        self.app.processEvents()
        flex_columns = {"customers": 0, "equipment": 4, "orders": 2}
        self.assertEqual(window.minimumSize().width(), 760)
        for key, flex_column in flex_columns.items():
            window._navigate(key)
            self.app.processEvents()
            page = window.pages[key]
            table = page.table
            header = table.horizontalHeader()
            self.assertTrue(table.isVisible(), key)
            self.assertGreaterEqual(table.width(), page.width() - 60, key)
            self.assertEqual(
                [header.sectionResizeMode(i) for i in range(table.columnCount())],
                [QHeaderView.ResizeMode.Interactive] * table.columnCount(),
                key,
            )
            self.assertFalse(table.isColumnHidden(flex_column), key)
            self.assertEqual(
                table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            self.assertFalse(table.horizontalScrollBar().isVisible(), key)
            self.assertLessEqual(
                abs(sum(table.columnWidth(i) for i in range(table.columnCount())) - table.viewport().width()),
                2,
                key,
            )
            self.assertGreaterEqual(header.height(), 38, key)
            original = table.columnWidth(0)
            header.resizeSection(0, original + 17)
            self.assertEqual(table.columnWidth(0), original + 17, key)
            self.assertTrue(table.item(0, 0).toolTip(), key)

        window.resize(760, 520)
        self.app.processEvents()
        self.assertEqual(window.size().width(), 760)
        for key in flex_columns:
            window._navigate(key)
            self.app.processEvents()
            table = window.pages[key].table
            self.assertTrue(table.horizontalScrollBar().isVisible(), key)
            self.assertGreater(table.horizontalScrollBar().maximum(), 0, key)
            table.horizontalScrollBar().setValue(table.horizontalScrollBar().maximum())
            self.assertEqual(
                table.horizontalScrollBar().value(), table.horizontalScrollBar().maximum(), key
            )
            self.assertGreaterEqual(table.rowCount(), 25, key)
            self.assertTrue(table.verticalScrollBar().isVisible(), key)
            table.verticalScrollBar().setValue(table.verticalScrollBar().maximum())
            self.assertEqual(
                table.verticalScrollBar().value(), table.verticalScrollBar().maximum(), key
            )


if __name__ == "__main__":
    unittest.main()
