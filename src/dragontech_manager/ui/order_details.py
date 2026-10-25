"""Detalle técnico de una orden y sus cambios de estado."""

import sqlite3

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from dragontech_manager.services.errors import ServiceError
from .pages import format_cop, format_local_datetime
from .widgets import build_table, set_cell

_STATE_LABELS = {
    "recibida": "Recibida (pendiente)",
    "diagnostico": "Diagnóstico (pendiente)",
    "espera_aprobacion": "Espera aprobación",
    "en_proceso": "En proceso",
    "lista": "Lista",
    "entregada": "Entregada",
    "cancelada": "Cancelada",
}


class OrderDetailDialog(QDialog):
    def __init__(self, service, order_id: int, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.order_id = order_id
        self.changed = False
        self._dirty = False
        self._loading = False
        self.setMinimumSize(700, 560)
        self.resize(1000, 820)
        self.order: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        self.heading = QLabel("Detalle de orden")
        self.heading.setStyleSheet("font-size: 18pt; font-weight: 700;")
        root.addWidget(self.heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 8, 8)
        content_layout.setSpacing(20)

        summary = QFormLayout()
        summary.setHorizontalSpacing(18)
        summary.setVerticalSpacing(7)
        self.customer_label = QLabel()
        self.equipment_label = QLabel()
        self.received_label = QLabel()
        self.status_label = QLabel()
        self.delivery_label = QLabel()
        self.price_label = QLabel()
        for label in (
            self.customer_label,
            self.equipment_label,
            self.received_label,
            self.status_label,
            self.delivery_label,
            self.price_label,
        ):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
        summary.addRow("Cliente solicitante", self.customer_label)
        summary.addRow("Equipo / propietario", self.equipment_label)
        summary.addRow("Recibida", self.received_label)
        summary.addRow("Estado", self.status_label)
        summary.addRow("Fecha de entrega", self.delivery_label)
        summary.addRow("Precio acordado", self.price_label)
        general_section, general_layout = self._section("Información general")
        general_layout.addLayout(summary)
        content_layout.addWidget(general_section)

        self.problem = self._text_field(read_only=True, height=140)
        self.diagnosis = self._text_field(height=150)
        self.work = self._text_field(height=170)
        self.tests = self._text_field(height=150)
        self.technician = QLineEdit()
        self.technician.setPlaceholderText("Técnico asignado (opcional)")
        self.diagnosis.textChanged.connect(self._mark_dirty)
        self.work.textChanged.connect(self._mark_dirty)
        self.tests.textChanged.connect(self._mark_dirty)
        self.technician.textChanged.connect(self._mark_dirty)
        form = QFormLayout()
        form.addRow("Problema reportado", self.problem)
        form.addRow("Diagnóstico", self.diagnosis)
        form.addRow("Trabajo realizado / reparación", self.work)
        form.addRow("Pruebas realizadas", self.tests)
        form.addRow("Técnico", self.technician)
        technical_section, technical_layout = self._section("Problema, diagnóstico y trabajo")
        technical_layout.addLayout(form)
        content_layout.addWidget(technical_section)

        self.save_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Save)
        self.save_button.button(QDialogButtonBox.StandardButton.Save).setText("Guardar datos técnicos")
        self.save_button.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        self.save_button.accepted.connect(self._save_technical)
        technical_layout.addWidget(self.save_button)

        additional_section, additional_layout = self._section(
            "Servicios adicionales y aprobación del cliente"
        )
        self.additional_hint = QLabel(
            "Cada propuesta conserva su precio y sus decisiones. La nota registra lo indicado por el usuario; "
            "no verifica por sí sola la identidad del cliente."
        )
        self.additional_hint.setObjectName("muted")
        self.additional_hint.setWordWrap(True)
        additional_layout.addWidget(self.additional_hint)
        proposal_form = QFormLayout()
        self.proposal_description = self._text_field(height=120)
        self.proposal_description.setPlaceholderText(
            "Describe el trabajo o repuesto adicional propuesto"
        )
        self.proposal_amount = QLineEdit("0")
        self.proposal_amount.setPlaceholderText("Importe en pesos colombianos")
        self.proposal_amount.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,19}"), self.proposal_amount)
        )
        proposal_form.addRow("Descripción propuesta", self.proposal_description)
        proposal_form.addRow("Precio propuesto (COP)", self.proposal_amount)
        additional_layout.addLayout(proposal_form)
        self.propose_button = QPushButton("Registrar propuesta para el cliente")
        self.propose_button.setObjectName("primaryButton")
        self.propose_button.clicked.connect(self._propose_additional_service)
        additional_layout.addWidget(self.propose_button)

        self.additional_table = build_table(
            ["Servicio propuesto", "Precio", "Decisión", "Fecha", "Nota"],
            column_widths=[280, 150, 150, 190, 260],
            flexible_column=0,
        )
        self.additional_table.setMinimumHeight(260)
        self.additional_table.itemSelectionChanged.connect(self._load_selected_additional_history)
        additional_layout.addWidget(self.additional_table)
        additional_layout.addWidget(QLabel("Nota de confirmación indicada por el cliente"))
        self.decision_evidence = self._text_field(height=110)
        self.decision_evidence.setPlaceholderText(
            "Indica cuándo y por qué medio se comunicó la decisión (por ejemplo, llamada o WhatsApp)."
        )
        additional_layout.addWidget(self.decision_evidence)
        decision_actions = QHBoxLayout()
        self.approve_additional_button = QPushButton("Registrar aprobación")
        self.approve_additional_button.setObjectName("primaryButton")
        self.reject_additional_button = QPushButton("Registrar rechazo")
        self.approve_additional_button.clicked.connect(
            lambda: self._decide_additional_service("aprobado")
        )
        self.reject_additional_button.clicked.connect(
            lambda: self._decide_additional_service("rechazado")
        )
        decision_actions.addWidget(self.approve_additional_button)
        decision_actions.addWidget(self.reject_additional_button)
        decision_actions.addStretch(1)
        additional_layout.addLayout(decision_actions)
        additional_layout.addWidget(QLabel("Historial de decisiones de la propuesta seleccionada"))
        self.additional_history = build_table(["Decisión", "Fecha", "Nota registrada"])
        self.additional_history.setMinimumHeight(160)
        additional_layout.addWidget(self.additional_history)
        content_layout.addWidget(additional_section)
        self.proposal_description.textChanged.connect(self._mark_dirty)
        self.proposal_amount.textChanged.connect(self._mark_dirty)
        self.decision_evidence.textChanged.connect(self._mark_dirty)

        state_row = QHBoxLayout()
        self.next_state = QComboBox()
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Motivo opcional del cambio")
        self.transition_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply)
        self.transition_button.button(QDialogButtonBox.StandardButton.Apply).setText("Cambiar estado")
        self.transition_button.button(QDialogButtonBox.StandardButton.Apply).setObjectName("primaryButton")
        self.transition_button.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._change_state
        )
        state_row.addWidget(QLabel("Siguiente estado"))
        state_row.addWidget(self.next_state, 1)
        state_row.addWidget(self.reason, 2)
        state_row.addWidget(self.transition_button)
        status_section, status_layout = self._section("Estado de la orden")
        status_layout.addLayout(state_row)
        self.transition_hint = QLabel()
        self.transition_hint.setObjectName("muted")
        self.transition_hint.setWordWrap(True)
        status_layout.addWidget(self.transition_hint)
        content_layout.addWidget(status_section)

        self.history = build_table(
            ["Estado anterior", "Estado nuevo", "Fecha", "Motivo"],
            column_widths=[190, 190, 220, 360],
            flexible_column=3,
        )
        self.history.setMinimumHeight(280)
        self.history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.history.setWordWrap(True)
        self.history.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.history.verticalHeader().setMinimumSectionSize(54)
        self.history.verticalHeader().setDefaultSectionSize(54)
        self.history.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.history.horizontalHeader().setMinimumHeight(46)
        history_section, history_layout = self._section("Historial de estados")
        history_layout.addWidget(self.history)
        content_layout.addWidget(history_section)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_buttons.rejected.connect(self.reject)
        root.addWidget(self.close_buttons)
        self._reload()

    @staticmethod
    def _text_field(*, read_only: bool = False, height: int = 68) -> QPlainTextEdit:
        field = QPlainTextEdit()
        field.setReadOnly(read_only)
        field.setMinimumHeight(height)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        field.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        return field

    @staticmethod
    def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame()
        section.setProperty("role", "surface")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 13pt; font-weight: 700;")
        layout.addWidget(heading)
        return section, layout

    def _reload(self) -> None:
        self._loading = True
        self.order = self.service.get_order_detail(self.order_id)
        order = self.order
        self.setWindowTitle(f"Orden {order['codigo']}")
        self.heading.setText(f"Orden {order['codigo']}")
        self.customer_label.setText(
            " ".join(
                value
                for value in (
                    order["cliente_solicitante_nombre"],
                    order["cliente_whatsapp"] or order["cliente_telefono"],
                )
                if value
            )
        )
        equipment = " · ".join(
            value
            for value in (
                order["equipo_codigo"],
                order["equipo_tipo"],
                " ".join(value for value in (order["equipo_marca"], order["equipo_modelo"]) if value),
                order["equipo_serial"],
                f"Propietario: {order['propietario_nombre']}",
            )
            if value
        )
        self.equipment_label.setText(equipment)
        self.received_label.setText(format_local_datetime(order["recibido_en_utc"]))
        self.status_label.setText(_STATE_LABELS.get(order["estado"], order["estado"]))
        self.delivery_label.setText(order["fecha_entrega"] or "Sin fecha registrada")
        self.price_label.setText(format_cop(order["importe_acordado_cop"]))
        self.problem.setPlainText(order["problema_reportado"])
        self.diagnosis.setPlainText(order["diagnostico"])
        self.work.setPlainText(order["trabajo_realizado"])
        self.tests.setPlainText(order["pruebas_realizadas"])
        self.technician.setText(order["tecnico"])

        editable = order["estado"] not in {"entregada", "cancelada"}
        self.diagnosis.setReadOnly(not editable)
        self.work.setReadOnly(not editable)
        self.tests.setReadOnly(not editable)
        self.technician.setReadOnly(not editable)
        self.save_button.setVisible(editable)
        additional_phase = editable and order["estado"] in {"diagnostico", "espera_aprobacion"}
        self.proposal_description.setReadOnly(not additional_phase)
        self.proposal_amount.setReadOnly(not additional_phase)
        self.propose_button.setEnabled(additional_phase and bool(order["diagnostico"].strip()))
        self.decision_evidence.setReadOnly(not additional_phase)

        next_states = self.service.allowed_next_states(self.order_id)
        self.next_state.clear()
        self.next_state.addItem("Selecciona una transición…", None)
        placeholder_item = self.next_state.model().item(0)
        if placeholder_item is not None:
            placeholder_item.setEnabled(False)
        for state in next_states:
            self.next_state.addItem(_STATE_LABELS.get(state, state), state)
        can_change = editable and bool(next_states)
        self.next_state.setEnabled(can_change)
        self.reason.setEnabled(can_change)
        self.transition_button.button(QDialogButtonBox.StandardButton.Apply).setEnabled(can_change)
        if not editable:
            self.next_state.setItemText(0, "Orden cerrada: no admite transiciones")
            self.transition_hint.setText("Las órdenes entregadas o canceladas son estados terminales.")
        elif not can_change and order["estado"] == "recibida":
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText(
                "Avanza a diagnóstico para registrar hallazgos antes de iniciar la reparación."
            )
        elif not can_change and order["estado"] == "diagnostico" and not order["diagnostico"].strip():
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText(
                "Guarda el diagnóstico antes de iniciar la reparación o solicitar aprobación."
            )
        elif not can_change and order["estado"] == "espera_aprobacion" and not order["diagnostico"].strip():
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText("Guarda el diagnóstico antes de iniciar la reparación.")
        elif not can_change and order["estado"] in {"diagnostico", "espera_aprobacion"} and any(
            row["estado"] == "pendiente"
            for row in self.service.list_additional_services(self.order_id)
        ):
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText(
                "Registra la aprobación o el rechazo de los servicios adicionales pendientes para continuar."
            )
        elif not can_change and order["estado"] == "en_proceso" and any(
            row["estado"] == "pendiente"
            for row in self.service.list_additional_services(self.order_id)
        ):
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText(
                "Hay servicios adicionales pendientes que deben resolverse antes de avanzar."
            )
        elif not can_change and order["estado"] == "en_proceso" and not order["trabajo_realizado"].strip():
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText(
                "Guarda el trabajo realizado y las pruebas antes de marcar la orden como lista."
            )
        elif not can_change and order["estado"] == "en_proceso" and not order["pruebas_realizadas"].strip():
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText(
                "Registra las pruebas realizadas antes de marcar la orden como lista."
            )
        elif order["estado"] == "diagnostico" and not next_states:
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText("Hay servicios adicionales pendientes de decisión antes de continuar.")
        elif order["estado"] == "espera_aprobacion" and not next_states:
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText("Registra la aprobación o el rechazo de los servicios adicionales para continuar.")
        else:
            next_labels = ", ".join(_STATE_LABELS.get(state, state) for state in next_states)
            self.transition_hint.setText(
                f"Estado actual: {_STATE_LABELS.get(order['estado'], order['estado'])}. "
                f"Transición{'es' if len(next_states) != 1 else ''} permitida{'s' if len(next_states) != 1 else ''}: {next_labels}."
            )

        events = self.service.get_status_history(self.order_id)
        self.history.setRowCount(len(events))
        for row, event in enumerate(events):
            previous = _STATE_LABELS.get(event["estado_anterior"], event["estado_anterior"]) if event["estado_anterior"] else "Inicio"
            values = (
                previous,
                _STATE_LABELS.get(event["estado_nuevo"], event["estado_nuevo"]),
                format_local_datetime(event["cambiado_en_utc"]),
                event["motivo"] or "—",
            )
            for column, value in enumerate(values):
                set_cell(self.history, row, column, value)
        self.history.resizeRowsToContents()
        for row in range(self.history.rowCount()):
            self.history.setRowHeight(row, max(54, self.history.rowHeight(row)))
        self._reload_additional_services()
        self._dirty = self._has_unsaved_additional_input()
        self._loading = False

    def _refresh_after_additional_operation(self) -> None:
        old_order = self.order
        technical_values = (
            self.diagnosis.toPlainText(),
            self.work.toPlainText(),
            self.tests.toPlainText(),
            self.technician.text(),
        )
        technical_dirty = technical_values != (
            old_order["diagnostico"],
            old_order["trabajo_realizado"],
            old_order["pruebas_realizadas"],
            old_order["tecnico"],
        )
        self._reload()
        if technical_dirty:
            self.diagnosis.setPlainText(technical_values[0])
            self.work.setPlainText(technical_values[1])
            self.tests.setPlainText(technical_values[2])
            self.technician.setText(technical_values[3])
        self._dirty = technical_dirty or self._has_unsaved_additional_input()

    def _reload_additional_services(self) -> None:
        entries = self.service.list_additional_services(self.order_id)
        self.additional_table.blockSignals(True)
        self.additional_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            decided_at = format_local_datetime(entry["decidido_en_utc"])
            values = (
                entry["descripcion"],
                format_cop(entry["importe_propuesto_cop"]),
                {
                    "pendiente": "Pendiente de decisión",
                    "aprobado": "Aprobado",
                    "rechazado": "Rechazado",
                }[entry["estado"]],
                decided_at,
                entry["evidencia"] or "—",
            )
            for column, value in enumerate(values):
                set_cell(self.additional_table, row, column, value)
            self.additional_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, entry["id"])
        if entries:
            pending_row = next(
                (index for index, entry in enumerate(entries) if entry["estado"] == "pendiente"),
                0,
            )
            self.additional_table.selectRow(pending_row)
        self.additional_table.blockSignals(False)
        self._load_selected_additional_history()

    def _selected_additional_id(self) -> int | None:
        row = self.additional_table.currentRow()
        if row < 0 or self.additional_table.item(row, 0) is None:
            return None
        return self.additional_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _load_selected_additional_history(self) -> None:
        additional_id = self._selected_additional_id()
        entries = self.service.list_additional_services(self.order_id)
        selected = next((row for row in entries if row["id"] == additional_id), None)
        can_decide = bool(
            selected
            and selected["estado"] == "pendiente"
            and self.order["estado"] in {"diagnostico", "espera_aprobacion"}
        )
        self.approve_additional_button.setEnabled(can_decide)
        self.reject_additional_button.setEnabled(can_decide)

        history = (
            self.service.list_additional_decision_history(additional_id)
            if additional_id is not None
            else []
        )
        self.additional_history.setRowCount(len(history))
        for row, event in enumerate(history):
            values = (
                "Aprobado" if event["decision"] == "aprobado" else "Rechazado",
                format_local_datetime(event["decidido_en_utc"]),
                event["evidencia"],
            )
            for column, value in enumerate(values):
                set_cell(self.additional_history, row, column, value)
        self.additional_history.resizeRowsToContents()

    def _propose_additional_service(self) -> None:
        try:
            amount = int(self.proposal_amount.text())
            self.service.propose_additional_service(
                self.order_id,
                self.proposal_description.toPlainText(),
                amount,
            )
            self.changed = True
            self.proposal_description.clear()
            self.proposal_amount.setText("0")
            self._refresh_after_additional_operation()
        except (ValueError, ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo registrar la propuesta", str(error))

    def _decide_additional_service(self, decision: str) -> None:
        additional_id = self._selected_additional_id()
        if additional_id is None:
            return
        label = "aprobar" if decision == "aprobado" else "rechazar"
        answer = QMessageBox.question(
            self,
            "Confirmar decisión del cliente",
            f"¿Confirmas registrar que el cliente indicó {label} este servicio adicional?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.decide_additional_service(
                additional_id,
                decision,
                self.decision_evidence.toPlainText(),
            )
            self.changed = True
            self.decision_evidence.clear()
            self._refresh_after_additional_operation()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo registrar la decisión", str(error))

    def _mark_dirty(self, *_args) -> None:
        if not self._loading:
            self._dirty = True

    def _has_unsaved_additional_input(self) -> bool:
        return bool(
            self.proposal_description.toPlainText().strip()
            or self.decision_evidence.toPlainText().strip()
            or self.proposal_amount.text().strip() not in {"", "0"}
        )

    def _confirm_discard_if_dirty(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Descartar cambios técnicos",
            "Hay cambios o información sin guardar en el detalle. ¿Quieres descartarlos?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Discard

    def accept(self) -> None:
        if self._confirm_discard_if_dirty():
            super().accept()

    def reject(self) -> None:
        if self._confirm_discard_if_dirty():
            super().reject()

    def _save_technical(self) -> None:
        try:
            self.service.update_technical_details(
                self.order_id,
                diagnosis=self.diagnosis.toPlainText(),
                work_performed=self.work.toPlainText(),
                tests_performed=self.tests.toPlainText(),
                technician=self.technician.text(),
            )
            self.changed = True
            self._reload()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudieron guardar los datos", str(error))

    def _change_state(self) -> None:
        new_state = self.next_state.currentData()
        if not new_state:
            return
        if self._has_unsaved_additional_input():
            QMessageBox.warning(
                self,
                "Información adicional sin registrar",
                "Registra o descarta la propuesta o nota de decisión antes de cambiar el estado.",
            )
            return
        label = _STATE_LABELS.get(new_state, new_state)
        confirmation = f"¿Confirmas cambiar la orden a «{label}»?"
        if new_state == "entregada":
            confirmation = (
                "¿Confirmas registrar la entrega del equipo? Se guardarán la fecha comercial "
                "y el evento con marca de tiempo UTC en el historial."
            )
        answer = QMessageBox.question(
            self,
            "Confirmar cambio de estado",
            confirmation,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.transition_order(
                self.order_id,
                new_state,
                reason=self.reason.text(),
                diagnosis=self.diagnosis.toPlainText(),
                work_performed=self.work.toPlainText(),
                tests_performed=self.tests.toPlainText(),
                technician=self.technician.text(),
            )
            self.changed = True
            self.reason.clear()
            self._reload()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo cambiar el estado", str(error))
