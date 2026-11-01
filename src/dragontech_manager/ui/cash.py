"""Entregas del día y arqueo de caja (solo lectura; el conteo físico no se guarda)."""

from datetime import date

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from dragontech_manager.services.cash import CashReportService
from dragontech_manager.services.errors import ServiceError
from .pages import format_cop
from .widgets import build_table, set_cell


class CashDialog(QDialog):
    def __init__(self, service: CashReportService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Entregas del día y arqueo de caja")
        self.setMinimumSize(980, 620)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.day = QLineEdit()
        self.day.setPlaceholderText("AAAA-MM-DD (vacío = hoy)")
        self.day.editingFinished.connect(self._render)
        refresh = QPushButton("Actualizar")
        refresh.clicked.connect(self._render)
        top.addWidget(QLabel("Día de negocio"))
        top.addWidget(self.day, 1)
        top.addWidget(refresh)
        layout.addLayout(top)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = build_table(["Hora (UTC)", "Venta", "Importe", "Medio", "Referencia", "Voucher", "Receptor"],
                                 column_widths=[200, 150, 150, 140, 190, 170, 180], flexible_column=4)
        self.table.setMinimumHeight(240)
        layout.addWidget(self.table, 1)
        form = QFormLayout()
        self.counted = QLineEdit()
        self.counted.setPlaceholderText("Suma física de los vouchers firmados entregados en efectivo")
        self.counted.textChanged.connect(self._render_difference)
        self.difference = QLabel("—")
        form.addRow("Conteo físico (no se guarda)", self.counted)
        form.addRow("Diferencia contra lo entregado", self.difference)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("formError")
        layout.addWidget(self.error)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._render()

    def _selected_day(self) -> str:
        return self.day.text().strip() or date.today().isoformat()

    def _render(self) -> None:
        try:
            day = self.day.text().strip() or None
            report = self.service.deliveries_of_day(day)
            self.arqueo = self.service.arqueo(day)
            self.error.clear()
        except ServiceError as error:
            self.error.setText(str(error))
            return
        a = self.arqueo
        by = {(r["criterio"], r["medio"]): r for r in report["por_criterio"]}
        registered = sum(r["importe_cop"] for r in report["por_criterio"] if r["criterio"] == "fecha_registro")
        effective = sum(r["importe_cop"] for r in report["por_criterio"] if r["criterio"] == "fecha_efectiva")
        self.summary.setText(
            f"{report['fecha']} · Efectivo entregado: {format_cop(a['entregado_efectivo_cop'])} · "
            f"Otros medios entregados: {format_cop(a['entregado_otros_medios_cop'])}\n"
            f"Comprometido en efectivo ese día: {format_cop(a['comprometido_efectivo_cop'])} · "
            f"Pendiente de entregar (hoy): {format_cop(a['pendiente_efectivo_cop'])} · "
            f"Anulado (hoy): {format_cop(a['anulado_efectivo_cop'])}\n"
            f"Entregas por fecha efectiva: {format_cop(effective)} · por fecha de registro: {format_cop(registered)}")
        self.table.setRowCount(len(report["entregas"]))
        for row, item in enumerate(report["entregas"]):
            for col, value in enumerate((item["ocurrido_efectivo_utc"], item["venta_codigo"], format_cop(item["importe_cop"]),
                                         item["medio"], item["referencia_externa"] or "—", item["voucher_codigo"] or "—",
                                         item["receptor"] or "—")):
                set_cell(self.table, row, col, value)
            self.table.setRowHeight(row, 40)
        self._render_difference()

    def _render_difference(self) -> None:
        text = self.counted.text().strip()
        if not text:
            self.difference.setText("—")
            return
        if not text.isdigit():
            self.difference.setText("Ingresa un entero en pesos.")
            return
        diff = int(text) - self.arqueo["entregado_efectivo_cop"]
        self.difference.setText(("Cuadra" if diff == 0 else "Sobra" if diff > 0 else "Falta") + f": {format_cop(abs(diff))}")
