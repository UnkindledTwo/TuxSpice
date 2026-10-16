"""Dialogs modelled on LTspice's: text/directive, net label, component editors,
attribute editor and Edit Simulation Command."""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from ..model import asc

JUSTS = ["Left", "Center", "Right", "Top", "Bottom"]
FONT_SIZES = ["0.625x", "1.0x", "1.5x(default)", "2.0x", "2.5x", "3.5x", "5.0x", "7.0x"]


def _buttons(dlg, layout):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    layout.addWidget(bb)
    return bb


def popup_at_cursor(dlg: QDialog):
    """LTspice opens its small editors centred on the mouse pointer (kept on screen)."""
    from PySide6.QtGui import QCursor, QGuiApplication
    dlg.adjustSize()
    pos = QCursor.pos()
    screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
    r = dlg.frameGeometry()
    r.moveCenter(pos)
    if screen is not None:
        g = screen.availableGeometry()
        r.moveLeft(max(g.left(), min(r.left(), g.right() - r.width())))
        r.moveTop(max(g.top(), min(r.top(), g.bottom() - r.height())))
    dlg.move(r.topLeft())


def _ok_cancel_column(dlg, extra=()):
    """OK / Cancel stacked at the top right, as in LTspice's component editors."""
    col = QVBoxLayout()
    ok = QPushButton("OK")
    ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    cancel = QPushButton("Cancel")
    cancel.clicked.connect(dlg.reject)
    col.addWidget(ok)
    col.addWidget(cancel)
    for b in extra:
        col.addWidget(b)
    col.addStretch()
    return col


# ---------------------------------------------------------------- text

class _TextEdit(QPlainTextEdit):
    """Enter accepts the dialog; Shift+Enter (or Ctrl+M) starts a new line, as in LTspice."""

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            if ev.modifiers() & Qt.ShiftModifier:
                self.insertPlainText("\n")
            else:
                self.dialog.accept()
            return
        if ev.key() == Qt.Key_M and ev.modifiers() & Qt.ControlModifier:
            self.insertPlainText("\n")
            return
        super().keyPressEvent(ev)


class TextDialog(QDialog):
    """'Edit Text on the Schematic' (T and . commands), laid out like LTspice 26's."""

    def __init__(self, parent=None, text: asc.Text | None = None, directive=False):
        super().__init__(parent)
        self.setWindowTitle("Edit Text on the Schematic:")
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        how = QGroupBox("How to netlist this text")
        hl = QVBoxLayout(how)
        self.comment = QRadioButton("Comment")
        self.directive = QRadioButton("SPICE directive")
        hl.addWidget(self.comment)
        hl.addWidget(self.directive)
        top.addWidget(how)
        jb = QGroupBox("Justification")
        jl = QVBoxLayout(jb)
        self.just = QComboBox()
        self.just.addItems(JUSTS)
        self.vertical = QCheckBox("Vertical Text")
        jl.addWidget(self.just)
        jl.addWidget(self.vertical)
        top.addWidget(jb)
        fb = QGroupBox("Font Size")
        fl = QVBoxLayout(fb)
        self.size = QComboBox()
        self.size.addItems(FONT_SIZES)
        fl.addWidget(self.size)
        fl.addStretch()
        top.addWidget(fb)
        top.addLayout(_ok_cancel_column(self))
        lay.addLayout(top)
        self.edit = _TextEdit(self)
        self.edit.setMinimumWidth(440)
        self.edit.setFixedHeight(70)
        lay.addWidget(self.edit)
        lay.addWidget(QLabel("Press Shift+Enter to start a new line."))

        is_dir = text.is_directive if text else directive
        (self.directive if is_dir else self.comment).setChecked(True)
        just = text.just if text else "Left"
        self.vertical.setChecked(just.startswith("V"))
        base = just[1:] if just.startswith("V") else just
        self.just.setCurrentText(base if base in JUSTS else "Left")
        self.size.setCurrentIndex(text.size if text else 2)
        if text:
            self.edit.setPlainText(text.body)
            self.edit.selectAll()
        self.edit.setFocus()
        popup_at_cursor(self)

    def result_text(self, x=0, y=0) -> asc.Text:
        body = self.edit.toPlainText().strip("\n").replace("\n", "\\n")
        marker = "!" if self.directive.isChecked() else ";"
        just = ("V" if self.vertical.isChecked() else "") + self.just.currentText()
        return asc.Text(x, y, just, self.size.currentIndex(), marker + body)


# ---------------------------------------------------------------- net label

def _flag_glyph(kind):
    """Small pictures next to the Net Name choices: GND, COM and a named label."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    pm = QPixmap(40, 26)
    pm.fill(QColor("#c0c0c0"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#0000ff"))
    pen.setWidthF(1.2)
    p.setPen(pen)
    if kind == "gnd":
        p.drawLine(QPointF(20, 3), QPointF(20, 9))
        p.drawPolyline([QPointF(6, 9), QPointF(34, 9), QPointF(20, 21), QPointF(6, 9)])
    elif kind == "com":
        p.drawLine(QPointF(20, 3), QPointF(20, 21))
        p.drawPolyline([QPointF(10, 11), QPointF(20, 21), QPointF(30, 11)])
    else:
        p.setPen(QColor("#000000"))
        f = p.font()
        f.setBold(True)
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(pm.rect().adjusted(0, -4, 0, 0), Qt.AlignHCenter | Qt.AlignTop, "???")
        p.setPen(pen)
        p.drawRect(17, 16, 6, 6)
    p.end()
    return pm


class NetLabelDialog(QDialog):
    """'Net Name' dialog (N), laid out like LTspice's: GND, COM or a name, and a port type."""
    PORTS = [("None", None), ("Input", "In"), ("Output", "Out"), ("BiDirect", "BiDir")]

    def __init__(self, parent=None, flag: asc.Flag | None = None):
        super().__init__(parent)
        self.setWindowTitle("Net Name")
        grid = QGridLayout(self)
        self.group = QButtonGroup(self)
        self.opts = {}
        for row, (key, label) in enumerate([("gnd", "GND(global node 0)"), ("com", "COM")]):
            pic = QLabel()
            pic.setPixmap(_flag_glyph(key))
            grid.addWidget(pic, row, 0)
            rb = QRadioButton(label)
            self.group.addButton(rb)
            self.opts[key] = rb
            grid.addWidget(rb, row, 1, 1, 2)
        pic = QLabel()
        pic.setPixmap(_flag_glyph("name"))
        grid.addWidget(pic, 2, 0)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setMinimumWidth(130)
        grid.addWidget(self.name, 2, 1, 1, 2)
        grid.addWidget(QLabel("Port Type:"), 3, 0, 1, 2, Qt.AlignRight)
        self.port = QComboBox()
        self.port.addItems([p for p, _ in self.PORTS])
        grid.addWidget(self.port, 3, 2)
        row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        grid.addLayout(row, 4, 0, 1, 3)
        # a hidden "named" choice so that typing a name clears GND/COM
        self.opts["none"] = QRadioButton()
        self.group.addButton(self.opts["none"])
        self.opts["none"].setChecked(True)
        self.name.editTextChanged.connect(lambda t: t and self.opts["none"].setChecked(True))
        if flag:
            if flag.name == "0":
                self.opts["gnd"].setChecked(True)
            elif flag.name.upper() == "COM":
                self.opts["com"].setChecked(True)
            else:
                self.name.setEditText(flag.name)
                self.opts["none"].setChecked(True)
                idx = next((i for i, (_, k) in enumerate(self.PORTS) if k == flag.iopin), 0)
                self.port.setCurrentIndex(idx)
        self.opts["gnd"].toggled.connect(lambda on: on and self.name.setEditText(""))
        self.opts["com"].toggled.connect(lambda on: on and self.name.setEditText(""))
        self.name.setFocus()
        self.name.lineEdit().selectAll()
        popup_at_cursor(self)

    def set_names(self, names):
        cur = self.name.currentText()
        self.name.addItems(sorted(set(names)))
        self.name.setEditText(cur)

    def apply_to(self, flag: asc.Flag):
        name = self.name.currentText().strip()
        if self.opts["gnd"].isChecked():
            name = "0"
        elif self.opts["com"].isChecked():
            name = "COM"
        flag.name = name or "N"
        flag.iopin = self.PORTS[self.port.currentIndex()][1] if name not in ("0", "COM") else None


# ---------------------------------------------------------------- component editors

_PARAM_RE = re.compile(r'(\w+)\s*=\s*("[^"]*"|\S+)')


def _split_value(v: str):
    """'10K tol=1 pwr=.25 mfg="Würth Elektronik"' -> ('10K', {'tol': '1', ..., 'mfg': 'Würth Elektronik'})"""
    params = {k: val.strip('"') for k, val in _PARAM_RE.findall(v)}
    base = _PARAM_RE.sub("", v).split()
    return " ".join(base), params


class PartPicker(QDialog):
    """'Select Resistor/Capacitor/Inductor': LTspice's table of real parts (lib/cmp/standard_*.db)."""
    TABLES = {
        "R": ("standard_res.db", "Resistor", "R", "Ω",
              [("R", "R"), ("Mfg", "Mfg"), ("Part No.", "Part No."), ("Power", "pwr"), ("Tolerance", "tol")]),
        "C": ("standard_cap.db", "Capacitor", "C", "F",
              [("C", "C"), ("Mfg", "Mfg"), ("Type", "Type"), ("Part No.", "Part No."), ("Voltage", "V"),
               ("Irms", "Irms"), ("Rser", "Rser"), ("Lser", "Lser")]),
        "L": ("standard_ind.db", "Inductor", "L", "H",
              [("L", "L"), ("Mfg", "Mfg"), ("Part No.", "Part No."), ("Ipk", "Ipk"), ("Rser", "Rser"),
               ("Rpar", "Rpar"), ("Cpar", "Cpar")]),
    }

    def __init__(self, parent, kind: str, value: str = ""):
        super().__init__(parent)
        from .. import config
        from ..sim.spicenum import fmt, parse
        self._fmt = fmt
        fname, table, vcol, self.unit, self.cols = self.TABLES[kind]
        self.setWindowTitle(f"Select {table}")
        self.rows = []
        db = config.CMP_DIR / fname
        try:
            import sqlite3
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            names = ", ".join(f'"{c}"' for c, _ in self.cols)
            self.rows = list(con.execute(f'SELECT {names} FROM "{table}" ORDER BY "{vcol}"'))
            con.close()
        except Exception:  # noqa: BLE001 - no database: show an empty table
            self.rows = []
        lay = QGridLayout(self)
        show_all = QPushButton("Show All")
        lay.addWidget(show_all, 0, 0)
        lay.addWidget(QLabel("Part No.:"), 0, 1)
        self.part = QLineEdit()
        lay.addWidget(self.part, 0, 2)
        filt = QPushButton("Filter")
        lay.addWidget(filt, 0, 3)
        lay.addLayout(_ok_cancel_column(self), 0, 4, 2, 1)
        self.table = QTableWidget(0, len(self.cols))
        self.table.setHorizontalHeaderLabels([c for c, _ in self.cols])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.accept)
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 2)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1, 0, 1, 4)
        show_all.clicked.connect(lambda: (self.part.clear(), self._fill()))
        filt.clicked.connect(self._fill)
        self.part.returnPressed.connect(self._fill)
        self.resize(640, 360)
        self.target = parse(value) if value else None
        self._fill()
        popup_at_cursor(self)

    def _cell(self, i, v):
        if v is None:
            return ""
        if isinstance(v, float):
            if i == 0:
                return self._fmt(v, "", 3)
            return f"{v:.6g}"
        return str(v)

    def _fill(self):
        q = self.part.text().strip().lower()
        rows = [r for r in self.rows if not q or q in str(r[[c for c, _ in self.cols].index("Part No.")] or "").lower()]
        self.shown = rows
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(self._cell(c, v)))
        # start at the part's present value, like LTspice
        start = 0
        if self.target is not None:
            start = next((k for k, row in enumerate(rows) if row[0] is not None and row[0] >= self.target * 0.999), 0)
        if rows:
            self.table.selectRow(start)
            self._scroll_selected()

    def _scroll_selected(self):
        r = self.table.currentRow()
        if r >= 0 and self.isVisible():
            self.table.scrollToItem(self.table.item(r, 0), QTableWidget.PositionAtTop)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._scroll_selected()

    def chosen(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0 or r >= len(self.shown):
            return None
        return {key: v for (_, key), v in zip(self.cols, self.shown[r])}


class RLCDialog(QDialog):
    """Resistor / Capacitor / Inductor editors, laid out like LTspice's: part info and a
    'Select ...' button on top, OK/Cancel at the right, the properties below."""
    FIELDS = {
        "R": ("Resistor", [("Resistance[Ω]:", "value"), ("Tolerance[%]:", "tol"),
                           ("Power Rating[W]:", "pwr")]),
        "C": ("Capacitor", [("Capacitance[F]:", "value"), ("Voltage Rating[V]:", "V"),
                            ("RMS Current Rating[A]:", "Irms"),
                            ("Equiv. Series Resistance[Ω]:", "Rser"),
                            ("Equiv. Series Inductance[H]:", "Lser"),
                            ("Equiv. Parallel Resistance[Ω]:", "Rpar"),
                            ("Equiv. Parallel Capacitance[F]:", "Cpar")]),
        "L": ("Inductor", [("Inductance[H]:", "value"), ("Peak Current[A]:", "Ipk"),
                           ("Series Resistance[Ω]:", "Rser"),
                           ("Parallel Resistance[Ω]:", "Rpar"),
                           ("Parallel Capacitance[F]:", "Cpar")]),
    }

    def __init__(self, parent, inst: asc.SymbolInst, kind: str, sym=None):
        super().__init__(parent)
        title, fields = self.FIELDS[kind]
        self.kind = kind
        self.setWindowTitle(f"{title} - {inst.name}")
        self.inst = inst
        value = inst.attrs.get("Value", sym.attrs.get("Value", "") if sym else "")
        base, params = _split_value(value + " " + inst.attrs.get("SpiceLine", ""))
        self.info = {k: params.pop(k, "") for k in ("mfg", "pn", "type")}
        outer = QVBoxLayout(self)
        top = QHBoxLayout()
        info = QGridLayout()
        self.info_labels = {}
        rows = [("Manufacturer:", "mfg"), ("Part Number:", "pn")] + ([("Type:", "type")] if kind == "C" else [])
        for r, (label, key) in enumerate(rows):
            info.addWidget(QLabel(label), r, 0, Qt.AlignRight)
            lab = QLabel(self.info[key] or "--------")
            self.info_labels[key] = lab
            info.addWidget(lab, r, 1)
        sel = QPushButton(f"Select {title}")
        sel.clicked.connect(self._select)
        info.addWidget(sel, len(rows), 0, 1, 2, Qt.AlignLeft)
        top.addLayout(info, 1)
        top.addLayout(_ok_cancel_column(self))
        outer.addLayout(top)
        box = QGroupBox(f"{title} Properties")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignRight)
        self.edits = {}
        for label, key in fields:
            e = QLineEdit(base if key == "value" else params.pop(key, ""))
            e.setMaximumWidth(90)
            form.addRow(label, e)
            self.edits[key] = e
        self.extra = params
        outer.addWidget(box)
        self.edits["value"].selectAll()
        self.edits["value"].setFocus()
        popup_at_cursor(self)

    def _select(self):
        dlg = PartPicker(self, self.kind, self.edits["value"].text().strip())
        if dlg.exec() != QDialog.Accepted:
            return
        row = dlg.chosen()
        if not row:
            return
        from ..sim.spicenum import fmt
        self.edits["value"].setText(fmt(row[{"R": "R", "C": "C", "L": "L"}[self.kind]], "", 3))
        for key, e in self.edits.items():
            if key != "value" and key in row:
                v = row[key]
                e.setText("" if v in (None, 0, 0.0) else f"{v:.6g}")
        self.info = {"mfg": row.get("Mfg") or "", "pn": row.get("Part No.") or "",
                     "type": row.get("Type") or ""}
        for k, lab in self.info_labels.items():
            lab.setText(self.info[k] or "--------")

    def apply(self):
        self.inst.attrs["Value"] = self.edits["value"].text().strip()
        spice = [f"{k}={e.text().strip()}" for k, e in self.edits.items()
                 if k != "value" and e.text().strip()]
        spice += [f"{k}={v}" for k, v in self.extra.items()]
        spice += [f'{k}="{v}"' for k, v in self.info.items() if v]
        if spice:
            self.inst.attrs["SpiceLine"] = " ".join(spice)
        else:
            self.inst.attrs.pop("SpiceLine", None)


class SimpleSourceDialog(QDialog):
    """The small editor LTspice opens for a plain DC source: value, series resistance, and
    'Advanced' for the full function editor."""

    def __init__(self, parent, inst: asc.SymbolInst, current=False):
        super().__init__(parent)
        self.inst = inst
        self.advanced = False
        unit = "A" if current else "V"
        self.setWindowTitle(f"{'Current' if current else 'Voltage'} Source - {inst.name}")
        lay = QHBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        value = (inst.attrs.get("Value", "") + " " + inst.attrs.get("Value2", "")).strip()
        rser = re.search(r"(?i)\bRser\s*=\s*(\S+)", value)
        dc = re.sub(r"(?i)\bRser\s*=\s*\S+", "", value)
        dc = re.sub(r"(?i)\bDC\b", "", dc).strip()
        self.dc = QLineEdit(dc)
        self.rser = QLineEdit(rser.group(1) if rser else "")
        form.addRow(f"DC value[{unit}]:", self.dc)
        if not current:
            form.addRow("Series Resistance[Ω]:", self.rser)
        lay.addLayout(form)
        adv = QPushButton("Advanced")
        adv.clicked.connect(self._advanced)
        lay.addLayout(_ok_cancel_column(self, [adv]))
        self.dc.selectAll()
        self.dc.setFocus()
        popup_at_cursor(self)

    @staticmethod
    def handles(inst: asc.SymbolInst) -> bool:
        """True when the source is just a DC value (maybe with Rser), as LTspice requires."""
        v = (inst.attrs.get("Value", "") + " " + inst.attrs.get("Value2", "")).strip()
        v = re.sub(r"(?i)\bRser\s*=\s*\S+", "", v)
        v = re.sub(r"(?i)^\s*DC\b", "", v).strip()
        return len(v.split()) <= 1 and "(" not in v

    def _advanced(self):
        self.advanced = True
        self.accept()

    def apply(self):
        parts = [self.dc.text().strip() or "0"]
        if self.rser.text().strip():
            parts.append(f"Rser={self.rser.text().strip()}")
        self.inst.attrs["Value"] = " ".join(parts)
        self.inst.attrs.pop("Value2", None)


class VoltageSourceDialog(QDialog):
    """'Independent Voltage Source' editor with the LTspice function list."""
    FUNCS = {
        "(none)": [],
        "PULSE": ["Vinitial[V]:", "Von[V]:", "Tdelay[s]:", "Trise[s]:", "Tfall[s]:",
                  "Ton[s]:", "Tperiod[s]:", "Ncycles:"],
        "SINE": ["DC offset[V]:", "Amplitude[V]:", "Freq[Hz]:", "Tdelay[s]:",
                 "Theta[1/s]:", "Phi[deg]:", "Ncycles:"],
        "EXP": ["Vinitial[V]:", "Vpulsed[V]:", "Rise Delay[s]:", "Rise Tau[s]:",
                "Fall Delay[s]:", "Fall Tau[s]:"],
        "SFFM": ["DC offset[V]:", "Amplitude[V]:", "Carrier Freq[Hz]:",
                 "Modulation Index:", "Signal Freq[Hz]:"],
        "PWL": [],
    }

    def __init__(self, parent, inst: asc.SymbolInst, current=False):
        super().__init__(parent)
        self.inst = inst
        unit = "A" if current else "V"
        self.setWindowTitle(f"Independent {'Current' if current else 'Voltage'} Source - {inst.name}")
        value = inst.attrs.get("Value", "")
        value2 = inst.attrs.get("Value2", "")
        full = (value + " " + value2).strip()
        lay = QHBoxLayout(self)
        left = QGroupBox("Functions")
        ll = QVBoxLayout(left)
        self.func_buttons = {}
        for f in self.FUNCS:
            label = {"PWL": "PWL(t1 v1 t2 v2...)"}.get(f, f if f == "(none)" else
                                                      f"{f}({' '.join(x.split('[')[0].split(':')[0] for x in self.FUNCS[f][:3])}...)")
            rb = QRadioButton(label)
            self.func_buttons[f] = rb
            ll.addWidget(rb)
        self.stack = QStackedWidget()
        self.param_edits = {}
        for f, names in self.FUNCS.items():
            w = QWidget()
            fl = QFormLayout(w)
            edits = []
            if f == "PWL":
                e = QPlainTextEdit()
                e.setPlaceholderText("t1 v1 t2 v2 ...")
                fl.addRow(e)
                edits.append(e)
            for n in names:
                e = QLineEdit()
                fl.addRow(n.replace("[V]", f"[{unit}]"), e)
                edits.append(e)
            self.param_edits[f] = edits
            self.stack.addWidget(w)
            self.func_buttons[f].toggled.connect(lambda on, w=w: on and self.stack.setCurrentWidget(w))
        ll.addWidget(self.stack)
        lay.addWidget(left)

        right = QVBoxLayout()
        dc = QGroupBox("DC Value")
        dl = QFormLayout(dc)
        self.dc = QLineEdit()
        dl.addRow(f"DC value[{unit}]:", self.dc)
        right.addWidget(dc)
        ac = QGroupBox("Small signal AC analysis(.AC)")
        al = QFormLayout(ac)
        self.ac_amp = QLineEdit()
        self.ac_phase = QLineEdit()
        al.addRow(f"AC Amplitude[{unit}]:", self.ac_amp)
        al.addRow("AC Phase[deg]:", self.ac_phase)
        right.addWidget(ac)
        par = QGroupBox("Parasitic Properties")
        pl = QFormLayout(par)
        self.rser = QLineEdit()
        self.cpar = QLineEdit()
        if not current:
            pl.addRow("Series Resistance[Ω]:", self.rser)
            pl.addRow("Parallel Capacitance[F]:", self.cpar)
            right.addWidget(par)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        right.addStretch()
        right.addWidget(bb)
        lay.addLayout(right)
        self._load(full)

    def _load(self, full):
        m = re.search(r"(?i)\b(PULSE|SINE?|EXP|SFFM|PWL)\s*\(([^)]*)\)", full)
        func = "(none)"
        if m:
            func = m.group(1).upper()
            func = "SINE" if func == "SIN" else func
            args = m.group(2).split()
            edits = self.param_edits[func]
            if func == "PWL":
                edits[0].setPlainText(" ".join(args))
            else:
                for e, a in zip(edits, args):
                    e.setText(a)
            rest = full[:m.start()] + full[m.end():]
        else:
            rest = full
        self.func_buttons[func].setChecked(True)
        self.stack.setCurrentIndex(list(self.FUNCS).index(func))
        acm = re.search(r"(?i)\bAC\s+(\S+)(?:\s+([-\d.e+]+))?", rest)
        if acm:
            self.ac_amp.setText(acm.group(1))
            self.ac_phase.setText(acm.group(2) or "")
            rest = rest[:acm.start()] + rest[acm.end():]
        for key, edit in (("Rser", self.rser), ("Cpar", self.cpar)):
            pm = re.search(rf"(?i)\b{key}\s*=\s*(\S+)", rest)
            if pm:
                edit.setText(pm.group(1))
                rest = rest[:pm.start()] + rest[pm.end():]
        rest = re.sub(r"(?i)\bDC\b", "", rest).strip()
        if rest:
            self.dc.setText(rest.split()[0])

    def apply(self):
        func = next(f for f, b in self.func_buttons.items() if b.isChecked())
        parts = []
        if self.dc.text().strip():
            parts.append(self.dc.text().strip())
        if func != "(none)":
            edits = self.param_edits[func]
            if func == "PWL":
                args = edits[0].toPlainText().split()
            else:
                args = [e.text().strip() for e in edits]
                while args and not args[-1]:
                    args.pop()
                args = [a or "0" for a in args]
            parts.append(f"{func}({' '.join(args)})")
        if self.ac_amp.text().strip():
            parts.append(f"AC {self.ac_amp.text().strip()} {self.ac_phase.text().strip()}".strip())
        if self.rser.text().strip():
            parts.append(f"Rser={self.rser.text().strip()}")
        if self.cpar.text().strip():
            parts.append(f"Cpar={self.cpar.text().strip()}")
        self.inst.attrs["Value"] = " ".join(parts) if parts else "0"
        self.inst.attrs.pop("Value2", None)


class AttributeEditor(QDialog):
    """'Component Attribute Editor' (Ctrl+right-click, Super Expert mode)."""
    KEYS = ["Prefix", "InstName", "SpiceModel", "Value", "Value2", "SpiceLine", "SpiceLine2"]
    WIN = {"InstName": 0, "Value": 3, "SpiceModel": 38, "SpiceLine": 39, "SpiceLine2": 40, "Value2": 123}

    def __init__(self, parent, inst: asc.SymbolInst, sym=None):
        super().__init__(parent)
        self.inst, self.sym = inst, sym
        self.setWindowTitle("Component Attribute Editor")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Open Symbol: {sym.path if sym and sym.path else inst.symbol}"))
        self.table = QTableWidget(len(self.KEYS), 3)
        self.table.setHorizontalHeaderLabels(["Attribute", "Value", "Vis."])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        for r, k in enumerate(self.KEYS):
            key_item = QTableWidgetItem(k)
            key_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, key_item)
            v = inst.attrs.get(k)
            if v is None and sym is not None:
                v = sym.attrs.get(k, "")
            self.table.setItem(r, 1, QTableWidgetItem(v or ""))
            vis = QTableWidgetItem("X" if self._visible(k) else "")
            vis.setFlags(Qt.ItemIsEnabled)
            vis.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 2, vis)
        self.table.cellDoubleClicked.connect(self._toggle_vis)
        self.table.setMinimumSize(520, 260)
        lay.addWidget(self.table)
        _buttons(self, lay)

    def _visible(self, key):
        idx = self.WIN.get(key)
        if idx is None:
            return False
        w = self.inst.windows.get(idx) or (self.sym.windows.get(idx) if self.sym else None)
        return w is not None and w.just != "Invisible"

    def _toggle_vis(self, r, c):
        if c == 2:
            it = self.table.item(r, 2)
            it.setText("" if it.text() else "X")

    def apply(self):
        from ..model.asy import Window
        for r, k in enumerate(self.KEYS):
            v = self.table.item(r, 1).text()
            sym_v = self.sym.attrs.get(k, "") if self.sym else ""
            if v != sym_v or k in self.inst.attrs or k == "InstName":
                if v or k in self.inst.attrs:
                    self.inst.attrs[k] = v
            vis = bool(self.table.item(r, 2).text())
            idx = self.WIN.get(k)
            if idx is None or vis == self._visible(k):
                continue
            base = self.inst.windows.get(idx) or (self.sym.windows.get(idx) if self.sym else None)
            if vis:
                self.inst.windows[idx] = Window(base.x, base.y, "Left", base.size) if base \
                    and base.just == "Invisible" else (base or Window(36, 40 + 16 * r, "Left", 2))
            elif base:
                self.inst.windows[idx] = Window(base.x, base.y, "Invisible", base.size)


# ---------------------------------------------------------------- simulation command

class SimCommandDialog(QDialog):
    """'Edit Simulation Command' with one tab per analysis."""
    TABS = [
        ("Transient", ".tran", [("Stop time:", ""), ("Time to start saving data:", ""),
                                ("Maximum Timestep:", "")],
         ["Start external DC supply voltages at 0V", "Stop simulating if steady state is detected",
          "Don't reset T=0 when steady state is detected", "Step the load current source",
          "Skip initial operating point solution"]),
        ("AC Analysis", ".ac", [("Type of sweep:", "combo:Octave,Decade,Linear,List"),
                                ("Number of points per octave:", ""), ("Start frequency:", ""),
                                ("Stop frequency:", "")], []),
        ("DC sweep", ".dc", [("Name of 1st source to sweep:", ""), ("Type of sweep:", "combo:Linear,Octave,Decade,List"),
                             ("Start value:", ""), ("Stop value:", ""), ("Increment:", "")], []),
        ("Noise", ".noise", [("Output:", ""), ("Input:", ""), ("Type of sweep:", "combo:Octave,Decade,Linear,List"),
                             ("Number of points per octave:", ""), ("Start frequency:", ""),
                             ("Stop frequency:", "")], []),
        ("DC Transfer", ".tf", [("Output:", ""), ("Source:", "")], []),
        ("DC op pnt", ".op", [], []),
        # ngspice extensions, not in LTspice
        ("Pole-Zero", ".pz", [("Input node:", ""), ("Input reference node:", ""), ("Output node:", ""),
                              ("Output reference node:", ""),
                              ("Transfer function:", "combo:Voltage gain,Transimpedance"),
                              ("Find:", "combo:Poles and zeros,Poles only,Zeros only")], []),
        ("Distortion", ".disto", [("Type of sweep:", "combo:Decade,Octave,Linear"),
                                  ("Number of points per decade:", ""), ("Start frequency:", ""),
                                  ("Stop frequency:", ""), ("F2/F1 (optional):", "")], []),
    ]
    SWEEP = {"Octave": "oct", "Decade": "dec", "Linear": "lin", "List": "list",
             "Voltage gain": "vol", "Transimpedance": "cur",
             "Poles and zeros": "pz", "Poles only": "pol", "Zeros only": "zer"}

    def __init__(self, parent=None, current: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Edit Simulation Command")
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.fields = []
        for title, cmd, fields, checks in self.TABS:
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.addWidget(QLabel({".tran": "Perform a non-linear, time-domain simulation.",
                                 ".ac": "Compute the small signal AC behavior of the circuit linearized about its DC operating point.",
                                 ".dc": "Compute the DC operating point of a circuit while stepping independent sources and treating capacitances as open circuits and inductances as short circuits.",
                                 ".noise": "Perform a frequency domain small signal noise analysis.",
                                 ".tf": "Find the DC small-signal transfer function.",
                                 ".op": "Find the DC operating point solution using capacitances as open circuits and inductances as short circuits.",
                                 ".pz": "Find the poles and zeros of a transfer function (ngspice only; LTspice has no .pz).",
                                 ".disto": "Small-signal 2nd and 3rd harmonic distortion; sources need DISTOF1/DISTOF2 "
                                           "(ngspice only; LTspice has no .disto)."}[cmd]))
            wl.itemAt(0).widget().setAlignment(Qt.AlignHCenter)
            wl.itemAt(0).widget().setWordWrap(True)
            # LTspice: right-aligned labels with short fields, and "label: [x]" check boxes
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight)
            form.setFormAlignment(Qt.AlignHCenter)
            edits = []
            for label, spec in fields:
                if spec.startswith("combo:"):
                    e = QComboBox()
                    e.addItems(spec[6:].split(","))
                    e.currentIndexChanged.connect(self._update)
                else:
                    e = QLineEdit()
                    e.textChanged.connect(self._update)
                e.setFixedWidth(110)
                form.addRow(label, e)
                edits.append(e)
            boxes = []
            for c in checks:
                cb = QCheckBox()
                cb.toggled.connect(self._update)
                form.addRow(c + ":", cb)
                boxes.append(cb)
            wl.addLayout(form)
            wl.addStretch()
            self.fields.append((cmd, edits, boxes))
            self.tabs.addTab(w, title)
        self.tabs.currentChanged.connect(self._update)
        lay.addWidget(self.tabs)
        self.syntax = QLabel()
        lay.addWidget(self.syntax)
        self.cmd = QLineEdit()
        self.cmd.setReadOnly(True)
        lay.addWidget(self.cmd)
        row = QHBoxLayout()
        row.addStretch()
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.setMinimumWidth(540)
        self._load(current)
        self._update()

    def _load(self, current):
        tok = current.split()
        if not tok:
            return
        head = tok[0].lower()
        for i, (cmd, edits, boxes) in enumerate(self.fields):
            if cmd != head:
                continue
            self.tabs.setCurrentIndex(i)
            args = tok[1:]
            if cmd == ".tran":
                mods = {a.lower() for a in args if a[0].isalpha()}
                nums = [a for a in args if not a[0].isalpha()]
                if len(nums) == 1:
                    edits[0].setText(nums[0])
                elif len(nums) >= 2:
                    edits[0].setText(nums[1])
                    if len(nums) > 2:
                        edits[1].setText(nums[2])
                    if len(nums) > 3:
                        edits[2].setText(nums[3])
                for cb, m in zip(boxes, ["startup", "steady", "nodiscard", "step", "uic"]):
                    cb.setChecked(m in mods)
            else:
                j = 0
                for e in edits:
                    if j >= len(args):
                        break
                    if isinstance(e, QComboBox):
                        rev = {v: k for k, v in self.SWEEP.items()}
                        if args[j].lower() in rev:
                            e.setCurrentText(rev[args[j].lower()])
                            j += 1
                        continue
                    e.setText(args[j])
                    j += 1

    SYNTAX = {".tran": ".tran <Tstop> [<option> [<option>] ...]",
              ".ac": ".ac <oct, dec, lin> <Nsteps> <StartFreq> <EndFreq>",
              ".dc": ".dc <srcnam> <Vstart> <Vstop> <Vincr> [<srcnam2> <Vstart2> <Vstop2> <Vincr2>]",
              ".noise": ".noise V(<out>[,<ref>]) <src> <oct, dec, lin> <Nsteps> <StartFreq> <EndFreq>",
              ".tf": ".tf V(<node>[,<ref>]) <source>",
              ".op": ".op",
              ".pz": ".pz <in> <inref> <out> <outref> <vol | cur> <pz | pol | zer>",
              ".disto": ".disto <dec | oct | lin> <Npoints> <Fstart> <Fstop> [<F2/F1>]"}

    def _update(self, *_):
        cmd, edits, boxes = self.fields[self.tabs.currentIndex()]
        self.syntax.setText("Syntax:  " + self.SYNTAX.get(cmd, cmd))
        vals = []
        for e in edits:
            if isinstance(e, QComboBox):
                s = self.SWEEP[e.currentText()]
                if cmd == ".dc" and s == "lin":
                    continue
                vals.append(s)
            else:
                vals.append(e.text().strip())
        if cmd == ".tran":
            stop, start, maxstep = vals
            args = ["0", stop, start or "0", maxstep] if (start or maxstep) else [stop]
            args = [a for a in args if a]
            mods = [m for cb, m in zip(boxes, ["startup", "steady", "nodiscard", "step", "uic"]) if cb.isChecked()]
            text = " ".join([cmd] + args + mods)
        else:
            text = " ".join([cmd] + [v for v in vals if v])
        self.cmd.setText(text)

    def command(self):
        return self.cmd.text()


class FFTDialog(QDialog):
    """'Select which waveforms to include in FFT' (View > FFT)."""

    def __init__(self, names, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget
        self.setWindowTitle("Select which waveforms to include in FFT")
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.addItems(names)
        self.list.selectAll()
        lay.addWidget(self.list)
        form = QFormLayout()
        self.npts = QComboBox()
        self.npts.addItems([str(2 ** k) for k in range(10, 21)])
        self.npts.setCurrentText(str(2 ** 16))
        self.window = QComboBox()
        from ..sim.fft import WINDOWS
        self.window.addItems(list(WINDOWS))
        form.addRow("Number of data point samples in time:", self.npts)
        form.addRow("Windowing function:", self.window)
        lay.addLayout(form)
        self.visible_only = QCheckBox("Use only the zoomed time range")
        self.visible_only.setChecked(True)
        lay.addWidget(self.visible_only)
        _buttons(self, lay)

    def selected(self):
        return [it.text() for it in self.list.selectedItems()]

    def points(self):
        return int(self.npts.currentText())
