"""Tools > Color Preferences."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QGridLayout, QLabel,
                               QPushButton, QVBoxLayout)

from .theme import DEFAULTS, theme

LABELS = {
    "background": "Background", "grid": "Grid", "wire": "Wires", "junction": "Junctions",
    "component": "Components", "attribute": "Component attributes", "flag": "Net labels",
    "directive": "SPICE directives", "comment": "Comments", "graphic": "Graphics",
    "selected": "Selected / sprited", "plot_background": "Waveform background",
    "plot_axis": "Waveform axes", "plot_text": "Waveform text",
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
