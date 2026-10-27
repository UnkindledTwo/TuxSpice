"""Tools > Settings: LTspice's tabbed settings dialog.

Tab order, labels, defaults and the [*] markers follow LTspice 26.1.1 under Wine (fresh settings,
see docs/ui_spec.md). As in LTspice, only settings marked [*] are remembered between program
invocations; the others (tolerances, ortho snapping, undo size...) last for this session only.
Options that have no meaning with ngspice, or that TuxSpice doesn't implement, are shown greyed out
with a tooltip that says why, so the dialog keeps LTspice's layout.
"""
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QRadioButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

# key: (default, remembered between invocations)
SPEC = {
    # Operation
    "operation/marching_waveforms": (True, False),
    "operation/expanded_listing": (False, True),
    "operation/save_on_run": (False, True),
    "operation/delete_raw": (False, True),
    "operation/warn_no_rser": (True, True),
    "operation/background": ("Oscilloscope", True),
    "operation/toolbar_style": ("Default", True),
    "operation/toolbar_size": ("Default", True),
    "operation/plot_priority": ("medium", True),
    "operation/fastaccess_ram": ("40%", True),
    "operation/app_theme": ("System", True),      # TuxSpice extra: window colours (not the canvases)
    # Schematic (drafting options); key names predate the dialog and are kept
    "drafting/allow_pin_shorts": (False, True),
    "drafting/autoscroll": (True, True),
    "view/mark_anchors": (False, False),
    "drafting/mark_unconnected": (True, False),
    "view/grid": (False, True),
    "drafting/ortho_wires": (True, False),
    "drafting/ortho_stretch": (False, True),
    "drafting/cut_angled": (True, False),
    "drafting/undo_size": (500, False),
    "drafting/pen_thickness": (1, True),
    "drafting/title_blocks": (True, True),
    "drafting/reverse_wheel": (False, True),
    "drafting/cursor_type": ("Auto", True),
    "drafting/font": ("Tahoma", True),
    "drafting/font_size": (28, True),
    "drafting/font_bold": (True, True),
    # Waveforms
    "waveform/trace_width": (1, True),
    "waveform/cursor_width": (1, True),
    "waveform/radians": (False, True),
    "waveform/cursor_type": ("Auto", True),
    "waveform/font": ("Arial", True),
    "waveform/font_size": (10, True),
    "waveform/font_bold": (True, True),
    "waveform/raw_dir_on": (False, True),
    "waveform/raw_dir": ("", True),
    # SPICE
    "spice/method": ("modified trap", True),
    "spice/noopiter": (False, False),
    "spice/skip_gmin": (False, False),
    "spice/solver": ("Normal", True),
    "spice/threads": ("12", False),
    "spice/matrix": ("object code", False),
    "spice/priority": ("medium", True),
    "spice/gmin": ("1e-12", False),
    "spice/abstol": ("1e-12", False),
    "spice/reltol": ("0.001", False),
    "spice/chgtol": ("1e-14", False),
    "spice/trtol": ("2", True),
    "spice/vntol": ("1e-06", False),
    "spice/sstol": ("0.001", False),
    "spice/mindeltagmin": ("0.0001", False),
    "spice/nobypass": (True, True),
    # Save Defaults
    "save/device_currents": (True, True),
    "save/subckt_voltages": (False, True),
    "save/subckt_currents": (False, True),
    "save/no_base_currents": (False, True),
    "save/internal_voltages": (False, False),
    # Netlist Options
    "netlist/convert_mu": (False, True),
    "netlist/reverse_order": (False, False),
    "netlist/default_devices": (True, True),
    "netlist/default_libraries": (True, True),
    # Compression
    "compression/ascii": (False, True),
    "compression/tran_only": (True, True),
    "compression/first_order": (False, True),
    "compression/second_order": (False, True),
    "compression/window": ("1024", True),
    "compression/reltol": ("0.0025", True),
    "compression/vtol": ("1e-05", True),
    "compression/itol": ("1e-09", True),
    # Search Paths
    "paths/no_subdirs": (False, True),
    "paths/user_dir": ("", True),
    "paths/symbol_paths": ("", True),
    "paths/lib_paths": ("", True),
    # Internet
    "internet/no_cache": (True, False),
    "internet/no_verify": (True, False),
    "internet/usage_data": (False, True),
    # Hacks
    "hacks/convergence": (True, False),
    "hacks/energy_check": (False, True),
    "hacks/tsts": (True, False),
    "hacks/gate_current": ("0", False),
    "hacks/min_shunt": ("1e-06", False),
    "hacks/no_jfet_isr": (False, True),
    "hacks/gmin_isources": (False, False),
    "hacks/ind_damping": (True, True),
    "hacks/mc_clock": (False, True),
}
DEFAULTS = {k: v[0] for k, v in SPEC.items()}

_session = {}           # values of settings LTspice doesn't remember ([*]-less ones)

NO_NGSPICE = "Not applicable: TuxSpice simulates with ngspice, which has no such option."
NOT_YET = "Not implemented in TuxSpice yet."


def _settings():
    return QSettings("pyltspice", "pyltspice")


def _coerce(v, d):
    if isinstance(d, bool):
        return v in (True, "true", "1", 1)
    try:
        return type(d)(v)
    except (TypeError, ValueError):
        return d


def get(key):
    d, keep = SPEC[key]
    if not keep:
        return _session.get(key, d)
    return _coerce(_settings().value(key, d), d)


def put(key, value):
    d, keep = SPEC[key]
    value = _coerce(value, d)
    if keep:
        _settings().setValue(key, value)
    else:
        _session[key] = value


def paths(key):
    """Search path lists: one directory per line or separated by semicolons."""
    import os
    out = []
    for part in get(key).replace(";", "\n").splitlines():
        part = os.path.expandvars(os.path.expanduser(part.strip()))
        if part:
            out.append(part)
    return out


def plot_defs_path():
    """plot.defs (user functions for waveform expressions) lives in the user files directory."""
    from pathlib import Path
    from .. import config
    user = get("paths/user_dir")
    return (Path(user).expanduser() if user else config.DATA_DIR) / "plot.defs"


def run_options():
    """The Settings values that shape a simulation run (sim.runner.RunOptions)."""
    from pathlib import Path
    from ..sim.runner import RunOptions
    user = get("paths/user_dir")
    threads = get("spice/threads")
    threads = threads if threads != DEFAULTS["spice/threads"] else ""   # ngspice's own default
    return RunOptions(
        default_devices=get("netlist/default_devices"), default_libraries=get("netlist/default_libraries"),
        user_dir=Path(user).expanduser() if user else None,
        save_currents=get("save/device_currents"), save_subckt_voltages=get("save/subckt_voltages"),
        save_subckt_currents=get("save/subckt_currents"), no_terminal_currents=get("save/no_base_currents"),
        ascii_raw=get("compression/ascii"), threads=int(threads) if str(threads).isdigit() else 0,
        solver=get("spice/solver"), mc_reseed=get("hacks/mc_clock"),
        expanded_listing=get("operation/expanded_listing"), warn_no_rser=get("operation/warn_no_rser"))


def spice_options() -> str:
    """A .options line for the SPICE-tab values that differ from LTspice's defaults (empty if none).
    LTspice's own defaults are left alone so runs match what the translation layer was tuned for."""
    opts = []
    method = get("spice/method")
    if method != DEFAULTS["spice/method"]:
        opts.append("method=gear" if method == "Gear" else "method=trap")
    for key, name in (("gmin", "gmin"), ("abstol", "abstol"), ("reltol", "reltol"), ("chgtol", "chgtol"),
                      ("trtol", "trtol"), ("vntol", "vntol")):
        v = get(f"spice/{key}").strip()
        if v and v != DEFAULTS[f"spice/{key}"]:
            opts.append(f"{name}={v}")
    if get("spice/noopiter"):
        opts.append("noopiter")
    if get("spice/skip_gmin"):
        opts.append("gminsteps=0")
    return (".options " + " ".join(opts)) if opts else ""


def _row(label, widget, tip=None):
    """'Label: [widget]' with the label right-aligned, as LTspice lays out its settings."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addStretch(1)
    lab = QLabel(label)
    h.addWidget(lab)
    h.addWidget(widget)
    if tip:
        for x in (lab, widget):
            x.setToolTip(tip)
        lab.setEnabled(False)
        widget.setEnabled(False)
    return w


class _Check(QCheckBox):
    """LTspice puts the check box to the right of its label."""

    def __init__(self, text):
        super().__init__(text + "\u200e")      # keeps a trailing "[*]" on the right in RTL layout
        self.setLayoutDirection(Qt.RightToLeft)


class SettingsDialog(QDialog):
    TABS = ["Operation", "Schematic", "Waveforms", "SPICE", "Save Defaults", "Netlist Options",
            "Compression", "Search Paths", "Internet", "Hacks"]
    HELP = {"Operation": "operation.htm", "Schematic": "draftingoptions.htm", "Waveforms": "waveforms.htm",
            "SPICE": "spice.htm", "Save Defaults": "savedefaults.htm", "Netlist Options": "netlistoptions.htm",
            "Compression": "compression.htm", "Search Paths": "symbolandlibrarysearchpaths.htm",
            "Internet": "internetoptions.htm", "Hacks": "hacks.htm"}

    def __init__(self, parent=None, tab=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.main = parent
        self.w = {}                  # key -> widget
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(False)
        for name in self.TABS:
            page = QWidget()
            getattr(self, "_tab_" + name.lower().replace(" ", "_"))(page)
            self.tabs.addTab(page, name)
        lay.addWidget(self.tabs)
        bb = QHBoxLayout()
        bb.addStretch(1)
        for text, slot in (("OK", self._ok), ("Cancel", self.reject), ("Help", self._help)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if text == "OK":
                b.setDefault(True)
            bb.addWidget(b)
        lay.addLayout(bb)
        self._load()
        if tab in self.TABS:
            self.tabs.setCurrentIndex(self.TABS.index(tab))

    # ---------------------------------------------------------------- widgets
    def _check(self, key, text, tip=None):
        star = SPEC[key][1]
        cb = _Check(text + ("[*]" if star and "[*]" not in text else ""))
        self.w[key] = cb
        if tip:
            cb.setEnabled(False)
            cb.setToolTip(tip)
        return cb

    def _combo(self, key, items, editable=False):
        c = QComboBox()
        c.addItems(items)
        c.setEditable(editable)
        self.w[key] = c
        return c

    def _edit(self, key, width=70):
        e = QLineEdit()
        e.setFixedWidth(width)
        self.w[key] = e
        return e

    def _spin(self, key, lo, hi):
        s = QSpinBox()
        s.setRange(lo, hi)
        self.w[key] = s
        return s

    def _footer(self, v, text="[*] Setting remembered between program invocations."):
        v.addStretch(1)
        lab = QLabel(text)
        lab.setAlignment(Qt.AlignCenter)
        v.addWidget(lab)
        b = QPushButton("Reset to Default Values")
        b.clicked.connect(self._reset_tab)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(b)
        h.addStretch(1)
        v.addLayout(h)

    # ---------------------------------------------------------------- tabs
    def _tab_operation(self, page):
        v = QVBoxLayout(page)
        v.addWidget(self._check("operation/marching_waveforms", "Marching Waveforms",
                                tip="Plots are drawn when ngspice finishes; incremental plotting " + NOT_YET[4:]))
        v.addWidget(self._check("operation/expanded_listing", "Generate Expanded Listing"))
        v.addWidget(self._check("operation/save_on_run", "Save all open files on start of simulation"))
        v.addWidget(self._check("operation/delete_raw", "Automatically delete .raw files"))
        v.addWidget(self._check("operation/warn_no_rser", "Warn if no Rser is specified for inductors"))
        v.addWidget(_row("Background image[*]:", self._combo(
            "operation/background", ["Oscilloscope", "None", "User supplied (~/.config/pyltspice/TuxSpice.jpg)"])))
        v.addWidget(_row("Toolbar Style[*]:", self._combo("operation/toolbar_style", ["Default"])))
        v.addWidget(_row("Toolbar icon size[*]:", self._combo("operation/toolbar_size", ["Small", "Default", "Large"])))
        theme = _row("Application theme[*]:", self._combo("operation/app_theme", ["System", "Light", "Dark"]))
        theme.setToolTip("Window and dialog colours: follow the desktop (System) or force light or dark.\n"
                         "Schematic and plot colours are set in Tools > Color Preferences.\n"
                         "(TuxSpice only; LTspice has no such setting.)")
        v.addWidget(theme)
        v.addWidget(_row("Waveform Plotting Thread Priority[*]:",
                         self._combo("operation/plot_priority", ["low", "medium", "high"]), tip=NO_NGSPICE))
        v.addWidget(_row("RAM for Fast Access Conversion[*]:",
                         self._combo("operation/fastaccess_ram", ["10%", "20%", "40%", "60%", "80%"]),
                         tip="TuxSpice has no Fast Access file format."))
        self._footer(v)

    def _tab_schematic(self, page):
        g = QGridLayout(page)
        left = QVBoxLayout()
        left.addWidget(self._check("drafting/allow_pin_shorts", "Allow direct component pin shorts"))
        left.addWidget(self._check("drafting/autoscroll", "Automatically scroll the view"))
        left.addWidget(self._check("view/mark_anchors", "Mark text justification anchor points"))
        left.addWidget(self._check("drafting/mark_unconnected", "Mark unconnected pins"))
        left.addWidget(self._check("view/grid", "Show schematic grid points"))
        left.addWidget(self._check("drafting/ortho_wires", "Orthogonal snap wires"))
        left.addWidget(self._check("drafting/ortho_stretch", "Ortho stretch mode"))
        left.addWidget(self._check("drafting/cut_angled", "Cut angled wires during stretch"))
        left.addWidget(_row("Un-do history size:", self._spin("drafting/undo_size", 10, 100000)))
        left.addWidget(_row("Pen thickness[*]:", self._spin("drafting/pen_thickness", 1, 5)))
        left.addWidget(self._check("drafting/title_blocks", "Show Title Blocks",
                                   tip="LTspice: for internal use."))
        left.addWidget(self._check("drafting/reverse_wheel", "Reverse Mouse Wheel Scroll"))
        left.addWidget(_row("Cursor type[*]:", self._combo("drafting/cursor_type", ["Auto"])))
        g.addLayout(left, 0, 0, 2, 1)
        font = QGroupBox("Font Properties[*]")
        fv = QVBoxLayout(font)
        fam = self._combo("drafting/font", sorted(set(QFontDatabase.families()) | {"Tahoma"}))
        fv.addWidget(fam)
        fv.addWidget(_row("Size[*]:", self._spin("drafting/font_size", 8, 72)))
        fv.addWidget(self._check("drafting/font_bold", "Bold"))
        g.addWidget(font, 0, 1)
        side = QVBoxLayout()
        side.addStretch(1)
        b = QPushButton("Color Scheme[*]")
        b.clicked.connect(self._colors)
        side.addWidget(b)
        b = QPushButton("Keyboard Shortcuts[*]")
        b.clicked.connect(self._shortcuts)
        side.addWidget(b)
        side.addStretch(1)
        g.addLayout(side, 1, 1)
        v = QVBoxLayout()
        g.addLayout(v, 2, 0, 1, 2)
        self._footer(v)

    def _tab_waveforms(self, page):
        v = QVBoxLayout(page)
        v.addWidget(_row("Data trace width[*]:", self._spin("waveform/trace_width", 1, 5)))
        v.addWidget(_row("Cursor width[*]:", self._spin("waveform/cursor_width", 1, 5)))
        v.addWidget(self._check("waveform/radians", "Use radian measure in waveform expressions"))
        v.addWidget(_row("Mouse cursor type[*]:", self._combo("waveform/cursor_type", ["Auto"])))
        v.addWidget(_row("Font[*]:", self._combo("waveform/font", sorted(set(QFontDatabase.families()) | {"Arial"}))))
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(QLabel("Font point size[*]:"))
        h.addWidget(self._spin("waveform/font_size", 6, 36))
        h.addWidget(self._check("waveform/font_bold", "Bold Font"))
        v.addLayout(h)
        h = QHBoxLayout()
        for text, slot in (("Color Scheme[*]", self._colors), ("Open Plot Defs", self._plot_defs),
                           ("Keyboard Shortcuts[*]", self._shortcuts)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        box = QGroupBox("Directory for .raw and .log data files[*]")
        bv = QVBoxLayout(box)
        bv.addWidget(self._check("waveform/raw_dir_on", "Store .raw and .log data files in a specific directory"))
        h = QHBoxLayout()
        e = QLineEdit()
        self.w["waveform/raw_dir"] = e
        h.addWidget(e)
        b = QPushButton("Browse")
        b.clicked.connect(lambda: self._browse_dir(e))
        h.addWidget(b)
        bv.addLayout(h)
        cb = self.w["waveform/raw_dir_on"]
        cb.toggled.connect(e.setEnabled)
        cb.toggled.connect(b.setEnabled)
        v.addWidget(box)
        self._footer(v)

    def _tab_spice(self, page):
        g = QGridLayout(page)
        left = QVBoxLayout()
        box = QGroupBox("Default Integration Method[*]")
        bv = QVBoxLayout(box)
        self.method = {}
        for m in ("trapezoidal", "modified trap", "Gear"):
            r = QRadioButton(m)
            self.method[m] = r
            bv.addWidget(r)
        self.method["modified trap"].setToolTip("ngspice has no modified trapezoidal method; "
                                                "plain trapezoidal is used.")
        left.addWidget(box)
        box = QGroupBox("Default DC solve strategy")
        bv = QVBoxLayout(box)
        for key, text in (("spice/noopiter", "Noopiter"), ("spice/skip_gmin", "Skip Gmin Stepping")):
            cb = QCheckBox(text)
            self.w[key] = cb
            bv.addWidget(cb)
        left.addWidget(box)
        box = QGroupBox("Engine")
        bv = QVBoxLayout(box)
        solver = _row("Solver[*]:", self._combo("spice/solver", ["Normal", "Alternate"]))
        solver.setToolTip("Normal: ngspice's KLU solver. Alternate: Sparse 1.3, ngspice's classic solver.")
        bv.addWidget(solver)
        threads = _row("Max threads:", self._combo("spice/threads", [str(i) for i in range(1, 33)]))
        threads.setToolTip("ngspice's num_threads (OpenMP device evaluation, when ngspice is built with it).")
        bv.addWidget(threads)
        bv.addWidget(_row("Matrix Compiler:", self._combo("spice/matrix", ["object code", "assembly"]),
                          tip=NO_NGSPICE))
        bv.addWidget(_row("Thread Priority[*]:", self._combo("spice/priority", ["low", "medium", "high"]),
                          tip=NO_NGSPICE))
        left.addWidget(box)
        g.addLayout(left, 0, 0)
        right = QVBoxLayout()
        for key, label in (("gmin", "Gmin:"), ("abstol", "Abstol:"), ("reltol", "Reltol:"),
                           ("chgtol", "Chgtol:"), ("trtol", "Trtol[*]:"), ("vntol", "Volttol:")):
            right.addWidget(_row(label, self._edit(f"spice/{key}")))
        right.addWidget(_row("Sstol:", self._edit("spice/sstol"), tip=NO_NGSPICE))
        right.addWidget(_row("MinDeltaGmin:", self._edit("spice/mindeltagmin"), tip=NO_NGSPICE))
        right.addWidget(self._check("spice/nobypass", "No Bypass", tip=NO_NGSPICE))
        right.addStretch(1)
        g.addLayout(right, 0, 1)
        v = QVBoxLayout()
        g.addLayout(v, 1, 0, 1, 2)
        self._footer(v)

    def _tab_save_defaults(self, page):
        v = QVBoxLayout(page)
        v.addWidget(QLabel('These defaults are used when there is no explicit ".save" command'))
        v.addWidget(self._check("save/device_currents", "Save Device Currents"))
        v.addWidget(self._check("save/subckt_voltages", "Save Subcircuit Node Voltages"))
        v.addWidget(self._check("save/subckt_currents", "Save Subcircuit Device Currents"))
        v.addWidget(self._check("save/no_base_currents", "Don't save Ib(), Ie(), Is(), Ig(), or Ix()"))
        v.addSpacing(12)
        v.addWidget(self._check("save/internal_voltages", "Save Internal Device Voltages",
                                tip="ngspice doesn't write internal device nodes to its .raw files."))
        self._footer(v)

    def _tab_netlist_options(self, page):
        v = QVBoxLayout(page)
        box = QGroupBox("Style/Convention")
        bv = QVBoxLayout(box)
        for key, text in (("netlist/convert_mu", "Convert  'µ' to 'u' [*]"),
                          ("netlist/reverse_order", "Reverse comp. order")):
            cb = QCheckBox(text)
            self.w[key] = cb
            bv.addWidget(cb)
        v.addWidget(box)
        box = QGroupBox("Semiconductor Models")
        bv = QVBoxLayout(box)
        for key, text, tip in (
                ("netlist/default_devices", "Default Devices[*]",
                 "Add '.model D D' and the like for parts without a model. Off: SPICE's defaults are "
                 "still used, with a warning."),
                ("netlist/default_libraries", "Default Libraries[*]",
                 "Find models by name in standard.*, TuxSpice's library and your user.dio/.bjt/.mos/.jft.")):
            cb = QCheckBox(text)
            cb.setToolTip(tip)
            self.w[key] = cb
            bv.addWidget(cb)
        v.addWidget(box)
        self._footer(v)

    def _tab_compression(self, page):
        v = QVBoxLayout(page)
        tip = "ngspice's .raw files are never compressed."
        v.addWidget(self._check("compression/ascii", "ASCII data files"))
        for key, text in (("compression/tran_only", "Only compress transient analyses"),
                          ("compression/first_order", "Enable 1st Order Compression"),
                          ("compression/second_order", "Enable 2nd Order Compression")):
            v.addWidget(self._check(key, text, tip=tip))
        for key, label in (("window", "Window Size(No. of Points)[*]:"), ("reltol", "Relative Tolerance[*]:"),
                           ("vtol", "Absolute Voltage tolerance[V][*]:"),
                           ("itol", "Absolute Current tolerance[A][*]:")):
            v.addWidget(_row(label, self._edit(f"compression/{key}"), tip=tip))
        self._footer(v, "[*] These settings are remembered\nbetween program invocations.")

    def _tab_search_paths(self, page):
        v = QVBoxLayout(page)
        v.addWidget(self._check("paths/no_subdirs", "Don't place symbols from schematic subdirectories "))
        box = QGroupBox("User files (.lib, .asy, .sub, .defs, user.dio, user.res, etc)[*]")
        h = QHBoxLayout(box)
        e = QLineEdit()
        self.w["paths/user_dir"] = e
        h.addWidget(e)
        b = QPushButton("Browse")
        b.clicked.connect(lambda: self._browse_dir(e))
        h.addWidget(b)
        v.addWidget(box)
        outer = QGroupBox()
        ov = QVBoxLayout(outer)
        ov.addWidget(QLabel("Separate search path directories with semicolons or new lines."))
        for key, title in (("paths/symbol_paths", "Symbol Search Paths[*]"),
                           ("paths/lib_paths", "Simulation Library Search Paths[*]")):
            box = QGroupBox(title)
            bv = QVBoxLayout(box)
            t = QPlainTextEdit()
            t.setContextMenuPolicy(Qt.CustomContextMenu)
            t.customContextMenuRequested.connect(lambda p, t=t: self._path_menu(t, p))
            t.setToolTip("Right-Click > Browse to browse for folders.")
            self.w[key] = t
            bv.addWidget(t)
            ov.addWidget(box)
        v.addWidget(outer)
        self._footer(v)

    def _tab_internet(self, page):
        v = QVBoxLayout(page)
        tip = "TuxSpice never connects to the internet: there are no web updates and no usage data."
        h = QHBoxLayout()
        h.addWidget(self._check("internet/no_cache", "Don't cache files", tip=tip))
        h.addWidget(self._check("internet/no_verify", "Don't verify checksums", tip=tip))
        v.addLayout(h)
        v.addWidget(self._check("internet/usage_data", "Send my anonymous usage data to the TuxSpice team", tip=tip))
        v.addSpacing(10)
        url = QComboBox()
        url.addItem("(none)")
        v.addWidget(_row("Update URL:", url, tip=tip))
        conn = QComboBox()
        conn.addItem("Default (Recommended)")
        v.addWidget(_row("Connection Type:", conn, tip=tip))
        box = QGroupBox("Proxy Server Configuration (Usually Found Automatically)")
        box.setEnabled(False)
        bv = QVBoxLayout(box)
        for label in ("Server:", "User Name:", "Password:"):
            bv.addWidget(_row(label, QLineEdit()))
        v.addWidget(box)
        self._footer(v)

    def _tab_hacks(self, page):
        v = QVBoxLayout(page)
        tip = "Hacks are LTspice simulator internals (deprecated); ngspice has no equivalent."
        v.addWidget(self._check("hacks/convergence", "Latest Convergence Hacks", tip=tip))
        v.addWidget(self._check("hacks/energy_check", "Show Energy Conservation Check Sum", tip=tip))
        v.addWidget(self._check("hacks/tsts", "Trade accuracy for convergence for TSTS", tip=tip))
        v.addWidget(_row("Gate Current:", self._edit("hacks/gate_current"), tip=tip))
        v.addWidget(_row("Minimum shunt to main capacitance ratio:", self._edit("hacks/min_shunt"), tip=tip))
        v.addWidget(self._check("hacks/no_jfet_isr", "Don't temperature scale JFET Isr", tip=tip))
        v.addWidget(self._check("hacks/gmin_isources", "Add GMIN across current sources", tip=tip))
        v.addWidget(self._check("hacks/ind_damping", "Supply a min. inductor damping if no Rpar is given", tip=tip))
        v.addWidget(self._check("hacks/mc_clock", "Use the clock to reseed the MC generator"))
        note = QLabel("Note: To use default Rser=0 for all inductors\nadd '.options thev_induc=1' to the circuit")
        note.setAlignment(Qt.AlignCenter)
        v.addWidget(note)
        self._footer(v)

    # ---------------------------------------------------------------- load/save
    def _set_widget(self, key, value):
        w = self.w[key]
        if isinstance(w, QCheckBox):
            w.setChecked(bool(value))
        elif isinstance(w, QComboBox):
            i = w.findText(str(value))
            if i < 0 and w.count() and "(" in w.itemText(w.count() - 1) and str(value).startswith("User"):
                i = w.count() - 1
            if i < 0:
                w.addItem(str(value))
                i = w.count() - 1
            w.setCurrentIndex(i)
        elif isinstance(w, QSpinBox):
            w.setValue(int(value))
        elif isinstance(w, QPlainTextEdit):
            w.setPlainText(str(value))
        else:
            w.setText(str(value))

    def _widget_value(self, key):
        w = self.w[key]
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, QSpinBox):
            return w.value()
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText()
        return w.text()

    def _load(self, defaults=False, keys=None):
        for key in keys or self.w:
            self._set_widget(key, DEFAULTS[key] if defaults else get(key))
        m = DEFAULTS["spice/method"] if defaults else get("spice/method")
        if keys is None or "spice/method" in keys:
            self.method.get(m, self.method["modified trap"]).setChecked(True)
        e, cb = self.w["waveform/raw_dir"], self.w["waveform/raw_dir_on"]
        e.setEnabled(cb.isChecked())

    def _reset_tab(self):
        prefixes = {"Operation": ("operation/",), "Schematic": ("drafting/", "view/"),
                    "Waveforms": ("waveform/",), "SPICE": ("spice/",), "Save Defaults": ("save/",),
                    "Netlist Options": ("netlist/",), "Compression": ("compression/",),
                    "Search Paths": ("paths/",), "Internet": ("internet/",), "Hacks": ("hacks/",)}
        pre = prefixes[self.TABS[self.tabs.currentIndex()]]
        keys = [k for k in self.w if k.startswith(pre)] + (["spice/method"] if "spice/" in pre else [])
        self._load(defaults=True, keys=[k for k in keys if k in self.w] or ["spice/method"])

    def _ok(self):
        for key in self.w:
            if self.w[key].isEnabled() or isinstance(self.w[key], QLineEdit):
                put(key, self._widget_value(key))
        put("spice/method", next(m for m, r in self.method.items() if r.isChecked()))
        self.accept()

    # ---------------------------------------------------------------- buttons
    def _help(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from .. import config
        page = config.HELP_DIR / self.HELP[self.TABS[self.tabs.currentIndex()]]
        if page.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(page)))

    def _colors(self):
        if self.main is not None and hasattr(self.main, "color_prefs"):
            self.main.color_prefs()

    def _shortcuts(self):
        if self.main is not None and hasattr(self.main, "edit_shortcuts"):
            self.main.edit_shortcuts()

    def _plot_defs(self):
        if self.main is not None and hasattr(self.main, "open_plot_defs"):
            self.main.open_plot_defs()

    def _browse_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Browse", edit.text())
        if d:
            edit.setText(d)

    def _path_menu(self, text_edit, pos):
        m = text_edit.createStandardContextMenu()
        m.addSeparator()

        def browse():
            d = QFileDialog.getExistingDirectory(self, "Browse")
            if d:
                cur = text_edit.toPlainText().rstrip()
                text_edit.setPlainText((cur + "\n" if cur else "") + d)
        m.addAction("Browse...", browse)
        m.exec(text_edit.mapToGlobal(pos))
