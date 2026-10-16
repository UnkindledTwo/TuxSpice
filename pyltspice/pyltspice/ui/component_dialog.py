"""'Select Component Symbol' browser (F2)."""
from PySide6.QtCore import QRectF, QSettings, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QWidget)

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
        # pins as LTspice's little squares
        p.setPen(make_pen(theme().color("unconnected")))
        for pin in self.sym.pins:
            p.drawRect(QRectF(pin.x - 4, pin.y - 4, 8, 8))
        p.setPen(theme().color("component"))
        for pin in self.sym.pins:
            j = pin.just.upper()
            if j != "NONE" and pin.name:
                off = pin.offset
                dx, dy, just = {"LEFT": (off, 0, "Left"), "RIGHT": (-off, 0, "Right"),
                                "TOP": (0, off, "Top"), "BOTTOM": (0, -off, "Bottom")}.get(j, (off, 0, "Left"))
                draw_text(p, pin.x + dx, pin.y + dy, TextFrame.from_just(just), 1, pin.name)


class ComponentDialog(QDialog):
    """Laid out like LTspice 26's component browser: name, description and preview on the left;
    Show / Search, the folder path and a multi-column list on the right; Refresh/Cancel/Place.

    Typing in Search does not filter: it jumps to the first symbol whose name starts with the
    text, opening the folder that holds it, as LTspice does. Clicking a name copies it into
    Search."""

    def __init__(self, lib: SymbolLibrary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Component Symbol")
        self.lib = lib
        self.tree = lib.categories()
        self.folder = ""
        self.selected = None
        self.open_example = None
        self._quiet = False
        grid = QGridLayout(self)

        # left column
        self.name_label = QLabel()
        self.desc_label = QLabel()
        self.desc_label.setWordWrap(True)
        grid.addWidget(self.name_label, 0, 0)
        grid.addWidget(self.desc_label, 1, 0, 2, 1, Qt.AlignTop)
        self.preview = SymbolPreview()
        self.preview.setFixedSize(204, 256)
        grid.addWidget(self.preview, 3, 0, 4, 1)
        self.info_btn = QPushButton("Get Product Info")
        self.info_btn.setEnabled(False)
        grid.addWidget(self.info_btn, 7, 0)
        self.example_btn = QPushButton("Open Example Circuit")
        self.example_btn.setEnabled(False)
        self.example_btn.clicked.connect(self._open_example)
        grid.addWidget(self.example_btn, 8, 0)

        # right column
        grid.addWidget(QLabel("Show:"), 0, 1, 1, 3)
        self.show = QComboBox()
        self.show.addItem("All")
        for root in lib.roots:
            self.show.addItem(str(root))
        grid.addWidget(self.show, 1, 1, 1, 3)
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Search:"))
        self.search = QLineEdit()
        self.search.setToolTip("Type here to search for a component by name")
        self.search.textEdited.connect(self._search)
        srow.addWidget(self.search, 1)
        grid.addLayout(srow, 2, 1, 1, 3)
        prow = QHBoxLayout()
        self.up_btn = QPushButton()
        self.up_btn.setFlat(True)
        self.up_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogToParent))
        self.up_btn.setToolTip("Parent folder")
        self.up_btn.clicked.connect(self._up)
        prow.addWidget(self.up_btn)
        self.path_label = QLabel()
        prow.addWidget(self.path_label, 1)
        grid.addLayout(prow, 3, 1, 1, 3)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ListMode)
        self.list.setFlow(QListWidget.TopToBottom)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.setSpacing(0)
        self.list.setMinimumSize(410, 190)
        self.list.currentItemChanged.connect(self._current)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDoubleClicked.connect(self._activated)
        grid.addWidget(self.list, 4, 1, 3, 3)
        self.sym_label = QLabel()
        grid.addWidget(self.sym_label, 7, 1, 1, 3)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        grid.addWidget(refresh, 8, 1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        grid.addWidget(cancel, 8, 2)
        self.place_btn = QPushButton("Place")
        self.place_btn.setDefault(True)
        self.place_btn.setEnabled(False)
        self.place_btn.clicked.connect(self._ok)
        grid.addWidget(self.place_btn, 8, 3)
        grid.setColumnStretch(1, 1)

        s = QSettings("pyltspice", "pyltspice")
        self.folder = s.value("component_dialog/folder", "") or ""
        if self.folder not in self.tree:
            self.folder = ""
        self._populate()
        self.search.setFocus()

    # -- names as found on disk (the index is lower-case)
    def _display(self, rel):
        p = self.lib.path_for(rel)
        return p.stem if p else rel.rsplit("/", 1)[-1]

    def _display_folder(self, folder):
        if not folder:
            return "*"
        names = self.tree.get(folder) or []
        if names:
            p = self.lib.path_for(f"{folder}/{names[0]}")
            if p:
                return p.parent.name
        return folder.rsplit("/", 1)[-1]

    def _real_rel(self, rel):
        p = self.lib.path_for(rel)
        if p is None:
            return rel
        for root in self.lib.roots:
            try:
                return str(p.relative_to(root).with_suffix(""))
            except ValueError:
                continue
        return rel

    def _populate(self, select=None):
        self._quiet = True
        self.list.clear()
        self.path_label.setText(self._display_folder(self.folder))
        self.up_btn.setEnabled(bool(self.folder))
        prefix = self.folder + "/" if self.folder else ""
        subs = sorted({f[len(prefix):].split("/")[0] for f in self.tree
                       if f.startswith(prefix) and f != self.folder and f})
        for sub in subs:
            it = QListWidgetItem(f"[{self._display_folder(prefix + sub)}]")
            it.setData(FOLDER_ROLE, prefix + sub)
            self.list.addItem(it)
        for n in sorted(self.tree.get(self.folder, []), key=str.lower):
            it = QListWidgetItem(self._display(prefix + n))
            it.setData(Qt.UserRole, prefix + n)
            self.list.addItem(it)
            if select is not None and prefix + n == select:
                self.list.setCurrentItem(it)
        # columns as wide as the longest name, so nothing is cut off
        fm = self.list.fontMetrics()
        texts = [self.list.item(i).text() for i in range(self.list.count())]
        w = max((fm.horizontalAdvance(t) for t in texts), default=40) + 14
        self.list.setGridSize(QSize(w, fm.height() + 2))
        self._quiet = False
        self._current(self.list.currentItem())
        self._scroll_current()

    def _scroll_current(self):
        # before the dialog is shown the list has no geometry; showEvent scrolls again
        cur = self.list.currentItem()
        if cur is not None and self.isVisible():
            self.list.scrollToItem(cur, QListWidget.PositionAtCenter)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._scroll_current()

    def _search(self, text):
        q = text.strip().lower().replace("\\", "/").replace("\\", "/")
        if not q:
            return
        # prefer the folder on screen, then the top level, then any folder
        folders = [self.folder, ""] + sorted(f for f in self.tree if f not in (self.folder, ""))
        for exact in (True, False):
            for f in folders:
                for n in sorted(self.tree.get(f, []), key=str.lower):
                    rel = f"{f}/{n}" if f else n
                    if (n == q or rel == q) if exact else (n.startswith(q) or rel.startswith(q)):
                        if f != self.folder:
                            self.folder = f
                        self._populate(select=rel)
                        return

    def _up(self):
        if self.folder:
            self.folder = self.folder.rpartition("/")[0]
            self._populate()

    def _refresh(self):
        self.tree = self.lib.categories()
        self._populate()

    def _clicked(self, it):
        if it is not None and it.data(Qt.UserRole) is not None:
            self.search.setText(it.text())

    def _current(self, it, _prev=None):
        if self._quiet:
            return
        rel = it.data(Qt.UserRole) if it is not None else None
        self.place_btn.setEnabled(rel is not None)
        if rel is None:
            self.preview.set_symbol(None)
            self.name_label.setText("")
            self.desc_label.setText("")
            self.sym_label.setText("")
            self.example_btn.setEnabled(False)
            return
        sym = self.lib.get(rel)
        self.preview.set_symbol(sym)
        name = self._display(rel)
        self.name_label.setText(name)
        self.desc_label.setText((sym.attrs.get("Description", "") if sym else "").replace("\\n", " "))
        self.sym_label.setText("Symbols: " + self._real_rel(rel).replace("/", "\\"))
        self.info_btn.setText(f"Get {name} Info" if self.folder else "Get Product Info")
        self.example_btn.setEnabled(_example_for(name) is not None)

    def _open_example(self):
        it = self.list.currentItem()
        if it is not None:
            self.open_example = _example_for(it.text())
            self.reject()

    def _activated(self, it):
        folder = it.data(FOLDER_ROLE)
        if folder is not None:
            self.folder = folder
            self._populate()
        else:
            self._ok()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._ok()
            return
        super().keyPressEvent(ev)

    def _ok(self):
        it = self.list.currentItem()
        if it is None:
            return
        if it.data(FOLDER_ROLE) is not None:
            self._activated(it)
            return
        rel = self._real_rel(it.data(Qt.UserRole))
        self.selected = rel.replace("/", "\\\\")  # .asc files store a doubled backslash
        QSettings("pyltspice", "pyltspice").setValue("component_dialog/folder", self.folder)
        self.accept()


_examples = None


def _example_for(name: str):
    """An example schematic named after the part (LTspice's 'Open Example Circuit')."""
    global _examples
    if _examples is None:
        from .. import config
        _examples = {}
        if config.EXAMPLES_DIR.is_dir():
            for p in config.EXAMPLES_DIR.rglob("*.asc"):
                _examples.setdefault(p.stem.lower(), p)
    return _examples.get(name.lower())
