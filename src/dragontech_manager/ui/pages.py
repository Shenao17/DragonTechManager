"""Pantallas principales conectadas a los servicios existentes."""

from datetime import datetime
import sqlite3
from zoneinfo import ZoneInfo

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from dragontech_manager.services.errors import ServiceError
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

    def _fill_rows(self, rows: list[dict]) -> None:
        raise NotImplementedError

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
            self.table.setRowHeight(index, 48)

    def create_dialog(self, parent=None) -> bool:
        dialog = CustomerDialog(self.service, parent)
        created = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_record if created else None
        return created


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
            self.table.item(index, 4).setForeground(QColor(_STATUS_COLORS.get(order["estado"], "#FFFFFF")))

    def create_dialog(self, parent=None) -> bool:
        customers = self.customer_service.list_customers(limit=500)
        equipment = self.equipment_service.list_equipment(limit=500)
        dialog = ServiceOrderDialog(self.service, customers, equipment, parent)
        created = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_record if created else None
        return created


class DashboardPage(QWidget):
    request_navigation = Signal(str)

    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 28)
        layout.setSpacing(22)

        welcome = QFrame()
        welcome.setProperty("role", "surface")
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setContentsMargins(24, 20, 24, 20)
        eyebrow = QLabel("DRAGONTECH CARE  /  CENTRO DE OPERACIONES")
        eyebrow.setStyleSheet("color: #8CB0A8; font-size: 8pt; font-weight: 700; letter-spacing: 1.4px;")
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
            "entregadas": MetricCard("Entregadas", "Órdenes cerradas con el cliente", "#778A9C"),
        }
        for column, card in enumerate(self.cards.values()):
            cards.addWidget(card, 0, column)
            cards.setColumnStretch(column, 1)
        layout.addLayout(cards)

        lower = QHBoxLayout()
        activity = QFrame()
        activity.setProperty("role", "surface")
        activity_layout = QVBoxLayout(activity)
        activity_layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel("Actividad de servicio")
        title.setStyleSheet("font-size: 13pt; font-weight: 700;")
        activity_layout.addWidget(title)
        self.activity_state = EmptyState(
            "Todavía no hay órdenes",
            "Las órdenes reales aparecerán aquí cuando se registren en el sistema.",
            action_text="Ir a órdenes",
            action=lambda: self.request_navigation.emit("orders"),
        )
        activity_layout.addWidget(self.activity_state)
        lower.addWidget(activity, 3)

        shortcuts = QFrame()
        shortcuts.setProperty("role", "surface")
        shortcut_layout = QVBoxLayout(shortcuts)
        shortcut_layout.setContentsMargins(20, 18, 20, 18)
        shortcut_title = QLabel("Accesos rápidos")
        shortcut_title.setStyleSheet("font-size: 13pt; font-weight: 700;")
        shortcut_layout.addWidget(shortcut_title)
        for text, destination, hint in (
            ("Clientes", "customers", "Buscar o crear un cliente"),
            ("Equipos", "equipment", "Registrar un equipo recibido"),
            ("Órdenes", "orders", "Abrir y consultar servicios"),
        ):
            button = QPushButton(f"{text}    ›\n{hint}")
            button.setMinimumHeight(58)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton { text-align: left; background: #252A30; border: 1px solid #373D44; "
                "border-radius: 8px; padding: 8px 12px; font-weight: 700; } "
                "QPushButton:hover { background: #30383D; border-color: #5E9188; }"
            )
            button.clicked.connect(
                lambda _checked=False, target=destination: self.request_navigation.emit(target)
            )
            shortcut_layout.addWidget(button)
        shortcut_layout.addStretch(1)
        lower.addWidget(shortcuts, 2)
        layout.addLayout(lower, 1)

    def refresh(self) -> None:
        try:
            summary = self.service.order_summary()
        except (ServiceError, sqlite3.Error, OSError):
            for card in self.cards.values():
                card.value_label.setText("—")
            self.activity_state.title_label.setText("No se pudo cargar el resumen")
            self.activity_state.description_label.setText(
                "Revisa la base de datos local y vuelve a entrar al panel principal."
            )
            return
        for key, card in self.cards.items():
            card.set_value(summary[key])
        total = summary["total"]
        if total:
            self.activity_state.title_label.setText("Actividad registrada")
            self.activity_state.description_label.setText(
                f"Hay {total} órdenes en el tablero. Consulta el módulo de servicio para revisar el detalle."
            )
        else:
            self.activity_state.title_label.setText("Todavía no hay órdenes")
            self.activity_state.description_label.setText(
                "Las órdenes reales aparecerán aquí cuando se registren en el sistema."
            )


class ComingSoonPage(QWidget):
    def __init__(self, title: str, description: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(44, 38, 44, 38)
        self.state = EmptyState(
            f"{title}: próximamente",
            description,
        )
        layout.addStretch(1)
        layout.addWidget(self.state)
        layout.addStretch(1)


class InformationPage(QWidget):
    def __init__(self, database_path: str, schema_version: int, parent=None) -> None:
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
        panel_layout.addRow("Versión", QLabel("0.1.0 · En desarrollo"))
        panel_layout.addRow("Esquema SQLite", QLabel(str(schema_version)))
        path_label = QLabel(database_path)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        panel_layout.addRow("Base de datos local", path_label)
        note = QLabel(
            "Los datos se guardan localmente en este computador. La base se crea vacía en el primer inicio; "
            "no se cargan clientes ni registros de demostración. Las copias de seguridad aún no están disponibles desde la interfaz."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        panel_layout.addRow(note)
        layout.addWidget(panel)
        layout.addStretch(1)


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
