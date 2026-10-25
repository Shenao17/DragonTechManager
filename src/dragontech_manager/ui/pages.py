"""Pantallas principales conectadas a los servicios existentes."""

from datetime import datetime
from platform import python_version
import sqlite3
from zoneinfo import ZoneInfo

from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QApplication,
    QFrame,
    QFormLayout,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from dragontech_manager.services.errors import ServiceError
from dragontech_manager.services.updates import UpdateCheckResult
from .dialogs import CustomerDialog, EquipmentDialog, ServiceOrderDialog
from .widgets import EmptyState, MetricCard, build_table, set_cell

_BOGOTA = ZoneInfo("America/Bogota")
_STATUS_LABELS = {
    "recibida": "Recibida",
    "diagnostico": "Diagnóstico",
    "espera_aprobacion": "Espera aprobación",
    "en_proceso": "En proceso",
    "lista": "Lista",
    "entregada": "Entregada",
    "cancelada": "Cancelada",
}
_STATUS_COLORS = {
    "recibida": "#AAB7C4",
    "diagnostico": "#8DB5D0",
    "espera_aprobacion": "#D4B779",
    "en_proceso": "#79AA9F",
    "lista": "#8DBB91",
    "entregada": "#89939C",
    "cancelada": "#C98282",
}
_STATUS_COLORS_LIGHT = {
    "recibida": "#516170",
    "diagnostico": "#355F7A",
    "espera_aprobacion": "#7C5B20",
    "en_proceso": "#3E5954",
    "lista": "#36623B",
    "entregada": "#5D6872",
    "cancelada": "#853B3B",
}


def format_cop(amount: int | None) -> str:
    if amount is None:
        return "—"
    return "$ " + f"{amount:,}".replace(",", ".") + " COP"


def format_local_datetime(value: str | None) -> str:
    if not value:
        return "—"
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return instant.astimezone(_BOGOTA).strftime("%d %b %Y · %H:%M")


class RegistryPage(QWidget):
    request_create = Signal()
    request_edit = Signal(int)
    request_details = Signal(int)

    def __init__(
        self,
        columns: list[str],
        *,
        search_hint: str,
        column_widths: list[int],
        flexible_column: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.page_size = 100
        self.offset = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(16)

        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText(search_hint)
        self.search.setMaximumWidth(460)
        tools.addWidget(self.search)
        tools.addStretch(1)
        self.page_label = QLabel("")
        self.page_label.setObjectName("muted")
        tools.addWidget(self.page_label)
        self.edit_button = QPushButton("Editar seleccionado")
        self.edit_button.setEnabled(False)
        self.edit_button.hide()
        self.edit_button.clicked.connect(self._emit_selected_edit)
        tools.addWidget(self.edit_button)
        self.details_button = QPushButton("Ver detalle")
        self.details_button.setEnabled(False)
        self.details_button.hide()
        self.details_button.clicked.connect(self._emit_selected_details)
        tools.addWidget(self.details_button)
        self.previous = QPushButton("‹  Anterior")
        self.next = QPushButton("Siguiente  ›")
        tools.addWidget(self.previous)
        tools.addWidget(self.next)
        layout.addLayout(tools)

        self.table = build_table(
            columns,
            column_widths=column_widths,
            flexible_column=flexible_column,
        )
        self.empty_title = "Todavía no hay registros"
        self.empty_state = EmptyState(
            self.empty_title,
            "Cuando registres información, aparecerá aquí.",
            action_text="Crear primer registro",
            action=self.request_create.emit,
        )
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty_state)
        self.stack.addWidget(self.table)
        layout.addWidget(self.stack, 1)
        self.table.itemSelectionChanged.connect(self._sync_action_buttons)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._search_changed)
        self.previous.clicked.connect(self.previous_page)
        self.next.clicked.connect(self.next_page)

    def _search_changed(self, _value: str) -> None:
        self.offset = 0
        self.search_timer.start()

    def previous_page(self) -> None:
        self.offset = max(0, self.offset - self.page_size)
        self.refresh()

    def next_page(self) -> None:
        self.offset += self.page_size
        self.refresh()

    def refresh(self) -> None:
        raise NotImplementedError

    def show_rows(self, rows: list[dict], *, search_term: str = "") -> None:
        has_next = len(rows) > self.page_size
        rows = rows[: self.page_size]
        self.table.setRowCount(len(rows))
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(has_next)
        first = self.offset + 1 if rows else 0
        last = self.offset + len(rows)
        self.page_label.setText(f"{first}–{last}" if rows else "")
        if rows:
            self.stack.setCurrentWidget(self.table)
        else:
            if search_term:
                self.empty_state.title_label.setText("Sin coincidencias")
                self.empty_state.description_label.setText("Prueba con otro término de búsqueda.")
            else:
                self.empty_state.title_label.setText(self.empty_title)
            self.stack.setCurrentWidget(self.empty_state)
        self._fill_rows(rows)
        restore_id = getattr(self, "_restore_selection_id", None)
        if restore_id is not None:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == restore_id:
                    self.table.selectRow(row)
                    break
            self._restore_selection_id = None
        self._sync_action_buttons()

    def _fill_rows(self, rows: list[dict]) -> None:
        raise NotImplementedError

    def _selected_record_id(self) -> int | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _sync_action_buttons(self) -> None:
        enabled = self._selected_record_id() is not None
        self.edit_button.setEnabled(enabled)
        self.details_button.setEnabled(enabled)

    def _emit_selected_edit(self) -> None:
        record_id = self._selected_record_id()
        if record_id is not None:
            self.request_edit.emit(record_id)

    def _emit_selected_details(self) -> None:
        record_id = self._selected_record_id()
        if record_id is not None:
            self.request_details.emit(record_id)

    def restore_selection_after_refresh(self, record_id: int) -> None:
        self._restore_selection_id = record_id

    def show_load_error(self, error: Exception) -> None:
        self.table.setRowCount(0)
        self.empty_state.title_label.setText("No se pudo cargar la información")
        self.empty_state.description_label.setText(
            str(error)
            if isinstance(error, ServiceError)
            else "Revisa que la base de datos esté disponible y vuelve a intentarlo."
        )
        self.stack.setCurrentWidget(self.empty_state)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)


class CustomerPage(RegistryPage):
    def __init__(self, service, parent=None) -> None:
        super().__init__(
            ["Cliente", "Teléfono / WhatsApp", "Correo", "Notas"],
            search_hint="Buscar nombre, teléfono, WhatsApp o correo…",
            column_widths=[240, 185, 235, 260],
            flexible_column=0,
            parent=parent,
        )
        self.service = service
        self.empty_title = "Aún no tienes clientes"
        self.edit_button.show()
        self.table.cellDoubleClicked.connect(self._edit_row)
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.service.list_customers(
                search=self.search.text(), limit=self.page_size + 1, offset=self.offset
            )
        except (ServiceError, sqlite3.Error, OSError) as error:
            self.show_load_error(error)
            return
        self.show_rows(rows, search_term=self.search.text().strip())

    def _fill_rows(self, rows: list[dict]) -> None:
        for index, customer in enumerate(rows):
            contact = customer["whatsapp"] or customer["telefono"] or "—"
            values = (customer["nombre"], contact, customer["correo"] or "—", customer["notas"] or "—")
            for column, value in enumerate(values):
                set_cell(self.table, index, column, value, muted=(column == 3 and value == "—"))
            self.table.item(index, 0).setData(Qt.ItemDataRole.UserRole, customer["id"])
            self.table.setRowHeight(index, 48)

    def create_dialog(self, parent=None) -> bool:
        dialog = CustomerDialog(self.service, parent)
        created = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_record if created else None
        return created

    def edit_dialog(self, customer_id: int, parent=None) -> bool:
        customer = self.service.get_customer(customer_id)
        dialog = CustomerDialog(self.service, parent, customer=customer)
        updated = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_record if updated else None
        return updated

    def _edit_row(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item:
            self.request_edit.emit(item.data(Qt.ItemDataRole.UserRole))


class EquipmentPage(RegistryPage):
    history_requested = Signal(int)

    def __init__(self, service, customer_service, parent=None) -> None:
        super().__init__(
            ["Código", "Equipo", "Marca / modelo", "Serial", "Propietario"],
            search_hint="Buscar código, tipo, marca, modelo, serial o propietario…",
            column_widths=[155, 170, 245, 190, 220],
            flexible_column=4,
            parent=parent,
        )
        self.service = service
        self.customer_service = customer_service
        self.empty_title = "Aún no hay equipos registrados"
        self.edit_button.show()
        self.table.cellDoubleClicked.connect(self._open_history)
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.service.list_equipment(
                search=self.search.text(), limit=self.page_size + 1, offset=self.offset
            )
        except (ServiceError, sqlite3.Error, OSError) as error:
            self.show_load_error(error)
            return
        self.show_rows(rows, search_term=self.search.text().strip())

    def _fill_rows(self, rows: list[dict]) -> None:
        for index, equipment in enumerate(rows):
            values = (
                equipment["codigo"],
                equipment["tipo"],
                " ".join(value for value in (equipment["marca"], equipment["modelo"]) if value) or "—",
                equipment["serial"] or "—",
                equipment["cliente_nombre"],
            )
            for column, value in enumerate(values):
                set_cell(self.table, index, column, value, muted=(value == "—"))
            self.table.item(index, 0).setData(Qt.ItemDataRole.UserRole, equipment["id"])

    def create_dialog(self, parent=None) -> bool:
        customers = self.customer_service.list_customers(limit=500)
        dialog = EquipmentDialog(self.service, customers, parent)
        created = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_record if created else None
        return created

    def edit_dialog(self, equipment_id: int, parent=None) -> bool:
        equipment = self.service.get_equipment(equipment_id)
        customers = self.customer_service.list_customers(limit=500)
        if all(row["id"] != equipment["cliente_id"] for row in customers):
            customers.append(self.customer_service.get_customer(equipment["cliente_id"]))
        dialog = EquipmentDialog(self.service, customers, parent, equipment=equipment)
        updated = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_record if updated else None
        return updated

    def _open_history(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item:
            self.history_requested.emit(item.data(Qt.ItemDataRole.UserRole))


class OrdersPage(RegistryPage):
    def __init__(self, service, customer_service, equipment_service, parent=None) -> None:
        super().__init__(
            ["Orden", "Equipo", "Cliente solicitante", "Recibida", "Estado", "Precio acordado"],
            search_hint="Filtra por estado de la orden…",
            column_widths=[165, 160, 240, 175, 145, 190],
            flexible_column=2,
            parent=parent,
        )
        self.service = service
        self.customer_service = customer_service
        self.equipment_service = equipment_service
        self.empty_title = "Aún no hay órdenes de servicio"
        self.details_button.show()
        self.table.cellDoubleClicked.connect(self._show_details)
        self.search.setPlaceholderText("Filtrar por estado: recibida, en proceso, lista…")
        self.refresh()

    def refresh(self) -> None:
        state_query = self.search.text().strip().casefold()
        states = {
            label.casefold(): key for key, label in _STATUS_LABELS.items()
        }
        state = state_query if state_query in _STATUS_LABELS else states.get(state_query)
        if state_query and state is None:
            self.show_rows([], search_term=state_query)
            return
        try:
            rows = self.service.list_orders(
                state=state,
                limit=self.page_size + 1,
                offset=self.offset,
            )
        except (ServiceError, sqlite3.Error, OSError) as error:
            self.show_load_error(error)
            return
        self.show_rows(rows, search_term=state_query)

    def _fill_rows(self, rows: list[dict]) -> None:
        for index, order in enumerate(rows):
            values = (
                order["codigo"],
                order["equipo_codigo"],
                order["cliente_nombre"],
                format_local_datetime(order["recibido_en_utc"]),
                _STATUS_LABELS.get(order["estado"], order["estado"]),
                format_cop(order["importe_acordado_cop"]),
            )
            for column, value in enumerate(values):
                set_cell(self.table, index, column, value)
            self.table.item(index, 0).setData(Qt.ItemDataRole.UserRole, order["id"])
            application = QApplication.instance()
            palette = _STATUS_COLORS_LIGHT if application and application.property("dragontechTheme") == "light" else _STATUS_COLORS
            self.table.item(index, 4).setForeground(
                QColor(palette.get(order["estado"], "#FFFFFF" if palette is _STATUS_COLORS else "#232226"))
            )

    def create_dialog(self, parent=None) -> bool:
        customers = self.customer_service.list_customers(limit=500)
        equipment = self.equipment_service.list_equipment(limit=500)
        dialog = ServiceOrderDialog(self.service, customers, equipment, parent)
        created = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_record if created else None
        return created

    def _show_details(self, row: int, _column: int) -> None:
        item = self.table.item(row, 0)
        if item:
            self.request_details.emit(item.data(Qt.ItemDataRole.UserRole))


class DashboardPage(QWidget):
    request_navigation = Signal(str)
    request_create = Signal(str)
    request_order_details = Signal(int)

    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content = QWidget()
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(22)
        scroll.setWidget(self.content)
        outer.addWidget(scroll)

        welcome = QFrame()
        welcome.setProperty("role", "surface")
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setContentsMargins(24, 20, 24, 20)
        eyebrow = QLabel("DRAGONTECH CARE  /  CENTRO DE OPERACIONES")
        eyebrow.setObjectName("dashboardEyebrow")
        welcome_layout.addWidget(eyebrow)
        headline = QLabel("Todo el servicio, en un solo lugar.")
        headline.setStyleSheet("font-size: 20pt; font-weight: 700;")
        welcome_layout.addWidget(headline)
        description = QLabel("Consulta el trabajo técnico y mantén a la mano tus registros del día.")
        description.setObjectName("muted")
        welcome_layout.addWidget(description)
        layout.addWidget(welcome)

        cards = QGridLayout()
        cards.setSpacing(14)
        self.cards = {
            "pendientes": MetricCard("Pendientes", "Recibidas, diagnóstico o aprobación", "#D4B779"),
            "en_proceso": MetricCard("En proceso", "Trabajo técnico activo", "#5E9188"),
            "listas": MetricCard("Listas", "Preparadas para coordinar entrega", "#8DBB91"),
        }
        for column, card in enumerate(self.cards.values()):
            cards.addWidget(card, 0, column)
            cards.setColumnStretch(column, 1)
        layout.addLayout(cards)

        activity = QFrame()
        activity.setProperty("role", "surface")
        activity_layout = QVBoxLayout(activity)
        activity_layout.setContentsMargins(20, 18, 20, 20)
        activity_layout.setSpacing(14)
        title = QLabel("Órdenes recientes")
        title.setStyleSheet("font-size: 14pt; font-weight: 700;")
        activity_layout.addWidget(title)
        self.recent_table = build_table(
            ["Orden", "Cliente", "Equipo", "Recibida", "Estado"],
            column_widths=[175, 250, 225, 185, 165],
            flexible_column=1,
        )
        self.recent_table.setMinimumHeight(270)
        self.recent_table.cellDoubleClicked.connect(self._open_recent_order)
        activity_layout.addWidget(self.recent_table)
        self.activity_state = EmptyState(
            "Todavía no hay actividad de servicio",
            "Al abrir una orden real, aquí aparecerán el cliente, el equipo, la fecha y el estado actual.",
        )
        self.activity_state.setMinimumHeight(210)
        self.activity_state.hide()
        activity_layout.addWidget(self.activity_state)
        activity_actions = QHBoxLayout()
        activity_actions.addStretch(1)
        self.open_recent_button = QPushButton("Ver detalle de la orden seleccionada")
        self.open_recent_button.setEnabled(False)
        self.open_recent_button.clicked.connect(self._emit_selected_order)
        activity_actions.addWidget(self.open_recent_button)
        activity_layout.addLayout(activity_actions)
        layout.addWidget(activity)

        shortcuts = QFrame()
        shortcuts.setProperty("role", "surface")
        shortcut_layout = QVBoxLayout(shortcuts)
        shortcut_layout.setContentsMargins(20, 18, 20, 20)
        shortcut_layout.setSpacing(12)
        shortcut_title = QLabel("Acciones rápidas")
        shortcut_title.setStyleSheet("font-size: 14pt; font-weight: 700;")
        shortcut_layout.addWidget(shortcut_title)
        actions = QGridLayout()
        actions.setHorizontalSpacing(14)
        actions.setVerticalSpacing(12)
        self.quick_action_buttons: dict[str, QPushButton] = {}
        for column, (text, destination, hint) in enumerate((
            ("＋  Crear cliente", "customers", "Registrar datos de contacto"),
            ("＋  Registrar equipo", "equipment", "Asociarlo a un cliente"),
            ("＋  Abrir orden", "orders", "Crear una visita técnica"),
        )):
            button = QPushButton(f"{text}\n{hint}")
            button.setObjectName("quickActionButton")
            button.setMinimumHeight(76)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, target=destination: self.request_create.emit(target)
            )
            self.quick_action_buttons[destination] = button
            actions.addWidget(button, 0, column)
            actions.setColumnStretch(column, 1)
        shortcut_layout.addLayout(actions)
        layout.addWidget(shortcuts)
        layout.addStretch(1)
        self.recent_table.itemSelectionChanged.connect(self._sync_recent_action)
        self.refresh()

    def refresh(self) -> None:
        try:
            summary = self.service.order_summary()
            recent_orders = self.service.recent_orders(limit=8)
        except (ServiceError, sqlite3.Error, OSError):
            for card in self.cards.values():
                card.value_label.setText("—")
            self.activity_state.title_label.setText("No se pudo cargar el resumen")
            self.activity_state.description_label.setText(
                "Revisa la base de datos local y vuelve a entrar al panel principal."
            )
            self.recent_table.hide()
            self.activity_state.show()
            return
        for key, card in self.cards.items():
            card.set_value(summary[key])
        self.recent_table.setRowCount(len(recent_orders))
        for row, order in enumerate(recent_orders):
            values = (
                order["codigo"],
                order["cliente_nombre"],
                f"{order['equipo_codigo']} · {order['equipo_tipo']}",
                format_local_datetime(order["recibido_en_utc"]),
                _STATUS_LABELS.get(order["estado"], order["estado"]),
            )
            for column, value in enumerate(values):
                set_cell(self.recent_table, row, column, value)
            self.recent_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, order["id"])
        has_orders = bool(recent_orders)
        self.recent_table.setVisible(has_orders)
        self.activity_state.setVisible(not has_orders)
        self.open_recent_button.setEnabled(False)

    def _selected_recent_order_id(self) -> int | None:
        row = self.recent_table.currentRow()
        if row < 0 or self.recent_table.item(row, 0) is None:
            return None
        return self.recent_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _sync_recent_action(self) -> None:
        self.open_recent_button.setEnabled(self._selected_recent_order_id() is not None)

    def _emit_selected_order(self) -> None:
        order_id = self._selected_recent_order_id()
        if order_id is not None:
            self.request_order_details.emit(order_id)

    def _open_recent_order(self, row: int, _column: int) -> None:
        item = self.recent_table.item(row, 0)
        if item is not None:
            self.request_order_details.emit(item.data(Qt.ItemDataRole.UserRole))


class ComingSoonPage(QWidget):
    def __init__(
        self,
        title: str,
        description: str,
        planned_features: tuple[str, ...] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 38, 44, 38)
        layout.setSpacing(18)
        layout.addStretch(1)
        panel = QFrame()
        panel.setProperty("role", "surface")
        panel.setMaximumWidth(920)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(34, 30, 34, 32)
        panel_layout.setSpacing(18)
        heading = QLabel(f"{title}: próximamente")
        heading.setStyleSheet("font-size: 20pt; font-weight: 700;")
        panel_layout.addWidget(heading)
        explanatory_text = QLabel(description)
        explanatory_text.setObjectName("muted")
        explanatory_text.setWordWrap(True)
        panel_layout.addWidget(explanatory_text)
        if planned_features:
            features_heading = QLabel("Funciones previstas")
            features_heading.setStyleSheet("font-size: 12pt; font-weight: 700;")
            panel_layout.addWidget(features_heading)
            for feature in planned_features:
                feature_label = QLabel(f"•  {feature}")
                feature_label.setWordWrap(True)
                panel_layout.addWidget(feature_label)
        panel_layout.addWidget(QLabel("Este módulo aún no guarda ni modifica datos."))
        layout.addWidget(panel, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)


class InformationPage(QWidget):
    theme_changed = Signal(str)
    update_requested = Signal()
    open_release_requested = Signal(str)

    def __init__(self, schema_version: int, theme_name: str = "dark", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(14)
        panel = QFrame()
        panel.setProperty("role", "surface")
        panel_layout = QFormLayout(panel)
        panel_layout.setContentsMargins(22, 20, 22, 20)
        panel_layout.setHorizontalSpacing(20)
        title = QLabel("Información de la aplicación")
        title.setStyleSheet("font-size: 15pt; font-weight: 700;")
        panel_layout.addRow(title)
        panel_layout.addRow("Aplicación", QLabel("DragonTech Manager"))
        panel_layout.addRow("Desarrollado por", QLabel("BlackLabs Dev"))
        from dragontech_manager import __version__

        panel_layout.addRow("Versión", QLabel(f"{__version__} · En desarrollo"))
        panel_layout.addRow("Python / PySide6", QLabel(f"Python {python_version()} · Qt {PYSIDE_VERSION}"))
        panel_layout.addRow("Esquema SQLite", QLabel(str(schema_version)))
        note = QLabel(
            "Los datos se guardan localmente en este computador. La base se crea vacía en el primer inicio; "
            "no se cargan clientes ni registros de demostración. La ruta local se omite para no exponer datos privados. "
            "Las copias de seguridad aún no están disponibles desde la interfaz."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        panel_layout.addRow(note)
        layout.addWidget(panel)

        appearance = QFrame()
        appearance.setProperty("role", "surface")
        appearance_layout = QFormLayout(appearance)
        appearance_layout.setContentsMargins(22, 20, 22, 20)
        appearance_layout.setHorizontalSpacing(20)
        appearance_title = QLabel("Apariencia")
        appearance_title.setStyleSheet("font-size: 14pt; font-weight: 700;")
        appearance_layout.addRow(appearance_title)
        self.theme_selector = QComboBox()
        self.theme_selector.addItem("Oscuro", "dark")
        self.theme_selector.addItem("Claro", "light")
        index = self.theme_selector.findData(theme_name)
        self.theme_selector.setCurrentIndex(max(0, index))
        self.theme_selector.currentIndexChanged.connect(
            lambda _index: self.theme_changed.emit(self.theme_selector.currentData())
        )
        appearance_layout.addRow("Tema", self.theme_selector)
        layout.addWidget(appearance)

        updates = QFrame()
        updates.setProperty("role", "surface")
        updates_layout = QVBoxLayout(updates)
        updates_layout.setContentsMargins(22, 20, 22, 20)
        updates_layout.setSpacing(10)
        updates_title = QLabel("Actualizaciones")
        updates_title.setStyleSheet("font-size: 14pt; font-weight: 700;")
        updates_layout.addWidget(updates_title)
        self.update_status = QLabel("El canal oficial de actualizaciones aún no está configurado.")
        self.update_status.setObjectName("muted")
        self.update_status.setWordWrap(True)
        updates_layout.addWidget(self.update_status)
        buttons = QHBoxLayout()
        self.check_updates_button = QPushButton("Buscar actualizaciones")
        self.check_updates_button.setObjectName("primaryButton")
        self.check_updates_button.clicked.connect(self.update_requested.emit)
        buttons.addWidget(self.check_updates_button)
        self.open_release_button = QPushButton("Abrir página de versión")
        self.open_release_button.hide()
        self.open_release_button.clicked.connect(
            lambda: self.open_release_requested.emit(self._release_url)
        )
        self._release_url = ""
        buttons.addWidget(self.open_release_button)
        buttons.addStretch(1)
        updates_layout.addLayout(buttons)
        layout.addWidget(updates)
        layout.addStretch(1)

    def set_update_checking(self) -> None:
        self.update_status.setText("Comprobando el canal de versiones…")
        self.check_updates_button.setEnabled(False)

    def set_update_result(self, result: UpdateCheckResult) -> None:
        self.check_updates_button.setEnabled(True)
        self.update_status.setText(result.message)
        self._release_url = result.release_url or ""
        self.open_release_button.setVisible(result.status == "available" and bool(self._release_url))


class EquipmentHistoryDialog(QDialog):
    def __init__(self, history: dict, parent=None) -> None:
        super().__init__(parent)
        equipment = history["equipment"]
        self.setWindowTitle(f"Historial · {equipment['codigo']}")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        heading = QLabel(f"{equipment['codigo']}  ·  {equipment['tipo']}")
        heading.setStyleSheet("font-size: 16pt; font-weight: 700;")
        layout.addWidget(heading)
        owner = QLabel(f"Propietario actual: {equipment['cliente_nombre']}  |  {equipment['marca']} {equipment['modelo']}")
        owner.setObjectName("muted")
        layout.addWidget(owner)
        table = build_table(["Orden", "Recibida", "Problema", "Estado", "Importe inicial"])
        orders = history["service_orders"]
        table.setRowCount(len(orders))
        for row_index, order in enumerate(orders):
            values = (
                order["codigo"],
                format_local_datetime(order["recibido_en_utc"]),
                order["problema_reportado"],
                _STATUS_LABELS.get(order["estado"], order["estado"]),
                format_cop(order["importe_inicial_cop"]),
            )
            for column, value in enumerate(values):
                set_cell(table, row_index, column, value)
        layout.addWidget(table, 1)
        if not orders:
            layout.addWidget(
                EmptyState("Sin historial todavía", "Este equipo aún no tiene órdenes de servicio registradas.")
            )
            table.hide()
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        close_buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        layout.addWidget(close_buttons)
