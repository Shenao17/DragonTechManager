"""Interfaz para ventas directas y pagos asociados exclusivamente a ventas."""

import sqlite3
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QInputDialog,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QTableWidget, QTextEdit, QVBoxLayout, QWidget,
)

from dragontech_manager.services.errors import ServiceError
from dragontech_manager.services.idempotency import IntentKey
from dragontech_manager.services.returns import ReturnsService
from .pages import format_cop, format_local_datetime
from .widgets import EmptyState, build_table, set_cell
from .product_defaults import ProductFieldBinding
from .proposals import ProposalPage
from .returns import PaymentReversalDialog, ReturnDialog

_SALE_STATES = {"abierta": "Pendiente de pago", "parcial": "Pago parcial",
                "completada": "Pagada", "cancelada": "Cancelada",
                "reembolso_pendiente": "Reembolso pendiente"}


def _integer(text: str, label: str, *, positive: bool = False) -> int:
    value = text.strip()
    if not value.isdigit():
        raise ValueError(f"{label} debe ser un entero en pesos colombianos.")
    number = int(value)
    if positive and number == 0:
        raise ValueError(f"{label} debe ser mayor que cero.")
    return number


class SaleLineDialog(QDialog):
    def __init__(self, products: list[dict], parent=None, *, line: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar concepto" if line else "Agregar concepto a la venta")
        self.setMinimumSize(620, 470)
        self.resize(760, 580)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setVerticalSpacing(15)
        self.product = QComboBox()
        self.product.addItem("Concepto no inventariable", None)
        for product in products:
            self.product.addItem(f"{product['sku']} · {product['nombre']}", product)
        self.description = QTextEdit()
        self.description.setMinimumHeight(110)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 1_000_000)
        self.price = QLineEdit()
        self.price.setPlaceholderText("Pesos enteros, por ejemplo 250000")
        form.addRow("Producto / tipo de concepto", self.product)
        form.addRow("Descripción histórica *", self.description)
        form.addRow("Cantidad *", self.quantity)
        form.addRow("Precio unitario (COP) *", self.price)
        layout.addLayout(form, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Aceptar concepto")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._accept_line)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.line = None
        self.binding = ProductFieldBinding(self.product, self.description, self.price, "precio_actual_cop")
        if line:
            self.binding.load_existing(line.get("product_id"), description=line["description"],
                                       amount=line["unit_price_cop"])
            self.quantity.setValue(line["quantity"])

    def _accept_line(self) -> None:
        try:
            product = self.binding.sync_for_save()
            description = self.description.toPlainText().strip()
            if not description:
                raise ValueError("La descripción histórica es obligatoria.")
            self.line = {
                "description": description, "quantity": self.quantity.value(),
                "unit_price_cop": _integer(self.price.text(), "El precio"),
                "product_id": product["id"] if product else None,
            }
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()


class SaleDialog(QDialog):
    def __init__(self, service, customers: list[dict], products: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.idempotency_key = uuid4().hex
        self.created_sale = None
        self._lines: list[dict] = []
        self.setWindowTitle("Confirmar nueva venta")
        self.setMinimumSize(820, 650)
        self.resize(1050, 830)
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(18)
        form = QFormLayout()
        self.customer = QComboBox()
        for customer in customers:
            if customer.get("archivado_en_utc") is None:
                self.customer.addItem(customer["nombre"], customer["id"])
        self.sale_date = QLineEdit()
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.sale_date.setText(datetime.now(ZoneInfo("America/Bogota")).date().isoformat())
        self.notes = QTextEdit()
        self.notes.setMinimumHeight(95)
        form.addRow("Cliente *", self.customer)
        form.addRow("Fecha de venta *", self.sale_date)
        form.addRow("Observaciones", self.notes)
        layout.addLayout(form)
        controls = QHBoxLayout()
        self.add_line = QPushButton("＋ Agregar concepto")
        self.add_line.setObjectName("primaryButton")
        self.edit_line = QPushButton("Editar línea")
        self.remove_line = QPushButton("Retirar línea")
        controls.addWidget(self.add_line)
        controls.addWidget(self.edit_line)
        controls.addWidget(self.remove_line)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.table = build_table(["Concepto", "Cantidad", "Precio unitario", "Subtotal", "Inventario"],
                                 column_widths=[380, 100, 180, 180, 145], flexible_column=0)
        self.table.setMinimumHeight(240)
        layout.addWidget(self.table)
        self.total = QLabel("Total: $ 0 COP")
        self.total.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.total.setStyleSheet("font-size: 17pt; font-weight: 700;")
        layout.addWidget(self.total)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Revisar y confirmar venta")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.products = products
        self.add_line.clicked.connect(self._add)
        self.edit_line.clicked.connect(self._edit)
        self.remove_line.clicked.connect(self._remove)
        self.table.itemSelectionChanged.connect(self._sync)
        self.table.cellDoubleClicked.connect(lambda *_: self._edit())
        self._sync()

    def _sync(self) -> None:
        selected = self.table.currentRow() >= 0
        self.edit_line.setEnabled(selected)
        self.remove_line.setEnabled(selected)

    def _render(self) -> None:
        self.table.setRowCount(len(self._lines))
        total = 0
        for row, line in enumerate(self._lines):
            subtotal = line["quantity"] * line["unit_price_cop"]
            total += subtotal
            values = (line["description"], line["quantity"], format_cop(line["unit_price_cop"]),
                      format_cop(subtotal), "Sí" if line["product_id"] else "No")
            for col, value in enumerate(values):
                set_cell(self.table, row, col, value)
            self.table.setRowHeight(row, 52)
        self.total.setText(f"Total: {format_cop(total)}")
        self._sync()

    def _add(self) -> None:
        dialog = SaleLineDialog(self.products, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._lines.append(dialog.line)
            self._render()

    def _edit(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        dialog = SaleLineDialog(self.products, self, line=self._lines[row])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._lines[row] = dialog.line
            self._render()

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            del self._lines[row]
            self._render()

    def _save(self) -> None:
        try:
            customer_id = self.customer.currentData()
            if customer_id is None:
                raise ValueError("Selecciona un cliente existente.")
            if not self._lines:
                raise ValueError("Agrega al menos un concepto a la venta.")
            total = sum(line["quantity"] * line["unit_price_cop"] for line in self._lines)
            inventory = [f"• {line['description']}: {line['quantity']} unidad(es)" for line in self._lines if line["product_id"]]
            summary = (f"Cliente: {self.customer.currentText()}\n\n" +
                       "Conceptos:\n" + "\n".join(
                           f"• {line['description']} × {line['quantity']} · {format_cop(line['unit_price_cop'])} c/u"
                           for line in self._lines
                       ) + f"\n\nTotal: {format_cop(total)}\n\n" +
                       ("Unidades que se descontarán del inventario:\n" + "\n".join(inventory)
                        if inventory else "Esta venta no afecta el inventario."))
            answer = QMessageBox.question(
                self, "Confirmar venta", summary,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.created_sale = self.service.create_sale(
                customer_id, self._lines, idempotency_key=self.idempotency_key,
                sale_date=self.sale_date.text().strip(), notes=self.notes.toPlainText(),
            )
        except (ValueError, ServiceError) as error:
            self.error.setText(str(error))
            return
        except sqlite3.Error:
            self.error.setText("No se pudo confirmar la venta. No se guardaron cambios parciales; revisa el inventario e inténtalo de nuevo.")
            return
        self.accept()


class PaymentDialog(QDialog):
    def __init__(self, sale: dict, methods: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.sale = sale
        self.idempotency_key = uuid4().hex
        self.setWindowTitle("Registrar pago de cliente")
        self.setMinimumSize(580, 420)
        self.resize(680, 510)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Venta {sale['codigo']} · {sale['cliente_nombre']}"))
        form = QFormLayout()
        self.amount = QLineEdit(str(sale["saldo_pendiente_cop"]))
        self.method = QComboBox()
        for method in methods:
            self.method.addItem(method["nombre"], method["id"])
        self.reference = QLineEdit()
        form.addRow("Importe (COP) *", self.amount)
        form.addRow("Medio de pago *", self.method)
        form.addRow("Referencia", self.reference)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("formError")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Revisar y registrar pago")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def payment_values(self) -> tuple[int, int, str]:
        method_id = self.method.currentData()
        if method_id is None:
            raise ValueError("El medio de pago es obligatorio.")
        return (_integer(self.amount.text(), "El importe", positive=True),
                method_id, self.reference.text().strip())

    def _validate(self) -> None:
        try:
            amount, _method, _reference = self.payment_values()
            if amount > self.sale["saldo_pendiente_cop"]:
                raise ValueError("El pago supera el saldo pendiente.")
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()


class SaleDetailsDialog(QDialog):
    changed = False

    def __init__(self, service, sale_id: int, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.sale_id = sale_id
        self.changed = False
        self.returns_service = ReturnsService(service.connection)
        self._return_intent = IntentKey()
        self.setMinimumSize(820, 620)
        self.resize(1100, 820)
        self.outer = QVBoxLayout(self)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.outer.addWidget(self.body)
        self._render()

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                SaleDetailsDialog._clear_layout(item.layout())

    def _render(self) -> None:
        self._clear_layout(self.body_layout)
        self.sale = self.service.get_sale(self.sale_id)
        self.setWindowTitle(f"Venta {self.sale['codigo']}")
        self.body_layout.addWidget(QLabel(
            f"{self.sale['codigo']} · {_SALE_STATES[self.sale['estado_cobro']]}\n"
            f"Cliente: {self.sale['cliente_nombre']} · Fecha: {self.sale['fecha_venta']}\n"
            f"Total: {format_cop(self.sale['importe_acordado_cop'])} · Pagado: {format_cop(self.sale['pagado_neto_cop'])} · Saldo: {format_cop(self.sale['saldo_pendiente_cop'])}"
            + (f"\nDevuelto reconocido: {format_cop(self.sale['devuelto_reconocido_cop'])} · "
               f"Pagado en exceso pendiente de compensar: {format_cop(self.sale['sobrepago_pendiente_cop'])}"
               if self.sale["estado_devolucion"] != "ninguna" else "")
        ))
        lines = build_table(["Concepto", "Cantidad", "Precio unitario", "Subtotal", "SKU"],
                            column_widths=[410, 100, 180, 180, 130], flexible_column=0)
        lines.setMinimumHeight(180)
        lines.setRowCount(len(self.sale["lineas"]))
        for row, line in enumerate(self.sale["lineas"]):
            values = (line["descripcion"], line["cantidad"], format_cop(line["precio_unitario_cop"]),
                      format_cop(line["cantidad"] * line["precio_unitario_cop"]), line["producto_sku"] or "—")
            for col, value in enumerate(values):
                set_cell(lines, row, col, value)
            lines.setRowHeight(row, 52)
        self.body_layout.addWidget(QLabel("Conceptos de la venta"))
        self.body_layout.addWidget(lines, 1)
        controls = QHBoxLayout()
        self.pay_button = QPushButton("＋ Registrar pago")
        self.pay_button.setObjectName("primaryButton")
        self.reverse_button = QPushButton("Revertir pago seleccionado")
        controls.addWidget(self.pay_button)
        controls.addWidget(self.reverse_button)
        self.return_button = QPushButton("Registrar devolución")
        self.return_button.setEnabled(self.sale["estado_devolucion"] != "total")
        self.return_button.clicked.connect(self._return)
        controls.addWidget(self.return_button)
        controls.addStretch(1)
        self.body_layout.addLayout(controls)
        self.payments = build_table(["Tipo", "Importe", "Medio", "Referencia / motivo", "Registrado (UTC)"],
                                    column_widths=[130, 170, 150, 360, 240], flexible_column=3)
        self.payments.setMinimumHeight(180)
        self.payments.setRowCount(len(self.sale["pagos"]))
        for row, payment in enumerate(self.sale["pagos"]):
            is_receipt = payment["tipo"] == "recibo"
            values = ("Pago recibido" if is_receipt else "Reversión", format_cop(payment["importe_cop"]),
                      payment["metodo"], payment["motivo"] or payment["referencia"] or "—",
                      payment["registrado_en_utc"])
            for col, value in enumerate(values):
                set_cell(self.payments, row, col, value)
            self.payments.item(row, 0).setData(Qt.ItemDataRole.UserRole, payment["id"])
            self.payments.item(row, 0).setData(Qt.ItemDataRole.UserRole + 1, payment["tipo"])
            self.payments.item(row, 0).setData(Qt.ItemDataRole.UserRole + 2, bool(payment["reversado"]))
            self.payments.setRowHeight(row, 48)
        self.body_layout.addWidget(QLabel("Historial de pagos y reversos"))
        self.body_layout.addWidget(self.payments, 1)
        self.pay_button.setEnabled(self.sale["saldo_pendiente_cop"] > 0 and self.sale["estado_cobro"] != "cancelada")
        self.reverse_button.setEnabled(False)
        self.payments.itemSelectionChanged.connect(self._sync_reverse)
        self.pay_button.clicked.connect(self._payment)
        self.reverse_button.clicked.connect(self._reverse)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        self.body_layout.addWidget(close)

    def _sync_reverse(self) -> None:
        row = self.payments.currentRow()
        item = self.payments.item(row, 0) if row >= 0 else None
        self.reverse_button.setEnabled(
            bool(item) and item.data(Qt.ItemDataRole.UserRole + 1) == "recibo"
            and not item.data(Qt.ItemDataRole.UserRole + 2)
        )

    def _payment(self) -> None:
        dialog = PaymentDialog(self.sale, self.service.methods.list_methods("cliente"), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            amount, method, reference = dialog.payment_values()
            new_balance = self.sale["saldo_pendiente_cop"] - amount
            answer = QMessageBox.question(
                self, "Confirmar pago",
                f"Venta: {self.sale['codigo']} · {self.sale['cliente_nombre']}\n"
                f"Pago: {format_cop(amount)}\nTotal previamente recibido: {format_cop(self.sale['pagado_neto_cop'])}\n"
                f"Saldo anterior: {format_cop(self.sale['saldo_pendiente_cop'])}\nSaldo resultante: {format_cop(new_balance)}\n"
                f"Medio: {dialog.method.currentText()} · Referencia: {reference or '—'}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.service.register_payment(self.sale_id, amount, method=method,
                                          reference=reference, idempotency_key=dialog.idempotency_key)
            self.changed = True
            self._render()
        except (ValueError, ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo registrar el pago", str(error))

    def _reverse(self) -> None:
        row = self.payments.currentRow()
        if row < 0:
            return
        item = self.payments.item(row, 0)
        if (item.data(Qt.ItemDataRole.UserRole + 1) != "recibo"
                or item.data(Qt.ItemDataRole.UserRole + 2)):
            return
        reversal = PaymentReversalDialog(self)
        if reversal.exec() != QDialog.DialogCode.Accepted:
            return
        details = reversal.values()
        answer = QMessageBox.question(
            self, "Confirmar reversión", "Se conservará el pago original y se registrará una reversión por el mismo importe. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.reverse_payment(item.data(Qt.ItemDataRole.UserRole), **details)
            self.changed = True
            self._render()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo revertir el pago", str(error))

    def _return(self) -> None:
        dialog = ReturnDialog(self.sale, self.returns_service.returnable_lines(self.sale_id), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            values = dialog.values()
            key = self._return_intent.for_payload({"venta": self.sale_id, **values})
            answer = QMessageBox.question(
                self, "Confirmar devolución",
                "Se registrará la devolución y las unidades aptas volverán al inventario. "
                "No se genera reembolso automático. ¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.return_button.setEnabled(False)
            self.returns_service.register_return(self.sale_id, idempotency_key=key, **values)
            self._return_intent.complete()
            self.changed = True
            self._render()
        except (ValueError, ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo registrar la devolución", str(error))
            self.return_button.setEnabled(self.sale["estado_devolucion"] != "total")


class SalesPage(QWidget):
    changed = Signal()
    request_details = Signal(int)

    def __init__(self, service, customer_service, inventory_service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.customer_service = customer_service
        self.inventory_service = inventory_service
        self.offset = 0
        self.page_size = 100
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 20)
        layout.setSpacing(14)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar código de venta o cliente…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(430)
        tools.addWidget(self.search)
        self.status_filter = QComboBox()
        self.status_filter.addItem("Todos los estados", None)
        for key, label in _SALE_STATES.items():
            self.status_filter.addItem(label, key)
        tools.addWidget(self.status_filter)
        self.from_date = QLineEdit()
        self.from_date.setPlaceholderText("Desde AAAA-MM-DD")
        self.from_date.setMaximumWidth(160)
        self.to_date = QLineEdit()
        self.to_date.setPlaceholderText("Hasta AAAA-MM-DD")
        self.to_date.setMaximumWidth(160)
        tools.addWidget(self.from_date)
        tools.addWidget(self.to_date)
        tools.addStretch(1)
        self.create_button = QPushButton("＋ Nueva venta")
        self.create_button.setObjectName("primaryButton")
        self.detail_button = QPushButton("Ver detalle y pagos")
        tools.addWidget(self.create_button)
        tools.addWidget(self.detail_button)
        layout.addLayout(tools)
        self.table = build_table(["Venta", "Cliente", "Fecha", "Total", "Pagado", "Saldo", "Estado"],
                                 column_widths=[240, 300, 150, 190, 190, 190, 160], flexible_column=1)
        self.table.setMinimumHeight(320)
        self.empty = EmptyState("Aún no hay ventas", "Las ventas directas y las propuestas aceptadas aparecerán aquí.")
        from PySide6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.table)
        layout.addWidget(self.stack, 1)
        controls = QHBoxLayout()
        self.page_label = QLabel()
        self.page_label.setObjectName("muted")
        self.previous = QPushButton("‹ Anterior")
        self.next = QPushButton("Siguiente ›")
        controls.addWidget(self.page_label)
        controls.addStretch(1)
        controls.addWidget(self.previous)
        controls.addWidget(self.next)
        layout.addLayout(controls)
        self.search.textChanged.connect(self._reset)
        self.status_filter.currentIndexChanged.connect(self._reset)
        self.from_date.textChanged.connect(self._reset)
        self.to_date.textChanged.connect(self._reset)
        self.previous.clicked.connect(self._previous)
        self.next.clicked.connect(self._next)
        self.create_button.clicked.connect(self._create)
        self.detail_button.clicked.connect(self._open_selected)
        self.table.cellDoubleClicked.connect(lambda *_: self._open_selected())
        self.table.itemSelectionChanged.connect(self._sync)
        self.refresh()

    def _reset(self, *_args) -> None:
        self.offset = 0
        self.refresh()

    def _previous(self) -> None:
        self.offset = max(0, self.offset - self.page_size)
        self.refresh()

    def _next(self) -> None:
        self.offset += self.page_size
        self.refresh()

    def refresh(self) -> None:
        try:
            rows = self.service.list_sales(search=self.search.text(), state=self.status_filter.currentData(),
                                           date_from=self.from_date.text().strip() or None,
                                           date_to=self.to_date.text().strip() or None,
                                           limit=self.page_size + 1, offset=self.offset)
        except (ServiceError, sqlite3.Error) as error:
            self.empty.title_label.setText("No se pudieron cargar las ventas")
            self.empty.description_label.setText(str(error))
            self.stack.setCurrentWidget(self.empty)
            return
        has_next = len(rows) > self.page_size
        rows = rows[:self.page_size]
        self.table.setRowCount(len(rows))
        for row, sale in enumerate(rows):
            values = (sale["codigo"], sale["cliente_nombre"], sale["fecha_venta"],
                      format_cop(sale["importe_acordado_cop"]), format_cop(sale["pagado_neto_cop"]),
                      format_cop(sale["saldo_pendiente_cop"]), _SALE_STATES[sale["estado_cobro"]])
            for col, value in enumerate(values):
                set_cell(self.table, row, col, value)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, sale["id"])
            self.table.setRowHeight(row, 50)
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(has_next)
        self.page_label.setText(f"{self.offset + 1}–{self.offset + len(rows)}" if rows else "")
        if rows:
            self.stack.setCurrentWidget(self.table)
        else:
            self.empty.title_label.setText("No hay ventas coincidentes" if self.search.text().strip() else "Aún no hay ventas")
            self.empty.description_label.setText("Ajusta la búsqueda o crea una venta. Las propuestas se convierten desde su detalle una vez aceptadas.")
            self.stack.setCurrentWidget(self.empty)
        self._sync()

    def _selected_id(self) -> int | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _sync(self) -> None:
        self.detail_button.setEnabled(self._selected_id() is not None)

    def _create(self) -> None:
        try:
            customers = self.customer_service.list_customers(limit=500)
            products = self.inventory_service.list_products(active=True, limit=500)
            dialog = SaleDialog(self.service, customers, products, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.offset = 0
                self.refresh()
                self.changed.emit()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo iniciar la venta", str(error))

    def create_dialog(self, parent=None) -> bool:
        customers = self.customer_service.list_customers(limit=500)
        products = self.inventory_service.list_products(active=True, limit=500)
        dialog = SaleDialog(self.service, customers, products, parent)
        created = dialog.exec() == QDialog.DialogCode.Accepted
        self.last_created_record = dialog.created_sale if created else None
        return created

    def _open_selected(self) -> None:
        sale_id = self._selected_id()
        if sale_id is None:
            return
        dialog = SaleDetailsDialog(self.service, sale_id, self)
        dialog.exec()
        if dialog.changed:
            self.refresh()
            self.changed.emit()


class SalesWorkspacePage(QWidget):
    """Pestañas de ventas y propuestas; mantiene las señales esperadas por la ventana."""
    request_create = Signal()
    request_details = Signal(int)
    changed = Signal()
    action_label_changed = Signal(str)

    def __init__(self, sales_service, proposal_service, customer_service,
                 inventory_service, parent=None) -> None:
        super().__init__(parent)
        self.sales_service = sales_service
        self.proposals = ProposalPage(proposal_service, customer_service, self,
                                      sales_service=sales_service)
        self.sales = SalesPage(sales_service, customer_service, inventory_service, self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.proposals, "Propuestas a clientes")
        self.tabs.addTab(self.sales, "Ventas y pagos")
        self.tabs.currentChanged.connect(self._emit_action_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        self.proposals.request_create.connect(self.request_create)
        self.proposals.request_details.connect(self.request_details)
        self.sales.changed.connect(self.changed)

    @property
    def table(self) -> QTableWidget:
        return self.proposals.table

    @property
    def offset(self) -> int:
        return self.sales.offset if self.tabs.currentIndex() == 1 else self.proposals.offset

    @offset.setter
    def offset(self, value: int) -> None:
        if self.tabs.currentIndex() == 1:
            self.sales.offset = value
        else:
            self.proposals.offset = value

    def refresh(self) -> None:
        self.proposals.refresh()
        self.sales.refresh()

    def create_dialog(self, parent=None) -> bool:
        if self.tabs.currentIndex() == 1:
            return self.sales.create_dialog(parent)
        return self.proposals.create_dialog(parent)

    @property
    def last_created_record(self):
        if self.tabs.currentIndex() == 1:
            return getattr(self.sales, "last_created_record", None)
        return getattr(self.proposals, "last_created_record", None)

    def _emit_action_label(self, _index: int) -> None:
        label = "＋  Nueva venta" if self.tabs.currentIndex() == 1 else "＋  Nueva propuesta"
        self.action_label_changed.emit(label)

    def open_details(self, proposal_id: int, parent=None) -> bool:
        return self.proposals.open_details(proposal_id, parent)
