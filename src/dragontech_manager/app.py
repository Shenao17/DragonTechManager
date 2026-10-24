"""Arranque provisional de la interfaz Qt."""

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


def create_main_window() -> QMainWindow:
    """Construye una ventana temporal para validar el arranque de PySide6."""
    window = QMainWindow()
    window.setWindowTitle("DragonTech Manager")
    window.setCentralWidget(QLabel("Aplicación en desarrollo"))
    window.resize(900, 600)
    return window


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = create_main_window()
    window.show()
    return app.exec()
