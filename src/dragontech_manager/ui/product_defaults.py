"""Vínculo entre un selector de producto y los campos derivados del producto.

Causa del defecto que corrige: los diálogos rellenaban la descripción y el precio/costo
solo cuando el campo estaba vacío, así que tras la primera selección cualquier otro
producto conservaba los valores del anterior. Aquí el cambio de producto *siempre*
restablece los valores predeterminados del nuevo producto (lo editado a mano pertenecía
al producto anterior) y lo que el usuario edite después se respeta. Al guardar,
``sync_for_save`` reaplica los valores si la selección no coincide con el producto cuyos
valores se aplicaron, de modo que nunca se combinan id, descripción y precio de
productos distintos aunque se haya perdido una señal.
"""

from PySide6.QtWidgets import QComboBox, QLineEdit, QTextEdit


class ProductFieldBinding:
    def __init__(self, combo: QComboBox, description: QTextEdit, amount: QLineEdit,
                 amount_key: str) -> None:
        self.combo, self.description, self.amount = combo, description, amount
        self.amount_key = amount_key
        self._applied_id: int | None = None
        self._loading = False
        combo.currentIndexChanged.connect(self._product_changed)

    def current_product(self) -> dict | None:
        data = self.combo.currentData()
        return data if isinstance(data, dict) else None

    def _product_changed(self, _index: int) -> None:
        if not self._loading:
            self.apply_defaults()

    def apply_defaults(self) -> None:
        """Sustituye descripción y monto por los del producto seleccionado (o los limpia)."""
        product = self.current_product()
        self._loading = True
        try:
            self.description.setPlainText(product["nombre"] if product else "")
            self.amount.setText(str(product[self.amount_key]) if product else "")
        finally:
            self._loading = False
        self._applied_id = product["id"] if product else None

    def load_existing(self, product_id: int | None, *, description: str, amount: int) -> None:
        """Carga una línea guardada tal cual (valores históricos), sin tocarla con defaults."""
        self._loading = True
        try:
            index = next((i for i in range(self.combo.count())
                          if (self.combo.itemData(i) or {}).get("id") == product_id), -1)
            self.combo.setCurrentIndex(index if product_id is not None else 0)
            self.description.setPlainText(description)
            self.amount.setText(str(amount))
        finally:
            self._loading = False
        product = self.current_product()
        self._applied_id = product["id"] if product else None

    def sync_for_save(self) -> dict | None:
        """Devuelve el producto vigente garantizando que los campos le corresponden."""
        product = self.current_product()
        if (product["id"] if product else None) != self._applied_id:
            self.apply_defaults()
        return product
