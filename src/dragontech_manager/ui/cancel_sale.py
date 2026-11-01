"""Asistente de cancelación de una venta: guía los pasos aprobados sin crear conceptos nuevos."""

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .pages import format_cop


class CancelSaleDialog(QDialog):
    """Muestra lo que falta para cancelar y liquidar; cada paso abre la operación existente."""

    def __init__(self, load_status, steps: dict, parent=None) -> None:
        super().__init__(parent)
        self.load_status, self.steps = load_status, steps
        self.setWindowTitle("Cancelar venta")
        self.setMinimumWidth(700)
        layout = QVBoxLayout(self)
        intro = QLabel("Una venta se cancela devolviendo lo vendido. Si el cliente retiene bienes o servicios, ese valor "
                       "queda como cargo explícito: debe cobrarse, condonarse o castigarse. No se puede cerrar de otra forma.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        row = QHBoxLayout()
        self.buttons = {}
        for key, text in (("return", "1. Registrar devolución…"), ("compensate", "2. Compensar al cliente…"),
                          ("debt", "3. Cargo / deuda…")):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, k=key: self._run(k))
            row.addWidget(button)
            self.buttons[key] = button
        row.addStretch(1)
        layout.addLayout(row)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._render()

    def _run(self, key: str) -> None:
        self.steps[key]()
        self._render()

    def _render(self) -> None:
        status = self.load_status()
        sale = status["venta"]
        lines = [f"Estado: {sale['estado_comercial']} · Retenido por el cliente: {format_cop(sale['importe_neto_cop'])} · "
                 f"Pagado: {format_cop(sale['pagado_neto_cop'])}"]
        lines += [f"• {text}" for text in status["bloqueos"]] or ["✔ La venta está cancelada y liquidada."]
        self.summary.setText("\n".join(lines))
        self.buttons["compensate"].setEnabled(sale["sobrepago_pendiente_cop"] > 0)
        self.buttons["return"].setEnabled(status["unidades_pendientes"] > 0)
