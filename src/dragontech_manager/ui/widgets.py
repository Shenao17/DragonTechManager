"""Controles visuales reutilizables de la aplicación."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class MetricCard(QFrame):
    def __init__(self, title: str, detail: str, accent: str = "#5E9188") -> None:
        super().__init__()
        self.setProperty("role", "surface")
        self.setMinimumHeight(140)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 17, 18, 16)
        layout.setSpacing(8)

        stripe = QFrame()
        stripe.setFixedSize(34, 3)
        stripe.setStyleSheet(f"background: {accent}; border-radius: 1px;")
        layout.addWidget(stripe)

        title_label = QLabel(title.upper())
        title_label.setObjectName("metricTitle")
        layout.addWidget(title_label)

        self.value_label = QLabel("—")
        self.value_label.setObjectName("metricValue")
        layout.addWidget(self.value_label)

        detail_label = QLabel(detail)
        detail_label.setObjectName("metricDetail")
        layout.addWidget(detail_label)

    def set_value(self, value: int) -> None:
        self.value_label.setText(f"{value:,}".replace(",", "."))


class EmptyState(QFrame):
    def __init__(
        self,
        title: str,
        description: str,
        *,
        action_text: str | None = None,
        action=None,
    ) -> None:
        super().__init__()
        self.setProperty("role", "surface")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 32, 28, 32)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mark = QLabel("DT")
        mark.setObjectName("emptyMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(48, 48)
        layout.addWidget(mark, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.title_label = QLabel(title)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet("font-size: 14pt; font-weight: 700;")
        layout.addWidget(self.title_label)

        self.description_label = QLabel(description)
        self.description_label.setObjectName("muted")
        self.description_label.setWordWrap(True)
        self.description_label.setMaximumWidth(440)
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.description_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        if action_text and action:
            self.action_button = QPushButton(action_text)
            self.action_button.setObjectName("primaryButton")
            self.action_button.clicked.connect(action)
            layout.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        else:
            self.action_button = None


class ReadableTableWidget(QTableWidget):
    """Tabla de registro con columnas ajustables y una columna flexible."""

    def __init__(
        self,
        columns: list[str],
        *,
        column_widths: list[int] | None = None,
        flexible_column: int | None = None,
    ) -> None:
        super().__init__(0, len(columns))
        self._flexible_column = flexible_column
        self._preferred_widths = column_widths or [160] * len(columns)
        self.setHorizontalHeaderLabels(columns)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(44)
        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStretchLastSection(False)
        header.setMinimumHeight(38)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        for column, width in enumerate(self._preferred_widths):
            self.setColumnWidth(column, width)
        self._fit_flexible_column()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_flexible_column()

    def _fit_flexible_column(self) -> None:
        column = self._flexible_column
        if column is None or not 0 <= column < self.columnCount():
            return
        fixed_width = sum(
            self.columnWidth(index)
            for index in range(self.columnCount())
            if index != column
        )
        preferred_width = self._preferred_widths[column]
        target = max(preferred_width, self.viewport().width() - fixed_width)
        if self.columnWidth(column) != target:
            self.setColumnWidth(column, target)


def build_table(
    columns: list[str],
    *,
    column_widths: list[int] | None = None,
    flexible_column: int | None = None,
) -> QTableWidget:
    return ReadableTableWidget(
        columns,
        column_widths=column_widths,
        flexible_column=flexible_column,
    )


def set_cell(table: QTableWidget, row: int, column: int, value: object, *, muted: bool = False) -> None:
    display_value = "" if value is None else str(value)
    item = QTableWidgetItem(display_value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    if display_value:
        item.setToolTip(display_value)
    if muted:
        item.setForeground(table.palette().color(QPalette.ColorRole.PlaceholderText))
    table.setItem(row, column, item)
