"""Temas DragonTech y persistencia estándar de la preferencia visual."""

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEME_SETTINGS_KEY = "appearance/theme"
DEFAULT_THEME = "dark"
SUPPORTED_THEMES = {"dark", "light"}


def load_theme_preference(settings: QSettings | None = None) -> str:
    settings = settings or QSettings()
    theme = settings.value(THEME_SETTINGS_KEY, DEFAULT_THEME, type=str)
    return theme if theme in SUPPORTED_THEMES else DEFAULT_THEME


def save_theme_preference(theme: str, settings: QSettings | None = None) -> str:
    if theme not in SUPPORTED_THEMES:
        raise ValueError("El tema debe ser 'dark' o 'light'.")
    settings = settings or QSettings()
    settings.setValue(THEME_SETTINGS_KEY, theme)
    settings.sync()
    return theme


def apply_theme(app: QApplication, theme_name: str = DEFAULT_THEME) -> str:
    """Aplica tema oscuro o claro coherente sin efectos de compositor."""
    theme = theme_name if theme_name in SUPPORTED_THEMES else DEFAULT_THEME
    dark = theme == "dark"
    colors = {
        "window": "#232226" if dark else "#F2F5F4",
        "base": "#1C2025" if dark else "#FFFFFF",
        "alternate": "#272D34" if dark else "#EDF2F0",
        "text": "#FFFFFF" if dark else "#232226",
        "muted": "#AAB2BB" if dark else "#5F6D69",
        "surface": "#2B2E33" if dark else "#FFFFFF",
        "surface_border": "#3A3E43" if dark else "#D7E0DD",
        "sidebar": "#1B1E23" if dark else "#253342",
        "topbar": "#24262B" if dark else "#FFFFFF",
        "control": "#1E2227" if dark else "#FFFFFF",
        "button": "#30363D" if dark else "#E8EFED",
        "button_hover": "#3B444B" if dark else "#DCE7E4",
        "table": "#25292E" if dark else "#FFFFFF",
        "table_alt": "#2A2F35" if dark else "#F2F6F5",
        "header": "#2B3036" if dark else "#E9EFED",
        "header_text": "#AEB8C0" if dark else "#3E5954",
        "border": "#414850" if dark else "#CDD8D4",
        "scroll_track": "#25292E" if dark else "#E9EFED",
        "scroll_handle": "#525B63" if dark else "#9BAFA9",
        "status": "#1B1E23" if dark else "#E8EFED",
        "selection": "#344A47" if dark else "#C7DBD5",
        "selection_text": "#FFFFFF" if dark else "#1F3530",
    }

    app.setStyle("Fusion")
    app.setProperty("dragontechTheme", theme)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(colors["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(colors["base"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["alternate"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(colors["button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#5E9188" if dark else "#5E9188"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(colors["muted"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#253342"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    app.setPalette(palette)

    app.setStyleSheet(
        f"""
        QWidget {{ color: {colors['text']}; font-size: 10pt; }}
        QWidget#appShell {{ background: {colors['window']}; }}
        QFrame#sidebar {{ background: {colors['sidebar']}; border-right: 1px solid {colors['surface_border']}; }}
        QFrame#topBar {{ background: {colors['topbar']}; border-bottom: 1px solid {colors['surface_border']}; }}
        QFrame[role="surface"] {{ background: {colors['surface']}; border: 1px solid {colors['surface_border']}; border-radius: 12px; }}
        QLabel#brand {{ color: #FFFFFF; font-size: 15pt; font-weight: 800; letter-spacing: 1px; }}
        QLabel#brandSub {{ color: #91A9A4; font-size: 8pt; letter-spacing: 2px; }}
        QLabel#dashboardEyebrow {{ color: {'#8CB0A8' if dark else '#3E5954'}; font-size: 8pt; font-weight: 700; letter-spacing: 1.4px; }}
        QLabel#pageTitle {{ color: {colors['text']}; font-size: 19pt; font-weight: 700; }}
        QLabel#pageSubtitle, QLabel#muted, QLabel#metricDetail {{ color: {colors['muted']}; }}
        QLabel#metricTitle {{ color: {colors['muted']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
        QLabel#metricValue {{ color: {colors['text']}; font-size: 28pt; font-weight: 700; }}
        QLabel#emptyMark {{ color: #8CB0A8; background: {'#2E3B3A' if dark else '#E2EEEB'}; border: 1px solid {'#496A64' if dark else '#C2D7D1'}; border-radius: 24px; font-weight: 800; font-size: 12pt; }}
        QLabel#formError {{ color: {'#F0A3A3' if dark else '#8B2828'}; background: {'#382B2E' if dark else '#FCEBEC'}; border: 1px solid {'#67464B' if dark else '#E9C2C5'}; border-radius: 6px; padding: 9px; }}
        QPushButton {{ background: {colors['button']}; color: {colors['text']}; border: 1px solid {colors['border']}; border-radius: 8px; padding: 9px 14px; font-weight: 600; }}
        QPushButton:hover {{ background: {colors['button_hover']}; border-color: #5E9188; }}
        QPushButton:pressed {{ background: #253342; }}
        QPushButton:disabled {{ color: {colors['muted']}; background: {colors['window']}; border-color: {colors['surface_border']}; }}
        QPushButton#primaryButton {{ background: #5E9188; color: #10211E; border: 1px solid #78A79E; font-weight: 700; }}
        QPushButton#primaryButton:hover {{ background: #75A89E; }}
        QPushButton#navButton {{ text-align: left; background: transparent; border: 1px solid transparent; color: #B6BEC6; padding: 11px 13px; }}
        QPushButton#navButton:hover {{ background: {'#292F35' if dark else '#344858'}; color: #FFFFFF; }}
        QPushButton#navButton[selected="true"] {{ color: #FFFFFF; background: {'#2E3B3A' if dark else '#3E5954'}; border-color: #5E9188; }}
        QPushButton#quickActionButton {{ text-align: left; background: {colors['table_alt']}; border: 1px solid {colors['surface_border']}; border-radius: 8px; padding: 8px 12px; font-weight: 700; }}
        QPushButton#quickActionButton:hover {{ background: {colors['button_hover']}; border-color: #5E9188; }}
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{ background: {colors['control']}; color: {colors['text']}; border: 1px solid {colors['border']}; border-radius: 7px; padding: 9px 10px; selection-background-color: #5E9188; }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border-color: #76A69D; }}
        QComboBox QAbstractItemView {{ background: {colors['surface']}; color: {colors['text']}; selection-background-color: #3E5954; border: 1px solid {colors['border']}; }}
        QTableWidget {{ background: {colors['table']}; alternate-background-color: {colors['table_alt']}; border: 1px solid {colors['surface_border']}; border-radius: 10px; gridline-color: transparent; selection-background-color: {colors['selection']}; selection-color: {colors['selection_text']}; outline: 0; }}
        QHeaderView::section {{ background: {colors['header']}; color: {colors['header_text']}; border: none; border-bottom: 1px solid {colors['border']}; padding: 10px 8px; font-size: 8pt; font-weight: 700; }}
        QTableWidget::item {{ padding: 8px; border-bottom: 1px solid {colors['surface_border']}; }}
        QScrollBar:vertical {{ background: {colors['scroll_track']}; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{ background: {colors['scroll_handle']}; border-radius: 4px; min-height: 30px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: {colors['scroll_track']}; height: 10px; margin: 2px; }}
        QScrollBar::handle:horizontal {{ background: {colors['scroll_handle']}; border-radius: 4px; min-width: 30px; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QStatusBar {{ background: {colors['status']}; color: {colors['muted']}; border-top: 1px solid {colors['surface_border']}; }}
        QDialog {{ background: {colors['window']}; }}
        QToolTip {{ color: #FFFFFF; background: #253342; border: 1px solid #5E9188; padding: 5px; }}
        """
    )
    return theme
