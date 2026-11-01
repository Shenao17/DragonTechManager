"""Panel de pendientes: entregas de reembolso por confirmar y solicitudes de operación sin completar."""

import sqlite3

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from dragontech_manager.services import operation_retry
from dragontech_manager.services.compensations import CompensationService
from dragontech_manager.services.errors import ServiceError
from dragontech_manager.services.operations import REJECTED, OperationRegistry
from .compensations import CompensationsDialog
from .pages import format_cop, format_local_datetime
from .widgets import build_table, set_cell

_STATE_LABELS = {"comprometida": "Comprometida", "preparada": "Voucher preparado", "en_investigacion": "En investigación",
                 "entregada": "Entregada (en investigación)"}


def pending_count(connection: sqlite3.Connection) -> int:
    """Pendientes totales; consulta barata para el indicador de la ventana."""
    deliveries = connection.execute("SELECT COUNT(*) FROM v_compensaciones_pendientes").fetchone()[0]
    requests = connection.execute("SELECT COUNT(*) FROM solicitudes_operacion WHERE estado = 'pendiente'").fetchone()[0]
    return deliveries + requests


class PendingOperationsDialog(QDialog):
    def __init__(self, connection: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.connection = connection
        self.compensations = CompensationService(connection)
        self.registry = OperationRegistry(connection)
        self.registry.reconcile()  # cierra solicitudes cuya operación ya se confirmó (Informe2 §3.5)
        self.setWindowTitle("Operaciones pendientes")
        self.setMinimumSize(1020, 640)
        layout = QVBoxLayout(self)
        note = QLabel("Una entrega preparada nunca se anula automáticamente: el dinero pudo haber salido. "
                      "Verifica el voucher y el efectivo antes de confirmar, anular o marcar en investigación.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel("Entregas de reembolso por confirmar"))
        self.deliveries = build_table(["Venta", "Importe", "Medio", "Estado", "Voucher", "Antigüedad"],
                                      column_widths=[200, 150, 150, 220, 190, 120], flexible_column=3)
        self.deliveries.setMinimumHeight(170)
        layout.addWidget(self.deliveries, 1)
        row = QHBoxLayout()
        self.manage_button = QPushButton("Gestionar entrega seleccionada")
        self.manage_button.clicked.connect(self._manage)
        row.addWidget(self.manage_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(QLabel("Solicitudes de operación sin completar (cierre inesperado o rechazo)"))
        self.requests = build_table(["Operación", "Resumen", "Solicitó", "Creada", "Detalle"],
                                    column_widths=[170, 330, 140, 190, 330], flexible_column=1)
        self.requests.setMinimumHeight(170)
        layout.addWidget(self.requests, 1)
        row = QHBoxLayout()
        self.retry_button = QPushButton("Reintentar")
        self.abandon_button = QPushButton("Abandonar")
        self.retry_button.clicked.connect(self._retry)
        self.abandon_button.clicked.connect(self._abandon)
        row.addWidget(self.retry_button)
        row.addWidget(self.abandon_button)
        row.addStretch(1)
        layout.addLayout(row)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._render()

    def _render(self) -> None:
        self.delivery_items = self.compensations.pending_deliveries()
        self.deliveries.setRowCount(len(self.delivery_items))
        for row, item in enumerate(self.delivery_items):
            for col, value in enumerate((item["venta_codigo"], format_cop(item["importe_cop"]), item["metodo_nombre"] or "—",
                                         _STATE_LABELS.get(item["estado"], item["estado"]), item["voucher_codigo"] or "—",
                                         f"{item['antiguedad_dias']} d")):
                set_cell(self.deliveries, row, col, value)
            self.deliveries.setRowHeight(row, 44)
        self.request_items = self.registry.pending()
        self.requests.setRowCount(len(self.request_items))
        for row, item in enumerate(self.request_items):
            detail = item["detalle"] or "Sin confirmar (posible cierre inesperado)"
            for col, value in enumerate((item["tipo_operacion"].replace("_", " "), item["resumen"], item["solicitado_por"],
                                         format_local_datetime(item["creada_en_utc"]), detail)):
                set_cell(self.requests, row, col, value)
            self.requests.setRowHeight(row, 46)
        self.manage_button.setEnabled(bool(self.delivery_items))
        self.retry_button.setEnabled(bool(self.request_items))
        self.abandon_button.setEnabled(bool(self.request_items))

    def _selected(self, table, items):
        row = table.currentRow()
        return items[row] if 0 <= row < len(items) else None

    def _manage(self) -> None:
        item = self._selected(self.deliveries, self.delivery_items)
        if item is None:
            QMessageBox.information(self, "Selecciona una entrega", "Elige la entrega que quieres gestionar.")
            return
        CompensationsDialog(self.compensations, item["venta_id"], self).exec()
        self._render()

    def _retry(self) -> None:
        item = self._selected(self.requests, self.request_items)
        if item is None:
            QMessageBox.information(self, "Selecciona una solicitud", "Elige la solicitud que quieres reintentar.")
            return
        try:
            outcome = operation_retry.retry(self.connection, item["clave_idempotencia"])
            QMessageBox.information(self, "Solicitud completada",
                                    "La operación se completó." if outcome["reintentada"] else "La operación ya estaba registrada.")
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo reintentar", f"{error}\n\nPuedes corregir la causa y reintentar, o abandonar la solicitud.")
        self._render()

    def _abandon(self) -> None:
        item = self._selected(self.requests, self.request_items)
        if item is None:
            QMessageBox.information(self, "Selecciona una solicitud", "Elige la solicitud que quieres abandonar.")
            return
        reason, accepted = QInputDialog.getText(self, "Abandonar solicitud", "Motivo (no se borra nada; la clave queda retirada):")
        if not accepted:
            return
        try:
            self.registry.abandon(item["clave_idempotencia"], reason)
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo abandonar", str(error))
        self._render()


__all__ = ["PendingOperationsDialog", "pending_count", "REJECTED"]
