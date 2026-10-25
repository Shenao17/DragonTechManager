"""Formularios breves conectados a los servicios de aplicación."""

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import sqlite3

from dragontech_manager.services.errors import ServiceError


class FormDialog(QDialog):
    def __init__(self, title: str, description: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(680, 540)
        self.resize(820, 720)
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_content = QWidget()
        self.form = QFormLayout(form_content)
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(18)
        scroll.setWidget(form_content)
        outer.addWidget(scroll, 1)

        self.error_label = QLabel()
        self.error_label.setObjectName("formError")
        self.error_label.setWordWrap(True)
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
    def __init__(self, service, parent=None, *, customer: dict | None = None) -> None:
        editing = customer is not None
        super().__init__(
            "Editar cliente" if editing else "Nuevo cliente",
            "Actualiza los datos del cliente. El historial relacionado se conserva.",
            parent,
        )
        self.service = service
        self.customer_id = customer["id"] if customer else None
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
        self.notes.setMinimumHeight(130)
        self.notes.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        if customer:
            self.name.setText(customer["nombre"])
            self.phone.setText(customer["telefono"] or "")
            self.whatsapp.setText(customer["whatsapp"] or "")
            self.email.setText(customer["correo"] or "")
            self.notes.setPlainText(customer["notas"] or "")

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
            values = {
                "phone": self.phone.text(),
                "whatsapp": self.whatsapp.text(),
                "email": self.email.text(),
                "notes": self.notes.toPlainText(),
            }
            if self.customer_id is None:
                self.created_record = self.service.create_customer(self.name.text(), **values)
            else:
                self.created_record = self.service.update_customer(
                    self.customer_id, name=self.name.text(), **values
                )
        except ServiceError as error:
            self.show_error(str(error))
            return
        except sqlite3.Error:
            self.show_error("No se pudo guardar en la base de datos. No se perdió la información existente; inténtalo de nuevo.")
            return
        self.accept()


class EquipmentDialog(FormDialog):
    def __init__(
        self,
        service,
        customers: list[dict],
        parent=None,
        *,
        equipment: dict | None = None,
    ) -> None:
        editing = equipment is not None
        description = (
            f"Edita los datos actuales del equipo {equipment['codigo']}. El código público no se puede cambiar."
            if equipment
            else "El código del equipo se asignará automáticamente al guardar."
        )
        super().__init__("Editar equipo" if editing else "Registrar equipo", description, parent)
        self.service = service
        self.equipment_id = equipment["id"] if equipment else None
        self.public_code = equipment["codigo"] if equipment else None
        self.customer = QComboBox()
        for customer in customers:
            self.customer.addItem(customer["nombre"], customer["id"])
        self.equipment_type = QLineEdit()
        self.equipment_type.setPlaceholderText("Ej. Portátil, torre, impresora")
        self.brand = QLineEdit()
        self.model = QLineEdit()
        self.serial = QLineEdit()
        self.specifications = QTextEdit()
        self.specifications.setMinimumHeight(130)
        self.specifications.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.accessories = QLineEdit()
        self.condition = QLineEdit()

        if equipment:
            self.equipment_type.setText(equipment["tipo"])
            self.brand.setText(equipment["marca"] or "")
            self.model.setText(equipment["modelo"] or "")
            self.serial.setText(equipment["serial"] or "")
            self.specifications.setPlainText(equipment["especificaciones"] or "")
            self.accessories.setText(equipment["accesorios_recibidos"] or "")
            self.condition.setText(equipment["estado_fisico"] or "")
            self.customer.setCurrentIndex(self.customer.findData(equipment["cliente_id"]))

        if equipment:
            self.form.addRow("Código público", QLabel(equipment["codigo"]))
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
            values = {
                "brand": self.brand.text(),
                "model": self.model.text(),
                "serial": self.serial.text(),
                "specifications": self.specifications.toPlainText(),
                "accessories_received": self.accessories.text(),
                "physical_condition": self.condition.text(),
            }
            if self.equipment_id is None:
                self.created_record = self.service.register_equipment(
                    self.customer.currentData(), self.equipment_type.text(), **values
                )
            else:
                self.created_record = self.service.update_equipment(
                    self.equipment_id,
                    customer_id=self.customer.currentData(),
                    equipment_type=self.equipment_type.text(),
                    **values,
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
        self.problem.setMinimumHeight(150)
        self.problem.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.amount = QLineEdit("0")
        self.amount.setPlaceholderText("0")
        self.amount.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,19}"), self.amount)
        )
        self.diagnosis = QTextEdit()
        self.diagnosis.setPlaceholderText("Opcional al recibir el equipo")
        self.diagnosis.setMinimumHeight(130)
        self.diagnosis.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
