"""Place a part from a vendor SPICE model file (TuxSpice extra; see sim/libimport.py): the
picker for files with several definitions, and handling of files dropped on the window."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QVBoxLayout)

from ..sim import libimport


class PickDefinition(QDialog):
    def __init__(self, path, defs, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Place from {Path(path).name}")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"{len(defs)} definitions in {path}. Pick one to place:"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter")
        self.filter.textChanged.connect(self._filter)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        for d in defs:
            it = QListWidgetItem(f"{d.name}    ({d.summary()})")
            it.setData(Qt.UserRole, d)
            it.setToolTip(d.description or d.summary())
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(560, 420)

    def _filter(self, text):
        t = text.lower()
        first = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            hide = t not in it.text().lower()
            it.setHidden(hide)
            if not hide and first is None:
                first = i
        if first is not None:
            self.list.setCurrentRow(first)

    def chosen(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it is not None and not it.isHidden() else None


def place_from_file(main, sw, path) -> bool:
    """Scan `path`, let the user pick a definition, write its symbol if needed and start placing
    it on schematic window `sw`. False if nothing was placed."""
    path = Path(path)
    try:
        defs, encrypted = libimport.scan(path)
    except OSError as e:
        QMessageBox.warning(main, "Place SPICE Model", f"Could not read {path}:\n{e}")
        return False
    if encrypted:
        QMessageBox.information(main, "Place SPICE Model",
                                f"{path.name} is an encrypted Analog Devices model; only LTspice can use it.")
        return False
    usable = [d for d in defs if d.kind == "subckt" or d.symbol]
    if not usable:
        QMessageBox.information(main, "Place SPICE Model",
                                f"No .subckt, or .model of a type TuxSpice has a symbol for, in {path.name}.")
        return False
    if len(usable) == 1:
        d = usable[0]
    else:
        dlg = PickDefinition(path, usable, main)
        if dlg.exec() != QDialog.Accepted or dlg.chosen() is None:
            return False
        d = dlg.chosen()
    sym_name, attrs, asy_text, asy_path = libimport.placement(d, path, sw.doc.path)
    if asy_text is not None:
        if asy_path.exists() and asy_path.read_text(errors="replace") != asy_text:
            if "SYMATTR ModelFile" not in asy_path.read_text(errors="replace"):
                r = QMessageBox.question(main, "Place SPICE Model",
                                         f"{asy_path} exists and wasn't made by TuxSpice. Replace it?")
                if r != QMessageBox.Yes:
                    return False
        try:
            asy_path.parent.mkdir(parents=True, exist_ok=True)
            asy_path.write_text(asy_text)
        except OSError as e:
            QMessageBox.warning(main, "Place SPICE Model", f"Could not write {asy_path}:\n{e}")
            return False
        sw.doc.lib.rescan()
    sw.place_symbol(sym_name, attrs, label=f"Place {d.name}")
    main.status_label.setText(f"Placing {d.name} from {path.name}"
                              + (f" (symbol written to {asy_path})" if asy_path else ""))
    return True


def ask_and_place(main, sw):
    """Edit > Place SPICE Model from File..."""
    start = main.settings.value("file/model_dir", str(Path.home()))
    exts = " ".join(f"*{e}" for e in libimport.MODEL_EXTS)
    path, _ = QFileDialog.getOpenFileName(main, "Place SPICE Model from File", start,
                                          f"SPICE model files ({exts});;All files (*)")
    if path:
        main.settings.setValue("file/model_dir", str(Path(path).parent))
        place_from_file(main, sw, path)


def is_model_file(path) -> bool:
    p = Path(path)
    if p.suffix.lower() not in libimport.MODEL_EXTS or not p.is_file():
        return False
    try:
        defs, encrypted = libimport.scan(p)
    except OSError:
        return False
    return encrypted or bool(defs)
