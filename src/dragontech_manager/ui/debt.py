"""Deuda de una venta: condonación, castigo, recuperación H e historial financiero."""

import sqlite3

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from dragontech_manager.services.actors import AUTH_MEDIA, IDENTITY_WARNING
from dragontech_manager.services.errors import ServiceError
from dragontech_manager.services.idempotency import IntentKey
from .actors import actor_options
from .compensations import FormDialog, _pesos
from .pages import format_cop
from .widgets import build_table, set_cell

_MEDIA_LABELS = {"presencial": "Presencial", "telefono": "Teléfono", "whatsapp": "WhatsApp", "correo": "Correo",
                 "documento_firmado": "Documento firmado", "otro": "Otro"}
_KINDS = {"condonacion": "Condonación", "castigo": "Castigo"}


class DebtDialog(QDialog):
    def __init__(self, debt_service, sale_id: int, methods: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.service, self.sale_id, self.methods = debt_service, sale_id, methods
        self.changed = False
        self._intents: dict[str, IntentKey] = {}
        self.setWindowTitle("Deuda y liquidación de la venta")
        self.setMinimumSize(1000, 640)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.extinctions = build_table(["Tipo", "Importe", "Vigente", "Autorizó", "Ejecutó", "Motivo"],
                                       column_widths=[130, 150, 150, 190, 190, 330], flexible_column=5)
        self.extinctions.setMinimumHeight(150)
        layout.addWidget(QLabel("Condonaciones y castigos (no mueven caja)"))
        layout.addWidget(self.extinctions, 1)
        self.history = build_table(["Fecha", "Evento", "Residuo", "Caja", "Responsable"],
                                   column_widths=[120, 480, 150, 150, 180], flexible_column=1)
        self.history.setMinimumHeight(190)
        layout.addWidget(QLabel("Historial financiero (la suma del residuo es el residuo de liquidación)"))
        layout.addWidget(self.history, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for key, text, handler in (("forgive", "Condonar", lambda: self._extinguish("condonacion")),
                                   ("write_off", "Castigar", lambda: self._extinguish("castigo")),
                                   ("annul", "Anular extinción seleccionada", self._annul),
                                   ("recover", "Registrar recuperación", self._recover)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch(1)
        layout.addLayout(row)
        warning = QLabel(IDENTITY_WARNING)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._render()

    def _render(self) -> None:
        data = self.service.list_for_sale(self.sale_id)
        liq, self.items = data["liquidacion"], data["extinciones"]
        self.summary.setText(
            f"Estado comercial: {liq['estado_comercial']} · Liquidación: {liq['estado_liquidacion']}\n"
            f"Deuda bruta: {format_cop(liq['deuda_bruta_cop'])} · Recuperado: {format_cop(liq['recuperado_cop'])} · "
            f"Condonado: {format_cop(liq['condonado_cop'])} · Castigado: {format_cop(liq['castigado_cop'])} · "
            f"Deuda pendiente: {format_cop(liq['deuda_pendiente_cop'])} · Residuo: {format_cop(liq['residuo_liquidacion_cop'])}\n"
            f"Cobrable como pago de venta: {format_cop(liq['saldo_pendiente_cop'])} · "
            f"Reembolsado sin respaldo: {format_cop(liq['exceso_reembolsado_cop'])}")
        self.extinctions.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            for col, value in enumerate((_KINDS[item["tipo"]], format_cop(item["importe_cop"]),
                                         format_cop(item["importe_vigente_cop"]), item["autorizador_nombre"],
                                         item["ejecutor_nombre"], item["motivo"])):
                set_cell(self.extinctions, row, col, value)
            self.extinctions.setRowHeight(row, 44)
        history = self.service.history(self.sale_id)
        self.history.setRowCount(len(history))
        for row, event in enumerate(history):
            for col, value in enumerate((event["fecha_negocio"], event["descripcion"],
                                         format_cop(event["efecto_residuo_cop"]), format_cop(event["efecto_caja_cop"]),
                                         event["responsable"] or "—")):
                set_cell(self.history, row, col, value)
            self.history.setRowHeight(row, 40)
        pending = liq["deuda_pendiente_cop"] > 0
        self.buttons["forgive"].setEnabled(pending)
        self.buttons["write_off"].setEnabled(pending)
        self.buttons["annul"].setEnabled(any(i["importe_vigente_cop"] > 0 for i in self.items))
        self.buttons["recover"].setEnabled(pending)

    def _actor_fields(self):
        return [("executor", "Responsable de ejecución *", "combo", actor_options(self.service.actors.list_actors())),
                ("authorizer", "Autorizador *", "combo", actor_options(self.service.actors.list_authorizers())),
                ("ref", "Referencia de autorización *", "text"),
                ("medium", "Medio de autorización *", "combo", [(v, k) for k, v in _MEDIA_LABELS.items()])]

    def _call(self, name: str, dialog: FormDialog, call) -> None:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        v = dialog.values()
        intent = self._intents.setdefault(name, IntentKey())
        try:
            key = intent.for_payload(v)
            for button in self.buttons.values():
                button.setEnabled(False)
            call(v, key)
            intent.complete()
            self.changed = True
        except (ValueError, ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo completar la operación", str(error))
        finally:
            self._render()

    def _extinguish(self, kind: str) -> None:
        pending = self.service.liquidation(self.sale_id)["deuda_pendiente_cop"]
        fields = [("amount", "Importe (COP) *", "text", str(pending)), ("reason", "Motivo *", "text")]
        if kind == "castigo":
            fields.append(("evidence", "Evidencia de las gestiones de cobro *", "text"))
        dialog = FormDialog(
            _KINDS[kind], f"Deuda pendiente: {format_cop(pending)}. No mueve caja ni se registra como pago. "
            "Requiere autorizador distinto con límite definido.", fields + self._actor_fields(), self)

        def call(v, key):
            common = dict(reason=v["reason"], executor=v["executor"], authorizer=v["authorizer"],
                          authorization_ref=v["ref"], authorization_medium=v["medium"], idempotency_key=key)
            amount = _pesos(v["amount"], "El importe")
            if kind == "condonacion":
                self.service.forgive(self.sale_id, amount, **common)
            else:
                self.service.write_off(self.sale_id, amount, collection_evidence=v["evidence"], **common)
        self._call(kind, dialog, call)

    def _annul(self) -> None:
        row = self.extinctions.currentRow()
        item = self.items[row] if 0 <= row < len(self.items) else None
        if item is None or item["importe_vigente_cop"] <= 0:
            QMessageBox.information(self, "Selecciona una extinción", "Elige una extinción con importe vigente.")
            return
        dialog = FormDialog("Anular extinción", "La deuda reaparece por el importe anulado; el hecho original se conserva.",
                            [("amount", "Importe a anular (COP) *", "text", str(item["importe_vigente_cop"])),
                             ("reason", "Motivo *", "text")] + self._actor_fields(), self)
        self._call(f"annul{item['id']}", dialog, lambda v, key: self.service.annul_extinction(
            item["id"], _pesos(v["amount"], "El importe"), reason=v["reason"], executor=v["executor"],
            authorizer=v["authorizer"], authorization_ref=v["ref"], authorization_medium=v["medium"],
            idempotency_key=key))

    def _recover(self) -> None:
        dialog = FormDialog(
            "Registrar recuperación", "Dinero real que cubre la deuda que NO cabe en un pago normal de la venta "
            "(por ejemplo, un reembolso entregado cuyo pago fue revertido). Entra a caja pero no aumenta lo pagado.",
            [("amount", "Importe (COP) *", "text"),
             ("method", "Medio de cobro *", "combo", [(m["nombre"], m["id"]) for m in self.methods]),
             ("reference", "Referencia externa", "text"), ("reason", "Motivo *", "text")] + self._actor_fields(), self)
        self._call("recover", dialog, lambda v, key: self.service.record_recovery(
            self.sale_id, _pesos(v["amount"], "El importe"), method=v["method"], reason=v["reason"],
            reference=v["reference"], executor=v["executor"], authorizer=v["authorizer"],
            authorization_ref=v["ref"], authorization_medium=v["medium"], idempotency_key=key))
