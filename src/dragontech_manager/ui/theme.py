"""Tema oscuro y componentes visuales DragonTech."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#232226"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1C2025"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#272D34"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#30363D"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#5E9188"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#98A2AD"))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QWidget { color: #FFFFFF; font-size: 10pt; }
        QWidget#appShell { background: #232226; }
        QFrame#sidebar { background: #1B1E23; border-right: 1px solid #34383E; }
        QFrame#topBar { background: #24262B; border-bottom: 1px solid #34383E; }
        QFrame[role="surface"] { background: #2B2E33; border: 1px solid #3A3E43; border-radius: 12px; }
        QLabel#brand { color: #FFFFFF; font-size: 15pt; font-weight: 800; letter-spacing: 1px; }
        QLabel#brandSub { color: #91A9A4; font-size: 8pt; letter-spacing: 2px; }
        QLabel#pageTitle { color: #FFFFFF; font-size: 19pt; font-weight: 700; }
        QLabel#pageSubtitle { color: #ABB3BC; font-size: 9pt; }
        QLabel#muted { color: #AAB2BB; }
        QPushButton { background: #30363D; color: #F7F8F8; border: 1px solid #414850; border-radius: 8px; padding: 9px 14px; font-weight: 600; }
        QPushButton:hover { background: #3B444B; border-color: #5E9188; }
        QPushButton:pressed { background: #253342; }
        QPushButton:disabled { color: #6F7881; background: #292C31; border-color: #34383E; }
        QPushButton#primaryButton { background: #5E9188; color: #10211E; border: 1px solid #78A79E; font-weight: 700; }
        QPushButton#primaryButton:hover { background: #75A89E; }
        QPushButton#navButton { text-align: left; background: transparent; border: 1px solid transparent; color: #B6BEC6; padding: 11px 13px; }
        QPushButton#navButton:hover { background: #292F35; color: #FFFFFF; }
        QPushButton#navButton[selected="true"] { color: #FFFFFF; background: #2E3B3A; border-color: #496A64; }
        QLineEdit, QTextEdit, QComboBox { background: #1E2227; color: #FFFFFF; border: 1px solid #42474E; border-radius: 7px; padding: 9px 10px; selection-background-color: #5E9188; }
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #76A69D; }
        QComboBox QAbstractItemView { background: #252A30; color: #FFFFFF; selection-background-color: #3E5954; border: 1px solid #454B52; }
        QTableWidget { background: #25292E; alternate-background-color: #2A2F35; border: 1px solid #3A4047; border-radius: 10px; gridline-color: transparent; selection-background-color: #344A47; selection-color: #FFFFFF; outline: 0; }
        QHeaderView::section { background: #2B3036; color: #AEB8C0; border: none; border-bottom: 1px solid #42474E; padding: 10px 8px; font-size: 8pt; font-weight: 700; }
        QTableWidget::item { padding: 8px; border-bottom: 1px solid #343940; }
        QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
        QScrollBar::handle:vertical { background: #525B63; border-radius: 4px; min-height: 30px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
        QScrollBar::handle:horizontal { background: #525B63; border-radius: 4px; min-width: 30px; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QStatusBar { background: #1B1E23; color: #ABB3BC; border-top: 1px solid #34383E; }
        QDialog { background: #23262B; }
        QToolTip { color: #FFFFFF; background: #253342; border: 1px solid #5E9188; padding: 5px; }
        """
    )
