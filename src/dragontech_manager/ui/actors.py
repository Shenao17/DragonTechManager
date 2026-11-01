"""Directorio de actores: quién ejecuta y quién autoriza las operaciones financieras."""

import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout,
)

from dragontech_manager.services.actors import IDENTITY_WARNING, ROLES, ActorService
from dragontech_manager.services.errors import ServiceError
from .pages import format_cop
from .widgets import build_table, set_cell

_ROLE_LABELS = {"vendedor": "Vendedor", "tecnico": "Técnico", "cajero": "Cajero", "supervisor": "Supervisor",
                "propietario": "Propietario", "contador": "Contador", "otro": "Otro"}


def actor_options(actors: list[dict], *, blank: str | None = None) -> list[tuple[str, object]]:
    """Opciones de selector (texto, id); ``blank`` agrega una opción vacía (sin autorizador)."""
    options = [(blank, "")] if blank else []
    return options + [(f"{a['nombre']} · {_ROLE_LABELS[a['rol_operativo']]}", a["id"]) for a in actors]


class ActorEditDialog(QDialog):
    def __init__(self, actor: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar actor" if actor else "Nuevo actor")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(actor["nombre"] if actor else "")
        self.document = QLineEdit((actor or {}).get("documento") or "")
        self.role = QComboBox()
        for role in ROLES:
            self.role.addItem(_ROLE_LABELS[role], role)
        self.can_authorize = QCheckBox("Puede autorizar operaciones")
        self.limit = QLineEdit()
        self.limit.setPlaceholderText("Vacío = sin límite definido (no podrá autorizar importes)")
        self.active = QCheckBox("Activo")
        self.active.setChecked(True)
        self.notes = QLineEdit((actor or {}).get("notas") or "")
        if actor:
            self.role.setCurrentIndex(self.role.findData(actor["rol_operativo"]))
            self.can_authorize.setChecked(bool(actor["puede_autorizar"]))
            self.active.setChecked(bool(actor["activo"]))
            if actor["limite_autorizacion_cop"] is not None:
                self.limit.setText(str(actor["limite_autorizacion_cop"]))
        for label, widget in (("Nombre *", self.name), ("Documento", self.document), ("Rol *", self.role),
                              ("Autorización", self.can_authorize), ("Límite de autorización (COP)", self.limit),
                              ("Estado", self.active), ("Notas", self.notes)):
            form.addRow(label, widget)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        try:
            self.values()
        except ValueError as error:
            self.error.setText(str(error))
            return
        self.accept()

    def values(self) -> dict:
        text = self.limit.text().strip()
        if text and not text.isdigit():
            raise ValueError("El límite debe ser un entero en pesos.")
        return {"name": self.name.text().strip(), "role": self.role.currentData(),
                "document": self.document.text().strip() or None, "can_authorize": self.can_authorize.isChecked(),
                "limit_cop": int(text) if text else None, "notes": self.notes.text().strip(),
                "active": self.active.isChecked()}


class ActorsDialog(QDialog):
    """Mantenimiento del directorio (lo administra el propietario)."""

    def __init__(self, service: ActorService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Directorio de actores")
        self.setMinimumSize(900, 520)
        layout = QVBoxLayout(self)
        warning = QLabel(IDENTITY_WARNING)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.table = build_table(["Nombre", "Rol", "Autoriza", "Límite", "Estado"],
                                 column_widths=[280, 150, 110, 180, 120], flexible_column=0)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.new_button = QPushButton("Nuevo actor")
        self.edit_button = QPushButton("Editar seleccionado")
        self.toggle_button = QPushButton("Activar / desactivar")
        for button, handler in ((self.new_button, self._new), (self.edit_button, self._edit),
                                (self.toggle_button, self._toggle)):
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self._render()

    def _render(self) -> None:
        self.actors = self.service.list_actors(active_only=False)
        self.table.setRowCount(len(self.actors))
        for row, actor in enumerate(self.actors):
            limit = ("Sin límite definido" if actor["limite_autorizacion_cop"] is None
                     else format_cop(actor["limite_autorizacion_cop"])) if actor["puede_autorizar"] else "—"
            for col, value in enumerate((actor["nombre"], _ROLE_LABELS[actor["rol_operativo"]],
                                         "Sí" if actor["puede_autorizar"] else "No", limit,
                                         "Activo" if actor["activo"] else "Inactivo")):
                set_cell(self.table, row, col, value)
            self.table.setRowHeight(row, 44)

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        return self.actors[row] if 0 <= row < len(self.actors) else None

    def _save(self, call) -> None:
        try:
            call()
        except (ServiceError, sqlite3.Error) as error:
            QMessageBox.warning(self, "No se pudo guardar el actor", str(error))
        self._render()

    def _new(self) -> None:
        dialog = ActorEditDialog(None, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            v = dialog.values()
            self._save(lambda: self.service.create_actor(
                v["name"], v["role"], document=v["document"], can_authorize=v["can_authorize"],
                limit_cop=v["limit_cop"], notes=v["notes"]))

    def _edit(self) -> None:
        actor = self._selected()
        if actor is None:
            return
        dialog = ActorEditDialog(actor, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            v = dialog.values()
            self._save(lambda: self.service.update_actor(
                actor["id"], name=v["name"], role=v["role"], document=v["document"],
                can_authorize=v["can_authorize"], limit_cop=v["limit_cop"], active=v["active"], notes=v["notes"]))

    def _toggle(self) -> None:
        actor = self._selected()
        if actor is not None:
            self._save(lambda: self.service.set_active(actor["id"], not actor["activo"]))
