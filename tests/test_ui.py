"""Verificaciones pequeñas de integración PySide6, ejecutables sin pantalla."""

import os
from pathlib import Path
import tempfile
import unittest

# El runner puede definir DISPLAY aunque no haya un servidor accesible. Estas
# pruebas de widgets no verifican el compositor y siempre deben ser headless.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
)

from dragontech_manager.app import create_main_window, initialize_database
from dragontech_manager.database.connection import open_database
from dragontech_manager.database.migrations import migrate
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.equipment import EquipmentService
from dragontech_manager.services.service_orders import ServiceOrderService
from dragontech_manager.ui.dialogs import CustomerDialog, EquipmentDialog, ServiceOrderDialog
from dragontech_manager.ui.order_details import OrderDetailDialog
from dragontech_manager.services.updates import UpdateCheckResult
from dragontech_manager.ui.theme import apply_theme, load_theme_preference


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
            self.assertEqual(version, 3)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            connection.execute(
                "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('Registro de prueba', '2026-10-24T15:30:00Z', '2026-10-24T15:30:00Z')"
            )
            connection.commit()
            connection.close()

            reopened, reopened_version = initialize_database(database_path)
            try:
                self.assertEqual(reopened_version, 3)
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

    def test_theme_setting_is_persisted_and_applied_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            window = create_main_window(
                self.connection,
                database_path=":memory:",
                schema_version=self.schema_version,
                settings=settings,
            )
            self.addCleanup(window.close)
            information = window.pages["information"]
            self.assertEqual(information.theme_selector.currentData(), "dark")
            information.theme_selector.setCurrentIndex(information.theme_selector.findData("light"))
            self.assertEqual(self.app.property("dragontechTheme"), "light")
            self.assertEqual(load_theme_preference(settings), "light")
            reopened = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            self.assertEqual(load_theme_preference(reopened), "light")
            self.assertIn("BlackLabs Dev", [label.text() for label in information.findChildren(QLabel)])
            self.assertEqual(information.update_status.text(), "El canal oficial de actualizaciones aún no está configurado.")
            information.check_updates_button.click()
            self.assertIn("no está configurado", information.update_status.text())
            information.set_update_result(
                UpdateCheckResult(
                    "available",
                    "Hay una versión publicada.",
                    "0.2.0",
                    "https://example.test/release",
                )
            )
            self.assertFalse(information.open_release_button.isHidden())
        apply_theme(self.app, "dark")

    def test_customer_and_equipment_edit_actions_preserve_selection_and_history(self) -> None:
        customer = CustomerService(self.connection).create_customer(
            "Cliente original", phone="3001111111", email="original@example.test"
        )
        new_owner = CustomerService(self.connection).create_customer("Nuevo propietario")
        equipment = EquipmentService(self.connection).register_equipment(
            customer["id"], "Portátil", brand="Marca", model="Modelo original", serial="SERIAL-1"
        )
        order = ServiceOrderService(self.connection).open_service_order(
            customer["id"], equipment["id"], "Conservar relación histórica"
        )
        window = create_main_window(
            self.connection,
            database_path=":memory:",
            schema_version=self.schema_version,
        )
        self.addCleanup(window.close)
        window.show()
        window._navigate("customers")
        customers_page = window.pages["customers"]
        customers_page.table.selectRow(0)
        self.app.processEvents()
        self.assertTrue(customers_page.edit_button.isEnabled())

        def edit_customer() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets() if isinstance(item, CustomerDialog))
            dialog.name.setText("Cliente actualizado")
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, edit_customer)
        customers_page.edit_button.click()
        self.assertEqual(self.customers_row(customer["id"])["nombre"], "Cliente actualizado")
        self.assertEqual(customers_page._selected_record_id(), customer["id"])

        window._navigate("equipment")
        equipment_page = window.pages["equipment"]
        equipment_page.table.selectRow(0)
        self.app.processEvents()

        def edit_equipment() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets() if isinstance(item, EquipmentDialog))
            dialog.model.setText("Modelo actualizado")
            dialog.customer.setCurrentIndex(dialog.customer.findData(new_owner["id"]))
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, edit_equipment)
        equipment_page.edit_button.click()
        current = self.connection.execute("SELECT * FROM equipos WHERE id=?", (equipment["id"],)).fetchone()
        self.assertEqual(current["modelo"], "Modelo actualizado")
        self.assertEqual(current["codigo"], equipment["codigo"])
        self.assertEqual(current["cliente_id"], new_owner["id"])
        self.assertEqual(equipment_page._selected_record_id(), equipment["id"])
        unchanged_order = self.connection.execute(
            "SELECT cliente_id, equipo_id FROM ordenes_servicio WHERE id=?", (order["id"],)
        ).fetchone()
        self.assertEqual(tuple(unchanged_order), (customer["id"], equipment["id"]))

    def customers_row(self, customer_id: int):
        return self.connection.execute("SELECT * FROM clientes WHERE id=?", (customer_id,)).fetchone()

    def test_order_detail_confirms_state_change_and_refreshes_dashboard(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente orden")
        equipment = EquipmentService(self.connection).register_equipment(customer["id"], "Portátil")
        order = ServiceOrderService(self.connection).open_service_order(
            customer["id"], equipment["id"], "No enciende"
        )
        window = create_main_window(
            self.connection,
            database_path=":memory:",
            schema_version=self.schema_version,
        )
        self.addCleanup(window.close)
        window.show()
        window._navigate("orders")

        def interact_with_detail() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets() if isinstance(item, OrderDetailDialog))
            self.assertIn(order["codigo"], dialog.heading.text())
            self.assertEqual(dialog.next_state.count(), 2)
            self.assertIsNone(dialog.next_state.itemData(0))
            self.assertEqual(dialog.next_state.itemData(1), "diagnostico")
            self.assertIn("Transición permitida", dialog.transition_hint.text())
            dialog.next_state.setCurrentIndex(1)

            def confirm() -> None:
                message = next(
                    item for item in QApplication.topLevelWidgets()
                    if isinstance(item, QMessageBox) and item.windowTitle() == "Confirmar cambio de estado"
                )
                message.button(QMessageBox.StandardButton.Yes).click()

            QTimer.singleShot(0, confirm)
            dialog.transition_button.button(QDialogButtonBox.StandardButton.Apply).click()
            dialog.close_buttons.button(QDialogButtonBox.StandardButton.Close).click()

        QTimer.singleShot(0, interact_with_detail)
        window._show_order_detail(order["id"])
        self.assertEqual(self.connection.execute(
            "SELECT estado FROM ordenes_servicio WHERE id=?", (order["id"],)
        ).fetchone()[0], "diagnostico")
        self.assertEqual(window.pages["dashboard"].cards["pendientes"].value_label.text(), "1")
        events = ServiceOrderService(self.connection).get_status_history(order["id"])
        self.assertEqual([event["estado_nuevo"] for event in events], ["recibida", "diagnostico"])

    def test_order_detail_long_text_fields_wrap_grow_and_round_trip(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente texto largo")
        equipment = EquipmentService(self.connection).register_equipment(customer["id"], "Portátil")
        service = ServiceOrderService(self.connection)
        long_problem = ("Falla reportada con detalle. " * 220).strip()
        long_diagnosis = ("Diagnóstico técnico con hallazgos detallados. " * 180).strip()
        long_work = ("Se realizaron pruebas, limpieza y validación completa. " * 190).strip()
        order = service.open_service_order(customer["id"], equipment["id"], long_problem)
        dialog = OrderDetailDialog(service, order["id"])
        self.addCleanup(dialog.close)

        self.assertGreaterEqual(dialog.problem.minimumHeight(), 110)
        self.assertGreaterEqual(dialog.diagnosis.minimumHeight(), 110)
        self.assertGreaterEqual(dialog.work.minimumHeight(), 110)
        self.assertEqual(dialog.problem.lineWrapMode(), QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.assertEqual(dialog.problem.toPlainText(), long_problem)
        scroll = dialog.findChild(QScrollArea)
        self.assertIsNotNone(scroll)
        dialog.resize(700, 560)
        dialog.show()
        self.app.processEvents()
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)

        dialog.diagnosis.setPlainText(long_diagnosis)
        dialog.work.setPlainText(long_work)
        dialog._save_technical()

        stored = service.get_order_detail(order["id"])
        self.assertEqual(stored["diagnostico"], long_diagnosis)
        self.assertEqual(stored["trabajo_realizado"], long_work)
        self.assertEqual(dialog.diagnosis.toPlainText(), long_diagnosis)
        self.assertEqual(dialog.work.toPlainText(), long_work)

    def test_order_detail_dropdown_tracks_only_allowed_transitions_at_each_state(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente transiciones UI")
        equipment = EquipmentService(self.connection).register_equipment(customer["id"], "Portátil")
        service = ServiceOrderService(self.connection)
        order = service.open_service_order(customer["id"], equipment["id"], "Revisión")
        dialog = OrderDetailDialog(service, order["id"])
        self.addCleanup(dialog.close)

        self.assertEqual(
            [dialog.next_state.itemData(i) for i in range(dialog.next_state.count())],
            [None, "diagnostico"],
        )
        service.transition_order(order["id"], "diagnostico")
        dialog._reload()
        self.assertEqual(dialog.next_state.itemData(1), "en_proceso")

        service.transition_order(order["id"], "en_proceso")
        dialog._reload()
        self.assertEqual(dialog.next_state.count(), 1)
        self.assertFalse(dialog.next_state.isEnabled())
        self.assertIn("Guarda el trabajo realizado", dialog.transition_hint.text())

        service.update_technical_details(
            order["id"], diagnosis="Diagnóstico", work_performed="Pruebas completadas"
        )
        dialog._reload()
        self.assertEqual(dialog.next_state.itemData(1), "lista")
        service.transition_order(order["id"], "lista")
        dialog._reload()
        self.assertEqual(dialog.next_state.itemData(1), "entregada")
        service.transition_order(order["id"], "entregada")
        dialog._reload()
        self.assertEqual(dialog.next_state.count(), 1)
        self.assertFalse(dialog.next_state.isEnabled())
        self.assertIn("estados terminales", dialog.transition_hint.text())

    def test_dashboard_lists_recent_orders_and_quick_action_creates_real_customer(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente de actividad")
        equipment = EquipmentService(self.connection).register_equipment(customer["id"], "Torre")
        order = ServiceOrderService(self.connection).open_service_order(
            customer["id"], equipment["id"], "Revisar ventilación"
        )
        window = create_main_window(
            self.connection,
            database_path=":memory:",
            schema_version=self.schema_version,
        )
        self.addCleanup(window.close)
        window.resize(760, 520)
        window.show()
        self.app.processEvents()
        dashboard = window.pages["dashboard"]
        dashboard_scroll = dashboard.findChild(QScrollArea)
        self.assertIsNotNone(dashboard_scroll)
        self.assertGreater(dashboard_scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(dashboard.recent_table.rowCount(), 1)
        self.assertEqual(dashboard.recent_table.item(0, 0).text(), order["codigo"])
        self.assertEqual(dashboard.recent_table.item(0, 1).text(), customer["nombre"])
        selected_ids: list[int] = []
        dashboard.request_order_details.disconnect()
        dashboard.request_order_details.connect(selected_ids.append)
        dashboard._open_recent_order(0, 0)
        self.assertEqual(selected_ids, [order["id"]])

        def save_quick_client() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets() if isinstance(item, CustomerDialog))
            dialog.name.setText("Cliente desde acción rápida")
            dialog.buttons.button(QDialogButtonBox.StandardButton.Save).click()

        QTimer.singleShot(0, save_quick_client)
        dashboard.quick_action_buttons["customers"].click()
        self.assertEqual(
            self.connection.execute(
                "SELECT COUNT(*) FROM clientes WHERE nombre = ?", ("Cliente desde acción rápida",)
            ).fetchone()[0],
            1,
        )
        self.assertEqual(window._current_key, "customers")


if __name__ == "__main__":
    unittest.main()
