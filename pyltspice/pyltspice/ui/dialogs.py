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


# ---------------------------------------------------------------- text

class TextDialog(QDialog):
    """'Edit Text on the Schematic' (T and S commands)."""

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
        right = QFormLayout()
        self.just = QComboBox()
        self.just.addItems(JUSTS)
        self.vertical = QCheckBox("Vertical Text")
        self.size = QComboBox()
        self.size.addItems(FONT_SIZES)
        right.addRow("Justification", self.just)
        right.addRow("Font Size", self.size)
        right.addRow(self.vertical)
        top.addLayout(right)
        lay.addLayout(top)
        lay.addWidget(QLabel("Type Ctrl-M to start a new line."))
        self.edit = QPlainTextEdit()
        f = QFont("Monospace")
        f.setStyleHint(QFont.TypeWriter)
        self.edit.setFont(f)
        self.edit.setMinimumSize(480, 140)
        lay.addWidget(self.edit)
        _buttons(self, lay)

        is_dir = text.is_directive if text else directive
        (self.directive if is_dir else self.comment).setChecked(True)
        just = text.just if text else "Left"
        self.vertical.setChecked(just.startswith("V"))
        base = just[1:] if just.startswith("V") else just
        self.just.setCurrentText(base if base in JUSTS else "Left")
        self.size.setCurrentIndex(text.size if text else 2)
        if text:
            self.edit.setPlainText(text.body)
        self.edit.setFocus()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_M and ev.modifiers() & Qt.ControlModifier:
            self.edit.insertPlainText("\n")
            return
        super().keyPressEvent(ev)

    def result_text(self, x=0, y=0) -> asc.Text:
        body = self.edit.toPlainText().strip("\n").replace("\n", "\\n")
        marker = "!" if self.directive.isChecked() else ";"
        just = ("V" if self.vertical.isChecked() else "") + self.just.currentText()
        return asc.Text(x, y, just, self.size.currentIndex(), marker + body)


# ---------------------------------------------------------------- net label

class NetLabelDialog(QDialog):
    """'Net Name' dialog (F4)."""

    def __init__(self, parent=None, flag: asc.Flag | None = None):
        super().__init__(parent)
        self.setWindowTitle("Net Name")
        lay = QVBoxLayout(self)
        self.name = QComboBox()
        self.name.setEditable(True)
        lay.addWidget(self.name)
        kind = QGroupBox("Port Type")
        gl = QGridLayout(kind)
        self.group = QButtonGroup(self)
        self.opts = {}
        for i, (key, label) in enumerate([("gnd", "GND(global node 0)"), ("com", "COM"),
                                          ("none", "None"), ("In", "Input"),
                                          ("Out", "Output"), ("BiDir", "Bi-Direct.")]):
            rb = QRadioButton(label)
            self.group.addButton(rb)
            self.opts[key] = rb
            gl.addWidget(rb, i // 2, i % 2)
        lay.addWidget(kind)
        _buttons(self, lay)
        self.opts["none"].setChecked(True)
        if flag:
            if flag.name == "0":
                self.opts["gnd"].setChecked(True)
            else:
                self.name.setEditText(flag.name)
                if flag.iopin in self.opts:
                    self.opts[flag.iopin].setChecked(True)
        self.opts["gnd"].toggled.connect(lambda on: on and self.name.setEditText("0"))
        self.opts["com"].toggled.connect(lambda on: on and self.name.setEditText("COM"))

    def set_names(self, names):
        cur = self.name.currentText()
        self.name.addItems(sorted(set(names)))
        self.name.setEditText(cur)

    def apply_to(self, flag: asc.Flag):
        name = self.name.currentText().strip()
        if self.opts["gnd"].isChecked():
            name = "0"
        flag.name = name or "N"
        flag.iopin = next((k for k in ("In", "Out", "BiDir") if self.opts[k].isChecked()), None)


# ---------------------------------------------------------------- component editors

def _split_value(v: str):
    """'10K tol=1 pwr=.25' -> ('10K', {'tol': '1', 'pwr': '.25'})"""
    toks = re.sub(r"\s*=\s*", "=", v).split()
    base = [t for t in toks if "=" not in t]
    params = dict(t.split("=", 1) for t in toks if "=" in t)
    return " ".join(base), params


class RLCDialog(QDialog):
    """Resistor / Capacitor / Inductor quick editors."""
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
        self.setWindowTitle(f"{title} - {inst.name}")
        self.inst = inst
        lay = QVBoxLayout(self)
        form = QFormLayout()
        value = inst.attrs.get("Value", sym.attrs.get("Value", "") if sym else "")
        base, params = _split_value(value + " " + inst.attrs.get("SpiceLine", ""))
        self.edits = {}
        for label, key in fields:
            e = QLineEdit(base if key == "value" else params.pop(key, ""))
            form.addRow(label, e)
            self.edits[key] = e
        self.extra = params
        lay.addLayout(form)
        self.show_value = QCheckBox("Show value on schematic")
        self.show_value.setChecked(True)
        lay.addWidget(self.show_value)
        _buttons(self, lay)

    def apply(self):
        self.inst.attrs["Value"] = self.edits["value"].text().strip()
        spice = [f"{k}={e.text().strip()}" for k, e in self.edits.items()
                 if k != "value" and e.text().strip()]
        spice += [f"{k}={v}" for k, v in self.extra.items()]
        if spice:
            self.inst.attrs["SpiceLine"] = " ".join(spice)
        else:
            self.inst.attrs.pop("SpiceLine", None)


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
    ]
    SWEEP = {"Octave": "oct", "Decade": "dec", "Linear": "lin", "List": "list"}

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
                                 ".op": "Find the DC operating point solution using capacitances as open circuits and inductances as short circuits."}[cmd]))
            form = QFormLayout()
            edits = []
            for label, spec in fields:
                if spec.startswith("combo:"):
                    e = QComboBox()
                    e.addItems(spec[6:].split(","))
                    e.currentIndexChanged.connect(self._update)
                else:
                    e = QLineEdit()
                    e.textChanged.connect(self._update)
                form.addRow(label, e)
                edits.append(e)
            wl.addLayout(form)
            boxes = []
            for c in checks:
                cb = QCheckBox(c)
                cb.toggled.connect(self._update)
                wl.addWidget(cb)
                boxes.append(cb)
            wl.addStretch()
            self.fields.append((cmd, edits, boxes))
            self.tabs.addTab(w, title)
        self.tabs.currentChanged.connect(self._update)
        lay.addWidget(self.tabs)
        lay.addWidget(QLabel("Syntax:"))
        self.cmd = QLineEdit()
        self.cmd.setReadOnly(True)
        lay.addWidget(self.cmd)
        _buttons(self, lay)
        self.setMinimumWidth(560)
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

    def _update(self, *_):
        cmd, edits, boxes = self.fields[self.tabs.currentIndex()]
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
