"""'Select Component Symbol' browser (F2)."""
from PySide6.QtCore import QRectF, QSettings, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QSplitter, QVBoxLayout,
                               QWidget)

from ..model.geometry import TextFrame
from ..model.library import SymbolLibrary
from .render import draw_text, make_pen, shape_path
from .theme import theme

FOLDER_ROLE = Qt.UserRole + 1


class SymbolPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.sym = None
        self.setMinimumSize(260, 220)

    def set_symbol(self, sym):
        self.sym = sym
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), theme().color("background"))
        if self.sym is None:
            return
        p.setRenderHint(QPainter.Antialiasing)
        x0, y0, x1, y1 = self.sym.bbox()
        r = QRectF(x0, y0, max(x1 - x0, 1), max(y1 - y0, 1)).adjusted(-24, -24, 24, 24)
        s = min(self.width() / r.width(), self.height() / r.height(), 3.0)
        p.translate(self.width() / 2, self.height() / 2)
        p.scale(s, s)
        p.translate(-r.center())
        for sh in self.sym.shapes:
            p.setPen(make_pen(theme().color("component"), style=sh.style))
            p.drawPath(shape_path(sh.kind, sh.coords))
        p.setPen(theme().color("component"))
        for t in self.sym.texts:
            draw_text(p, t.x, t.y, TextFrame.from_just(t.just), t.size, t.text)
        for pin in self.sym.pins:
            j = pin.just.upper()
            if j != "NONE" and pin.name:
                off = pin.offset
                dx, dy, just = {"LEFT": (off, 0, "Left"), "RIGHT": (-off, 0, "Right"),
                                "TOP": (0, off, "Top"), "BOTTOM": (0, -off, "Bottom")}.get(j, (off, 0, "Left"))
                draw_text(p, pin.x + dx, pin.y + dy, TextFrame.from_just(just), 1, pin.name)


class ComponentDialog(QDialog):
    def __init__(self, lib: SymbolLibrary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Component Symbol")
        self.lib = lib
        self.tree = lib.categories()
        self.folder = ""
        self.selected = None
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Top Directory:"))
        self.top_dir = QComboBox()
        for root in lib.roots:
            self.top_dir.addItem(str(root))
        top.addWidget(self.top_dir, 1)
        lay.addLayout(top)

        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.path_label = QLabel()
        ll.addWidget(self.path_label)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a symbol name to search all directories")
        self.search.textChanged.connect(self._populate)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ListMode)
        self.list.setFlow(QListWidget.TopToBottom)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.currentItemChanged.connect(self._current)
        self.list.itemDoubleClicked.connect(self._activated)
        ll.addWidget(self.list)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.preview = SymbolPreview()
        rl.addWidget(self.preview, 1)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setMinimumHeight(60)
        self.desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        rl.addWidget(self.desc)
        split.addWidget(right)
        split.setSizes([520, 300])
        lay.addWidget(split, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(900, 560)
        s = QSettings("pyltspice", "pyltspice")
        self.folder = s.value("component_dialog/folder", "") or ""
        if self.folder not in self.tree:
            self.folder = ""
        self._populate()
        self.search.setFocus()

    def _populate(self, *_):
        self.list.clear()
        q = self.search.text().strip().lower()
        if q:
            self.path_label.setText("Search results")
            for folder, names in sorted(self.tree.items()):
                for n in sorted(names):
                    if q in n:
                        rel = f"{folder}/{n}" if folder else n
                        it = QListWidgetItem(rel)
                        it.setData(Qt.UserRole, rel)
                        self.list.addItem(it)
            if self.list.count():
                self.list.setCurrentRow(0)
            return
        self.path_label.setText(f"{self.top_dir.currentText()}/{self.folder}".rstrip("/"))
        if self.folder:
            it = QListWidgetItem("[..]")
            it.setData(FOLDER_ROLE, self.folder.rpartition("/")[0])
            self.list.addItem(it)
        prefix = self.folder + "/" if self.folder else ""
        subs = sorted({f[len(prefix):].split("/")[0] for f in self.tree
                       if f.startswith(prefix) and f != self.folder and f})
        for s in subs:
            it = QListWidgetItem(f"[{s}]")
            it.setData(FOLDER_ROLE, prefix + s)
            self.list.addItem(it)
        for n in sorted(self.tree.get(self.folder, [])):
            it = QListWidgetItem(n)
            it.setData(Qt.UserRole, prefix + n)
            self.list.addItem(it)

    def _current(self, it, _prev=None):
        if it is None or it.data(Qt.UserRole) is None:
            self.preview.set_symbol(None)
            self.desc.setText("")
            return
        rel = it.data(Qt.UserRole)
        sym = self.lib.get(rel)
        self.preview.set_symbol(sym)
        if sym:
            self.desc.setText(sym.attrs.get("Description", "").replace("\\n", "\n"))

    def _activated(self, it):
        folder = it.data(FOLDER_ROLE)
        if folder is not None:
            self.folder = folder
            self.search.clear()
            self._populate()
        else:
            self._ok()

    def _ok(self):
        it = self.list.currentItem()
        if it is None:
            return
        if it.data(FOLDER_ROLE) is not None:
            self._activated(it)
            return
        rel = it.data(Qt.UserRole)
        self.selected = rel.replace("/", "\\\\")  # .asc files store a doubled backslash
        QSettings("pyltspice", "pyltspice").setValue("component_dialog/folder", self.folder)
        self.accept()
