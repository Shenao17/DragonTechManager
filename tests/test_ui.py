"""Verificaciones pequeñas de integración PySide6, ejecutables sin pantalla."""

import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch

# El runner puede definir DISPLAY aunque no haya un servidor accesible. Estas
# pruebas de widgets no verifican el compositor y siempre deben ser headless.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
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
from dragontech_manager.services.proposals import ProposalService
from dragontech_manager.services.inventory import InventoryService
from dragontech_manager.services.procurement import ProcurementService
from dragontech_manager.services.sales import SalesService
from dragontech_manager.ui.dialogs import CustomerDialog, EquipmentDialog, ServiceOrderDialog
from dragontech_manager.ui.order_details import OrderDetailDialog, OrderPaymentDialog
from dragontech_manager.ui.proposals import ProposalDialog, ProposalDetailsDialog
from dragontech_manager.ui.inventory import InventoryWorkspacePage, ProductDialog
from dragontech_manager.ui.procurement import PurchaseDialog, SupplierDialog
from dragontech_manager.ui.sales import PaymentDialog, SaleDetailsDialog, SaleDialog
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
        self.assertTrue(window.action_button.isVisible())
        self.assertEqual(window.action_button.text(), "＋  Nueva propuesta")

    def test_proposals_module_creates_lists_filters_and_opens_details(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente propuestas UI")
        window = create_main_window(
            self.connection, database_path=":memory:", schema_version=self.schema_version
        )
        self.addCleanup(window.close)
        window._navigate("sales")
        page = window.pages["sales"].proposals
        self.assertGreaterEqual(page.table.minimumHeight(), 320)
        self.assertEqual(page.table.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.assertEqual(page.table.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.assertEqual(page.table.horizontalHeader().count(), 6)

        def complete_proposal_form() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets() if isinstance(item, ProposalDialog))
            dialog.customer.setCurrentIndex(dialog.customer.findData(customer["id"]))
            dialog.expiry.setText("2030-05-20")
            dialog._lines = [{"description": "Servicio y repuesto", "quantity": 2, "unit_price_cop": 75_000}]
            dialog._save()

        QTimer.singleShot(0, complete_proposal_form)
        window.action_button.click()
        proposal = self.connection.execute("SELECT * FROM cotizaciones").fetchone()
        self.assertIsNotNone(proposal)
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual(page.table.item(0, 1).text(), "Cliente propuestas UI")

        self.assertEqual(page.table.item(0, 4).text(), "$ 150.000 COP")
        self.assertIn("2030-05-20", page.table.item(0, 3).text())

        page.search.setText(proposal["codigo"])
        page.refresh()
        self.assertEqual(page.table.rowCount(), 1)
        page.state_filter.setCurrentIndex(page.state_filter.findData("enviada"))
        self.assertEqual(page.table.rowCount(), 0)
        page.state_filter.setCurrentIndex(page.state_filter.findData(None))
        self.assertEqual(page.table.rowCount(), 1)
        ProposalService(self.connection).transition_proposal(proposal["id"], "enviada")
        page.refresh()
        page.table.selectRow(0)

        def close_details() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets()
                          if isinstance(item, ProposalDetailsDialog)
                          and proposal["codigo"] in item.windowTitle())
            self.assertIn(proposal["codigo"], dialog.windowTitle())
            self.assertGreater(dialog.size().height(), 500)
            action_labels = [
                dialog.actions.itemAt(index).widget().text()
                for index in range(dialog.actions.count())
                if dialog.actions.itemAt(index).widget() is not None
            ]
            self.assertIn("Registrar aceptación", action_labels)
            self.assertNotIn("Marcar vencida", action_labels)
            dialog.accept()

        QTimer.singleShot(0, close_details)
        page._open_selected()

    def test_sales_workspace_confirms_direct_sale_and_updates_payment_status(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente ventas UI")
        inventory = InventoryService(self.connection)
        product = inventory.create_product(sku="UI-SKU", name="Producto UI",
                                           unit_cost_cop=10_000, suggested_price_cop=25_000)
        inventory.adjust_stock(product["id"], 2, unit_cost_cop=10_000, reason="Ingreso de prueba UI", idempotency_key=uuid4().hex)
        window = create_main_window(self.connection, database_path=":memory:",
                                    schema_version=self.schema_version)
        self.addCleanup(window.close)
        page = window.pages["sales"]
        self.assertEqual([page.tabs.tabText(i) for i in range(page.tabs.count())],
                         ["Propuestas a clientes", "Ventas y pagos"])
        page.tabs.setCurrentIndex(1)
        self.assertEqual(window.action_button.text(), "＋  Nueva venta")

        def confirm_sale() -> None:
            dialog = next(widget for widget in QApplication.topLevelWidgets() if isinstance(widget, SaleDialog))
            dialog.customer.setCurrentIndex(dialog.customer.findData(customer["id"]))
            dialog._lines = [{"description": "Producto UI", "quantity": 1,
                              "unit_price_cop": 25_000, "product_id": product["id"]}]
            dialog._render()
            dialog._save()

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            QTimer.singleShot(0, confirm_sale)
            page.sales.create_button.click()
        self.assertEqual(page.sales.table.rowCount(), 1)
        self.assertEqual(page.sales.table.item(0, 6).text(), "Pendiente de pago")
        sale_id = page.sales.table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        details = SaleDetailsDialog(SalesService(self.connection), sale_id)

        def accept_default_payment() -> int:
            return QDialog.DialogCode.Accepted

        with patch.object(PaymentDialog, "exec", autospec=True, side_effect=accept_default_payment), \
             patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            details._payment()
        self.assertEqual(details.sale["estado_cobro"], "completada")
        self.assertEqual(details.sale["pagado_neto_cop"], 25_000)

    def test_accepted_proposal_conversion_requires_ui_confirmation_and_refreshes_sales(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente conversión UI")
        inventory = InventoryService(self.connection)
        product = inventory.create_product(sku="QUOTE-UI", name="Artículo acordado",
                                           unit_cost_cop=12_000, suggested_price_cop=20_000)
        inventory.adjust_stock(product["id"], 1, unit_cost_cop=12_000, reason="Ingreso de prueba UI", idempotency_key=uuid4().hex)
        proposals = ProposalService(self.connection)
        proposal = proposals.create_proposal(customer["id"], [{
            "description": "Artículo acordado", "quantity": 1, "unit_price_cop": 20_000,
            "product_id": product["id"],
        }])
        proposals.transition_proposal(proposal["id"], "enviada")
        proposals.transition_proposal(proposal["id"], "aceptada")
        window = create_main_window(self.connection, database_path=":memory:",
                                    schema_version=self.schema_version)
        self.addCleanup(window.close)
        page = window.pages["sales"]

        def convert_and_close() -> None:
            dialog = next(widget for widget in QApplication.topLevelWidgets()
                          if isinstance(widget, ProposalDetailsDialog))
            self.assertTrue(any(dialog.actions.itemAt(i).widget().text() == "Convertir en venta"
                                for i in range(dialog.actions.count())
                                if dialog.actions.itemAt(i).widget()))
            dialog._convert_to_sale()
            dialog.accept()

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
             patch.object(QMessageBox, "information"):
            QTimer.singleShot(0, convert_and_close)
            self.assertTrue(page.open_details(proposal["id"], window))
        page.tabs.setCurrentIndex(1)
        page.refresh()
        self.assertEqual(page.sales.table.rowCount(), 1)
        self.assertEqual(page.sales.table.item(0, 1).text(), "Cliente conversión UI")
        self.assertEqual(inventory.get_product(product["id"])["existencia"], 0)

    def test_inventory_workspace_creates_product_supplier_and_draft_purchase(self) -> None:
        window = create_main_window(
            self.connection, database_path=":memory:", schema_version=self.schema_version
        )
        self.addCleanup(window.close)
        window._navigate("inventory")
        page = window.pages["inventory"]
        self.assertIsInstance(page, InventoryWorkspacePage)
        self.assertEqual(page.tabs.count(), 3)

        def create_product() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets() if isinstance(item, ProductDialog))
            dialog.sku.setText("UI-PROD-1")
            dialog.name.setText("Producto visual de prueba")
            dialog.category.setText("Accesorios")
            dialog.unit_cost.setText("25000")
            dialog.unit_price.setText("40000")
            dialog._save()

        QTimer.singleShot(0, create_product)
        page.products._create()
        product = self.connection.execute("SELECT * FROM productos WHERE sku='UI-PROD-1'").fetchone()
        self.assertIsNotNone(product)
        self.assertEqual(page.products.table.rowCount(), 1)

        page.tabs.setCurrentWidget(page.suppliers)

        def create_supplier() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets() if isinstance(item, SupplierDialog))
            dialog.name.setText("Proveedor visual de prueba")
            dialog.tax_id.setText("NIT-UI-1")
            dialog.email.setText("ui@example.test")
            dialog._save()

        QTimer.singleShot(0, create_supplier)
        page.suppliers._create()
        supplier = self.connection.execute("SELECT * FROM proveedores WHERE identificacion_fiscal='NIT-UI-1'").fetchone()
        self.assertIsNotNone(supplier)
        self.assertEqual(page.suppliers.table.rowCount(), 1)

        page.tabs.setCurrentWidget(page.purchases)

        def create_purchase() -> None:
            dialog = next(item for item in QApplication.topLevelWidgets() if isinstance(item, PurchaseDialog))
            dialog.supplier.setCurrentIndex(dialog.supplier.findData(supplier["id"]))
            dialog.lines = [{"product_id": product["id"], "quantity": 3,
                             "unit_cost_cop": 25_000, "description": "Snapshot UI"}]
            dialog._save()

        QTimer.singleShot(0, create_purchase)
        page.purchases._create()
        purchase = self.connection.execute("SELECT * FROM compras").fetchone()
        self.assertEqual(purchase["estado"], "borrador")
        self.assertEqual(page.purchases.table.rowCount(), 1)
        self.assertEqual(page.purchases.table.item(0, 5).text(), "$ 75.000 COP")

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
            self.assertEqual(version, 9)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            connection.execute(
                "INSERT INTO clientes (nombre, creado_en_utc, actualizado_en_utc) VALUES ('Registro de prueba', '2026-10-24T15:30:00Z', '2026-10-24T15:30:00Z')"
            )
            connection.commit()
            connection.close()

            reopened, reopened_version = initialize_database(database_path)
            try:
                self.assertEqual(reopened_version, 9)
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
        service.update_technical_details(
            order["id"], diagnosis="Se detectó fuente dañada", work_performed="", tests_performed=""
        )
        dialog._reload()
        self.assertEqual(dialog.next_state.itemData(1), "en_proceso")

        service.transition_order(order["id"], "en_proceso")
        dialog._reload()
        self.assertEqual(dialog.next_state.count(), 1)
        self.assertFalse(dialog.next_state.isEnabled())
        self.assertIn("Guarda el trabajo realizado", dialog.transition_hint.text())

        service.update_technical_details(
            order["id"],
            diagnosis="Diagnóstico",
            work_performed="Se reemplazó el componente",
            tests_performed="Prueba funcional completada",
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

    def test_status_history_rows_expand_for_long_reasons_and_keep_full_tooltip(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente historial")
        equipment = EquipmentService(self.connection).register_equipment(customer["id"], "Portátil")
        service = ServiceOrderService(self.connection)
        order = service.open_service_order(customer["id"], equipment["id"], "Falla")
        service.transition_order(order["id"], "diagnostico", reason="Revisión inicial")
        service.update_technical_details(
            order["id"], diagnosis="Fuente defectuosa", work_performed="", tests_performed=""
        )
        long_reason = ("Cliente confirmó por llamada y se explicó el alcance del trabajo. " * 24).strip()
        service.transition_order(order["id"], "en_proceso", reason=long_reason)
        dialog = OrderDetailDialog(service, order["id"])
        self.addCleanup(dialog.close)
        dialog.resize(700, 560)
        dialog.show()
        self.app.processEvents()

        self.assertEqual(dialog.history.rowCount(), 3)
        self.assertEqual(
            dialog.history.verticalHeader().sectionResizeMode(0),
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.assertGreaterEqual(dialog.history.horizontalHeader().height(), 46)
        self.assertEqual(dialog.history.item(2, 3).toolTip(), long_reason)
        self.assertGreater(dialog.history.rowHeight(2), dialog.history.rowHeight(1))
        self.assertGreater(dialog.history.visualRect(dialog.history.model().index(2, 3)).height(), 54)

    def test_order_detail_proposes_and_records_additional_service_decision(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente adicionales UI")
        equipment = EquipmentService(self.connection).register_equipment(customer["id"], "Portátil")
        service = ServiceOrderService(self.connection)
        order = service.open_service_order(
            customer["id"], equipment["id"], "No enciende", initial_amount_cop=15000
        )
        service.transition_order(order["id"], "diagnostico")
        service.update_technical_details(
            order["id"], diagnosis="Fuente fallando", work_performed="", tests_performed=""
        )
        dialog = OrderDetailDialog(service, order["id"])
        self.addCleanup(dialog.close)

        dialog.proposal_description.setPlainText("Cambio de fuente")
        dialog.proposal_amount.setText("24000")
        dialog.propose_button.click()
        self.assertEqual(dialog.additional_table.rowCount(), 1)
        self.assertEqual(dialog.additional_table.item(0, 2).text(), "Pendiente de decisión")
        self.assertEqual(dialog.price_label.text(), "$ 15.000 COP")
        self.assertEqual(dialog.next_state.itemData(1), "espera_aprobacion")

        service.transition_order(order["id"], "espera_aprobacion")
        dialog._reload()
        dialog.decision_evidence.setPlainText("Cliente indicó aprobación por llamada, según nota del técnico.")
        with patch(
            "dragontech_manager.ui.order_details.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog.approve_additional_button.click()

        self.assertEqual(dialog.additional_table.item(0, 2).text(), "Aprobado")
        self.assertEqual(dialog.additional_history.rowCount(), 1)
        self.assertEqual(dialog.price_label.text(), "$ 39.000 COP")
        self.assertEqual(dialog.next_state.itemData(1), "en_proceso")
        self.assertEqual(
            service.get_order_detail(order["id"])["importe_acordado_cop"], 39000
        )

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

    def test_order_detail_payments_and_reversals_flow(self) -> None:
        customer = CustomerService(self.connection).create_customer("Cliente cobros UI")
        equipment = EquipmentService(self.connection).register_equipment(customer["id"], "Portátil")
        service = ServiceOrderService(self.connection)
        order = service.open_service_order(
            customer["id"], equipment["id"], "Mantenimiento preventivo", initial_amount_cop=60_000
        )
        dialog = OrderDetailDialog(service, order["id"])
        self.addCleanup(dialog.close)

        # 1. Verificar estado inicial
        self.assertEqual(dialog.price_label.text(), "$ 60.000 COP")
        self.assertEqual(dialog.paid_label.text(), "$ 0 COP")
        self.assertEqual(dialog.balance_label.text(), "$ 60.000 COP")
        self.assertTrue(dialog.register_payment_button.isEnabled())
        self.assertFalse(dialog.reverse_payment_button.isEnabled())
        self.assertEqual(dialog.payments_table.rowCount(), 0)

        # 2. Registrar anticipo de 20.000 COP
        def fill_payment_dialog() -> None:
            dlg = next(w for w in QApplication.topLevelWidgets() if isinstance(w, OrderPaymentDialog))
            dlg.amount.setText("20000")
            dlg.method.setCurrentText("Efectivo")
            dlg.reference.setText("Recibo #101")
            dlg.findChild(QDialogButtonBox).accepted.emit()

        QTimer.singleShot(0, fill_payment_dialog)
        with patch(
            "dragontech_manager.ui.order_details.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog.register_payment_button.click()

        self.assertTrue(dialog.changed)
        self.assertEqual(dialog.paid_label.text(), "$ 20.000 COP")
        self.assertEqual(dialog.balance_label.text(), "$ 40.000 COP")
        self.assertEqual(dialog.payments_table.rowCount(), 1)
        self.assertEqual(dialog.payments_table.item(0, 0).text(), "Pago recibido")
        self.assertEqual(dialog.payments_table.item(0, 1).text(), "$ 20.000 COP")

        # 3. Registrar pago del saldo restante (40.000 COP)
        def fill_second_payment() -> None:
            dlg = next(w for w in QApplication.topLevelWidgets() if isinstance(w, OrderPaymentDialog))
            self.assertEqual(dlg.amount.text(), "40000")  # Sugerido automáticamente
            dlg.method.setCurrentText("Transferencia bancaria")
            dlg.reference.setText("Transf-5544")
            dlg.findChild(QDialogButtonBox).accepted.emit()

        QTimer.singleShot(0, fill_second_payment)
        with patch(
            "dragontech_manager.ui.order_details.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog.register_payment_button.click()

        self.assertEqual(dialog.paid_label.text(), "$ 60.000 COP")
        self.assertEqual(dialog.balance_label.text(), "$ 0 COP")
        self.assertEqual(dialog.payments_table.rowCount(), 2)
        self.assertFalse(dialog.register_payment_button.isEnabled())

        # 4. Seleccionar el primer pago para revertir
        dialog.payments_table.selectRow(0)
        self.assertTrue(dialog.reverse_payment_button.isEnabled())

        # 5. Revertir el primer pago
        with patch(
            "dragontech_manager.ui.order_details.QInputDialog.getText",
            return_value=("Devolución de anticipo solicitado por cliente", True),
        ), patch(
            "dragontech_manager.ui.order_details.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog.reverse_payment_button.click()

        self.assertEqual(dialog.payments_table.rowCount(), 3)
        self.assertEqual(dialog.paid_label.text(), "$ 40.000 COP")
        self.assertEqual(dialog.balance_label.text(), "$ 20.000 COP")
        self.assertTrue(dialog.register_payment_button.isEnabled())

        # Fila 0 (revertido): no debe permitir revertirse de nuevo
        dialog.payments_table.selectRow(0)
        self.assertFalse(dialog.reverse_payment_button.isEnabled())

        # Fila 2 (es una reversión): no debe permitir revertirse
        dialog.payments_table.selectRow(2)
        self.assertFalse(dialog.reverse_payment_button.isEnabled())

        # Fila 1 (segundo pago aún activo): sí debe permitir revertirse
        dialog.payments_table.selectRow(1)
        self.assertTrue(dialog.reverse_payment_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
