"""Detalle técnico de una orden y sus cambios de estado."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
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
        self.technician = QLineEdit()
        self.technician.setPlaceholderText("Técnico asignado (opcional)")
        self.diagnosis.textChanged.connect(self._mark_dirty)
        self.work.textChanged.connect(self._mark_dirty)
        self.technician.textChanged.connect(self._mark_dirty)
        form = QFormLayout()
        form.addRow("Problema reportado", self.problem)
        form.addRow("Diagnóstico", self.diagnosis)
        form.addRow("Trabajo realizado", self.work)
        form.addRow("Técnico", self.technician)
        technical_section, technical_layout = self._section("Problema, diagnóstico y trabajo")
        technical_layout.addLayout(form)
        content_layout.addWidget(technical_section)

        self.save_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Save)
        self.save_button.button(QDialogButtonBox.StandardButton.Save).setText("Guardar datos técnicos")
        self.save_button.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        self.save_button.accepted.connect(self._save_technical)
        technical_layout.addWidget(self.save_button)

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

        self.history = build_table(["Estado anterior", "Estado nuevo", "Fecha", "Motivo"])
        self.history.setMinimumHeight(220)
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
        self.technician.setText(order["tecnico"])

        editable = order["estado"] not in {"entregada", "cancelada"}
        self.diagnosis.setReadOnly(not editable)
        self.work.setReadOnly(not editable)
        self.technician.setReadOnly(not editable)
        self.save_button.setVisible(editable)

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
        elif not can_change and order["estado"] == "en_proceso" and not order["trabajo_realizado"].strip():
            self.next_state.setItemText(0, "Sin transición disponible")
            self.transition_hint.setText("Guarda el trabajo realizado antes de marcar la orden como lista.")
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
        self._dirty = False
        self._loading = False

    def _mark_dirty(self, *_args) -> None:
        if not self._loading:
            self._dirty = True

    def _confirm_discard_if_dirty(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Descartar cambios técnicos",
            "Hay datos técnicos sin guardar. ¿Quieres descartarlos?",
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
        label = _STATE_LABELS.get(new_state, new_state)
        answer = QMessageBox.question(
            self,
            "Confirmar cambio de estado",
            f"¿Confirmas cambiar la orden a «{label}»?",
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
                technician=self.technician.text(),
            )
            self.changed = True
            self.reason.clear()
            self._reload()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo cambiar el estado", str(error))
