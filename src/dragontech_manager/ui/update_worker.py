"""Trabajo de red aislado del hilo de la interfaz."""

from PySide6.QtCore import QThread, Signal

from dragontech_manager.services.updates import UpdateCheckResult, UpdateChecker


class UpdateCheckWorker(QThread):
    completed = Signal(object)

    def __init__(self, checker: UpdateChecker, current_version: str, parent=None) -> None:
        super().__init__(parent)
        self.checker = checker
        self.current_version = current_version

    def run(self) -> None:
        try:
            result = self.checker.check(self.current_version)
        except Exception:
            result = UpdateCheckResult("error", "Ocurrió un error al consultar el canal de versiones.")
        self.completed.emit(result)
