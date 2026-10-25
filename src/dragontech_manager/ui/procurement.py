"""Interfaz de proveedores, compras, recepción y pagos a proveedor."""

import sqlite3

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QInputDialog,
    QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from dragontech_manager.services.errors import ServiceError
from .inventory import _integer_value
from .pages import format_cop
from .widgets import EmptyState, build_table, set_cell

_PURCHASE_LABELS = {
    "borrador": "Borrador", "pendiente": "Pendiente de recepción",
    "recibida": "Recibida", "cancelada": "Cancelada",
}


class SupplierDialog(QDialog):
    def __init__(self, service, parent=None, *, supplier: dict | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.supplier = supplier
        self.saved: dict | None = None
        self.setWindowTitle("Editar proveedor" if supplier else "Nuevo proveedor")
        self.setMinimumSize(680, 600)
        self.resize(820, 740)
        outer = QVBoxLayout(self)
        title = QLabel(self.windowTitle())
        title.setStyleSheet("font-size: 18pt; font-weight: 700;")
        outer.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setVerticalSpacing(16)
        self.name = QLineEdit()
        self.tax_id = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.address = QTextEdit()
        self.address.setMinimumHeight(100)
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(125)
        self.active = QCheckBox("Proveedor activo")
        self.active.setChecked(True)
        form.addRow("Nombre / razón social *", self.name)
        form.addRow("Identificación fiscal", self.tax_id)
        form.addRow("Teléfono", self.phone)
        form.addRow("Correo", self.email)
        form.addRow("Dirección", self.address)
        form.addRow("Notas", self.notes)
        form.addRow(self.active)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar proveedor")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        if supplier:
            self.name.setText(supplier["nombre"])
            self.tax_id.setText(supplier["identificacion_fiscal"] or "")
            self.phone.setText(supplier["telefono"] or "")
            self.email.setText(supplier["correo"] or "")
            self.address.setPlainText(supplier["direccion"] or "")
            self.notes.setPlainText(supplier["notas"])
            self.active.setChecked(bool(supplier["activo"]))

    def _save(self) -> None:
        values = dict(name=self.name.text(), tax_id=self.tax_id.text(), phone=self.phone.text(),
                      email=self.email.text(), address=self.address.toPlainText(),
                      notes=self.notes.toPlainText())
        try:
            if self.supplier:
                self.saved = self.service.update_supplier(
                    self.supplier["id"], **values, active=self.active.isChecked()
                )
            else:
                self.saved = self.service.create_supplier(**values)
        except (ServiceError, sqlite3.Error) as error:
            self.error.setText(str(error) if isinstance(error, ServiceError)
                               else "No se pudo guardar el proveedor en SQLite.")
            return
        self.accept()


class SupplierDetailsDialog(QDialog):
    def __init__(self, supplier: dict, purchases: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Proveedor · {supplier['nombre']}")
        self.setMinimumSize(720, 520)
        self.resize(960, 700)
        layout = QVBoxLayout(self)
        info = QLabel(
            f"Identificación: {supplier['identificacion_fiscal'] or '—'}   ·   "
            f"Teléfono: {supplier['telefono'] or '—'}   ·   Correo: {supplier['correo'] or '—'}\n"
            f"Dirección: {supplier.get('direccion', '') or '—'}\n"
            f"Estado: {'Activo' if supplier['activo'] else 'Inactivo'}\n"
            f"Notas: {supplier['notas'] or '—'}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addWidget(QLabel("Compras y saldos relacionados"))
        self.table = build_table(
            ["Compra", "Fecha", "Referencia", "Estado", "Total", "Pagado", "Saldo"],
            column_widths=[100, 140, 170, 180, 160, 160, 160], flexible_column=2,
        )
        self.table.setMinimumHeight(260)
        self.table.setRowCount(len(purchases))
        for row, purchase in enumerate(purchases):
            values = (f"#{purchase['id']}", purchase["fecha_compra"], purchase["referencia"] or "—",
                      _PURCHASE_LABELS[purchase["estado"]], format_cop(purchase["importe_compra_cop"]),
                      format_cop(purchase["pagado_neto_cop"]), format_cop(purchase["saldo_pendiente_cop"]))
            for column, value in enumerate(values):
                set_cell(self.table, row, column, value)
        layout.addWidget(self.table, 1)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        layout.addWidget(close)


class SupplierPage(QWidget):
    changed = Signal()

    def __init__(self, service, procurement_service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.procurement_service = procurement_service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(14)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar proveedor, identificación o contacto…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(450)
        tools.addWidget(self.search)
        tools.addStretch(1)
        self.add_button = QPushButton("＋ Nuevo proveedor")
        self.add_button.setObjectName("primaryButton")
        self.edit_button = QPushButton("Editar")
        self.detail_button = QPushButton("Ver compras")
        self.add_button.clicked.connect(self._create)
        self.edit_button.clicked.connect(self._edit)
        self.detail_button.clicked.connect(self._details)
        tools.addWidget(self.add_button)
        tools.addWidget(self.edit_button)
        tools.addWidget(self.detail_button)
        layout.addLayout(tools)
        self.table = build_table(["Proveedor", "Identificación", "Teléfono", "Correo", "Estado"],
                                 column_widths=[280, 180, 170, 300, 130], flexible_column=0)
        self.table.setMinimumHeight(320)
        layout.addWidget(self.table, 1)
        self.edit_button.setEnabled(False)
        self.detail_button.setEnabled(False)
        self.search.textChanged.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._sync_selection)
        self.table.cellDoubleClicked.connect(lambda *_: self._details())
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.service.list_suppliers(search=self.search.text(), active=None, limit=500)
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudieron cargar los proveedores", str(error))
            return
        self.table.setRowCount(len(rows))
        for row, supplier in enumerate(rows):
            values = (supplier["nombre"], supplier["identificacion_fiscal"] or "—",
                      supplier["telefono"] or "—", supplier["correo"] or "—",
                      "Activo" if supplier["activo"] else "Inactivo")
            for column, value in enumerate(values):
                set_cell(self.table, row, column, value)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, supplier["id"])
            self.table.setRowHeight(row, 50)
        self._sync_selection()

    def _selected_id(self) -> int | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _sync_selection(self) -> None:
        enabled = self._selected_id() is not None
        self.edit_button.setEnabled(enabled)
        self.detail_button.setEnabled(enabled)

    def _create(self) -> None:
        dialog = SupplierDialog(self.service, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.changed.emit()

    def _edit(self) -> None:
        supplier_id = self._selected_id()
        if supplier_id is None:
            return
        try:
            supplier = self.service.get_supplier(supplier_id)
            dialog = SupplierDialog(self.service, self, supplier=supplier)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.refresh()
                self.changed.emit()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo abrir el proveedor", str(error))

    def _details(self) -> None:
        supplier_id = self._selected_id()
        if supplier_id is None:
            return
        try:
            supplier = self.service.get_supplier(supplier_id)
            purchases = self.procurement_service.supplier_purchase_history(supplier_id)
            SupplierDetailsDialog(supplier, purchases, self).exec()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo cargar el historial del proveedor", str(error))


class PurchaseLineDialog(QDialog):
    def __init__(self, products: list[dict], parent=None, *, line: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar línea de compra" if line else "Agregar producto a compra")
        self.setMinimumSize(620, 450)
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setVerticalSpacing(16)
        self.product = QComboBox()
        for product in products:
            marker = "Inactivo · " if not product["activo"] else ""
            self.product.addItem(f"{marker}{product['sku']} · {product['nombre']}", product)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1_000_000)
        self.cost = QLineEdit()
        self.description = QTextEdit()
        self.description.setMinimumHeight(115)
        form.addRow("Producto activo *", self.product)
        form.addRow("Cantidad *", self.quantity)
        form.addRow("Costo unitario (COP) *", self.cost)
        form.addRow("Descripción guardada en la compra", self.description)
        layout.addLayout(form, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Aceptar línea")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._accept_line)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.product.currentIndexChanged.connect(self._suggest_description)
        if line:
            index = next((i for i in range(self.product.count())
                          if self.product.itemData(i)["id"] == line["product_id"]), -1)
            self.product.setCurrentIndex(index)
            self.quantity.setValue(line["quantity"])
            self.cost.setText(str(line["unit_cost_cop"]))
            self.description.setPlainText(line["description"])
        else:
            if self.product.count():
                product = self.product.currentData()
                self.cost.setText(str(product["costo_actual_cop"]))
                self.description.setPlainText(product["nombre"])
        self.line: dict | None = None

    def _suggest_description(self, index: int) -> None:
        product = self.product.itemData(index)
        if product and not self.description.toPlainText().strip():
            self.description.setPlainText(product["nombre"])

    def _accept_line(self) -> None:
        product = self.product.currentData()
        if product is None:
            self.error.setText("Registra un producto activo antes de agregar líneas a la compra.")
            return
        try:
            cost = _integer_value(self.cost.text(), "El costo")
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.line = {
            "product_id": product["id"], "quantity": self.quantity.value(),
            "unit_cost_cop": cost,
            "description": self.description.toPlainText().strip() or product["nombre"],
        }
        self.accept()


class PurchaseDialog(QDialog):
    def __init__(self, inventory_service, procurement_service, suppliers: list[dict],
                 parent=None, *, purchase: dict | None = None) -> None:
        super().__init__(parent)
        self.inventory_service = inventory_service
        self.procurement_service = procurement_service
        self.purchase = purchase
        self.saved: dict | None = None
        self.products = inventory_service.list_products(active=True, limit=500)
        self.active_products = list(self.products)
        self.setWindowTitle("Editar compra borrador" if purchase else "Nueva compra")
        self.setMinimumSize(780, 620)
        self.resize(1040, 840)
        outer = QVBoxLayout(self)
        title = QLabel(self.windowTitle())
        title.setStyleSheet("font-size: 18pt; font-weight: 700;")
        outer.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        form = QFormLayout()
        form.setVerticalSpacing(16)
        self.supplier = QComboBox()
        for row in suppliers:
            if row["activo"]:
                self.supplier.addItem(row["nombre"], row["id"])
        self.reference = QLineEdit()
        self.purchase_date = QDateEdit()
        self.purchase_date.setCalendarPopup(True)
        self.purchase_date.setDisplayFormat("yyyy-MM-dd")
        self.purchase_date.setDate(QDate.currentDate())
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(110)
        form.addRow("Proveedor activo *", self.supplier)
        form.addRow("Factura / referencia", self.reference)
        form.addRow("Fecha de compra", self.purchase_date)
        form.addRow("Observaciones", self.notes)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.add_line = QPushButton("＋ Agregar producto")
        self.add_line.setObjectName("primaryButton")
        self.edit_line = QPushButton("Editar línea")
        self.remove_line = QPushButton("Retirar línea")
        actions.addWidget(self.add_line)
        actions.addWidget(self.edit_line)
        actions.addWidget(self.remove_line)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.table = build_table(["Producto / descripción", "Cantidad", "Costo unitario", "Subtotal"],
                                 column_widths=[430, 110, 190, 190], flexible_column=0)
        self.table.setMinimumHeight(230)
        self.table.setWordWrap(True)
        layout.addWidget(self.table)
        self.total = QLabel("Total documentado: $ 0 COP")
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total.setStyleSheet("font-size: 17pt; font-weight: 700;")
        layout.addWidget(self.total)
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
        self.lines: list[dict] = []
        self.add_line.clicked.connect(self._add_line)
        self.edit_line.clicked.connect(self._edit_line)
        self.remove_line.clicked.connect(self._remove_line)
        self.table.itemSelectionChanged.connect(self._sync_line_buttons)
        if purchase:
            self.supplier.setCurrentIndex(self.supplier.findData(purchase["proveedor_id"]))
            self.reference.setText(purchase["referencia"])
            self.purchase_date.setDate(QDate.fromString(purchase["fecha_compra"], "yyyy-MM-dd"))
            self.notes.setPlainText(purchase["notas"])
            self.lines = [
                {"product_id": line["producto_id"], "quantity": line["cantidad"],
                 "unit_cost_cop": line["costo_unitario_historico_cop"],
                 "description": line["descripcion_historica"] or line["producto_nombre"],
                 "snapshot_missing": not bool(line["descripcion_historica"])}
                for line in purchase["lineas"]
            ]
            known_ids = {product["id"] for product in self.products}
            for line in purchase["lineas"]:
                if line["producto_id"] not in known_ids:
                    product = inventory_service.get_product(line["producto_id"])
                    self.products.append(product)
        self._render_lines()

    def _add_line(self) -> None:
        dialog = PurchaseLineDialog(self.active_products, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.line:
            self.lines.append(dialog.line)
            self._render_lines()

    def _edit_line(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        products = list(self.active_products)
        line_product = next((item for item in self.products if item["id"] == self.lines[row]["product_id"]), None)
        if line_product and not line_product["activo"]:
            products.append(line_product)
        dialog = PurchaseLineDialog(products, self, line=self.lines[row])
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.line:
            self.lines[row] = dialog.line
            self._render_lines()
            self.table.selectRow(row)

    def _remove_line(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            del self.lines[row]
            self._render_lines()

    def _render_lines(self) -> None:
        self.table.setRowCount(len(self.lines))
        total = 0
        for row, line in enumerate(self.lines):
            subtotal = line["quantity"] * line["unit_cost_cop"]
            total += subtotal
            description = line["description"]
            if line.get("snapshot_missing"):
                description += " (descripción histórica original no disponible)"
            values = (description, line["quantity"], format_cop(line["unit_cost_cop"]), format_cop(subtotal))
            for column, value in enumerate(values):
                set_cell(self.table, row, column, value)
            self.table.setRowHeight(row, 55)
        self.total.setText(f"Total documentado: {format_cop(total)}")
        self._sync_line_buttons()

    def _sync_line_buttons(self) -> None:
        selected = self.table.currentRow() >= 0
        self.edit_line.setEnabled(selected)
        self.remove_line.setEnabled(selected)

    def _save(self) -> None:
        supplier_id = self.supplier.currentData()
        if supplier_id is None:
            self.error.setText("Registra un proveedor activo antes de crear una compra.")
            return
        values = dict(
            reference=self.reference.text(),
            purchase_date=self.purchase_date.date().toString("yyyy-MM-dd"),
            notes=self.notes.toPlainText(),
        )
        try:
            if self.purchase:
                self.saved = self.procurement_service.update_purchase(
                    self.purchase["id"], supplier_id, self.lines, **values
                )
            else:
                self.saved = self.procurement_service.create_purchase(supplier_id, self.lines, **values)
        except (ServiceError, sqlite3.Error) as error:
            self.error.setText(str(error) if isinstance(error, ServiceError)
                               else "No se pudo guardar la compra. Los datos siguen en el formulario.")
            return
        self.accept()


class PaymentDialog(QDialog):
    def __init__(self, purchase: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Registrar pago · Compra #{purchase['id']}")
        self.setMinimumSize(560, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Total: {format_cop(purchase['importe_compra_cop'])}   ·   "
            f"Pagado: {format_cop(purchase['pagado_neto_cop'])}   ·   "
            f"Saldo: {format_cop(purchase['saldo_pendiente_cop'])}"
        ))
        form = QFormLayout()
        self.amount = QLineEdit(str(purchase["saldo_pendiente_cop"]))
        self.method = QLineEdit()
        self.method.setPlaceholderText("Transferencia, efectivo…")
        self.reference = QLineEdit()
        form.addRow("Importe (COP) *", self.amount)
        form.addRow("Medio de pago *", self.method)
        form.addRow("Referencia", self.reference)
        layout.addLayout(form, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Registrar pago")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[int, str, str]:
        amount = _integer_value(self.amount.text(), "El pago", allow_zero=False)
        method = self.method.text().strip()
        if not method:
            raise ValueError("El medio de pago es obligatorio.")
        return amount, method, self.reference.text().strip()


class PurchaseDetailsDialog(QDialog):
    changed = False

    def __init__(self, inventory_service, procurement_service, purchase_id: int, parent=None) -> None:
        super().__init__(parent)
        self.inventory_service = inventory_service
        self.procurement_service = procurement_service
        self.purchase_id = purchase_id
        self.changed = False
        self.setMinimumSize(820, 620)
        self.resize(1120, 840)
        outer = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        self.lines_table = build_table(["Producto / snapshot de descripción", "Cantidad", "Costo unitario", "Subtotal"],
                                       column_widths=[440, 100, 190, 190], flexible_column=0)
        self.lines_table.setMinimumHeight(210)
        outer.addWidget(QLabel("Detalle de compra"))
        outer.addWidget(self.lines_table)
        self.payments_table = build_table(["Tipo", "Importe", "Medio", "Fecha UTC", "Referencia / motivo"],
                                          column_widths=[130, 170, 160, 220, 300], flexible_column=4)
        self.payments_table.setMinimumHeight(170)
        outer.addWidget(QLabel("Pagos y reversiones a proveedor"))
        outer.addWidget(self.payments_table, 1)
        actions = QHBoxLayout()
        self.edit_button = QPushButton("Editar borrador")
        self.confirm_button = QPushButton("Confirmar compra")
        self.receive_button = QPushButton("Registrar recepción física")
        self.cancel_button = QPushButton("Cancelar compra")
        self.payment_button = QPushButton("Registrar pago")
        self.reverse_button = QPushButton("Revertir pago seleccionado")
        close = QPushButton("Cerrar")
        for button in (self.confirm_button, self.receive_button, self.payment_button):
            button.setObjectName("primaryButton")
        self.reverse_button.setEnabled(False)
        for button in (self.edit_button, self.confirm_button, self.receive_button,
                       self.cancel_button, self.payment_button, self.reverse_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(close)
        outer.addLayout(actions)
        self.edit_button.clicked.connect(self._edit)
        self.confirm_button.clicked.connect(lambda: self._transition("pendiente"))
        self.receive_button.clicked.connect(lambda: self._transition("recibida"))
        self.cancel_button.clicked.connect(lambda: self._transition("cancelada"))
        self.payment_button.clicked.connect(self._payment)
        self.reverse_button.clicked.connect(self._reverse_payment)
        self.payments_table.itemSelectionChanged.connect(self._sync_reverse)
        close.clicked.connect(self.accept)
        self._refresh()

    def _refresh(self) -> None:
        purchase = self.procurement_service.get_purchase(self.purchase_id)
        self.purchase = purchase
        self.setWindowTitle(f"Compra #{purchase['id']} · {purchase['proveedor_nombre']}")
        self.summary.setText(
            f"Proveedor: {purchase['proveedor_nombre']}   ·   Fecha: {purchase['fecha_compra']}   ·   "
            f"Referencia: {purchase['referencia'] or '—'}\n"
            f"Estado: {_PURCHASE_LABELS[purchase['estado']]}   ·   "
            f"Total: {format_cop(purchase['importe_compra_cop'])}   ·   "
            f"Pagado: {format_cop(purchase['pagado_neto_cop'])}   ·   "
            f"Saldo pendiente: {format_cop(purchase['saldo_pendiente_cop'])}\n"
            f"Recepción física: {purchase['fecha_recepcion'] or 'Aún no recibida'}\n"
            f"Observaciones: {purchase['notas'] or '—'}"
        )
        self.lines_table.setRowCount(len(purchase["lineas"]))
        for row, line in enumerate(purchase["lineas"]):
            description = line["descripcion_historica"] or f"{line['producto_nombre']} (sin snapshot histórico previo)"
            values = (f"{line['sku']} · {description}", line["cantidad"],
                      format_cop(line["costo_unitario_historico_cop"]),
                      format_cop(line["cantidad"] * line["costo_unitario_historico_cop"]))
            for column, value in enumerate(values):
                set_cell(self.lines_table, row, column, value)
            self.lines_table.setRowHeight(row, 52)
        payments = purchase["pagos"]
        self.payments_table.setRowCount(len(payments))
        for row, payment in enumerate(payments):
            values = ("Pago" if payment["tipo"] == "pago" else "Reversión",
                      format_cop(payment["importe_cop"]), payment["metodo"],
                      payment["registrado_en_utc"], payment["motivo"] or payment["referencia"] or "—")
            for column, value in enumerate(values):
                set_cell(self.payments_table, row, column, value)
            self.payments_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, payment["id"])
            self.payments_table.item(row, 0).setData(Qt.ItemDataRole.UserRole + 1, payment["tipo"])
            self.payments_table.setRowHeight(row, 48)
        state = purchase["estado"]
        self.edit_button.setVisible(state == "borrador")
        self.confirm_button.setVisible(state == "borrador")
        self.receive_button.setVisible(state == "pendiente")
        self.cancel_button.setVisible(state in {"borrador", "pendiente"})
        self.payment_button.setVisible(state in {"pendiente", "recibida"} and purchase["saldo_pendiente_cop"] > 0)
        self._sync_reverse()

    def _edit(self) -> None:
        suppliers = self.inventory_service.list_suppliers(active=None, limit=500)
        dialog = PurchaseDialog(self.inventory_service, self.procurement_service, suppliers,
                                self, purchase=self.purchase)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.changed = True
            self._refresh()

    def _transition(self, state: str) -> None:
        label = "confirmar la compra y dejarla pendiente de recepción" if state == "pendiente" else (
            "registrar la recepción física de todos los productos" if state == "recibida" else "cancelar la compra"
        )
        answer = QMessageBox.question(
            self, "Confirmar operación", f"¿Confirmas {label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.procurement_service.transition_purchase(self.purchase_id, state)
            self.changed = True
            self._refresh()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo cambiar la compra", str(error))

    def _payment(self) -> None:
        dialog = PaymentDialog(self.purchase, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            amount, method, reference = dialog.values()
            self.procurement_service.register_supplier_payment(
                self.purchase_id, amount, method=method, reference=reference
            )
            self.changed = True
            self._refresh()
        except (ValueError, ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo registrar el pago", str(error))

    def _sync_reverse(self) -> None:
        row = self.payments_table.currentRow()
        item = self.payments_table.item(row, 0) if row >= 0 else None
        payment_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        payment_type = item.data(Qt.ItemDataRole.UserRole + 1) if item else None
        self.reverse_button.setEnabled(bool(payment_id and payment_type == "pago"
                                            and self.procurement_service.can_reverse_supplier_payment(payment_id)))

    def _reverse_payment(self) -> None:
        row = self.payments_table.currentRow()
        item = self.payments_table.item(row, 0) if row >= 0 else None
        payment_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if payment_id is None:
            return
        reason, accepted = QInputDialog.getText(self, "Revertir pago", "Motivo de la reversión:")
        if not accepted:
            return
        try:
            self.procurement_service.reverse_supplier_payment(payment_id, reason=reason)
            self.changed = True
            self._refresh()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo revertir el pago", str(error))


class PurchasePage(QWidget):
    changed = Signal()

    def __init__(self, inventory_service, procurement_service, parent=None) -> None:
        super().__init__(parent)
        self.inventory_service = inventory_service
        self.procurement_service = procurement_service
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(14)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar proveedor, factura o número de compra…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(450)
        tools.addWidget(self.search)
        self.state_filter = QComboBox()
        self.state_filter.addItem("Todos los estados", None)
        for state, label in _PURCHASE_LABELS.items():
            self.state_filter.addItem(label, state)
        tools.addWidget(self.state_filter)
        tools.addStretch(1)
        self.add_button = QPushButton("＋ Nueva compra")
        self.add_button.setObjectName("primaryButton")
        self.detail_button = QPushButton("Ver detalle")
        self.add_button.clicked.connect(self._create)
        self.detail_button.clicked.connect(self._details)
        tools.addWidget(self.add_button)
        tools.addWidget(self.detail_button)
        layout.addLayout(tools)
        self.table = build_table(["Compra", "Proveedor", "Referencia", "Fecha", "Estado", "Total", "Pagado", "Saldo"],
                                 column_widths=[105, 260, 180, 140, 190, 170, 170, 170], flexible_column=1)
        self.table.setMinimumHeight(320)
        layout.addWidget(self.table, 1)
        controls = QHBoxLayout()
        self.previous = QPushButton("‹ Anterior")
        self.next = QPushButton("Siguiente ›")
        self.page_label = QLabel()
        self.page_label.setObjectName("muted")
        controls.addWidget(self.page_label)
        controls.addStretch(1)
        controls.addWidget(self.previous)
        controls.addWidget(self.next)
        layout.addLayout(controls)
        self.offset = 0
        self.page_size = 100
        self.search.textChanged.connect(self.refresh)
        self.state_filter.currentIndexChanged.connect(self.refresh)
        self.previous.clicked.connect(self._previous)
        self.next.clicked.connect(self._next)
        self.table.cellDoubleClicked.connect(lambda *_: self._details())
        self.table.itemSelectionChanged.connect(self._sync_selection)
        self.detail_button.setEnabled(False)
        self.refresh()

    def _previous(self) -> None:
        self.offset = max(0, self.offset - self.page_size)
        self.refresh()

    def _next(self) -> None:
        self.offset += self.page_size
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.procurement_service.list_purchases(
                search=self.search.text(), state=self.state_filter.currentData(),
                limit=self.page_size + 1, offset=self.offset,
            )
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudieron cargar las compras", str(error))
            return
        has_next = len(rows) > self.page_size
        rows = rows[:self.page_size]
        self.table.setRowCount(len(rows))
        for row, purchase in enumerate(rows):
            values = (f"#{purchase['id']}", purchase["proveedor_nombre"], purchase["referencia"] or "—",
                      purchase["fecha_compra"], _PURCHASE_LABELS[purchase["estado"]],
                      format_cop(purchase["importe_compra_cop"]), format_cop(purchase["pagado_neto_cop"]),
                      format_cop(purchase["saldo_pendiente_cop"]))
            for column, value in enumerate(values):
                set_cell(self.table, row, column, value)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, purchase["id"])
            self.table.setRowHeight(row, 50)
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(has_next)
        self.page_label.setText(f"{self.offset + 1}–{self.offset + len(rows)}" if rows else "Sin compras")
        self._sync_selection()

    def _selected_id(self) -> int | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _sync_selection(self) -> None:
        self.detail_button.setEnabled(self._selected_id() is not None)

    def _create(self) -> None:
        suppliers = self.inventory_service.list_suppliers(active=None, limit=500)
        dialog = PurchaseDialog(self.inventory_service, self.procurement_service, suppliers, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.offset = 0
            self.refresh()
            self.changed.emit()

    def _details(self) -> None:
        purchase_id = self._selected_id()
        if purchase_id is None:
            return
        try:
            dialog = PurchaseDetailsDialog(self.inventory_service, self.procurement_service, purchase_id, self)
            dialog.exec()
            if dialog.changed:
                self.refresh()
                self.changed.emit()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo cargar la compra", str(error))
