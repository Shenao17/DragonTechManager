"""Diálogos de devolución de ventas y de reversión clasificada de pagos."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QSpinBox,
    QTableWidget, QVBoxLayout,
)

from .pages import format_cop
from .widgets import build_table

_CONDITIONS = (("Dañado", "danado"), ("Incompleto", "incompleto"), ("No apto", "no_apto"), ("Otro", "otro"))
_REQUESTER_TYPES = (("Cliente", "cliente"), ("Interno", "interno"))
_NATURES = (
    ("Corrección de registro erróneo (el dinero nunca ingresó)", "correccion_registro_erroneo"),
    ("Reversión financiera real (ingresó y fue revertido)", "reversion_financiera_real"),
)
_SOURCES = (("Banco", "banco"), ("Operador", "operador"), ("Conciliación", "conciliacion"), ("Otro", "otro"))


def _combo(options) -> QComboBox:
    box = QComboBox()
    for label, value in options:
        box.addItem(label, value)
    return box


class PaymentReversalDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Revertir pago de venta")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("El pago original se conserva. Indica qué ocurrió realmente."))
        form = QFormLayout()
        self.nature = _combo(_NATURES)
        self.source = _combo(_SOURCES)
        self.reason = QLineEdit()
        self.evidence = QLineEdit()
        self.evidence.setPlaceholderText("Extracto, comprobante o conciliación que lo demuestra")
        form.addRow("Naturaleza *", self.nature)
        form.addRow("Origen del evento *", self.source)
        form.addRow("Motivo *", self.reason)
        form.addRow("Evidencia *", self.evidence)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("formError")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Continuar")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if not self.reason.text().strip() or not self.evidence.text().strip():
            self.error.setText("El motivo y la evidencia son obligatorios.")
            return
        self.accept()

    def values(self) -> dict:
        return {"reason": self.reason.text().strip(), "nature": self.nature.currentData(),
                "source": self.source.currentData(), "evidence": self.evidence.text().strip()}


class ReturnDialog(QDialog):
    """Captura una devolución parcial o total; no calcula reglas, las valida el servicio."""

    def __init__(self, sale: dict, lines: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Registrar devolución · {sale['codigo']}")
        self.setMinimumSize(900, 640)
        self.lines = [line for line in lines if line["cantidad_disponible"] > 0]
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Devolver no exige reembolso. Solo las unidades aptas vuelven al inventario; "
            "las demás se registran como pérdida."))
        self.table: QTableWidget = build_table(
            ["Concepto", "Disponible", "Devolver", "Reintegrar", "Condición si no se reintegra",
             "Valor reconocido (COP)"],
            column_widths=[300, 90, 90, 90, 190, 170], flexible_column=0)
        self.table.setRowCount(len(self.lines))
        self.devolver, self.reintegrar, self.condicion, self.valor = [], [], [], []
        for row, line in enumerate(self.lines):
            self.table.setItem(row, 0, self._item(line["descripcion"]))
            self.table.setItem(row, 1, self._item(str(line["cantidad_disponible"])))
            ret = QSpinBox(); ret.setRange(0, line["cantidad_disponible"])
            rest = QSpinBox(); rest.setRange(0, line["cantidad_disponible"])
            rest.setEnabled(line["producto_id"] is not None)
            cond = _combo(_CONDITIONS)
            val = QLineEdit(); val.setPlaceholderText(format_cop(line["precio_unitario_cop"]) + " c/u")
            ret.valueChanged.connect(lambda qty, r=rest, ln=line: r.setValue(qty if ln["producto_id"] is not None else 0))
            for col, widget in ((2, ret), (3, rest), (4, cond), (5, val)):
                self.table.setCellWidget(row, col, widget)
            self.table.setRowHeight(row, 48)
            self.devolver.append(ret); self.reintegrar.append(rest)
            self.condicion.append(cond); self.valor.append(val)
        layout.addWidget(self.table, 1)
        form = QFormLayout()
        self.reason = QLineEdit(); self.requester = QLineEdit()
        self.requester_type = _combo(_REQUESTER_TYPES); self.executor = QLineEdit()
        self.no_restock_reason = QLineEdit()
        self.no_restock_reason.setPlaceholderText("Obligatorio si hay unidades que no vuelven a stock")
        self.adjust_reason = QLineEdit()
        self.adjust_reason.setPlaceholderText("Obligatorio si reconoces menos que el precio")
        self.authorizer = QLineEdit(); self.reference = QLineEdit()
        for label, widget in (("Motivo de la devolución *", self.reason), ("Solicitante *", self.requester),
                              ("Tipo de solicitante *", self.requester_type),
                              ("Responsable de ejecución *", self.executor),
                              ("Motivo del no reintegro", self.no_restock_reason),
                              ("Motivo del valor reducido", self.adjust_reason),
                              ("Autorizador (si valor reducido)", self.authorizer),
                              ("Referencia de autorización", self.reference)):
            form.addRow(label, widget)
        layout.addLayout(form)
        self.error = QLabel(); self.error.setObjectName("formError"); self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Revisar y registrar")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _item(text: str):
        from PySide6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def lines_payload(self) -> list[dict]:
        payload = []
        for index, line in enumerate(self.lines):
            quantity = self.devolver[index].value()
            if quantity == 0:
                continue
            item = {"sale_line_id": line["venta_detalle_id"], "quantity": quantity,
                    "restock_quantity": self.reintegrar[index].value(),
                    "condition": self.condicion[index].currentData(),
                    "no_restock_reason": self.no_restock_reason.text().strip()}
            text = self.valor[index].text().strip()
            if text:
                if not text.isdigit():
                    raise ValueError("El valor reconocido debe ser un entero en pesos.")
                item["recognized_value_cop"] = int(text)
                item["value_adjustment_reason"] = self.adjust_reason.text().strip()
            payload.append(item)
        if not payload:
            raise ValueError("Indica la cantidad a devolver en al menos una línea.")
        return payload

    def values(self) -> dict:
        return {"lines": self.lines_payload(), "reason": self.reason.text().strip(),
                "requester": self.requester.text().strip(),
                "requester_type": self.requester_type.currentData(),
                "executor": self.executor.text().strip(),
                "authorizer": self.authorizer.text().strip(),
                "authorization_ref": self.reference.text().strip()}

    def _validate(self) -> None:
        try:
            self.values()
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()
