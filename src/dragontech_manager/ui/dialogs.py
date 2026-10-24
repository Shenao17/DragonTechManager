"""Formularios breves conectados a los servicios de aplicación."""

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)
import sqlite3

from dragontech_manager.services.errors import ServiceError


class FormDialog(QDialog):
    def __init__(self, title: str, description: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(500)
        self.resize(560, 540)
        self._dirty = False
        self.created_record: dict | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(14)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 18pt; font-weight: 700;")
        outer.addWidget(heading)
        subtitle = QLabel(description)
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        self.form = QFormLayout()
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(13)
        outer.addLayout(self.form)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #F0A3A3; background: #382B2E; border-radius: 6px; padding: 9px;")
        self.error_label.hide()
        outer.addWidget(self.error_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.buttons.accepted.connect(self.submit)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

    def mark_dirty(self, *_args) -> None:
        self._dirty = True
        self.error_label.hide()

    def show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def reject(self) -> None:
        if self._dirty:
            answer = QMessageBox.question(
                self,
                "Descartar cambios",
                "El formulario tiene cambios sin guardar. ¿Quieres descartarlos?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
        super().reject()

    def submit(self) -> None:
        raise NotImplementedError


class CustomerDialog(FormDialog):
    def __init__(self, service, parent=None) -> None:
        super().__init__("Nuevo cliente", "Registra la información de contacto que DragonTech Care necesita.", parent)
        self.service = service
        self.name = QLineEdit()
        self.name.setPlaceholderText("Nombre completo o razón social")
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("Teléfono")
        self.whatsapp = QLineEdit()
        self.whatsapp.setPlaceholderText("WhatsApp")
        self.email = QLineEdit()
        self.email.setPlaceholderText("correo@ejemplo.com")
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("Notas opcionales")
        self.notes.setMaximumHeight(88)

        self.form.addRow("Nombre *", self.name)
        self.form.addRow("Teléfono", self.phone)
        self.form.addRow("WhatsApp", self.whatsapp)
        self.form.addRow("Correo", self.email)
        self.form.addRow("Notas", self.notes)
        for field in (self.name, self.phone, self.whatsapp, self.email):
            field.textChanged.connect(self.mark_dirty)
        self.notes.textChanged.connect(self.mark_dirty)
        self.name.setFocus()

    def submit(self) -> None:
        try:
            self.created_record = self.service.create_customer(
                self.name.text(),
                phone=self.phone.text(),
                whatsapp=self.whatsapp.text(),
                email=self.email.text(),
                notes=self.notes.toPlainText(),
            )
        except ServiceError as error:
            self.show_error(str(error))
            return
        except sqlite3.Error:
            self.show_error("No se pudo guardar en la base de datos. No se perdió la información existente; inténtalo de nuevo.")
            return
        self.accept()


class EquipmentDialog(FormDialog):
    def __init__(self, service, customers: list[dict], parent=None) -> None:
        super().__init__("Registrar equipo", "El código del equipo se asignará automáticamente al guardar.", parent)
        self.service = service
        self.customer = QComboBox()
        for customer in customers:
            self.customer.addItem(customer["nombre"], customer["id"])
        self.equipment_type = QLineEdit()
        self.equipment_type.setPlaceholderText("Ej. Portátil, torre, impresora")
        self.brand = QLineEdit()
        self.model = QLineEdit()
        self.serial = QLineEdit()
        self.specifications = QTextEdit()
        self.specifications.setMaximumHeight(72)
        self.accessories = QLineEdit()
        self.condition = QLineEdit()

        self.form.addRow("Cliente propietario *", self.customer)
        self.form.addRow("Tipo *", self.equipment_type)
        self.form.addRow("Marca", self.brand)
        self.form.addRow("Modelo", self.model)
        self.form.addRow("Serial", self.serial)
        self.form.addRow("Especificaciones", self.specifications)
        self.form.addRow("Accesorios recibidos", self.accessories)
        self.form.addRow("Estado físico", self.condition)

        self.customer.currentIndexChanged.connect(self.mark_dirty)
        for field in (self.equipment_type, self.brand, self.model, self.serial, self.accessories, self.condition):
            field.textChanged.connect(self.mark_dirty)
        self.specifications.textChanged.connect(self.mark_dirty)
        if not customers:
            self.customer.setEnabled(False)
            self.show_error("Primero registra un cliente para poder asociarle un equipo.")
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.equipment_type.setFocus()

    def submit(self) -> None:
        try:
            self.created_record = self.service.register_equipment(
                self.customer.currentData(),
                self.equipment_type.text(),
                brand=self.brand.text(),
                model=self.model.text(),
                serial=self.serial.text(),
                specifications=self.specifications.toPlainText(),
                accessories_received=self.accessories.text(),
                physical_condition=self.condition.text(),
            )
        except ServiceError as error:
            self.show_error(str(error))
            return
        except sqlite3.Error:
            self.show_error("No se pudo guardar en la base de datos. No se perdió la información existente; inténtalo de nuevo.")
            return
        self.accept()


class ServiceOrderDialog(FormDialog):
    def __init__(
        self,
        service,
        customers: list[dict],
        equipment: list[dict],
        parent=None,
    ) -> None:
        super().__init__(
            "Abrir orden de servicio",
            "El cliente es quien solicita esta visita. Puede ser distinto del propietario actual del equipo.",
            parent,
        )
        self.service = service
        self.customer = QComboBox()
        for row in customers:
            self.customer.addItem(row["nombre"], row["id"])
        self.equipment = QComboBox()
        for row in equipment:
            label = f"{row['codigo']} · {row['tipo']} · {row['cliente_nombre']}"
            self.equipment.addItem(label, row["id"])
        self.problem = QTextEdit()
        self.problem.setPlaceholderText("Describe el problema reportado por el cliente")
        self.problem.setMaximumHeight(100)
        self.amount = QLineEdit("0")
        self.amount.setPlaceholderText("0")
        self.amount.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,19}"), self.amount)
        )
        self.diagnosis = QTextEdit()
        self.diagnosis.setPlaceholderText("Opcional al recibir el equipo")
        self.diagnosis.setMaximumHeight(78)
        self.technician = QLineEdit()
        self.technician.setPlaceholderText("Opcional")

        self.form.addRow("Cliente solicitante *", self.customer)
        self.form.addRow("Equipo recibido *", self.equipment)
        self.form.addRow("Problema reportado *", self.problem)
        self.form.addRow("Precio inicial (COP)", self.amount)
        self.form.addRow("Diagnóstico", self.diagnosis)
        self.form.addRow("Técnico", self.technician)

        self.customer.currentIndexChanged.connect(self.mark_dirty)
        self.equipment.currentIndexChanged.connect(self.mark_dirty)
        self.problem.textChanged.connect(self.mark_dirty)
        self.amount.textChanged.connect(self.mark_dirty)
        self.diagnosis.textChanged.connect(self.mark_dirty)
        self.technician.textChanged.connect(self.mark_dirty)
        if not customers or not equipment:
            self.show_error("Registra al menos un cliente y un equipo antes de abrir una orden.")
            self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.problem.setFocus()

    def submit(self) -> None:
        amount_text = self.amount.text().strip()
        if not amount_text:
            amount_text = "0"
        try:
            amount = int(amount_text)
            self.created_record = self.service.open_service_order(
                self.customer.currentData(),
                self.equipment.currentData(),
                self.problem.toPlainText(),
                initial_amount_cop=amount,
                diagnosis=self.diagnosis.toPlainText(),
                technician=self.technician.text(),
            )
        except (ValueError, ServiceError) as error:
            self.show_error(str(error) or "Escribe un importe válido en pesos colombianos.")
            return
        except sqlite3.Error:
            self.show_error("No se pudo guardar en la base de datos. No se perdió la información existente; inténtalo de nuevo.")
            return
        self.accept()
