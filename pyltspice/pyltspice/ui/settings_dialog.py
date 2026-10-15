"""Tools > Settings: the drafting options from LTspice's "Drafting Options" help page
that pyltspice supports."""
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QSpinBox, QVBoxLayout)

DEFAULTS = {
    "drafting/ortho_wires": True,
    "drafting/reverse_wheel": False,
    "drafting/mark_unconnected": False,
    "view/grid": False,
    "drafting/undo_size": 100,
}


def get(key):
    s = QSettings("pyltspice", "pyltspice")
    d = DEFAULTS[key]
    v = s.value(key, d)
    if isinstance(d, bool):
        return v in (True, "true", "1", 1)
    try:
        return type(d)(v)
    except (TypeError, ValueError):
        return d


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Control Panel")
        lay = QVBoxLayout(self)
        box = QGroupBox("Drafting Options")
        form = QFormLayout(box)
        self.checks = {}
        for key, label in (("drafting/ortho_wires", "Orthogonal snap wires (Ctrl toggles while drawing)"),
                           ("drafting/mark_unconnected", "Mark unconnected pins"),
                           ("view/grid", "Show schematic grid points"),
                           ("drafting/reverse_wheel", "Reverse mouse wheel zoom")):
            cb = QCheckBox(label)
            cb.setChecked(get(key))
            form.addRow(cb)
            self.checks[key] = cb
        self.undo = QSpinBox()
        self.undo.setRange(10, 10000)
        self.undo.setValue(get("drafting/undo_size"))
        form.addRow("Undo history size:", self.undo)
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        s = QSettings("pyltspice", "pyltspice")
        for key, cb in self.checks.items():
            s.setValue(key, cb.isChecked())
        s.setValue("drafting/undo_size", self.undo.value())
        self.accept()
