"""Interfaz de productos, existencias y movimientos trazables."""

import sqlite3

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QStackedWidget, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from dragontech_manager.services.errors import ServiceError
from dragontech_manager.services.inventory import InventoryService
from .pages import format_cop
from .widgets import EmptyState, build_table, set_cell

_MOVEMENT_LABELS = {
    "compra": "Entrada por compra", "venta": "Salida por venta", "orden": "Salida por orden",
    "armado": "Salida por armado", "ajuste": "Ajuste", "reversion": "Reversión",
}


def _integer_value(text: str, label: str, *, allow_zero: bool = True) -> int:
    value = text.strip()
    if not value.isdigit():
        raise ValueError(f"{label} debe ser un entero en pesos colombianos.")
    result = int(value)
    if not allow_zero and result == 0:
        raise ValueError(f"{label} debe ser mayor que cero.")
    return result


class ProductDialog(QDialog):
    def __init__(self, service: InventoryService, parent=None, *, product: dict | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.product = product
        self.saved: dict | None = None
        self.setWindowTitle("Editar producto" if product else "Nuevo producto")
        self.setMinimumSize(680, 600)
        self.resize(820, 760)
        outer = QVBoxLayout(self)
        title = QLabel(self.windowTitle())
        title.setStyleSheet("font-size: 18pt; font-weight: 700;")
        outer.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setVerticalSpacing(16)
        self.sku = QLineEdit()
        self.name = QLineEdit()
        self.category = QLineEdit()
        self.description = QTextEdit()
        self.description.setMinimumHeight(125)
        self.unit_cost = QLineEdit()
        self.unit_price = QLineEdit()
        self.minimum_enabled = QCheckBox("Controlar alerta de stock mínimo")
        self.minimum = QSpinBox()
        self.minimum.setRange(0, 1_000_000)
        self.minimum_enabled.toggled.connect(self.minimum.setEnabled)
        self.minimum.setEnabled(False)
        self.active = QCheckBox("Producto activo")
        self.active.setChecked(True)
        form.addRow("Código / SKU *", self.sku)
        form.addRow("Nombre *", self.name)
        form.addRow("Categoría", self.category)
        form.addRow("Descripción", self.description)
        form.addRow("Costo actual (COP) *", self.unit_cost)
        form.addRow("Precio sugerido (COP) *", self.unit_price)
        form.addRow(self.minimum_enabled)
        form.addRow("Stock mínimo", self.minimum)
        form.addRow(self.active)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        outer.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("Guardar producto")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        if product:
            self.sku.setText(product["sku"])
            self.name.setText(product["nombre"])
            self.category.setText(product.get("categoria", ""))
            self.description.setPlainText(product["descripcion"])
            self.unit_cost.setText(str(product["costo_actual_cop"]))
            self.unit_price.setText(str(product["precio_actual_cop"]))
            self.minimum_enabled.setChecked(product["umbral_reposicion"] is not None)
            if product["umbral_reposicion"] is not None:
                self.minimum.setValue(product["umbral_reposicion"])
            self.active.setChecked(bool(product["activo"]))

    def _save(self) -> None:
        try:
            values = dict(
                sku=self.sku.text(), name=self.name.text(), category=self.category.text(),
                description=self.description.toPlainText(),
                unit_cost_cop=_integer_value(self.unit_cost.text(), "El costo"),
                suggested_price_cop=_integer_value(self.unit_price.text(), "El precio"),
                minimum_stock=self.minimum.value() if self.minimum_enabled.isChecked() else None,
            )
            if self.product:
                self.saved = self.service.update_product(
                    self.product["id"], **values, active=self.active.isChecked()
                )
            else:
                self.saved = self.service.create_product(**values)
        except (ValueError, ServiceError) as error:
            self.error.setText(str(error))
            return
        except sqlite3.Error:
            self.error.setText("No se pudo guardar el producto en SQLite. Los datos siguen en el formulario.")
            return
        self.accept()


class StockAdjustmentDialog(QDialog):
    def __init__(self, product: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Registrar ajuste de inventario")
        self.setMinimumSize(560, 430)
        self.resize(660, 500)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Ajuste documentado · {product['sku']} · {product['nombre']}"))
        hint = QLabel("Usa una cantidad positiva para entrada o negativa para salida. El motivo queda en el historial.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.delta = QLineEdit()
        self.delta.setPlaceholderText("Ej. 5 o -2")
        self.cost = QLineEdit(str(product["costo_actual_cop"]))
        self.reason = QTextEdit()
        self.reason.setMinimumHeight(120)
        form.addRow("Cantidad con signo *", self.delta)
        form.addRow("Costo unitario histórico (COP) *", self.cost)
        form.addRow("Motivo *", self.reason)
        layout.addLayout(form, 1)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Registrar movimiento")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[int, int, str]:
        delta_text = self.delta.text().strip()
        if not delta_text or delta_text in {"+", "-"}:
            raise ValueError("Ingresa una cantidad entera con signo.")
        try:
            delta = int(delta_text)
        except ValueError as error:
            raise ValueError("La cantidad debe ser un entero, por ejemplo 5 o -2.") from error
        cost = _integer_value(self.cost.text(), "El costo")
        reason = self.reason.toPlainText().strip()
        if not reason:
            raise ValueError("El motivo del ajuste es obligatorio.")
        return delta, cost, reason


class ProductDetailDialog(QDialog):
    changed = False

    def __init__(self, service: InventoryService, product_id: int, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.product_id = product_id
        self.changed = False
        self.movement_offset = 0
        self.movement_page_size = 100
        self.setWindowTitle("Detalle de producto e historial")
        self.setMinimumSize(820, 620)
        self.resize(1120, 820)
        outer = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        actions = QHBoxLayout()
        self.adjust_button = QPushButton("Ajustar inventario")
        self.adjust_button.setObjectName("primaryButton")
        self.reverse_button = QPushButton("Revertir movimiento seleccionado")
        self.reverse_button.setEnabled(False)
        close = QPushButton("Cerrar")
        actions.addWidget(self.adjust_button)
        actions.addWidget(self.reverse_button)
        actions.addStretch(1)
        actions.addWidget(close)
        self.table = build_table(
            ["Tipo", "Cantidad", "Costo unitario", "Fecha UTC", "Referencia / motivo"],
            column_widths=[190, 110, 170, 220, 370], flexible_column=4,
        )
        self.table.setMinimumHeight(320)
        outer.addWidget(self.table, 1)
        history_controls = QHBoxLayout()
        self.history_page_label = QLabel()
        self.history_page_label.setObjectName("muted")
        self.history_previous = QPushButton("‹ Movimientos anteriores")
        self.history_next = QPushButton("Movimientos siguientes ›")
        history_controls.addWidget(self.history_page_label)
        history_controls.addStretch(1)
        history_controls.addWidget(self.history_previous)
        history_controls.addWidget(self.history_next)
        outer.addLayout(history_controls)
        outer.addLayout(actions)
        self.adjust_button.clicked.connect(self._adjust)
        self.reverse_button.clicked.connect(self._reverse)
        self.table.itemSelectionChanged.connect(self._sync_reverse)
        self.history_previous.clicked.connect(self._previous_movements)
        self.history_next.clicked.connect(self._next_movements)
        close.clicked.connect(self.accept)
        self._refresh()

    def _refresh(self) -> None:
        product = self.service.get_product(self.product_id)
        self.product = product
        self.setWindowTitle(f"{product['sku']} · {product['nombre']} · Movimientos")
        self.summary.setText(
            f"Categoría: {product['categoria'] or '—'}   ·   Existencia: {product['existencia']}   ·   "
            f"Reservado: {product['reservado']}   ·   Disponible: {product['disponible']}\n"
            f"Costo actual: {format_cop(product['costo_actual_cop'])}   ·   "
            f"Precio sugerido: {format_cop(product['precio_actual_cop'])}\n"
            f"{product['descripcion'] or 'Sin descripción'}"
        )
        movements = self.service.product_movements(
            self.product_id, limit=self.movement_page_size + 1, offset=self.movement_offset
        )
        has_next = len(movements) > self.movement_page_size
        movements = movements[:self.movement_page_size]
        self.table.setRowCount(len(movements))
        for row, move in enumerate(movements):
            reference = move["motivo"] or ""
            if move["compra_id"] is not None:
                reference = f"Compra #{move['compra_id']} {move['compra_referencia'] or ''} · {reference}".strip()
            elif move["venta_codigo"]:
                reference = f"Venta {move['venta_codigo']} · {reference}".strip()
            elif move["orden_codigo"]:
                reference = f"Orden {move['orden_codigo']} · {reference}".strip()
            elif move["armado_codigo"]:
                reference = f"Armado {move['armado_codigo']} · {reference}".strip()
            values = (
                _MOVEMENT_LABELS[move["tipo"]],
                f"+{move['cantidad_delta']}" if move["cantidad_delta"] > 0 else str(move["cantidad_delta"]),
                format_cop(move["costo_unitario_historico_cop"]), move["creado_en_utc"], reference or "—",
            )
            for column, value in enumerate(values):
                set_cell(self.table, row, column, value)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, move["id"])
            self.table.setRowHeight(row, 50)
        self._sync_reverse()
        self.history_previous.setEnabled(self.movement_offset > 0)
        self.history_next.setEnabled(has_next)
        self.history_page_label.setText(
            f"Movimientos {self.movement_offset + 1}–{self.movement_offset + len(movements)}"
            if movements else "Sin movimientos"
        )

    def _previous_movements(self) -> None:
        self.movement_offset = max(0, self.movement_offset - self.movement_page_size)
        self._refresh()

    def _next_movements(self) -> None:
        self.movement_offset += self.movement_page_size
        self._refresh()

    def _adjust(self) -> None:
        dialog = StockAdjustmentDialog(self.product, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            delta, cost, reason = dialog.values()
            self.service.adjust_stock(self.product_id, delta, unit_cost_cop=cost, reason=reason)
            self.changed = True
            self.movement_offset = 0
            self._refresh()
        except (ValueError, ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo registrar el ajuste", str(error))

    def _selected_movement_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _sync_reverse(self) -> None:
        movement_id = self._selected_movement_id()
        self.reverse_button.setEnabled(bool(movement_id and self.service.can_reverse_movement(movement_id)))

    def _reverse(self) -> None:
        movement_id = self._selected_movement_id()
        if movement_id is None:
            return
        reason, accepted = QInputDialog.getText(self, "Revertir movimiento", "Motivo de la corrección:")
        if not accepted:
            return
        try:
            self.service.reverse_movement(movement_id, reason=reason)
            self.changed = True
            self.movement_offset = 0
            self._refresh()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo revertir el movimiento", str(error))


class ProductPage(QWidget):
    changed = Signal()

    def __init__(self, service: InventoryService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.offset = 0
        self.page_size = 100
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(14)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        layout.addWidget(self.summary)
        tools = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar SKU, nombre, descripción o categoría…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(440)
        tools.addWidget(self.search)
        self.stock_filter = QComboBox()
        for label, value in (("Todo el inventario", "todos"), ("Agotados", "agotado"),
                             ("Stock bajo", "bajo"), ("Con existencias", "disponible")):
            self.stock_filter.addItem(label, value)
        tools.addWidget(self.stock_filter)
        self.active_filter = QComboBox()
        self.active_filter.addItem("Activos", True)
        self.active_filter.addItem("Inactivos", False)
        self.active_filter.addItem("Todos", None)
        tools.addWidget(self.active_filter)
        tools.addStretch(1)
        self.add_button = QPushButton("＋ Nuevo producto")
        self.add_button.setObjectName("primaryButton")
        self.edit_button = QPushButton("Editar")
        self.detail_button = QPushButton("Ver movimientos")
        self.edit_button.setEnabled(False)
        self.detail_button.setEnabled(False)
        tools.addWidget(self.add_button)
        tools.addWidget(self.edit_button)
        tools.addWidget(self.detail_button)
        layout.addLayout(tools)
        self.table = build_table(
            ["SKU", "Producto", "Categoría", "Costo", "Precio sugerido", "Existencia", "Reservado", "Stock mínimo", "Estado"],
            column_widths=[140, 250, 150, 170, 180, 100, 100, 120, 115], flexible_column=1,
        )
        self.table.setMinimumHeight(320)
        layout.addWidget(self.table, 1)
        page_controls = QHBoxLayout()
        self.page_label = QLabel()
        self.page_label.setObjectName("muted")
        self.previous = QPushButton("‹ Anterior")
        self.next = QPushButton("Siguiente ›")
        page_controls.addWidget(self.page_label)
        page_controls.addStretch(1)
        page_controls.addWidget(self.previous)
        page_controls.addWidget(self.next)
        layout.addLayout(page_controls)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self._new_search)
        self.search.textChanged.connect(lambda _text: self.search_timer.start())
        self.stock_filter.currentIndexChanged.connect(self._new_search)
        self.active_filter.currentIndexChanged.connect(self._new_search)
        self.add_button.clicked.connect(self._create)
        self.edit_button.clicked.connect(self._edit)
        self.detail_button.clicked.connect(self._details)
        self.table.cellDoubleClicked.connect(lambda *_: self._details())
        self.table.itemSelectionChanged.connect(self._sync_selection)
        self.previous.clicked.connect(self._previous)
        self.next.clicked.connect(self._next)
        self.refresh()

    def _new_search(self, *_args) -> None:
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
            summary = self.service.stock_summary()
            self.summary.setText(f"{summary['agotados']} sin existencias   ·   {summary['bajos']} con stock bajo")
            rows = self.service.list_products(
                search=self.search.text(), stock_filter=self.stock_filter.currentData(),
                active=self.active_filter.currentData(), limit=self.page_size + 1, offset=self.offset,
            )
        except (ServiceError, sqlite3.Error, OSError) as error:
            QMessageBox.warning(self, "No se pudo cargar el inventario", str(error))
            return
        has_next = len(rows) > self.page_size
        rows = rows[:self.page_size]
        self.table.setRowCount(len(rows))
        for row, product in enumerate(rows):
            status = "Inactivo" if not product["activo"] else (
                "Agotado" if product["existencia"] == 0 else
                "Stock bajo" if product["umbral_reposicion"] is not None and product["existencia"] <= product["umbral_reposicion"] else "Disponible"
            )
            values = (product["sku"], product["nombre"], product["categoria"] or "—",
                      format_cop(product["costo_actual_cop"]), format_cop(product["precio_actual_cop"]),
                      product["existencia"], product["reservado"],
                      product["umbral_reposicion"] if product["umbral_reposicion"] is not None else "—", status)
            for column, value in enumerate(values):
                set_cell(self.table, row, column, value)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, product["id"])
            self.table.setRowHeight(row, 49)
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(has_next)
        self.page_label.setText(f"{self.offset + 1}–{self.offset + len(rows)}" if rows else "Sin productos")
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
        dialog = ProductDialog(self.service, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.offset = 0
            self.refresh()
            self.changed.emit()

    def _edit(self) -> None:
        product_id = self._selected_id()
        if product_id is None:
            return
        try:
            dialog = ProductDialog(self.service, self, product=self.service.get_product(product_id))
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.refresh()
                self.changed.emit()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo abrir el producto", str(error))

    def _details(self) -> None:
        product_id = self._selected_id()
        if product_id is None:
            return
        try:
            dialog = ProductDetailDialog(self.service, product_id, self)
            dialog.exec()
            if dialog.changed:
                self.refresh()
                self.changed.emit()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo cargar el historial", str(error))


class InventoryWorkspacePage(QWidget):
    """Pestañas integradas para productos, proveedores y compras."""

    def __init__(self, inventory_service, procurement_service, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 20)
        self.tabs = QTabWidget()
        self.products = ProductPage(inventory_service)
        from .procurement import PurchasePage, SupplierPage
        self.suppliers = SupplierPage(inventory_service, procurement_service)
        self.purchases = PurchasePage(inventory_service, procurement_service)
        self.tabs.addTab(self.products, "Productos y existencias")
        self.tabs.addTab(self.suppliers, "Proveedores")
        self.tabs.addTab(self.purchases, "Compras y pagos")
        layout.addWidget(self.tabs, 1)
        self.products.changed.connect(self.purchases.refresh)
        self.purchases.changed.connect(self.products.refresh)
        self.purchases.changed.connect(self.suppliers.refresh)
