"""Diálogos de compensación de devoluciones, entrega de reembolsos y saldo a favor."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from dragontech_manager.services.errors import ServiceError
from dragontech_manager.services.idempotency import IntentKey
from .pages import format_cop
from .widgets import build_table, set_cell

_STATES = {"comprometida": "Comprometida", "preparada": "Voucher preparado", "entregada": "Entregada",
           "anulada": "Anulada", "en_investigacion": "En investigación", "corregida": "Corregida",
           "acreditada": "Crédito acreditado"}
_MEDIA = (("Efectivo", "efectivo"), ("Transferencia", "transferencia"), ("Tarjeta", "tarjeta"))


def _pesos(text: str, label: str) -> int:
    text = text.strip()
    if not text:
        return 0
    if not text.isdigit():
        raise ValueError(f"{label} debe ser un entero en pesos colombianos.")
    return int(text)


class FormDialog(QDialog):
    """Formulario mínimo de texto/combos; la validación de negocio la hace el servicio."""

    def __init__(self, title: str, intro: str, fields: list[tuple], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        label = QLabel(intro)
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        self.widgets: dict[str, object] = {}
        for key, caption, kind, *extra in fields:
            if kind == "combo":
                widget = QComboBox()
                for text, value in extra[0]:
                    widget.addItem(text, value)
            elif kind == "check":
                widget = QCheckBox()
            else:
                widget = QLineEdit(extra[0] if extra else "")
            self.widgets[key] = widget
            form.addRow(caption, widget)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Continuar")
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        result = {}
        for key, widget in self.widgets.items():
            if isinstance(widget, QComboBox):
                result[key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                result[key] = widget.isChecked()
            else:
                result[key] = widget.text().strip()
        return result


def compensation_form(sale: dict, methods: list[dict], parent=None) -> FormDialog:
    available = sale["sobrepago_pendiente_cop"]
    return FormDialog(
        "Compensar devolución",
        f"Sobrepago pendiente de compensar: {format_cop(available)}. Puedes reembolsar, acreditar "
        "como saldo a favor o repartir entre ambos. Requiere autorizador distinto del ejecutor.",
        [("refund", "Reembolso (COP)", "text", str(available)), ("credit", "Saldo a favor (COP)", "text", ""),
         ("method", "Medio del reembolso", "combo",
          [(m["nombre"], m["id"]) for m in methods if m["familia"] in {"efectivo", "transferencia", "tarjeta"}]),
         ("consent", "El cliente acepta recibir saldo a favor en lugar de efectivo", "check"),
         ("reason", "Motivo *", "text"), ("executor", "Responsable de ejecución *", "text"),
         ("authorizer", "Autorizador *", "text"), ("authorization_ref", "Referencia de autorización *", "text")],
        parent)


class CompensationsDialog(QDialog):
    """Compromisos de un sale: preparar voucher, confirmar entrega, anular o investigar."""

    def __init__(self, compensation_service, sale_id: int, parent=None) -> None:
        super().__init__(parent)
        self.service = compensation_service
        self.sale_id = sale_id
        self.changed = False
        self._intents: dict[str, IntentKey] = {}
        self.setWindowTitle("Reembolsos y saldo a favor de la venta")
        self.setMinimumSize(980, 520)
        layout = QVBoxLayout(self)
        self.table = build_table(["Tipo", "Importe", "Medio", "Estado", "Voucher", "Autorizó"],
                                 column_widths=[120, 150, 150, 190, 170, 190], flexible_column=3)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for key, text, handler in (("prepare", "Preparar voucher", self._prepare),
                                   ("deliver", "Confirmar entrega", self._deliver),
                                   ("annul", "Anular", self._annul),
                                   ("investigate", "Marcar en investigación", self._investigate)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch(1)
        layout.addLayout(row)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.table.itemSelectionChanged.connect(self._sync)
        self._render()

    def _render(self) -> None:
        self.items = self.service.list_for_sale(self.sale_id)
        self.table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            values = ("Reembolso" if item["tipo"] == "reembolso" else "Saldo a favor",
                      format_cop(item["importe_cop"]), item["metodo_nombre"] or "—",
                      _STATES[item["estado"]], item["voucher_codigo"] or "—", item["autorizador"])
            for col, value in enumerate(values):
                set_cell(self.table, row, col, value)
            self.table.setRowHeight(row, 46)
        self._sync()

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    def _sync(self) -> None:
        item = self._selected()
        state = item["estado"] if item and item["tipo"] == "reembolso" else None
        self.buttons["prepare"].setEnabled(state == "comprometida")
        self.buttons["deliver"].setEnabled(state in {"comprometida", "preparada", "en_investigacion"})
        self.buttons["annul"].setEnabled(state in {"comprometida", "preparada", "en_investigacion"})
        self.buttons["investigate"].setEnabled(state == "preparada")

    def _run(self, name: str, dialog: FormDialog | None, call) -> None:
        item = self._selected()
        if item is None:
            return
        values = {}
        if dialog is not None:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            values = dialog.values()
        intent = self._intents.setdefault(f"{name}:{item['id']}", IntentKey())
        try:
            key = intent.for_payload({"id": item["id"], **values})
            for button in self.buttons.values():
                button.setEnabled(False)
            call(item, values, key)
            intent.complete()
            self.changed = True
            self.error.clear()
        except (ValueError, ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo completar la operación", str(error))
        finally:
            self._render()

    def _prepare(self) -> None:
        dialog = FormDialog("Preparar voucher", "Se genera el voucher de la entrega; reimprimirlo no crea otro.",
                            [("by", "Registrado por *", "text")], self)
        self._run("prepare", dialog, lambda item, v, key: self.service.prepare(
            item["id"], registered_by=v["by"], idempotency_key=key))

    def _deliver(self) -> None:
        item = self._selected()
        if item is None:
            return
        dialog = FormDialog(
            "Confirmar entrega", "Registra que el dinero ya salió. Solo se confirma una vez. En transferencias "
            "y tarjetas la referencia es obligatoria.",
            [("medium", "Medio", "combo", list(_MEDIA)), ("reference", "Referencia externa", "text"),
             ("by", "Registrado por *", "text")], self)
        medium = dialog.widgets["medium"]
        medium.setCurrentIndex(max(0, medium.findData((item.get("metodo_familia") or "efectivo"))))
        self._run("deliver", dialog, lambda it, v, key: self.service.confirm_delivery(
            it["id"], registered_by=v["by"], idempotency_key=key, medium=v["medium"],
            external_reference=v["reference"]))

    def _annul(self) -> None:
        dialog = FormDialog("Anular compromiso", "Libera el tope del reembolso. Requiere autorizador distinto.",
                            [("reason", "Motivo *", "text"), ("by", "Registrado por *", "text"),
                             ("authorizer", "Autorizador *", "text"), ("ref", "Referencia de autorización *", "text")], self)
        self._run("annul", dialog, lambda item, v, key: self.service.annul(
            item["id"], reason=v["reason"], registered_by=v["by"], authorizer=v["authorizer"],
            authorization_ref=v["ref"], idempotency_key=key))

    def _investigate(self) -> None:
        dialog = FormDialog("Marcar en investigación",
                            "Bloquea nuevas entregas y reembolsos de esta venta hasta resolver.",
                            [("reason", "Motivo *", "text"), ("by", "Registrado por *", "text")], self)
        self._run("investigate", dialog, lambda item, v, key: self.service.mark_under_investigation(
            item["id"], reason=v["reason"], registered_by=v["by"], idempotency_key=key))


def apply_credit_form(balance: int, pending: int, parent=None) -> FormDialog:
    return FormDialog(
        "Aplicar saldo a favor",
        f"Saldo a favor disponible: {format_cop(balance)} · Saldo pendiente de la venta: {format_cop(pending)}.",
        [("amount", "Importe a aplicar (COP) *", "text", str(min(balance, pending))),
         ("reason", "Motivo *", "text"), ("by", "Registrado por *", "text")], parent)
