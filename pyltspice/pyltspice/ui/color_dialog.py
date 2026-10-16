"""Tools > Color Preferences."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QGridLayout, QLabel,
                               QPushButton, QVBoxLayout)

from .theme import DEFAULTS, theme

# names and order as in LTspice's Color Preferences dialog
LABELS = {
    "wire": "Wires", "junction": "Junctions", "component": "Component body",
    "flag_graphic": "Graphic Flag", "component_fill": "Component Fill-in", "attribute": "Component Text",
    "flag": "Flag Text", "directive": "SPICE Directive Text", "comment": "Comment Text",
    "unconnected": "Unconnected Pin", "selected": "Highlight Color", "grid": "Grid",
    "graphic": "Graphic Annotation", "background": "Background",
    "plot_axis": "Waveform Axis", "plot_inactive_axis": "Waveform Inactive Axis",
    "plot_grid": "Waveform Grid", "plot_background": "Waveform Background",
}


class ColorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Color Preferences")
        self.values = {k: theme().color(k) for k in LABELS}
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        self.buttons = {}
        for r, (k, label) in enumerate(LABELS.items()):
            grid.addWidget(QLabel(label), r, 0)
            b = QPushButton()
            b.setFixedWidth(80)
            b.clicked.connect(lambda _=False, k=k: self._pick(k))
            self.buttons[k] = b
            grid.addWidget(b, r, 1)
            self._paint(k)
        lay.addLayout(grid)
        reset = QPushButton("Reset to Default")
        reset.clicked.connect(self._reset)
        lay.addWidget(reset)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _paint(self, k):
        self.buttons[k].setStyleSheet(f"background:{self.values[k].name()}")

    def _pick(self, k):
        c = QColorDialog.getColor(self.values[k], self, LABELS[k])
        if c.isValid():
            self.values[k] = c
            self._paint(k)

    def _reset(self):
        for k in LABELS:
            self.values[k] = QColor(DEFAULTS[k])
            self._paint(k)

    def _ok(self):
        for k, c in self.values.items():
            theme().set_color(k, c)
        self.accept()
