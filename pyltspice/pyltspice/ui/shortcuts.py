"""Keyboard Shortcut Cheat Sheet / Edit Keyboard Shortcuts (Help menu).

Click a command, press the key combination to assign it; Delete removes it.
Shortcuts persist in QSettings and can be saved to / loaded from a text file."""
import json

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

KEY = "shortcuts/map"


def apply_saved(actions: dict):
    """Override default shortcuts with the user's saved ones."""
    raw = QSettings("pyltspice", "pyltspice").value(KEY)
    if not raw:
        return
    try:
        saved = json.loads(raw)
    except ValueError:
        return
    for k, seqs in saved.items():
        if k in actions:
            actions[k].setShortcuts([QKeySequence(s) for s in seqs])


class ShortcutDialog(QDialog):
    def __init__(self, actions: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.actions = actions
        self.keys = [k for k in actions if not actions[k].isCheckable() or k.startswith("view_")]
        self.current = {k: [s.toString() for s in actions[k].shortcuts()] for k in self.keys}
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Click a command, then press the key combination for it. "
                             "Delete removes the shortcut."))
        self.table = QTableWidget(len(self.keys), 2)
        self.table.setHorizontalHeaderLabels(["Command", "Shortcut"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._fill()
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, slot in (("Load from file...", self._load), ("Save to file...", self._save),
                           ("Restore defaults", self._defaults)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            b.setAutoDefault(False)
            row.addWidget(b)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(480, 600)
        self.table.installEventFilter(self)

    def _fill(self):
        for r, k in enumerate(self.keys):
            self.table.setItem(r, 0, QTableWidgetItem(self.actions[k].text().replace("&", "")))
            self.table.setItem(r, 1, QTableWidgetItem(", ".join(self.current[k])))

    def eventFilter(self, obj, ev):
        if obj is self.table and ev.type() == ev.Type.KeyPress:
            r = self.table.currentRow()
            if r < 0:
                return False
            key = ev.key()
            if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab, Qt.Key_Backtab):
                return False
            if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
                return True
            k = self.keys[r]
            if key in (Qt.Key_Delete, Qt.Key_Backspace) and not ev.modifiers():
                self.current[k] = []
            else:
                seq = QKeySequence(ev.keyCombination()).toString()
                for other, seqs in self.current.items():      # a key belongs to one command
                    if seq in seqs:
                        seqs.remove(seq)
                self.current[k] = [seq]
            self._fill()
            self.table.selectRow(r)
            return True
        return super().eventFilter(obj, ev)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save shortcuts", "", "Shortcuts (*.json)")
        if path:
            with open(path, "w") as f:
                json.dump(self.current, f, indent=1)

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load shortcuts", "", "Shortcuts (*.json)")
        if path:
            with open(path) as f:
                data = json.load(f)
            for k, v in data.items():
                if k in self.current:
                    self.current[k] = list(v)
            self._fill()

    def _defaults(self):
        QSettings("pyltspice", "pyltspice").remove(KEY)
        self.current = {k: list(getattr(self.actions[k], "default_keys", [])) for k in self.keys}
        self._fill()

    def _ok(self):
        for k, seqs in self.current.items():
            self.actions[k].setShortcuts([QKeySequence(s) for s in seqs])
        QSettings("pyltspice", "pyltspice").setValue(KEY, json.dumps(self.current))
        self.accept()
