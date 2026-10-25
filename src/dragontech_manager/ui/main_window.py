"""Ventana principal, navegación y composición de módulos funcionales."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from dragontech_manager import __version__
from dragontech_manager.services.customers import CustomerService
from dragontech_manager.services.dashboard import DashboardService
from dragontech_manager.services.equipment import EquipmentService
from dragontech_manager.services.errors import ServiceError
from dragontech_manager.services.service_orders import ServiceOrderService
from dragontech_manager.services.updates import UpdateChecker
from .pages import (
    ComingSoonPage,
    CustomerPage,
    DashboardPage,
    EquipmentHistoryDialog,
    EquipmentPage,
    InformationPage,
    OrdersPage,
)
from .order_details import OrderDetailDialog
from .theme import apply_theme, load_theme_preference, save_theme_preference
from .update_worker import UpdateCheckWorker

_NAV_ITEMS = (
    ("dashboard", "⌂", "Panel principal"),
    ("customers", "◎", "Clientes"),
    ("equipment", "▣", "Equipos"),
    ("orders", "≡", "Órdenes de servicio"),
    ("sales", "◇", "Cotizaciones y ventas"),
    ("inventory", "▦", "Inventario"),
    ("information", "⚙", "Información"),
)

_SUBTITLES = {
    "dashboard": "Resumen operativo de DragonTech Care",
    "customers": "Contactos y relaciones de servicio",
    "equipment": "Equipos registrados e historial técnico",
    "orders": "Recepción y seguimiento de visitas técnicas",
    "sales": "Módulo comercial",
    "inventory": "Productos y existencias",
    "information": "Preferencias locales y datos de la aplicación",
}


class MainWindow(QMainWindow):
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        database_path: str,
        schema_version: int,
        owns_connection: bool = True,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.connection = connection
        self.database_path = database_path
        self.schema_version = schema_version
        self.owns_connection = owns_connection
        self.settings = settings or QSettings()
        self.theme_name = load_theme_preference(self.settings)
        self.update_checker = UpdateChecker()
        self.update_worker: UpdateCheckWorker | None = None
        self.setWindowTitle("DragonTech Manager")
        # Un mínimo alto impedía encajar la ventana en pantallas compactas.
        # Las tablas conservan sus anchos legibles y desplazan horizontalmente.
        self.setMinimumSize(760, 520)
        self.resize(1440, 920)

        self.customer_service = CustomerService(connection)
        self.equipment_service = EquipmentService(connection)
        self.order_service = ServiceOrderService(connection)
        self.dashboard_service = DashboardService(connection)

        shell = QWidget()
        shell.setObjectName("appShell")
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.nav_buttons: dict[str, QPushButton] = {}
        root.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {
            "dashboard": DashboardPage(self.dashboard_service),
            "customers": CustomerPage(self.customer_service),
            "equipment": EquipmentPage(self.equipment_service, self.customer_service),
            "orders": OrdersPage(self.order_service, self.customer_service, self.equipment_service),
            "sales": ComingSoonPage(
                "Cotizaciones y ventas",
                "El esquema de datos existe, pero todavía no hay operaciones comerciales reales en la aplicación.",
                (
                    "Preparar y consultar cotizaciones con sus conceptos y vigencia.",
                    "Convertir una cotización aceptada en venta y registrar pagos parciales.",
                    "Consultar saldos calculados a partir de los pagos trazables.",
                ),
            ),
            "inventory": ComingSoonPage(
                "Inventario",
                "El módulo todavía no ofrece formularios ni modifica existencias.",
                (
                    "Consultar productos, referencias y existencias actuales.",
                    "Registrar compras, reservas y entradas o salidas confirmadas.",
                    "Consultar proveedores, garantías y el historial de movimientos.",
                ),
            ),
            "information": InformationPage(schema_version, self.theme_name),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        root.addWidget(content, 1)

        for key, page in self.pages.items():
            if isinstance(page, DashboardPage):
                page.request_navigation.connect(self._navigate)
                page.request_create.connect(self._dashboard_quick_create)
                page.request_order_details.connect(self._show_order_detail)
            if isinstance(page, (CustomerPage, EquipmentPage, OrdersPage)):
                page.request_create.connect(lambda page=page: self._run_create(page))
            if isinstance(page, (CustomerPage, EquipmentPage)):
                page.request_edit.connect(lambda record_id, page=page: self._run_edit(page, record_id))
            if isinstance(page, OrdersPage):
                page.request_details.connect(self._show_order_detail)
            if isinstance(page, InformationPage):
                page.theme_changed.connect(self._change_theme)
                page.update_requested.connect(self._check_for_updates)
                page.open_release_requested.connect(self._open_release_page)
            if isinstance(page, EquipmentPage):
                page.history_requested.connect(self._show_equipment_history)
        self._current_key = "dashboard"
        self.setCentralWidget(shell)

        self.statusBar().showMessage("Base local conectada · SQLite")
        self._navigate("dashboard")

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(17, 22, 17, 16)
        layout.setSpacing(6)

        brand = QLabel("DRAGONTECH")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        brand_sub = QLabel("CARE  /  MANAGER")
        brand_sub.setObjectName("brandSub")
        layout.addWidget(brand_sub)
        layout.addSpacing(24)

        section_label = QLabel("ESPACIO DE TRABAJO")
        section_label.setStyleSheet("color: #7F8992; font-size: 8pt; font-weight: 700; letter-spacing: 1px; padding-left: 9px;")
        layout.addWidget(section_label)
        layout.addSpacing(7)

        for key, icon, label in _NAV_ITEMS:
            button = QPushButton(f"{icon}    {label}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setMinimumHeight(42)
            button.clicked.connect(lambda _checked=False, destination=key: self._navigate(destination))
            layout.addWidget(button)
            self.nav_buttons[key] = button

        layout.addStretch(1)
        database_label = QLabel("●  BASE LOCAL ACTIVA")
        database_label.setStyleSheet("color: #83AAA1; font-size: 8pt; font-weight: 700; padding: 8px 5px;")
        layout.addWidget(database_label)
        version = QLabel(f"Versión {__version__} · esquema {self.schema_version}")
        version.setObjectName("muted")
        version.setStyleSheet("font-size: 8pt; padding-left: 5px;")
        layout.addWidget(version)
        return sidebar

    def _build_topbar(self) -> QFrame:
        topbar = QFrame()
        topbar.setObjectName("topBar")
        topbar.setMinimumHeight(96)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(28, 17, 30, 16)
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        self.section_title = QLabel("Panel principal")
        self.section_title.setObjectName("pageTitle")
        self.section_subtitle = QLabel(_SUBTITLES["dashboard"])
        self.section_subtitle.setObjectName("pageSubtitle")
        title_column.addWidget(self.section_title)
        title_column.addWidget(self.section_subtitle)
        layout.addLayout(title_column, 1)

        self.action_button = QPushButton()
        self.action_button.setObjectName("primaryButton")
        self.action_button.clicked.connect(self._create_current_record)
        self.action_button.hide()
        layout.addWidget(self.action_button)
        return topbar

    def _navigate(self, key: str) -> None:
        if key not in self.pages:
            return
        self._current_key = key
        self.stack.setCurrentWidget(self.pages[key])
        label = dict((item[0], item[2]) for item in _NAV_ITEMS)[key]
        self.section_title.setText(label)
        self.section_subtitle.setText(_SUBTITLES[key])
        for nav_key, button in self.nav_buttons.items():
            selected = nav_key == key
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)

        action_labels = {
            "customers": "＋  Nuevo cliente",
            "equipment": "＋  Registrar equipo",
            "orders": "＋  Abrir orden",
        }
        if key in action_labels:
            self.action_button.setText(action_labels[key])
            self.action_button.show()
        else:
            self.action_button.hide()

        page = self.pages[key]
        if hasattr(page, "refresh"):
            page.refresh()

    def _create_current_record(self) -> None:
        page = self.pages[self._current_key]
        self._run_create(page)

    def _dashboard_quick_create(self, destination: str) -> None:
        page = self.pages.get(destination)
        if page is None or not hasattr(page, "create_dialog"):
            return
        self._navigate(destination)
        self._run_create(page)

    def _run_create(self, page: QWidget) -> None:
        try:
            created = page.create_dialog(self)  # type: ignore[attr-defined]
        except (ServiceError, sqlite3.Error, OSError) as error:
            self._show_error(str(error) if isinstance(error, ServiceError) else "No se pudo acceder a la base local. Revisa permisos y espacio disponible.")
            return
        if not created:
            return
        page.offset = 0  # type: ignore[attr-defined]
        page.refresh()  # type: ignore[attr-defined]
        self.pages["dashboard"].refresh()
        record = getattr(page, "last_created_record", None)
        if record:
            code = record.get("codigo")
            message = f"Registro guardado correctamente · {code}" if code else "Registro guardado correctamente."
        else:
            message = "Registro guardado correctamente."
        self.statusBar().showMessage(message, 7000)

    def _show_equipment_history(self, equipment_id: int) -> None:
        try:
            history = self.equipment_service.get_equipment_history(equipment_id)
        except (ServiceError, sqlite3.Error) as error:
            self._show_error(str(error) if isinstance(error, ServiceError) else "No se pudo cargar el historial del equipo.")
            return
        EquipmentHistoryDialog(history, self).exec()

    def _run_edit(self, page: QWidget, record_id: int) -> None:
        try:
            updated = page.edit_dialog(record_id, self)  # type: ignore[attr-defined]
        except (ServiceError, sqlite3.Error, OSError) as error:
            self._show_error(
                str(error)
                if isinstance(error, ServiceError)
                else "No se pudo cargar o actualizar el registro. Revisa la base local e inténtalo de nuevo."
            )
            return
        if updated:
            page.restore_selection_after_refresh(record_id)  # type: ignore[attr-defined]
            page.refresh()  # type: ignore[attr-defined]
            self.statusBar().showMessage("Cambios guardados correctamente.", 7000)

    def _show_order_detail(self, order_id: int) -> None:
        try:
            dialog = OrderDetailDialog(self.order_service, order_id, self)
            dialog.exec()
        except (ServiceError, sqlite3.Error, OSError) as error:
            self._show_error(
                str(error)
                if isinstance(error, ServiceError)
                else "No se pudo cargar el detalle de la orden."
            )
            return
        if dialog.changed:
            self.pages["orders"].refresh()
            self.pages["dashboard"].refresh()
            self.statusBar().showMessage("Orden actualizada y su historial fue registrado.", 7000)

    def _change_theme(self, theme_name: str) -> None:
        try:
            self.theme_name = save_theme_preference(theme_name, self.settings)
        except ValueError as error:
            self._show_error(str(error))
            return
        application = QApplication.instance()
        if application:
            apply_theme(application, self.theme_name)
        for key in ("customers", "equipment", "orders"):
            page = self.pages[key]
            selected_id = page._selected_record_id()  # type: ignore[attr-defined]
            if selected_id is not None:
                page.restore_selection_after_refresh(selected_id)  # type: ignore[attr-defined]
            page.refresh()  # type: ignore[attr-defined]
        self.pages["dashboard"].refresh()
        self.statusBar().showMessage(
            f"Tema {'claro' if theme_name == 'light' else 'oscuro'} aplicado y guardado.", 5000
        )

    def _check_for_updates(self) -> None:
        page = self.pages["information"]
        if self.update_worker and self.update_worker.isRunning():
            return
        if not self.update_checker.is_configured:
            page.set_update_result(self.update_checker.check(__version__))
            return
        page.set_update_checking()
        worker = UpdateCheckWorker(self.update_checker, __version__, self)
        self.update_worker = worker
        worker.completed.connect(page.set_update_result)
        worker.finished.connect(lambda worker=worker: self._clear_update_worker(worker))
        worker.start()

    def _clear_update_worker(self, worker: UpdateCheckWorker) -> None:
        if self.update_worker is worker:
            self.update_worker = None

    @staticmethod
    def _open_release_page(url: str) -> None:
        parsed = QUrl(url)
        if parsed.scheme() == "https" and parsed.host():
            QDesktopServices.openUrl(parsed)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "No se pudo completar la operación", message)

    def closeEvent(self, event) -> None:
        if self.owns_connection:
            self.connection.close()
            self.owns_connection = False
        super().closeEvent(event)
