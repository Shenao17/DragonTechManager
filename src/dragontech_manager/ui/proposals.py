"""Listado y formularios de propuestas a clientes."""

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from dragontech_manager.services.errors import ServiceError
from .pages import format_cop, format_local_datetime
from .widgets import EmptyState, build_table, set_cell

_STATUS_LABELS = {
    "borrador": "Borrador", "enviada": "Enviada", "aceptada": "Aceptada",
    "rechazada": "Rechazada", "vencida": "Vencida", "convertida": "Convertida",
    "cancelada": "Cancelada",
}
_BOGOTA = ZoneInfo("America/Bogota")


class ProposalLineDialog(QDialog):
    def __init__(self, parent=None, *, line: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar concepto" if line else "Agregar concepto")
        self.setMinimumSize(540, 400)
        self.resize(650, 490)
        layout = QVBoxLayout(self)
        heading = QLabel(self.windowTitle())
        heading.setStyleSheet("font-size: 16pt; font-weight: 700;")
        layout.addWidget(heading)
        form = QFormLayout()
        form.setVerticalSpacing(16)
        self.description = QTextEdit()
        self.description.setPlaceholderText("Describe el producto o servicio ofrecido")
        self.description.setMinimumHeight(120)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1_000_000)
        self.quantity.setValue(1)
        self.price = QLineEdit()
        self.price.setPlaceholderText("Pesos enteros, por ejemplo 250000")
        form.addRow("Descripción *", self.description)
        form.addRow("Cantidad *", self.quantity)
        form.addRow("Precio unitario (COP) *", self.price)
        layout.addLayout(form, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Aceptar concepto")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._accept_line)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if line:
            self.description.setPlainText(line["description"])
            self.quantity.setValue(line["quantity"])
            self.price.setText(str(line["unit_price_cop"]))
        self.line: dict | None = None

    def _accept_line(self) -> None:
        raw_price = self.price.text().strip()
        if not raw_price.isdigit():
            self.error.setText("El precio debe ser un valor entero en pesos colombianos.")
            return
        description = self.description.toPlainText().strip()
        if not description:
            self.error.setText("La descripción del concepto es obligatoria.")
            return
        self.line = {
            "description": description,
            "quantity": self.quantity.value(),
            "unit_price_cop": int(raw_price),
        }
        self.accept()


class ProposalDialog(QDialog):
    def __init__(self, service, customers: list[dict], parent=None, *, proposal: dict | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.proposal = proposal
        self.created_record: dict | None = None
        self._dirty = False
        self.setWindowTitle("Editar propuesta" if proposal else "Nueva propuesta a cliente")
        self.setMinimumSize(760, 620)
        self.resize(980, 820)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(16)
        title = QLabel(self.windowTitle())
        title.setStyleSheet("font-size: 18pt; font-weight: 700;")
        outer.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(18)
        form = QFormLayout()
        form.setVerticalSpacing(16)
        self.customer = QComboBox()
        for row in customers:
            if row.get("archivado_en_utc") is None:
                self.customer.addItem(row["nombre"], row["id"])
        self.expiry = QLineEdit()
        self.expiry.setPlaceholderText("AAAA-MM-DD · opcional")
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Observaciones para el cliente")
        self.notes.setMinimumHeight(115)
        self.conditions = QTextEdit()
        self.conditions.setPlaceholderText("Condiciones comerciales de esta propuesta")
        self.conditions.setMinimumHeight(115)
        form.addRow("Cliente *", self.customer)
        form.addRow("Vigencia hasta", self.expiry)
        form.addRow("Observaciones", self.notes)
        form.addRow("Condiciones", self.conditions)
        layout.addLayout(form)

        section = QHBoxLayout()
        section.addWidget(QLabel("Conceptos de la propuesta"), 1)
        self.add_line_button = QPushButton("＋ Agregar concepto")
        self.add_line_button.setObjectName("primaryButton")
        self.edit_line_button = QPushButton("Editar concepto")
        self.remove_line_button = QPushButton("Retirar concepto")
        section.addWidget(self.add_line_button)
        section.addWidget(self.edit_line_button)
        section.addWidget(self.remove_line_button)
        layout.addLayout(section)
        self.lines_table = build_table(
            ["Descripción", "Cantidad", "Precio unitario", "Subtotal"],
            column_widths=[390, 100, 180, 180], flexible_column=0,
        )
        self.lines_table.setMinimumHeight(240)
        self.lines_table.setWordWrap(True)
        self.lines_table.cellDoubleClicked.connect(lambda *_: self._edit_line())
        layout.addWidget(self.lines_table)
        self.total_label = QLabel("Total: $ 0 COP")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total_label.setStyleSheet("font-size: 17pt; font-weight: 700;")
        layout.addWidget(self.total_label)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar borrador")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

        self._lines: list[dict] = []
        self.add_line_button.clicked.connect(self._add_line)
        self.edit_line_button.clicked.connect(self._edit_line)
        self.remove_line_button.clicked.connect(self._remove_line)
        self.lines_table.itemSelectionChanged.connect(self._sync_line_actions)
        if proposal:
            self.customer.setCurrentIndex(self.customer.findData(proposal["cliente_id"]))
            self.expiry.setText(proposal["vence_el"] or "")
            self.notes.setPlainText(proposal["notas"])
            self.conditions.setPlainText(proposal.get("condiciones", ""))
            self._lines = [
                {"id": line["id"], "description": line["descripcion"],
                 "quantity": line["cantidad"], "unit_price_cop": line["precio_unitario_cop"],
                 "product_id": line["producto_id"],
                 "historical_cost_cop": line["costo_unitario_historico_cop"]}
                for line in proposal["lineas"]
            ]
        self.customer.currentIndexChanged.connect(self._mark_dirty)
        self.expiry.textChanged.connect(self._mark_dirty)
        self.notes.textChanged.connect(self._mark_dirty)
        self.conditions.textChanged.connect(self._mark_dirty)
        self._render_lines()

    def _mark_dirty(self, *_args) -> None:
        self._dirty = True
        self.error.clear()

    def _add_line(self) -> None:
        dialog = ProposalLineDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.line:
            self._lines.append(dialog.line)
            self._dirty = True
            self._render_lines()

    def _edit_line(self) -> None:
        row = self.lines_table.currentRow()
        if row < 0:
            return
        dialog = ProposalLineDialog(self, line=self._lines[row])
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.line:
            dialog.line["id"] = self._lines[row].get("id")
            dialog.line["product_id"] = self._lines[row].get("product_id")
            dialog.line["historical_cost_cop"] = self._lines[row].get("historical_cost_cop")
            self._lines[row] = dialog.line
            self._dirty = True
            self._render_lines()
            self.lines_table.selectRow(row)

    def _remove_line(self) -> None:
        row = self.lines_table.currentRow()
        if row >= 0:
            del self._lines[row]
            self._dirty = True
            self._render_lines()

    def _render_lines(self) -> None:
        self.lines_table.setRowCount(len(self._lines))
        total = 0
        for row, line in enumerate(self._lines):
            subtotal = line["quantity"] * line["unit_price_cop"]
            total += subtotal
            for column, value in enumerate((
                line["description"], line["quantity"],
                format_cop(line["unit_price_cop"]), format_cop(subtotal),
            )):
                set_cell(self.lines_table, row, column, value)
        self.lines_table.resizeRowsToContents()
        for row in range(self.lines_table.rowCount()):
            self.lines_table.setRowHeight(row, max(54, self.lines_table.rowHeight(row)))
        self.total_label.setText(f"Total: {format_cop(total)}")
        self._sync_line_actions()

    def _sync_line_actions(self) -> None:
        selected = self.lines_table.currentRow() >= 0
        self.edit_line_button.setEnabled(selected)
        self.remove_line_button.setEnabled(selected)

    def _save(self) -> None:
        try:
            customer_id = self.customer.currentData()
            if customer_id is None:
                raise ValueError("Registra o selecciona un cliente antes de crear una propuesta.")
            values = dict(
                expires_on=self.expiry.text().strip() or None,
                notes=self.notes.toPlainText(), conditions=self.conditions.toPlainText(),
            )
            if self.proposal:
                self.created_record = self.service.update_proposal(
                    self.proposal["id"], customer_id, self._lines, **values
                )
            else:
                self.created_record = self.service.create_proposal(customer_id, self._lines, **values)
        except (ValueError, ServiceError) as error:
            self.error.setText(str(error))
            return
        except sqlite3.Error:
            self.error.setText("No se pudo guardar en la base local. Tus datos siguen en el formulario; inténtalo de nuevo.")
            return
        self.accept()

    def reject(self) -> None:
        if self._dirty:
            answer = QMessageBox.question(
                self, "Descartar propuesta", "Hay cambios sin guardar. ¿Quieres descartarlos?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
        super().reject()


class ProposalDetailsDialog(QDialog):
    changed = False

    def __init__(self, service, customers: list[dict], proposal_id: int, parent=None,
                 *, sales_service=None) -> None:
        super().__init__(parent)
        self.service = service
        self.customers = customers
        self.proposal_id = proposal_id
        self.sales_service = sales_service
        self.conversion_key = uuid4().hex
        self.changed = False
        self.setMinimumSize(760, 580)
        self.resize(1000, 760)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content_widget = QWidget()
        self.content = QVBoxLayout()
        content_widget.setLayout(self.content)
        scroll.setWidget(content_widget)
        outer.addWidget(scroll, 1)
        self.actions = QHBoxLayout()
        outer.addLayout(self.actions)
        self._render()

    def _render(self) -> None:
        while self.content.count():
            item = self.content.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        proposal = self.service.get_proposal(self.proposal_id)
        self.proposal = proposal
        self.setWindowTitle(f"Propuesta {proposal['codigo']}")
        heading = QLabel(f"{proposal['codigo']}  ·  {_STATUS_LABELS[proposal['estado']]}")
        heading.setStyleSheet("font-size: 18pt; font-weight: 700;")
        self.content.addWidget(heading)
        info = QLabel(
            f"Cliente: {proposal['cliente_nombre']}\n"
            f"Creada: {format_local_datetime(proposal['creada_en_utc'])}\n"
            f"Vigencia: {proposal['vence_el'] or 'Sin fecha de vencimiento'}\n"
            f"Observaciones: {proposal['notas'] or '—'}\n"
            f"Condiciones: {proposal.get('condiciones', '') or '—'}"
        )
        info.setWordWrap(True)
        self.content.addWidget(info)
        table = build_table(["Descripción", "Cantidad", "Precio unitario", "Subtotal"],
                            column_widths=[390, 100, 180, 180], flexible_column=0)
        table.setMinimumHeight(220)
        table.setRowCount(len(proposal["lineas"]))
        for row, line in enumerate(proposal["lineas"]):
            values = (line["descripcion"], line["cantidad"], format_cop(line["precio_unitario_cop"]),
                      format_cop(line["cantidad"] * line["precio_unitario_cop"]))
            for column, value in enumerate(values):
                set_cell(table, row, column, value)
        table.resizeRowsToContents()
        for row in range(table.rowCount()):
            table.setRowHeight(row, max(54, table.rowHeight(row)))
        self.content.addWidget(table, 1)
        total = QLabel(f"Total: {format_cop(proposal['total_cop'])}")
        total.setAlignment(Qt.AlignmentFlag.AlignRight)
        total.setStyleSheet("font-size: 17pt; font-weight: 700;")
        self.content.addWidget(total)
        history = self.service.proposal_history(self.proposal_id)
        history_table = build_table(["Evento", "Estado", "Fecha", "Detalle"],
                                    column_widths=[180, 140, 220, 320], flexible_column=3)
        history_table.setMinimumHeight(150)
        history_table.setRowCount(len(history))
        for row, event in enumerate(history):
            label = {
                "historial_inicial": "Estado histórico inicial",
                "creada": "Creación",
                "editada": "Edición",
                "estado_cambiado": "Cambio de estado",
            }[event["evento"]]
            values = (label, _STATUS_LABELS[event["estado_nuevo"]], format_local_datetime(event["creado_en_utc"]), event["detalle"] or "—")
            for column, value in enumerate(values):
                set_cell(history_table, row, column, value)
            history_table.setRowHeight(row, max(48, history_table.rowHeight(row)))
        self.content.addWidget(QLabel("Historial de actividad"))
        self.content.addWidget(history_table)

        if proposal["estado"] == "borrador":
            edit = QPushButton("Editar borrador")
            edit.clicked.connect(self._edit)
            self.actions.addWidget(edit)
        next_states = {
            "borrador": [("enviada", "Marcar enviada"), ("cancelada", "Cancelar borrador")],
            "enviada": [("aceptada", "Registrar aceptación"), ("rechazada", "Registrar rechazo"),
                        ("vencida", "Marcar vencida"), ("cancelada", "Cancelar")],
        }.get(proposal["estado"], [])
        if proposal["estado"] == "enviada":
            today_local = datetime.now(timezone.utc).astimezone(_BOGOTA).date().isoformat()
            if not proposal["vence_el"] or proposal["vence_el"] > today_local:
                next_states = [action for action in next_states if action[0] != "vencida"]
        for state, label in next_states:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, state=state: self._transition(state))
            self.actions.addWidget(button)
        if proposal["estado"] == "aceptada" and self.sales_service is not None:
            convert = QPushButton("Convertir en venta")
            convert.setObjectName("primaryButton")
            convert.clicked.connect(self._convert_to_sale)
            self.actions.addWidget(convert)
        self.actions.addStretch(1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        self.actions.addWidget(close)

    def _edit(self) -> None:
        dialog = ProposalDialog(self.service, self.customers, self, proposal=self.proposal)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.changed = True
            self._render()

    def _transition(self, state: str) -> None:
        answer = QMessageBox.question(
            self, "Confirmar estado", f"¿Confirmas registrar la propuesta como {_STATUS_LABELS[state].lower()}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.transition_proposal(self.proposal_id, state)
            self.changed = True
            self._render()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo actualizar la propuesta", str(error))

    def _convert_to_sale(self) -> None:
        if self.proposal["estado"] != "aceptada" or self.sales_service is None:
            return
        inventory_lines = [
            f"• {line['descripcion']} × {line['cantidad']}"
            for line in self.proposal["lineas"] if line["producto_id"] is not None
        ]
        details = "\n".join(
            f"• {line['descripcion']} × {line['cantidad']} · {format_cop(line['precio_unitario_cop'])} c/u"
            for line in self.proposal["lineas"]
        )
        stock = ("\n\nUnidades que se descontarán del inventario:\n" + "\n".join(inventory_lines)
                 if inventory_lines else "\n\nLa propuesta no contiene productos inventariables.")
        answer = QMessageBox.question(
            self, "Convertir propuesta aceptada",
            f"Cliente: {self.proposal['cliente_nombre']}\nPropuesta: {self.proposal['codigo']}\n\n"
            f"Conceptos:\n{details}\n\nTotal: {format_cop(self.proposal['total_cop'])}{stock}\n\n"
            "La conversión crea una venta confirmada y no se puede deshacer desde esta versión. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            sale = self.sales_service.convert_accepted_proposal(
                self.proposal_id, idempotency_key=self.conversion_key
            )
            self.changed = True
            QMessageBox.information(self, "Propuesta convertida", f"Venta {sale['codigo']} creada correctamente.")
            self._render()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo convertir la propuesta", str(error))


class ProposalPage(QWidget):
    request_details = Signal(int)
    request_create = Signal()

    def __init__(self, service, customer_service, parent=None, *, sales_service=None) -> None:
        super().__init__(parent)
        self.service = service
        self.customer_service = customer_service
        self.sales_service = sales_service
        self.page_size = 100
        self.offset = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 28)
        layout.setSpacing(16)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por código o cliente…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(460)
        tools.addWidget(self.search)
        self.state_filter = QComboBox()
        self.state_filter.addItem("Todos los estados", None)
        for key, label in _STATUS_LABELS.items():
            self.state_filter.addItem(label, key)
        tools.addWidget(self.state_filter)
        tools.addStretch(1)
        self.page_label = QLabel()
        self.page_label.setObjectName("muted")
        tools.addWidget(self.page_label)
        self.details_button = QPushButton("Ver detalle")
        self.details_button.setEnabled(False)
        tools.addWidget(self.details_button)
        self.previous = QPushButton("‹  Anterior")
        self.next = QPushButton("Siguiente  ›")
        tools.addWidget(self.previous)
        tools.addWidget(self.next)
        layout.addLayout(tools)
        self.table = build_table(
            ["Código", "Cliente", "Creada", "Vigencia", "Total", "Estado"],
            column_widths=[175, 300, 210, 150, 190, 150], flexible_column=1,
        )
        self.table.setMinimumHeight(320)
        self.empty = EmptyState(
            "Aún no hay propuestas", "Crea una propuesta para consultar y enviar conceptos y condiciones al cliente.",
            action_text="Crear primera propuesta", action=self.request_create.emit,
        )
        from PySide6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.table)
        layout.addWidget(self.stack, 1)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._search_changed)
        self.state_filter.currentIndexChanged.connect(self._filter_changed)
        self.previous.clicked.connect(self.previous_page)
        self.next.clicked.connect(self.next_page)
        self.details_button.clicked.connect(self._open_selected)
        self.table.cellDoubleClicked.connect(lambda *_: self._open_selected())
        self.table.itemSelectionChanged.connect(lambda: self.details_button.setEnabled(bool(self.table.selectionModel().selectedRows())))
        self.refresh()

    def _search_changed(self, _value: str) -> None:
        self.offset = 0
        self.search_timer.start()

    def _filter_changed(self, _index: int) -> None:
        self.offset = 0
        self.refresh()

    def previous_page(self) -> None:
        self.offset = max(0, self.offset - self.page_size)
        self.refresh()

    def next_page(self) -> None:
        self.offset += self.page_size
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.service.list_proposals(
                search=self.search.text(), state=self.state_filter.currentData(),
                limit=self.page_size + 1, offset=self.offset,
            )
        except (ServiceError, sqlite3.Error, OSError) as error:
            self.empty.title_label.setText("No se pudieron cargar las propuestas")
            self.empty.description_label.setText(str(error) if isinstance(error, ServiceError) else "Revisa el acceso a la base local e inténtalo de nuevo.")
            self.stack.setCurrentWidget(self.empty)
            return
        has_next = len(rows) > self.page_size
        rows = rows[:self.page_size]
        self.table.setRowCount(len(rows))
        for row, proposal in enumerate(rows):
            values = (proposal["codigo"], proposal["cliente_nombre"], format_local_datetime(proposal["creada_en_utc"]),
                      proposal["vence_el"] or "Sin vencimiento", format_cop(proposal["total_cop"]),
                      _STATUS_LABELS[proposal["estado"]])
            for column, value in enumerate(values):
                set_cell(self.table, row, column, value)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, proposal["id"])
            self.table.setRowHeight(row, max(48, self.table.rowHeight(row)))
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(has_next)
        self.page_label.setText(f"{self.offset + 1}–{self.offset + len(rows)}" if rows else "")
        if rows:
            self.stack.setCurrentWidget(self.table)
        else:
            if self.search.text().strip() or self.state_filter.currentData():
                self.empty.title_label.setText("No hay propuestas coincidentes")
                self.empty.description_label.setText("Prueba otro código, cliente o estado.")
            else:
                self.empty.title_label.setText("Aún no hay propuestas")
                self.empty.description_label.setText("Crea una propuesta para consultar y enviar conceptos y condiciones al cliente.")
            self.stack.setCurrentWidget(self.empty)
        self.details_button.setEnabled(bool(rows) and bool(self.table.selectionModel().selectedRows()))

    def _selected_id(self) -> int | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _open_selected(self) -> None:
        proposal_id = self._selected_id()
        if proposal_id is not None:
            self.request_details.emit(proposal_id)

    def create_dialog(self, parent=None) -> bool:
        customers = self.customer_service.list_customers(limit=500)
        dialog = ProposalDialog(self.service, customers, parent)
        created = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_record if created else None
        return created

    def open_details(self, proposal_id: int, parent=None) -> bool:
        customers = self.customer_service.list_customers(limit=500)
        dialog = ProposalDetailsDialog(self.service, customers, proposal_id, parent,
                                       sales_service=self.sales_service)
        dialog.exec()
        return dialog.changed
