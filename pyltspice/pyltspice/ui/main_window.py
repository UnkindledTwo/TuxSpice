"""Main window: LTspice-style menus, toolbar and MDI area."""
import re
from pathlib import Path

import numpy as np

from PySide6.QtCore import QSettings, QSize, Qt, QThread, Signal
from shiboken6 import isValid
from PySide6.QtGui import QAction, QImage, QKeySequence, QPainter
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHeaderView, QInputDialog, QLabel,
                               QMainWindow, QMdiArea, QMessageBox, QPlainTextEdit, QTabBar,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import config
from ..model import asc
from ..model.netlist import generate_netlist
from ..sim import pltfile
from ..sim.rawfile import read_raw
from ..sim.runner import Cancelled, SimResult, Simulator
from ..sim.spicenum import fmt
from ..sim.vectors import lt_name
from . import dialogs, icons, shortcuts, tools
from .component_dialog import ComponentDialog
from .document import SchematicDocument
from .schematic_window import SchematicWindow
from .waveform import WaveformViewer

APP_NAME = "TuxSpice"
ANALYSES = (".tran", ".ac", ".dc", ".op", ".noise", ".tf", ".pz", ".disto")


class SimThread(QThread):
    done = Signal(object)

    def __init__(self, sim: Simulator):
        super().__init__()
        self.sim = sim

    def run(self):
        try:
            res = self.sim.run()
        except Cancelled:
            res = SimResult(errors=["Simulation halted"])
        except Exception as e:  # noqa: BLE001 - report anything to the user
            res = SimResult(errors=[str(e)])
        self.done.emit(res)


class PlotWindow(QWidget):
    """MDI child wrapping a WaveformViewer and linked to its schematic."""

    def __init__(self, viewer: WaveformViewer, source=None, slot=0):
        super().__init__()
        self.viewer = viewer
        self.source = source
        self.slot = slot              # several result sets of one run (e.g. .disto HD2/HD3)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(viewer)
        self.raw_path = None
        self.setAttribute(Qt.WA_DeleteOnClose)

    def closeEvent(self, ev):
        """Settings > Operation > Automatically delete .raw files."""
        from .settings_dialog import get
        if self.raw_path is not None and get("operation/delete_raw"):
            try:
                Path(self.raw_path).unlink(missing_ok=True)
            except OSError:
                pass
        super().closeEvent(ev)

    @property
    def title(self):
        return self.viewer.title

    def replace_viewer(self, viewer):
        old = self.viewer
        self.layout().replaceWidget(old, viewer)
        old.deleteLater()
        self.viewer = viewer


class TextWindow(QPlainTextEdit):
    def __init__(self, title, text, path=None):
        super().__init__()
        self.title = title
        self.path = path
        self.setPlainText(text)
        f = self.font()
        f.setFamily("Monospace")
        f.setStyleHint(f.StyleHint.TypeWriter)
        self.setFont(f)
        self.setAttribute(Qt.WA_DeleteOnClose)


class ScopeMdiArea(QMdiArea):
    """MDI area whose empty background looks like LTspice's default 'Oscilloscope' backdrop:
    dark blue-black with faint glowing traces (drawn here, not copied)."""

    def paintEvent(self, ev):
        from PySide6.QtGui import QLinearGradient, QPainterPath, QPen, QColor
        import math
        from .settings_dialog import get
        p = QPainter(self.viewport())
        r = self.viewport().rect()
        bg = get("operation/background")
        if bg == "None":
            p.fillRect(r, QColor("#808080"))
            return
        if bg.startswith("User"):
            img = QImage(str(config.user_background()))
            if not img.isNull():
                p.drawImage(r, img)
                return
        g = QLinearGradient(0, 0, r.width(), r.height())
        g.setColorAt(0, QColor("#030a10"))
        g.setColorAt(1, QColor("#0b2734"))
        p.fillRect(r, g)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = max(r.width(), 1), max(r.height(), 1)
        for k, (amp, per, ph, y0) in enumerate(((0.28, 0.9, 0.0, 0.62), (0.18, 0.55, 1.3, 0.70),
                                                  (0.35, 1.4, 2.4, 0.55))):
            path = QPainterPath()
            for i in range(0, w + 8, 8):
                y = h * (y0 + amp * math.sin(i / w * 2 * math.pi / per + ph) * (0.6 + 0.4 * i / w))
                path.moveTo(i, y) if i == 0 else path.lineTo(i, y)
            for width, alpha in ((14, 18), (6, 40), (2, 110)):
                pen = QPen(QColor(40, 150, 190, alpha))
                pen.setWidthF(width)
                p.setPen(pen)
                p.drawPath(path)
        p.end()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("pyltspice", "pyltspice")
        self.cursors = icons.make_cursors()
        self.setWindowTitle(APP_NAME)
        self.mdi = ScopeMdiArea()
        self.mdi.setViewMode(QMdiArea.SubWindowView)
        self.mdi.setDocumentMode(True)
        self.mdi.subWindowActivated.connect(self._update_actions)
        QApplication.clipboard().dataChanged.connect(self._update_actions)
        # LTspice shows a strip of window tabs above the MDI area (View > Window Tabs)
        self.tabs = QTabBar()
        self.tabs.setDocumentMode(True)
        self.tabs.setExpanding(False)
        self.tabs.setTabsClosable(False)
        self.tabs.setIconSize(QSize(16, 16))
        self.tabs.currentChanged.connect(self._tab_clicked)
        self._tab_subs = []
        self._syncing_tabs = False
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.tabs)
        cl.addWidget(self.mdi, 1)
        self.setCentralWidget(central)
        self.sim_thread = None
        self.sim_owner = None
        self.untitled = 0
        self.floating = []             # windows popped out with Float Window
        self.line_style = 0            # Edit > Draw > Line Style for new graphics
        self.actions = {}
        from . import render
        from .settings_dialog import get
        render.set_font_settings(get("drafting/font"), get("drafting/font_bold"), get("drafting/font_size"),
                                 get("drafting/pen_thickness"))
        self._apply_search_paths()
        self._build_actions()
        shortcuts.apply_saved(self.actions)
        self._build_menus()
        self._build_toolbar()
        self.status_label = QLabel()
        f = self.status_label.font()
        f.setBold(True)              # LTspice's status bar text is bold
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.status_label.setFont(f)
        self.statusBar().addWidget(self.status_label, 1)
        self.tabs.setVisible(self.actions["view_tabs"].isChecked())
        self.resize(1280, 860)
        geo = self.settings.value("main/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self._update_actions()

    def settings_bool(self, key, default=False):
        v = self.settings.value(key, default)
        return v in (True, "true", "1", 1)

    # ------------------------------------------------------------ actions
    def _act(self, key, text, slot, shortcut=None, icon=None, checkable=False, tip=None, on="any"):
        """on: where the command is enabled: 'any', 'doc' (some window), 'sch' (schematic active),
        'plot' (waveform active), 'never' (not implemented in TuxSpice). Commands that share a key
        (A is Configure Analysis in a schematic, Add Trace in a plot, as in LTspice) are never
        enabled together, so the key is never ambiguous."""
        a = QAction(text, self)
        seqs = (shortcut if isinstance(shortcut, (list, tuple)) else [shortcut]) if shortcut else []
        a.default_keys = [QKeySequence(s).toString() for s in seqs]
        if seqs:
            a.setShortcuts([QKeySequence(s) for s in seqs])
        a.setShortcutContext(Qt.WindowShortcut)
        if icon and icon in icons.ICONS:
            a.setIcon(icons.icon(icon))
        a.setCheckable(checkable)
        a.setToolTip(tip or text.split("\t")[0].replace("&", ""))
        if on == "never":
            a.setStatusTip(tip or "Not implemented in TuxSpice yet")
        if slot is not None:
            a.triggered.connect(slot)
        a.on = on
        self.actions[key] = a
        return a

    def _alias(self, key, target, text):
        """A right-click menu entry worded differently from the menu bar's (no own shortcut)."""
        t = self.actions[target]
        keys = t.shortcuts()
        a = QAction(text + (f"\t{keys[0].toString()}" if keys else ""), self)
        a.setIcon(t.icon())
        a.triggered.connect(t.trigger)
        a.on = t.on
        a.alias_of = target
        self.actions[key] = a
        return a

    def _build_actions(self):
        # Texts, icons, default keys and grouping follow LTspice 26's menus and its "new" default
        # shortcuts (observed under Wine). F-key aliases from LTspice XVII are kept as secondary keys.
        A = self._act
        sw = self.schematic
        pv = self._plot_viewer
        # File
        A("file_new", "&New Schematic", self.new_schematic, "Ctrl+N", "new", tip="Start drafting a new schematic")
        A("file_new_symbol", "New Symbol", None, None, "new_symbol", on="never",
          tip="The symbol editor is not implemented in TuxSpice yet")
        A("file_new_lib_inductor", "Inductor", None, None, on="never",
          tip="Inductor libraries are not implemented in TuxSpice yet")
        A("file_open", "&Open...", self.open_dialog, "Ctrl+O", "open", tip="Open an existing document")
        A("file_examples", "Open E&xamples...", self.open_examples, None, "examples")
        A("file_close", "&Close", self.close_active, "Ctrl+W", "close", on="doc")
        A("file_save", "&Save", self.save, "Ctrl+S", "save", tip="Save the active document", on="sch")
        A("file_save_as", "Save &As...", self.save_as, "Ctrl+Shift+S", "save_as", on="sch")
        A("file_save_all", "Save A&ll", self.save_all)
        A("file_print", "&Print...", self.print_active, "Ctrl+P", "print", tip="Print the active document", on="doc")
        A("file_print_preview", "Print Pre&view", self.print_preview, None, "print_preview", on="doc")
        A("file_print_setup", "Print Se&tup...", self.print_setup, None, "print_setup")
        A("file_print_mono", "Print &Monochrome", self._set_print_mono, checkable=True)
        self.actions["file_print_mono"].setChecked(self.settings_bool("print/monochrome", True))
        A("file_export", "Export as Image...", self.export_image, on="sch")
        A("file_export_data", "&Export data as text", self.export_waveform_data, None, "export", on="plot")
        A("file_exec_meas", "Execute .MEAS Script", self.execute_meas_script, None, "meas", on="plot")
        A("file_fast_access", "Convert to Fast Access", None, None, "fast_access", on="never",
          tip="TuxSpice has no Fast Access file format")
        A("file_exit", "E&xit", self.close)
        # Edit (LTspice 26 default keys)
        A("edit_undo", "Und&o", lambda: self._undo(True), ["Ctrl+Z", "F9"], "undo", tip="Undo last edit.", on="sch")
        A("edit_redo", "&Redo", lambda: self._undo(False), ["Ctrl+Shift+Z", "Shift+F9", "Ctrl+Y"], "redo",
          tip="Re-do last undo.", on="sch")
        A("edit_text", "&Text", lambda: sw() and sw().place_text(False), "T", "text", tip="Annotate with text.",
          on="sch")
        A("edit_directive", "&SPICE Directive", lambda: sw() and sw().place_text(True), ".", "directive",
          tip="Place a SPICE directive on the schematic", on="sch")
        A("sim_edit_cmd", "Configure SPICE &Analysis", self.edit_sim_command, "A", "analysis",
          tip="Enter or Edit the SPICE analysis command", on="sch")
        A("edit_resistor", "Resistor", lambda: sw() and sw().place_symbol("res"), "R", "resistor",
          tip="Place a new Resistor on the schematic.", on="sch")
        A("edit_capacitor", "Capacitor", lambda: sw() and sw().place_symbol("cap"), "C", "capacitor",
          tip="Place a new Capacitor on the schematic.", on="sch")
        A("edit_inductor", "Inductor", lambda: sw() and sw().place_symbol("ind"), "L", "inductor",
          tip="Place a new Inductor on the schematic.", on="sch")
        A("edit_diode", "Diode", lambda: sw() and sw().place_symbol("diode"), "D", "diode",
          tip="Place a new Diode on the schematic.", on="sch")
        A("edit_voltage", "&Voltage Source", lambda: sw() and sw().place_symbol("voltage"), "V", "voltage",
          tip="Place a voltage source on the schematic.", on="sch")
        A("edit_current", "C&urrent Source", lambda: sw() and sw().place_symbol("current"), "I", "current",
          tip="Place a current source on the schematic.", on="sch")
        A("edit_component", "&Component", self.pick_component, ["P", "F2"], "component",
          tip="Place a new component on the schematic.", on="sch")
        A("edit_rotate", "&Rotate", lambda: sw() and sw().rotate_or_mirror(False), "Ctrl+R", "rotate",
          tip="Rotate the selected items.", on="sch")
        A("edit_mirror", "&Mirror", lambda: sw() and sw().rotate_or_mirror(True), "Ctrl+E", "mirror",
          tip="Mirror the selected items.", on="sch")
        A("edit_wire", "Draw &Wire", lambda: sw() and sw().start_wire(), ["W", "F3"], "wire", tip="Draft wires.",
          on="sch")
        A("edit_label", "Label &Net", lambda: sw() and sw().place_label(), ["N", "F4"], "label", tip="Label a node.",
          on="sch")
        A("edit_ground", "Place &GND", lambda: sw() and sw().place_ground(), "G", "ground",
          tip="Place a GND symbol on the schematic.", on="sch")
        A("edit_bustap", "Place &BUS tap", None, "B", "bustap", on="never",
          tip="Buses are not implemented in TuxSpice yet")
        A("edit_delete", "&Delete\tBackspace or Del", lambda: sw() and sw().start_delete(), ["Backspace", "Del", "F5"], "delete",
          tip="Delete Mode", on="sch")
        A("edit_duplicate", "D&uplicate", lambda: sw() and sw().start_move("duplicate"), ["Ctrl+C", "F6"],
          "duplicate", tip="Duplicate Mode", on="sch")
        A("edit_move", "&Move", lambda: sw() and sw().start_move("move"), ["M", "F7"], "move",
          tip="Move a section.", on="sch")
        A("edit_drag", "&Stretch", lambda: sw() and sw().start_move("drag"), ["S", "F8"], "drag",
          tip="Stretch a section.", on="sch")
        A("edit_paste", "&Paste", lambda: sw() and sw().start_paste(), "Ctrl+V", "paste", on="paste",
          tip="Paste what Duplicate picked, in this or another schematic.")
        for kind, label, ic in (("LINE", "Line", "line"), ("RECTANGLE", "Rectangle", "rectangle"),
                                ("CIRCLE", "Ellipse", "ellipse"), ("ARC", "Arc", "arc")):
            A(f"draw_{kind.lower()}", label, lambda _=False, k=kind: sw() and sw().start_draw(k), None, ic, on="sch")
        from PySide6.QtGui import QActionGroup
        grp = QActionGroup(self)
        for i, name in enumerate(("Solid", "Dash", "Dot", "Dash Dot", "Dash Dot Dot")):
            a = A(f"style_{i}", name, lambda _=False, i=i: self._set_line_style(i), checkable=True)
            grp.addAction(a)
        self.actions["style_0"].setChecked(True)
        A("edit_dataflag", ".op Data Label", lambda: sw() and sw().place_data_flag(), None, "dataflag", on="sch")
        A("edit_find", "Search", self.find_text, "Ctrl+F", "find", tip="Search for text string in deck", on="sch")
        # Hierarchy
        A("hier_symbol", "Open or Generate this Sheet's &Symbol", self.open_sheet_symbol, None, "component",
          on="sch")
        A("hier_new_symbol", "Create a &New Blank Symbol", None, None, "new_symbol", on="never",
          tip="The symbol editor is not implemented in TuxSpice yet")
        A("hier_new_sheet", "Create a New Blank S&heet", self.new_schematic, None, "blank_sheet", on="sch")
        A("hier_subckt", "Generate Sub&ckt Netlist", self.generate_subckt, None, "netlist", on="sch")
        # View
        A("view_zoom_area", "Zoom &Area", self._zoom_area, "Z", "zoom_in", tip="Drag a box and zoom in", on="doc")
        A("view_zoom_back", "Zoom &Back", self._zoom_back, ["Shift+Z", "Ctrl+B"], "zoom_out",
          tip="Zoom back two fold", on="doc")
        A("view_fit", "Zoom to &Fit", self.zoom_fit, "Space", "zoom_fit", tip="Zoom the full extent is visible",
          on="doc")
        A("view_zoom_in", "Zoom &In", lambda: self._zoom(1.5), "Ctrl+=", on="sch")
        A("view_zoom_out", "Zoom &Out", lambda: self._zoom(1 / 1.5), "Ctrl+-", on="sch")
        A("view_recenter", "Recenter", self.recenter, None, "recenter", on="doc")
        A("view_grid", "Show Grid", self.toggle_grid, "Ctrl+G", "check", checkable=True, on="sch")
        A("view_unconnected", "Mark Unconn. Pins", self.toggle_unconnected, "Ctrl+U", "check", checkable=True,
          on="sch")
        A("view_anchors", "Mark Anchors", self.toggle_anchors, "Ctrl+A", "check", checkable=True, on="sch")
        from .settings_dialog import get
        self.actions["view_unconnected"].setChecked(get("drafting/mark_unconnected"))
        self.actions["view_grid"].setChecked(get("view/grid"))
        self.actions["view_anchors"].setChecked(get("view/mark_anchors"))
        A("bom_show", "Show on Schematic", self.bom_on_schematic, None, "check", on="sch")
        A("bom_paste", "Paste to clipboard", self.bom_to_clipboard, on="sch")
        A("eff_show", "Show on Schematic", None, None, "check", on="never",
          tip="The efficiency report is not implemented in TuxSpice yet")
        A("eff_paste", "Paste to clipboard", None, on="never",
          tip="The efficiency report is not implemented in TuxSpice yet")
        A("view_netlist", "Update and View SPICE &Netlist", self.show_netlist, None, "view_netlist", on="sch")
        A("view_bom", "&Bill of Materials", self.show_bom, None, "bom", on="sch")
        A("view_log", "SPICE Output &Log", self.show_log, "Ctrl+L", "log", on="doc")
        A("view_fft", "FFT", self.show_fft, None, "fft", on="plot")
        A("view_probe_ref", "Set Probe Reference", self.set_probe_reference, None, "probe_ref", on="sch")
        A("view_opflags", "Show .op Data Flags", self.toggle_op_flags, None, "check", checkable=True, on="sch")
        self.actions["view_opflags"].setChecked(True)
        A("march_restart", "(Re-)Start", None, on="never",
          tip="Marching waveforms are not implemented: plots appear when ngspice finishes")
        A("march_pause", "Pause", None, on="never",
          tip="Marching waveforms are not implemented: plots appear when ngspice finishes")
        A("view_toolbar", "&Toolbar", lambda on: self.toolbar.setVisible(on), None, "check", checkable=True)
        A("view_statusbar", "&Status Bar", lambda on: self.statusBar().setVisible(on), None, "check",
          checkable=True)
        A("view_tabs", "Window Tabs", self.toggle_tabs, None, "check", checkable=True)
        for k in ("view_toolbar", "view_statusbar"):
            self.actions[k].setChecked(True)
        self.actions["view_tabs"].setChecked(self.settings_bool("view/window_tabs", True))
        # Plot Settings (waveform window); keys shared with schematic commands are swapped in
        # by enabling one or the other, as LTspice does
        A("sim_add_trace", "&Visible Traces", self.add_traces, None, "waves",
          tip="Select which traces are visible / Open the waveform viewer")
        A("plot_add_trace", "Add &trace", self.add_traces, "A", "add_trace", on="plot")
        A("plot_delete_traces", "&Delete Traces\tBackspace or Del", lambda: pv() and pv().start_delete_mode(),
          ["Backspace", "Del"], "delete", on="plot")
        A("plot_select_steps", "Select Steps", lambda: pv() and pv().select_steps_dialog(), "Shift+S",
          "select_steps", on="plot")
        A("plot_cursor", "Place &Cursor on Active Trace", lambda: pv() and pv().place_cursor(), "C", "cursor",
          on="plot")
        A("plot_clear_cursors", "Clear All Cursors\tShift+C or Esc", lambda: pv() and pv().clear_cursors(), ["Shift+C", "Esc"],
          "clear_cursors", on="plot")
        A("plot_redraw", "Redraw", lambda: pv() and pv().redraw(), "F5", "redraw", on="plot")
        A("plot_pane_above", "Add &Plot Pane Above Active Pane", lambda: pv() and pv().add_pane_at(above=True),
          "P", "pane_above", on="plot")
        A("plot_pane_below", "Add Plot Pane &Below Active Pane", lambda: pv() and pv().add_pane_at(above=False),
          "B", "pane_below", on="plot")
        A("plot_pane_up", "&Move Active Pane Up", lambda: pv() and pv().move_active_pane(-1), "U", "pane_up",
          on="plot")
        A("plot_pane_down", "Move Active Pane Do&wn", lambda: pv() and pv().move_active_pane(1), "D",
          "pane_down", on="plot")
        A("plot_pane_delete", "Delete Active Pane", lambda: pv() and pv().delete_pane(pv().active), None,
          "pane_delete", on="plot")
        A("plot_sync_x", "Sync. &Horiz. Axes", lambda on: pv() and pv().set_sync_x(on), None, "check",
          checkable=True, on="plot")
        A("plot_grid", "&Grid", lambda on: pv() and pv().set_grid(on), "Ctrl+G", "check", checkable=True,
          on="plot")
        A("plot_reset_colors", "Reset Colors", lambda: pv() and pv().reset_colors(), None, "colors_reset",
          on="plot")
        A("plot_mark_points", "Mark &Data Points", lambda on: pv() and pv().set_mark_points(on), None, "check",
          checkable=True, on="plot")
        A("eye_setup", "Setup Eye Diagram...", None, on="never",
          tip="Eye diagrams are not implemented in TuxSpice yet")
        A("plot_undo", "Und&o", lambda: pv() and pv().undo(), "Ctrl+Z", "undo", on="plot")
        A("plot_redo", "&Redo", lambda: pv() and pv().redo(), "Ctrl+Shift+Z", "redo", on="plot")
        A("plot_autorange", "Autorange &Y-axis", lambda: pv() and pv().autorange(), "Ctrl+Y", "autorange",
          tip="Autorange vertical scale(s)", on="plot")
        A("plot_manual_limits", "&Manual Limits", lambda: pv() and pv().manual_limits_dialog(), None,
          "manual_limits", on="plot")
        A("plot_autoranging", "&Autoranging", lambda on: pv() and setattr(pv(), "autoranging", on), None,
          "check", checkable=True, on="plot")
        A("notes_cursor_pos", "Cursor Position", lambda: pv() and pv().annotate_cursor(), "L", "cursor_pos",
          on="plot")
        A("notes_pm", "Annotate Phase Margin", lambda: pv() and pv().annotate_margin("pm"), on="plot",
          tip="Mark the phase margin at each AC trace's 0 dB crossing (active pane).")
        A("notes_gm", "Annotate Gain Margin", lambda: pv() and pv().annotate_margin("gm"), on="plot",
          tip="Mark the gain margin at each AC trace's -180° phase crossing (active pane).")
        A("notes_steps", "Annotate Steps", lambda: pv() and pv().annotate_steps(), on="plot",
          tip="Label each .step run's curve in the active pane.")
        A("notes_nyquist", "Draw Nyquist Unit Circle", None, on="never", tip="Not implemented in TuxSpice yet")
        for key, text, kind, keyseq, ic in (("notes_text", "Text", "text", "T", "text"),
                                           ("notes_arrow", "Arrow", "arrow", None, "arrow"),
                                           ("notes_line", "Line", "line", "I", "line"),
                                           ("notes_rect", "Rectangle", "rect", "R", "rectangle"),
                                           ("notes_ellipse", "Ellipse", "ellipse", None, "ellipse")):
            A(key, text, lambda _=False, k=kind: pv() and pv().start_annotation(k), keyseq, ic, on="plot")
        A("notes_style", "Line Style/Color", lambda: pv() and pv().annotation_style_dialog(), None, "line_style",
          on="plot")
        A("plot_save", "Save Plot Settings", lambda: self.save_plot_settings(), "Ctrl+S", "save", on="plot")
        A("plot_save_as", "Save Plot Settings &As...", lambda: self.save_plot_settings(ask=True), "Ctrl+Shift+S",
          "save_as", on="plot")
        A("plot_open", "Open Plot Settings File...", self.open_plot_settings, "O", "open", on="plot")
        A("plot_reload", "Reload Plot Settings", self.reload_plot_settings, "Ctrl+Space", "reload", on="plot")
        A("plot_defs", "Edit Plot Defs File", self.open_plot_defs, None, "plot_defs")
        A("plot_add_pane", "Add &Plot Pane", lambda: pv() and pv().add_pane(), on="plot")
        # Simulate
        A("sim_run", "&Run/Pause", self.run_simulation, "Alt+R", "run", tip="Run/Pause LTspice-compatible simulation")
        A("sim_halt", "S&top", self.halt_simulation, "Alt+S", "halt", tip="Stop the current simulation right now")
        A("sim_clear", "Clear Waveforms", self.clear_waveforms, "0", "clear_waves", on="sch")
        A("eff_start", "Mark Start", None, on="never", tip="Efficiency calculation is not implemented in TuxSpice yet")
        A("eff_end", "Mark End", None, on="never", tip="Efficiency calculation is not implemented in TuxSpice yet")
        # Tools
        A("tools_settings", "&Settings", self.open_settings, None, "settings",
          tip="Access simulation and operation options")
        A("tools_colors", "&Color Preferences", self.color_prefs, None, "colors")
        A("tools_copy_bitmap", "Copy bitmap to Clipboard", self.copy_bitmap, None, "copy_bitmap", on="sch")
        A("tools_copy_graph", "Copy Graph Image to Clipboard", self.copy_bitmap, None, "copy_bitmap", on="plot")
        A("tools_write_image", "Write image to .svg file", self.write_image, None, "write_image", on="doc")
        A("tools_export_netlist", "Export Netlist", self.export_pcb_netlist, None, "export", on="sch")
        A("tools_ai", "Configure Third-Party AI Assistants...", self.configure_ai, None, "ai",
          tip="Let AI assistants read, edit and simulate designs through MCP")
        # Window
        A("win_tile_h", "Tile &Horizontally", self.tile_horizontal, None, "tile_h",
          tip="Arrange windows as non-overlapping horizontal tiles", on="doc")
        A("win_tile_v", "Tile &Vertically", self.tile_vertical, None, "tile_v",
          tip="Arrange windows as non-overlapping vertical tiles", on="doc")
        A("win_cascade", "&Cascade", self.mdi.cascadeSubWindows, None, "cascade",
          tip="Arrange windows so they overlap", on="doc")
        A("win_close_all", "Close &Everything", self.close_everything, None, "close_all", on="doc")
        A("win_arrange", "&Arrange Icons", self.arrange_icons, None, "arrange", on="doc")
        A("win_float", "Float Window", self.float_window, None, "check", checkable=True, on="doc")
        # Help
        A("help_topics", "TuxSpice &Help", self.open_help, "F1", "help")
        A("help_shortcuts", "Keyboard Shortcut Cheat Sheet", self.show_shortcuts, None, "keyboard")
        A("help_edit_shortcuts", "&Edit Keyboard Shortcuts...", self.edit_shortcuts)
        A("help_changelog", "Show LTspice Change Log", lambda: self._show_help_text("LTspiceChangeLog.txt"),
          None, "ltspice_log")
        A("help_model_changelog", "Show Model Change Log", lambda: self._show_help_text("ChangeLog.txt"),
          None, "model_log")
        A("help_about", "&About TuxSpice", self.about, None, "about")
        # right-click menu wordings
        al = self._alias
        al("ctx_comment", "edit_text", "Comment Text")
        al("ctx_copy_image", "tools_copy_bitmap", "Copy Image to Clipboard")
        al("ctx_copy_graph", "tools_copy_graph", "Copy Image to Clipboard")
        al("ctx_plot_defs", "plot_defs", "Plot Defs File")
        al("ctx_add_traces", "plot_add_trace", "Add Traces")
        al("ctx_pane_above", "plot_pane_above", "Add Plot Pane Above")
        al("ctx_pane_below", "plot_pane_below", "Add Plot Pane Below")
        al("ctx_pane_up", "plot_pane_up", "Move Plot Pane Up")
        al("ctx_pane_down", "plot_pane_down", "Move Plot Pane Down")
        al("ctx_pane_delete", "plot_pane_delete", "Delete this Pane")
        al("ctx_waveform_settings", "tools_settings", "Waveform Settings")
        self.actions["ctx_waveform_settings"].triggered.disconnect()
        self.actions["ctx_waveform_settings"].triggered.connect(lambda: self.open_settings("Waveforms"))
        for key, text, mode, keyseq, ic, tip in (
                ("ctx_plot_move", "Move", "note_move", "M", "move", "Move an annotation."),
                ("ctx_plot_stretch", "Stretch", "note_stretch", "S", "drag",
                 "Drag one end or corner of an annotation."),
                ("ctx_plot_duplicate", "Duplicate", "note_dup", "Ctrl+C", "duplicate", "Copy an annotation.")):
            A(key, text, lambda _=False, m=mode: pv() and pv().start_note_edit(m), keyseq, ic, tip=tip, on="plot")

    def _build_menus(self):
        from . import menus
        mb = self.menuBar()
        self.recent_menus = []
        self.menu_sets = {}
        self._dynamic = []
        for kind, layout in (("empty", menus.EMPTY_MENUS), ("schematic", menus.SCHEMATIC_MENUS),
                             ("waveform", menus.WAVEFORM_MENUS)):
            top = []
            for title, entries in layout:
                m = mb.addMenu(title)
                top.append(m)
                m.aboutToShow.connect(self._update_actions)
                self._fill_menu(m, entries)
            self.menu_sets[kind] = top
        self.recent_menu = self.recent_menus[0] if self.recent_menus else None
        self._show_menus("empty")

    def _fill_menu(self, m, entries):
        """Menus holding the recent files or the window list are rebuilt each time they open."""
        from . import menus
        menus.build(m, entries, self.actions, self._special_entry)
        if any(e in ("@recent", "@windows") for e in entries if isinstance(e, str)):
            m.aboutToShow.connect(lambda m=m, e=entries: (m.clear(), menus.build(m, e, self.actions,
                                                                                    self._special_entry)))
            self.recent_menus.append(m)

    def _special_entry(self, name, menu):
        if name == "@recent":
            for i, p in enumerate(self._recent()[:8]):
                short = p if len(p) <= 48 else "..." + p[-45:]
                a = menu.addAction(icons.icon("schematic_doc" if p.lower().endswith(".asc") else "waveform_doc"),
                                   short, lambda p=p: self.open_file(p))
                a.setToolTip(p)
        elif name == "@windows":
            active = self.mdi.activeSubWindow()
            for i, sub in enumerate(self.mdi.subWindowList(), 1):
                w = sub.widget()
                a = menu.addAction(f"&{i} {getattr(w, 'title', sub.windowTitle())}",
                                   lambda s=sub: self.mdi.setActiveSubWindow(s))
                a.setCheckable(True)
                a.setChecked(sub is active)

    def _refresh_recent(self):
        pass                       # recent files are listed when the menu opens

    def _show_menus(self, kind):
        for k, menus_ in self.menu_sets.items():
            for m in menus_:
                m.menuAction().setVisible(k == kind)

    def context_menu(self, kind, global_pos):
        """Right-click menu of a schematic or waveform window (LTspice 26 layout)."""
        from PySide6.QtWidgets import QMenu
        from . import menus
        m = QMenu(self)
        menus.build(m, menus.SCHEMATIC_CONTEXT if kind == "schematic" else menus.WAVEFORM_CONTEXT,
                    self.actions)
        self._update_actions()
        m.exec(global_pos)

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(True)                # LTspice's toolbar sits in a rebar with a gripper
        self.toolbar = tb
        self.apply_toolbar_size()
        # same buttons, same order as LTspice 26
        for k in ["tools_settings", "file_new", "file_open", "file_save", "file_print", "sim_edit_cmd",
                  "sim_run", "sim_halt", "win_tile_v", "win_tile_h", "win_cascade", "view_zoom_area",
                  "view_zoom_back", "view_fit", "plot_autorange", "sim_add_trace", "edit_wire", "edit_ground",
                  "edit_voltage", "edit_resistor", "edit_capacitor", "edit_inductor", "edit_diode",
                  "edit_component", "edit_label", "edit_text", "edit_directive", "edit_delete",
                  "edit_duplicate", "edit_move", "edit_drag", "edit_rotate", "edit_mirror", "edit_undo",
                  "edit_redo", "edit_find"]:
            a = self.actions[k]
            keys = a.shortcuts()
            tip = a.toolTip().split(" (")[0]
            # toolbar tooltips read "Name (key)" and the status bar shows the long description
            a.setStatusTip(tip)
            a.setToolTip(a.text().split("\t")[0].replace("&", "") + (f" ({keys[0].toString()})" if keys else ""))
            tb.addAction(a)

    def apply_toolbar_size(self):
        """Settings > Operation > Toolbar icon size. Default: 28 px icons on a 34 px pitch."""
        from .settings_dialog import get
        px = {"Small": 20, "Large": 36}.get(get("operation/toolbar_size"), 28)
        self.toolbar.setIconSize(QSize(px, px))
        self.toolbar.setStyleSheet("QToolBar { spacing: 1px; padding: 2px 2px; }"
                                   "QToolButton { padding: 0px; margin: 0px; border: 1px solid transparent; }"
                                   "QToolButton:hover { border: 1px solid #a0a0a0; background: #e5f1fb; }"
                                   "QToolButton:pressed, QToolButton:checked { background: #cce4f7; }")

    def _update_actions(self, *_):
        sw = self.schematic()
        w = self.active_widget()
        on_plot = isinstance(w, PlotWindow)
        state = {"any": True, "doc": w is not None, "sch": sw is not None, "plot": on_plot, "never": False,
                 "paste": sw is not None and tools.clipboard_has_objects()}
        for k, a in self.actions.items():
            a.setEnabled(state.get(getattr(a, "on", "any"), True))
        pv = w.viewer if on_plot else None
        if pv is not None:
            for k, val in (("plot_grid", pv.show_grid), ("plot_sync_x", pv.sync_x),
                           ("plot_mark_points", pv.mark_points), ("plot_autoranging", pv.autoranging)):
                self.actions[k].setChecked(val)
            self.actions["plot_pane_delete"].setEnabled(len(pv.panes) > 1)
            self.actions["plot_pane_up"].setEnabled(pv.panes.index(pv.active) > 0 if pv.active in pv.panes else False)
            self.actions["plot_pane_down"].setEnabled(pv.active in pv.panes and pv.panes.index(pv.active) <
                                                      len(pv.panes) - 1)
            self.actions["plot_select_steps"].setEnabled(len(pv.steps()) > 1)
            self.actions["plot_cursor"].setEnabled(any(p.traces for p in pv.panes))
            self.actions["notes_cursor_pos"].setEnabled(bool(pv.cursors))
            has_traces = any(p.traces for p in pv.panes)
            for k in ("notes_pm", "notes_gm"):
                self.actions[k].setEnabled(pv.is_ac and has_traces)
            self.actions["notes_steps"].setEnabled(len(pv.steps()) > 1 and has_traces)
            self.actions["plot_clear_cursors"].setEnabled(bool(pv.cursors) or pv.mode is not None)
            self.actions["plot_undo"].setEnabled(pv.can_undo())
            self.actions["plot_redo"].setEnabled(pv.can_redo())
            self.actions["plot_reload"].setEnabled(pv.plt_path is not None)
        if sw is not None:
            self.actions["view_opflags"].setChecked(sw.doc.scene.show_op_flags)
        self.actions["view_probe_ref"].setEnabled(sw is not None and sw.sim_plot is not None)
        self.actions["win_float"].setChecked(w is not None and w in self.floating)
        self._show_menus("waveform" if on_plot else "schematic" if w is not None else "empty")
        running = self.sim_thread is not None
        self.actions["sim_halt"].setEnabled(running)
        can_run = not running and (sw is not None or isinstance(w, TextWindow) or
                                   (on_plot and w.source is not None))
        self.actions["sim_run"].setEnabled(can_run)
        self.actions["sim_add_trace"].setEnabled(self.plot_window() is not None)
        self.actions["plot_autorange"].setEnabled(self.plot_window() is not None)
        self.actions["sim_clear"].setEnabled(sw is not None and bool(self.plot_windows(sw)))
        self.update_orient_actions()
        for a in self.actions.values():
            if hasattr(a, "alias_of"):
                a.setEnabled(self.actions[a.alias_of].isEnabled())
        self._sync_tabs()
        if w is not None:
            self.setWindowTitle(f"{APP_NAME} - [{w.title}]")
        else:
            self.setWindowTitle(APP_NAME)

    def update_orient_actions(self, *_):
        """Rotate/Mirror are only enabled while a part is being placed or carried (LTspice)."""
        sw = self.schematic()
        tool = sw.tool if sw else None
        on = tool is not None and (type(tool).__name__ == "PlaceTool" or getattr(tool, "carry", None) is not None)
        for k in ("edit_rotate", "edit_mirror"):
            self.actions[k].setEnabled(bool(on))

    def _plot_viewer(self):
        pw = self.plot_window()
        return pw.viewer if pw else None

    # ------------------------------------------------------------ windows
    def active_widget(self):
        aw = QApplication.activeWindow()
        if aw is not None and aw in getattr(self, "floating", []):
            return aw
        sub = self.mdi.activeSubWindow()
        return sub.widget() if sub else None

    def schematic(self) -> SchematicWindow | None:
        w = self.active_widget()
        return w if isinstance(w, SchematicWindow) else None

    def plot_window(self, for_schematic=None, slot=0) -> PlotWindow | None:
        w = self.active_widget()
        if for_schematic is None and isinstance(w, PlotWindow):
            return w
        target = for_schematic or self.schematic()
        for sub in self.mdi.subWindowList():
            pw = sub.widget()
            if isinstance(pw, PlotWindow) and (target is None or pw.source is target) and pw.slot == slot:
                return pw
        return None

    def plot_windows(self, for_schematic):
        return [s.widget() for s in self.mdi.subWindowList()
                if isinstance(s.widget(), PlotWindow) and s.widget().source is for_schematic]

    def _add_window(self, widget, title):
        sub = self.mdi.addSubWindow(widget)
        sub.setWindowTitle(title)
        sub.setWindowIcon(icons.icon("schematic_doc" if isinstance(widget, SchematicWindow) else
                                     "waveform_doc" if isinstance(widget, PlotWindow) else "netlist"))
        if hasattr(widget, "title_changed"):
            widget.title_changed.connect(lambda: (sub.setWindowTitle(widget.title), self._update_actions()))
        if hasattr(widget, "status"):
            widget.status.connect(self.status_label.setText)
        widget.destroyed.connect(lambda *_: isValid(self.mdi) and self._update_actions())
        sub.show()
        if len(self.mdi.subWindowList()) == 1:
            sub.showMaximized()
        self.mdi.setActiveSubWindow(sub)
        return sub

    def _attach_schematic(self, doc):
        w = SchematicWindow(doc, self)
        w.mode_changed.connect(self.update_orient_actions)
        w.probed.connect(lambda expr, w=w: self._probe(w, expr))
        self._add_window(w, w.title)
        return w

    # ------------------------------------------------------------ file
    def new_schematic(self):
        self.untitled += 1
        doc = SchematicDocument(asc.Schematic(items=[]))
        self._attach_schematic(doc)

    def open_dialog(self):
        start = self.settings.value("file/last_dir", str(config.EXAMPLES_DIR))
        path, _ = QFileDialog.getOpenFileName(
            self, "Open", start,
            "LTspice files (*.asc *.net *.cir *.sp *.raw);;Schematics (*.asc);;"
            "Netlists (*.net *.cir *.sp);;Waveforms (*.raw);;All files (*)")
        if path:
            self.open_file(path)

    def open_examples(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Example", str(config.EXAMPLES_DIR),
                                              "Schematics (*.asc)")
        if path:
            self.open_file(path)

    def open_file(self, path):
        path = Path(path)
        for sub in self.mdi.subWindowList():
            w = sub.widget()
            if isinstance(w, SchematicWindow) and w.doc.path and w.doc.path.resolve() == path.resolve():
                self.mdi.setActiveSubWindow(sub)
                return
        self.settings.setValue("file/last_dir", str(path.parent))
        self._add_recent(path)
        ext = path.suffix.lower()
        try:
            if ext == ".asc":
                self._attach_schematic(SchematicDocument.open(path))
            elif ext == ".raw":
                plots = read_raw(path)
                plot = next((p for p in plots if p.analysis != "op"), plots[0])
                self._show_plot(None, plot, path.name)
            else:
                text = path.read_bytes().decode("latin-1")
                self._add_window(TextWindow(path.name, text, path), path.name)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Open", f"Could not open {path}:\n{e}")

    def _recent(self):
        v = self.settings.value("file/recent", []) or []
        return [v] if isinstance(v, str) else list(v)      # one entry comes back as a str

    def _add_recent(self, path):
        rec = [p for p in self._recent() if p != str(path)]
        rec.insert(0, str(path))
        self.settings.setValue("file/recent", rec[:10])
        self._refresh_recent()

    def _refresh_recent(self):
        if not hasattr(self, "recent_menu"):
            return
        for menu in self.recent_menus:
            menu.clear()
            for p in self._recent():
                menu.addAction(p, lambda p=p: self.open_file(p))

    def close_active(self):
        sub = self.mdi.activeSubWindow()
        if sub:
            sub.close()

    def save(self):
        sw = self.schematic()
        if sw is None:
            return False
        if sw.doc.path is None:
            return self.save_as()
        sw.doc.save()
        return True

    def save_as(self):
        sw = self.schematic()
        if sw is None:
            return False
        start = str(sw.doc.path or Path(self.settings.value("file/last_dir", str(Path.home()))) / "Draft1.asc")
        path, _ = QFileDialog.getSaveFileName(self, "Save As", start, "Schematics (*.asc)")
        if not path:
            return False
        if not path.lower().endswith(".asc"):
            path += ".asc"
        sw.doc.save(path)
        sw.title_changed.emit()
        self._add_recent(path)
        return True

    def save_all(self):
        cur = self.mdi.activeSubWindow()
        for sub in self.mdi.subWindowList():
            if isinstance(sub.widget(), SchematicWindow) and sub.widget().doc.modified:
                self.mdi.setActiveSubWindow(sub)
                self.save()
        if cur:
            self.mdi.setActiveSubWindow(cur)

    def closeEvent(self, ev):
        for sub in self.mdi.subWindowList():
            w = sub.widget()
            if isinstance(w, SchematicWindow) and w.doc.modified:
                self.mdi.setActiveSubWindow(sub)
                r = QMessageBox.question(self, APP_NAME, f"Save changes to {w.doc.title}?",
                                         QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
                if r == QMessageBox.Cancel or (r == QMessageBox.Yes and not self.save()):
                    ev.ignore()
                    return
        self.settings.setValue("main/geometry", self.saveGeometry())
        if getattr(self, "mcp_host", None) is not None:
            self.mcp_host.stop()
        self.halt_simulation()
        ev.accept()

    def _render_active(self):
        """Render the active schematic to a QImage."""
        sw = self.schematic()
        if sw is None:
            return None
        sc = sw.doc.scene
        rect = sc.itemsBoundingRect().adjusted(-32, -32, 32, 32)
        scale = 2.0
        img = QImage(int(rect.width() * scale), int(rect.height() * scale), QImage.Format_ARGB32)
        img.fill(Qt.white)
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        sc.render(p, source=rect)
        p.end()
        return img

    def export_image(self):
        img = self._render_active()
        if img is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export as Image", "", "PNG (*.png);;SVG (*.svg)")
        if path:
            img.save(path)

    def copy_bitmap(self):
        w = self.active_widget()
        img = w.viewer.grab().toImage() if isinstance(w, PlotWindow) else self._render_active()
        if img is not None:
            QApplication.clipboard().setImage(img)

    # ------------------------------------------------------------ edit / view
    def _undo(self, undo):
        sw = self.schematic()
        if sw:
            sw.set_tool(None)
            stack = sw.doc.undo
            if not (stack.canUndo() if undo else stack.canRedo()):
                # LTspice says so in a small message box
                QMessageBox.information(self, APP_NAME, "Nothing to Undo" if undo else "Nothing to Redo")
                return
            (stack.undo if undo else stack.redo)()

    def ensure_library(self):
        """First-run setup when the LTspice library is missing; open schematics then redraw
        with the real symbols. True if the library is there."""
        from .setup_dialog import ensure_library, library_missing
        was_missing = library_missing()
        ok = ensure_library(self)
        if ok and was_missing:
            for sub in self.mdi.subWindowList():
                if isinstance(sub.widget(), SchematicWindow):
                    sub.widget().doc.scene.rebuild()
        return ok

    def pick_component(self):
        sw = self.schematic()
        if sw is None or not self.ensure_library():
            return
        dlg = ComponentDialog(sw.doc.lib, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected:
            sw.place_symbol(dlg.selected)
        elif dlg.open_example:
            self.open_file(dlg.open_example)

    def zoom_fit(self):
        sw = self.schematic()
        if sw:
            sw.view.zoom_to_fit()
        pw = self.plot_window()
        if pw and self.active_widget() is pw:
            pw.viewer.autorange()

    def _zoom_area(self):
        sw = self.schematic()
        if sw:
            sw.start_zoom_area()
        elif isinstance(self.active_widget(), PlotWindow):
            self.status_label.setText("Drag a box in the plot to zoom in")

    def _zoom_back(self):
        sw = self.schematic()
        if sw:
            sw.view.zoom_back()
        elif isinstance(self.active_widget(), PlotWindow):
            for pane in self.active_widget().viewer.panes:
                pane.plot.getPlotItem().getViewBox().scaleBy(2.0)

    def find_text(self):
        """Edit > Search: highlight every object whose name, value or text contains the string."""
        sw = self.schematic()
        if sw is None:
            return
        text, ok = QInputDialog.getText(self, "Search", "Search for text string:")
        if not ok or not text:
            return
        n = sw.find_text(text)
        self.status_label.setText(f"{n} match(es) for \"{text}\"" if n else f"\"{text}\" not found")

    def _zoom(self, f):
        sw = self.schematic()
        if sw:
            sw.view.zoom(f)

    def toggle_grid(self, on):
        if isinstance(self.active_widget(), PlotWindow):
            # Ctrl+G in a waveform window toggles the plot grid (Plot Settings > Grid)
            self.actions["view_grid"].blockSignals(True)
            self.actions["view_grid"].setChecked(not on)
            self.actions["view_grid"].blockSignals(False)
            v = self.active_widget().viewer
            v.set_grid(not v.show_grid)
            self.actions["plot_grid"].setChecked(v.show_grid)
            return
        from .settings_dialog import put
        put("view/grid", on)
        for sub in self.mdi.subWindowList():
            w = sub.widget()
            if isinstance(w, SchematicWindow):
                w.view.show_grid = on
                w.view.viewport().update()

    def open_sheet_symbol(self):
        """Show the block symbol of this sheet, generating it from the I/O ports if needed."""
        sw = self.schematic()
        if sw is None:
            return
        if sw.doc.path is None:
            QMessageBox.information(self, "Hierarchy", "Save the schematic first.")
            return
        from ..model.asy import load_asy
        from ..model.symgen import sheet_ports, write_symbol_for
        asy = sw.doc.path.with_suffix(".asy")
        if not asy.exists():
            if not sheet_ports(sw.doc.sch):
                QMessageBox.information(self, "Hierarchy",
                                        "Add I/O port labels (F4, Input/Output) to this sheet first.")
                return
            if sw.doc.modified:
                sw.doc.save()
            write_symbol_for(sw.doc.path)
            sw.doc.lib._cache.clear()
        from .component_dialog import SymbolPreview
        dlg = QDialog(self)
        dlg.setWindowTitle(asy.name)
        lay = QVBoxLayout(dlg)
        prev = SymbolPreview()
        prev.set_symbol(load_asy(asy))
        lay.addWidget(prev)
        lay.addWidget(QLabel(f"{asy}\nPlace it in a parent schematic with F2 (same folder)."))
        dlg.exec()

    def toggle_unconnected(self, on):
        from .settings_dialog import put
        put("drafting/mark_unconnected", on)
        for sub in self.mdi.subWindowList():
            w = sub.widget()
            if isinstance(w, SchematicWindow):
                w.view.mark_unconnected = on
                w.view.viewport().update()

    def export_waveform_data(self):
        """File > Export: the plotted traces as tab-separated text (first .step run)."""
        pw = self.plot_window()
        if pw is None:
            QMessageBox.information(self, "Export", "Open a waveform window first.")
            return
        if not pw.viewer.trace_names():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export data as text", "", "Text (*.txt)")
        if path:
            pw.viewer.export_text(path)

    def show_netlist(self):
        sw = self.schematic()
        if sw is None:
            return
        nl = generate_netlist(sw.doc.sch, sw.doc.lib)
        self._add_window(TextWindow(f"{sw.doc.title} netlist", self._netlist_style(nl.text)),
                         f"{Path(sw.doc.title).stem}.net")

    @staticmethod
    def _netlist_style(text):
        """Settings > Netlist Options: convert µ to u, reverse the component order."""
        from .settings_dialog import get
        if get("netlist/convert_mu"):
            text = text.replace("µ", "u").replace("μ", "u")
        if get("netlist/reverse_order"):
            lines = text.splitlines()
            idx = [i for i, l in enumerate(lines) if l[:1].isalpha()]
            for i, l in zip(idx, [lines[i] for i in reversed(idx)]):
                lines[i] = l
            text = "\n".join(lines) + "\n"
        return text

    def show_bom(self):
        sw = self.schematic()
        if sw is None:
            return
        rows = {}
        for s in sw.doc.sch.symbols:
            sym = sw.doc.lib.get(s.symbol, sw.doc.local_dirs)
            val = s.attrs.get("Value") or (sym.attrs.get("Value", "") if sym else "")
            rows.setdefault((s.symbol, val), []).append(s.name)
        lines = ["Bill of Materials", "", f"{'Qty':<5}{'Part':<24}{'Value':<20}Reference"]
        for (symn, val), names in sorted(rows.items()):
            lines.append(f"{len(names):<5}{symn:<24}{val:<20}{', '.join(sorted(names))}")
        self._add_window(TextWindow("Bill of Materials", "\n".join(lines)), "Bill of Materials")

    def show_log(self):
        text = getattr(self, "last_log", "") or "No simulation has been run."
        self._add_window(TextWindow("SPICE Error Log", text), "SPICE Error Log")

    def open_settings(self, tab=None):
        from .settings_dialog import SettingsDialog
        if SettingsDialog(self, tab if isinstance(tab, str) else None).exec() == QDialog.Accepted:
            self.apply_settings()

    def color_prefs(self):
        from .color_dialog import ColorDialog
        if ColorDialog(self).exec() == QDialog.Accepted:
            for sub in self.mdi.subWindowList():
                w = sub.widget()
                if isinstance(w, SchematicWindow):
                    w.doc.scene.rebuild()
                    w.view.viewport().update()

    # ------------------------------------------------------------ window menu
    def tile_horizontal(self):
        subs = [s for s in self.mdi.subWindowList() if s.isVisible()]
        if not subs:
            return
        h = self.mdi.viewport().height() // len(subs)
        w = self.mdi.viewport().width()
        for i, s in enumerate(subs):
            s.showNormal()
            s.setGeometry(0, i * h, w, h)

    def tile_vertical(self):
        subs = [s for s in self.mdi.subWindowList() if s.isVisible()]
        if not subs:
            return
        w = self.mdi.viewport().width() // len(subs)
        h = self.mdi.viewport().height()
        for i, s in enumerate(subs):
            s.showNormal()
            s.setGeometry(i * w, 0, w, h)

    def toggle_tabs(self, on):
        self.settings.setValue("view/window_tabs", on)
        if hasattr(self, "tabs"):
            self.tabs.setVisible(on)

    def _sync_tabs(self):
        subs = [s for s in self.mdi.subWindowList() if isValid(s)]
        self._syncing_tabs = True
        try:
            if subs != self._tab_subs:
                while self.tabs.count():
                    self.tabs.removeTab(0)
                for sub in subs:
                    self.tabs.addTab(sub.windowIcon(), "")
                self._tab_subs = subs
            for i, sub in enumerate(subs):
                w = sub.widget()
                self.tabs.setTabText(i, getattr(w, "title", sub.windowTitle()) if w else sub.windowTitle())
            active = self.mdi.activeSubWindow()
            if active in subs:
                self.tabs.setCurrentIndex(subs.index(active))
        finally:
            self._syncing_tabs = False

    def _tab_clicked(self, i):
        if self._syncing_tabs or not 0 <= i < len(self._tab_subs):
            return
        sub = self._tab_subs[i]
        if isValid(sub):
            if sub.isMinimized():
                sub.showNormal()
            self.mdi.setActiveSubWindow(sub)

    # ------------------------------------------------------------ simulation
    def edit_sim_command(self):
        sw = self.schematic()
        if sw is None:
            return
        existing = next((t for t in sw.doc.sch.texts if t.is_directive and
                         t.body.split()[0].lower() in ANALYSES if t.body.split()), None)
        dlg = dialogs.SimCommandDialog(self, existing.body.splitlines()[0] if existing else "")
        if dlg.exec() != QDialog.Accepted:
            return False
        cmd = dlg.command()
        if existing:
            sw.doc.begin()
            lines = existing.body.splitlines()
            lines[0] = cmd
            existing.text = "!" + "\\n".join(lines)
            sw.doc.commit("Edit Simulation Command")
        else:
            sw.set_tool(sw_tools_place_text(sw, cmd))
        return True

    def run_simulation(self, _checked=False, target=None, interactive=True):
        """Run the active (or given) schematic or netlist. interactive=False (an AI assistant via
        MCP) never opens dialogs; returns (started, message)."""
        if self.sim_thread is not None:
            return False, "a simulation is already running"
        w = target if target is not None else self.active_widget()
        if isinstance(w, PlotWindow) and w.source is not None:
            w = w.source
        from .settings_dialog import get, paths, spice_options
        if get("operation/save_on_run"):
            self.save_all()
        if isinstance(w, SchematicWindow):
            if not any(t.is_directive and t.body.split() and t.body.split()[0].lower() in ANALYSES
                       for t in w.doc.sch.texts) and not any(
                    l.strip().lower().startswith(ANALYSES) for t in w.doc.sch.texts if t.is_directive
                    for l in t.body.splitlines()):
                if not interactive:
                    return False, "the schematic has no analysis command (.tran, .ac, .dc, .op, .noise, .tf)"
                self.edit_sim_command()
                return False, "no analysis command"
            nl = generate_netlist(w.doc.sch, w.doc.lib)
            if nl.errors and interactive:
                QMessageBox.warning(self, "Netlist", "\n".join(nl.errors))
            base = (w.doc.path.with_suffix("") if w.doc.path
                    else config.DATA_DIR / "untitled" / f"Draft{self.untitled or 1}")
            if w.doc.path:
                nl_path = w.doc.path.with_suffix(".net")
                try:
                    nl_path.write_text(self._netlist_style(nl.text), encoding="latin-1", errors="replace")
                except OSError:
                    base = config.DATA_DIR / "runs" / w.doc.path.stem
            text = nl.text
            sim_dirs = list(w.doc.local_dirs)
        elif isinstance(w, TextWindow):
            base = (w.path.with_suffix("") if w.path else config.DATA_DIR / "runs" / "netlist")
            text = w.toPlainText()
            sim_dirs = [w.path.parent] if w.path else []
        else:
            return False, "nothing to simulate: activate a schematic or netlist"
        # Settings > Waveforms: keep .raw/.log files in one directory
        if get("waveform/raw_dir_on") and get("waveform/raw_dir"):
            base = Path(get("waveform/raw_dir")).expanduser() / base.name
        # Settings > SPICE: non-default tolerances and integration method
        opts = spice_options()
        if opts:
            from ..sim.runner import _with_options
            text = _with_options(text, opts)
        from .settings_dialog import run_options
        user = get("paths/user_dir")
        sim = Simulator(text, base, sim_dirs + [Path(p) for p in paths("paths/lib_paths")] +
                        ([Path(user).expanduser()] if user else []), run_options())
        self.sim_owner = w
        self._sim_interactive = interactive
        self.sim_thread = SimThread(sim)
        self.sim_thread.done.connect(self._sim_done)
        self.status_label.setText("Simulating...")
        self.sim_thread.start()
        self._update_actions()
        return True, "\n".join(nl.errors) if isinstance(w, SchematicWindow) else ""

    def halt_simulation(self):
        if self.sim_thread is not None:
            self.sim_thread.sim.cancel()
            self.sim_thread.wait(3000)

    def _sim_done(self, res: SimResult):
        owner = self.sim_owner
        self.sim_thread = None
        self.last_log = "\n".join(res.errors + res.warnings) + ("\n\n" if res.errors or res.warnings else "") + res.log
        if res.measurements:
            self.last_log = "Measurements:\n" + "\n".join(f"{k}: {v}" for k, v in res.measurements) \
                + "\n\n" + self.last_log
        if owner is not None and isValid(owner):
            owner.sim_log = self.last_log           # per document, for MCP get_spice_log
            owner.sim_plots = res.plots if res.ok else None
        self._update_actions()
        if not res.ok:
            self.status_label.setText("Simulation failed")
            if not getattr(self, "_sim_interactive", True):
                self.status_label.setText("Simulation failed (started by an AI assistant; see Ctrl+L)")
                return
            msg = QMessageBox(QMessageBox.Critical, APP_NAME, "\n".join(res.errors[:12]) or "Simulation failed",
                              parent=self)
            msg.setDetailedText(res.log[-20000:])
            msg.exec()
            return
        self.status_label.setText("Simulation done" + (f" — {len(res.warnings)} warning(s), see Ctrl+L"
                                                       if res.warnings else ""))
        self._last_raw = res.raw_path
        plot = res.main_plot()
        if plot is None:
            return
        if plot.analysis == "op":
            self._show_op(plot, owner)
            return
        if plot.analysis == "pz":
            self._show_pz(plot, owner)
            return
        # LTspice names the waveform window after the .raw file
        title = f"{Path(owner.title.rstrip('*')).stem}.raw" if owner else plot.plotname
        if plot.analysis == "disto":
            # one window per harmonic; probes go to all of them
            sets = [p for p in res.plots if p.analysis == "disto"]
            for slot, p in enumerate(sets):
                self._show_plot(owner, p, f"{title} - {p.plotname.split('-')[-1].strip()}", slot)
            return
        self._show_plot(owner, plot, title)

    def _show_op(self, plot, owner=None):
        if isinstance(owner, SchematicWindow):
            values = {}
            for v in plot.variables:
                n = lt_name(v.name)
                if n:
                    values[n.lower()] = float(plot.data[v.index][0].real)
            owner.doc.scene.op_values = values
            owner.doc.scene.rebuild()
        dlg = QDialog(self)
        dlg.setWindowTitle("* Operating Point *")
        lay = QVBoxLayout(dlg)
        rows = [(lt_name(v.name), v) for v in plot.variables]
        rows = [(n, v) for n, v in rows if n]
        t = QTableWidget(len(rows), 3)
        t.setHorizontalHeaderLabels(["Name", "Value", "Type"])
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, (n, v) in enumerate(rows):
            t.setItem(r, 0, QTableWidgetItem(n))
            t.setItem(r, 1, QTableWidgetItem(f"{plot.data[v.index][0].real:.6g}"))
            t.setItem(r, 2, QTableWidgetItem("voltage" if n.startswith("V(") else "device_current"))
        lay.addWidget(t)
        dlg.resize(460, 520)
        dlg.show()

    def _show_pz(self, plot, owner=None):
        """.pz results (ngspice only): poles and zeros as a table, like the .op window."""
        import math
        rows = []
        for v in plot.variables:
            m = re.match(r"(?i)v\((pole|zero)\((\d+)\)\)$", v.name)
            if m:
                rows.append((m.group(1).title(), int(m.group(2)), complex(plot.data[v.index][0])))
        rows.sort(key=lambda r: (r[0] != "Pole", r[1]))
        stem = Path(owner.title.rstrip("*")).stem if owner else "netlist"
        dlg = QDialog(self)
        dlg.setWindowTitle(f"* Pole-Zero Analysis * {stem}")
        lay = QVBoxLayout(dlg)
        t = QTableWidget(len(rows), 6)
        t.setHorizontalHeaderLabels(["", "Real [rad/s]", "Imag [rad/s]", "Frequency", "Q", "Stable"])
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for r, (kind, n, s) in enumerate(rows):
            w0 = abs(s)
            q = (w0 / (-2 * s.real)) if s.real else math.inf
            vals = [f"{kind} {n}", f"{s.real:.6g}", f"{s.imag:.6g}", fmt(w0 / (2 * math.pi), "Hz", 5),
                    "∞" if math.isinf(q) else f"{q:.4g}",
                    ("yes" if s.real < 0 else "no") if kind == "Pole" else ""]
            for c, val in enumerate(vals):
                t.setItem(r, c, QTableWidgetItem(val))
        lay.addWidget(t)
        if not rows:
            lay.addWidget(QLabel("ngspice found no poles or zeros."))
        lay.addWidget(QLabel("Pole-zero analysis is an ngspice extension; LTspice has no .pz."))
        dlg.resize(640, 120 + 30 * max(len(rows), 2))
        dlg.show()
        self.pz_dialog = dlg

    def _new_viewer(self, plot, title):
        viewer = WaveformViewer(plot, title)
        viewer.status.connect(self.status_label.setText)
        viewer.menu_provider = lambda pos, v=viewer: self._plot_context_menu(v, pos)
        viewer.traces_changed.connect(self._update_actions)
        return viewer

    def _plot_context_menu(self, viewer, pos):
        for sub in self.mdi.subWindowList():
            if isinstance(sub.widget(), PlotWindow) and sub.widget().viewer is viewer:
                self.mdi.setActiveSubWindow(sub)
        self.context_menu("waveform", pos)

    def _show_plot(self, owner, plot, title, slot=0):
        viewer = self._new_viewer(plot, title)
        pw = self.plot_window(owner, slot) if owner is not None else None
        if pw is not None:
            old = pw.viewer.trace_names()
            viewer.plt_path = pw.viewer.plt_path
            pw.replace_viewer(viewer)
            for expr in old:
                viewer.add_trace(expr)
        else:
            pw = PlotWindow(viewer, owner, slot)
            sub = self._add_window(pw, title)
            if owner is not None:
                self._tile_with(owner, sub)
                # the schematic stays active so it can be probed right away
                osub = next((s for s in self.mdi.subWindowList() if s.widget() is owner), None)
                if osub is not None:
                    self.mdi.setActiveSubWindow(osub)
            # LTspice restores the traces saved next to the schematic in <name>.plt
            plt = pltfile.plt_for(owner.doc.path) if isinstance(owner, SchematicWindow) else None
            if plt is not None:
                try:
                    layout = pltfile.read_plt(plt).get(plot.plotname.lower())
                except (OSError, ValueError):
                    layout = None
                if layout:
                    viewer.apply_layout(layout)
                    viewer.plt_path = plt
        viewer.save_plot_settings.connect(lambda pw=pw: self.save_plot_settings(pw))
        if isinstance(owner, SchematicWindow):
            owner.sim_plot = plot
        pw.raw_path = getattr(self, "_last_raw", None)
        self._update_actions()

    def _tile_with(self, owner, plot_sub):
        """LTspice tiles every window horizontally after a run, the new plot on top and its
        schematic right below, and zooms each schematic to fit its tile."""
        osub = next((s for s in self.mdi.subWindowList() if s.widget() is owner), None)
        if osub is None or self.mdi.viewMode() == QMdiArea.TabbedView:
            return
        plots = sorted((s for s in self.mdi.subWindowList()
                        if isinstance(s.widget(), PlotWindow) and s.widget().source is owner),
                       key=lambda s: s.widget().slot)
        if plot_sub not in plots:
            plots.append(plot_sub)
        others = [s for s in self.mdi.subWindowList() if s.isVisible() and s not in plots and s is not osub]
        subs = plots + [osub] + others
        w = self.mdi.viewport().width()
        h = self.mdi.viewport().height()
        n = len(subs)
        for i, s in enumerate(subs):
            s.showNormal()
            s.setGeometry(0, i * h // n, w, (i + 1) * h // n - i * h // n)
        QApplication.processEvents()
        for s in subs:
            if isinstance(s.widget(), SchematicWindow):
                s.widget().view.zoom_to_fit()

    def _probe(self, sw, expr):
        for pw in self.plot_windows(sw):
            if pw.viewer.has_trace(expr):
                continue
            err = pw.viewer.add_trace(expr)
            if err:
                self.status_label.setText(err)

    def save_plot_settings(self, pw=None, ask=False):
        """Save Plot Settings (Ctrl+S in a plot) writes <schematic>.plt, which is reloaded after
        the next run; Save Plot Settings As asks for a name."""
        pw = pw or self.plot_window()
        if pw is None:
            return
        path = pw.viewer.plt_path
        if path is None:
            src = pw.source.doc.path if isinstance(pw.source, SchematicWindow) else None
            path = src.with_suffix(".plt") if src else None
        if ask or path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save Plot Settings As", str(path or ""),
                                                  "Plot settings (*.plt)")
            if not path:
                return
        name = pw.viewer.plot.plotname or "Transient Analysis"
        pltfile.write_plt(path, {name: pw.viewer.layout()})
        pw.viewer.plt_path = Path(path)
        self._update_actions()

    def show_fft(self):
        pw = self.plot_window()
        if pw is None or pw.viewer.is_ac:
            QMessageBox.information(self, "FFT", "Select a transient waveform window first.")
            return
        names = pw.viewer.trace_names()
        if not names:
            QMessageBox.information(self, "FFT", "Add a trace to the plot first.")
            return
        dlg = dialogs.FFTDialog(names, self)
        if dlg.exec() != QDialog.Accepted:
            return
        from ..sim.fft import fft_plot
        v = pw.viewer
        a, b = v.steps()[0]
        t = v.x[a:b]
        traces = {n: np.real(np.broadcast_to(np.asarray(v.vectors.eval(n)), v.x.shape))[a:b]
                  for n in dlg.selected()}
        t0, t1 = v.visible_x_range() if dlg.visible_only.isChecked() else (t[0], t[-1])
        plot = fft_plot(t, traces, npts=dlg.points(), window=dlg.window.currentText(), t0=t0, t1=t1)
        viewer = self._new_viewer(plot, f"FFT of {pw.title}")
        for n in traces:
            viewer.add_trace(n)
        self._add_window(PlotWindow(viewer, None), f"FFT of {pw.title}")

    def add_traces(self):
        pw = self.plot_window()
        if pw:
            pw.viewer.add_traces_dialog()

    # ------------------------------------------------------------ help
    def show_shortcuts(self):
        lines = []
        for k, a in self.actions.items():
            if a.shortcuts():
                keys = ", ".join(s.toString() for s in a.shortcuts())
                lines.append(f"{a.text().split(chr(9))[0].replace('&', ''):<36}{keys}")
        w = TextWindow("Keyboard Shortcuts", "\n".join(lines))
        w.setReadOnly(True)
        self._add_window(w, "Keyboard Shortcuts")

    def edit_shortcuts(self):
        shortcuts.ShortcutDialog(self.actions, self).exec()

    def _show_help_text(self, name):
        p = config.HELP_DIR / name
        if not p.exists():
            QMessageBox.information(self, "Help", f"{name} not found. Re-run scripts/extract_msi.py.")
            return
        from ..model.textio import read_text
        w = TextWindow(name, read_text(p)[0])
        w.setReadOnly(True)
        self._add_window(w, name)

    def open_help(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        idx = config.HELP_DIR / "ltspice.htm"
        if idx.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(idx)))
        else:
            QMessageBox.information(self, "Help", "Help files not found. Run scripts/extract_msi.py.")

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME}</b><br>LTspice-compatible schematic capture and waveform "
                          "viewer for Linux.<br>Simulation engine: ngspice.<br><br>"
                          "Symbol and model libraries are read from your own LTspice installer.")

    # ------------------------------------------------------------ LTspice 26 menu commands
    def _set_print_mono(self, on):
        self.settings.setValue("print/monochrome", on)

    def _printer(self):
        from PySide6.QtPrintSupport import QPrinter
        if getattr(self, "printer", None) is None:
            self.printer = QPrinter(QPrinter.HighResolution)
        return self.printer

    def _paint_active(self, painter, page_rect=None):
        """Draw the active schematic or plot onto a printer/preview page."""
        w = self.active_widget()
        if isinstance(w, SchematicWindow):
            sc = w.doc.scene
            target = page_rect if page_rect is not None else painter.viewport()
            sc.render(painter, target, sc.itemsBoundingRect().adjusted(-32, -32, 32, 32))
        elif isinstance(w, PlotWindow):
            pm = w.viewer.grab()
            target = page_rect if page_rect is not None else painter.viewport()
            size = pm.size().scaled(target.size(), Qt.KeepAspectRatio)
            painter.drawPixmap(target.x(), target.y(), size.width(), size.height(), pm)

    def _print_to(self, printer):
        from PySide6.QtPrintSupport import QPrinter
        printer.setColorMode(QPrinter.GrayScale if self.actions["file_print_mono"].isChecked()
                             else QPrinter.Color)
        p = QPainter(printer)
        self._paint_active(p, printer.pageRect(QPrinter.DevicePixel).toRect().translated(
            -printer.pageRect(QPrinter.DevicePixel).toRect().topLeft()))
        p.end()

    def print_active(self):
        from PySide6.QtPrintSupport import QPrintDialog
        if self.active_widget() is None:
            return
        printer = self._printer()
        if QPrintDialog(printer, self).exec() == QDialog.Accepted:
            self._print_to(printer)

    def print_preview(self):
        from PySide6.QtPrintSupport import QPrintPreviewDialog
        if self.active_widget() is None:
            return
        dlg = QPrintPreviewDialog(self._printer(), self)
        dlg.paintRequested.connect(self._print_to)
        dlg.exec()

    def print_setup(self):
        from PySide6.QtPrintSupport import QPageSetupDialog
        QPageSetupDialog(self._printer(), self).exec()

    def write_image(self):
        """Tools > Write image to file: SVG (LTspice writes .emf, which Linux tools don't use)."""
        from PySide6.QtCore import QRectF
        from PySide6.QtSvg import QSvgGenerator
        w = self.active_widget()
        if w is None:
            return
        stem = Path(getattr(w, "title", "image").rstrip("*")).stem
        path, _ = QFileDialog.getSaveFileName(self, "Write image to .svg file", f"{stem}.svg",
                                              "SVG image (*.svg);;PNG image (*.png)")
        if not path:
            return
        if path.lower().endswith(".png"):
            img = self._render_active() if isinstance(w, SchematicWindow) else w.viewer.grab().toImage()
            img.save(path)
            return
        gen = QSvgGenerator()
        gen.setFileName(path)
        if isinstance(w, SchematicWindow):
            r = w.doc.scene.itemsBoundingRect().adjusted(-32, -32, 32, 32)
        else:
            r = QRectF(w.viewer.rect())
        gen.setSize(r.size().toSize())
        gen.setViewBox(QRectF(0, 0, r.width(), r.height()))
        p = QPainter(gen)
        if isinstance(w, SchematicWindow):
            w.doc.scene.render(p, QRectF(0, 0, r.width(), r.height()), r)
        else:
            w.viewer.render(p)
        p.end()

    def _set_line_style(self, style):
        self.line_style = style

    def recenter(self):
        """View > Recenter: center the drawing (or the plot data) without changing the zoom."""
        sw = self.schematic()
        if sw is not None:
            sw.view.centerOn(sw.doc.scene.itemsBoundingRect().center())
            return
        pw = self._plot_viewer()
        if pw is not None:
            pw.recenter()

    def toggle_anchors(self, on):
        from .settings_dialog import put
        put("view/mark_anchors", on)
        for sub in self.mdi.subWindowList():
            w = sub.widget()
            if isinstance(w, SchematicWindow):
                w.view.mark_anchors = on
                w.view.viewport().update()

    def toggle_op_flags(self, on):
        sw = self.schematic()
        if sw is not None:
            sw.doc.scene.show_op_flags = on
            sw.doc.scene.rebuild()

    def _bom_text(self, sw):
        rows = {}
        for s in sw.doc.sch.symbols:
            sym = sw.doc.lib.get(s.symbol, sw.doc.local_dirs)
            val = s.attrs.get("Value") or (sym.attrs.get("Value", "") if sym else "")
            rows.setdefault((s.symbol.replace("\\\\", "\\").split("\\")[-1], val), []).append(s.name)
        lines = ["--- Bill of Materials ---", f"{'Ref.':<16}{'Qty':<5}{'Part':<20}Value"]
        for (symn, val), names in sorted(rows.items(), key=lambda kv: sorted(kv[1])[0]):
            lines.append(f"{', '.join(sorted(names)):<16}{len(names):<5}{symn:<20}{val}")
        return "\n".join(lines)

    def bom_on_schematic(self):
        """View > Bill of Materials > Show on Schematic: place the BOM as a comment."""
        sw = self.schematic()
        if sw is None:
            return
        from ..model import asc as _asc
        from .tools import PlaceTool
        text = self._bom_text(sw).replace("\n", "\\n")
        sw.set_tool(PlaceTool(sw, lambda: [_asc.Text(0, 0, "Left", 2, ";" + text)], repeat=False,
                              label="Bill of Materials"))

    def bom_to_clipboard(self):
        sw = self.schematic()
        if sw is not None:
            QApplication.clipboard().setText(self._bom_text(sw))
            self.status_label.setText("Bill of Materials copied to the clipboard")

    def set_probe_reference(self):
        sw = self.schematic()
        if sw is not None:
            sw.pick_probe_reference()

    def clear_waveforms(self):
        sw = self.schematic()
        for pw in self.plot_windows(sw) if sw else []:
            pw.viewer.clear()

    def generate_subckt(self):
        """Hierarchy > Generate Subckt Netlist: this sheet as a .subckt, its I/O ports as pins."""
        sw = self.schematic()
        if sw is None:
            return
        from ..model.netlist import subckt_netlist
        name = Path(sw.doc.title.rstrip("*")).stem or "sheet"
        text, errors = subckt_netlist(sw.doc.sch, sw.doc.lib, name)
        QApplication.clipboard().setText(text)
        self._add_window(TextWindow(f"{name}.sub", text), f"{name}.sub")
        self.status_label.setText("Subcircuit netlist copied to the clipboard"
                                  + (f" ({len(errors)} problem(s))" if errors else ""))

    def export_pcb_netlist(self):
        """Tools > Export Netlist: an ASCII netlist for PCB layout tools."""
        sw = self.schematic()
        if sw is None:
            return
        from ..model.pcbnetlist import FORMATS, export
        fmt_name, ok = QInputDialog.getItem(self, "Export Netlist", "Netlist format:", list(FORMATS), 0, False)
        if not ok:
            return
        ext = FORMATS[fmt_name]
        stem = (sw.doc.path.with_suffix(ext) if sw.doc.path else Path(f"Draft1{ext}"))
        path, _ = QFileDialog.getSaveFileName(self, "Export Netlist", str(stem), f"Netlist (*{ext});;All files (*)")
        if path:
            Path(path).write_text(export(sw.doc.sch, sw.doc.lib, fmt_name), encoding="latin-1", errors="replace")
            self.status_label.setText(f"Wrote {fmt_name} netlist {Path(path).name}")

    def execute_meas_script(self):
        """File > Execute .MEAS Script: evaluate .meas statements from a file on this plot."""
        pw = self.plot_window()
        if pw is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Execute .MEAS Script", self.settings.value("file/last_dir", ""),
                                              "Measurement scripts (*.meas *.txt *.cir *.net);;All files (*)")
        if not path:
            return
        from ..model.textio import read_text
        from ..sim import measure
        lines = [l for l in read_text(Path(path))[0].splitlines() if l.strip().lower().startswith(".meas")]
        parsed = [m for m in (measure.parse(l) for l in lines) if m]
        if not parsed:
            QMessageBox.information(self, "Execute .MEAS Script", "No .meas statements found.")
            return
        rows = measure.run_measures(parsed, [pw.viewer.plot])
        text = "\n".join(f"{k}: {v}" for k, v in rows)
        self.last_log = (getattr(self, "last_log", "") or "") + f"\n\n{Path(path).name}:\n" + text
        w = TextWindow(f"{Path(path).name} results", text)
        w.setReadOnly(True)
        self._add_window(w, w.title)

    def open_plot_settings(self):
        pw = self.plot_window()
        if pw is None:
            return
        start = str(pw.viewer.plt_path or "")
        path, _ = QFileDialog.getOpenFileName(self, "Open Plot Settings File", start, "Plot settings (*.plt)")
        if path:
            self._load_plt(pw, Path(path))

    def reload_plot_settings(self):
        pw = self.plot_window()
        if pw is not None and pw.viewer.plt_path is not None:
            self._load_plt(pw, pw.viewer.plt_path)

    def _load_plt(self, pw, path):
        try:
            layouts = pltfile.read_plt(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Plot Settings", f"Could not read {path}:\n{e}")
            return
        layout = layouts.get(pw.viewer.plot.plotname.lower()) or next(iter(layouts.values()), None)
        if layout:
            pw.viewer.clear_panes()
            pw.viewer.apply_layout(layout)
        pw.viewer.plt_path = Path(path)
        self._update_actions()

    def plot_defs_path(self):
        from .settings_dialog import plot_defs_path
        return plot_defs_path()

    def open_plot_defs(self):
        """Plot Settings > Edit Plot Defs File: .func/.param definitions for waveform expressions."""
        path = self.plot_defs_path()
        dlg = QDialog(self)
        dlg.setWindowTitle(str(path))
        lay = QVBoxLayout(dlg)
        ed = QPlainTextEdit()
        f = ed.font()
        f.setFamily("Monospace")
        ed.setFont(f)
        ed.setPlainText(path.read_text(errors="replace") if path.exists() else
                        "* User-defined functions and parameters for waveform expressions, e.g.\n"
                        "* .func Pythag(x,y) {sqrt(x*x+y*y)}\n* .param twopi = 2*pi\n")
        lay.addWidget(ed)
        from PySide6.QtWidgets import QDialogButtonBox
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        dlg.resize(640, 420)
        if dlg.exec() == QDialog.Accepted:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(ed.toPlainText())

    def configure_ai(self):
        from .ai_dialog import AiAssistantsDialog
        AiAssistantsDialog(self).exec()

    def start_mcp_host(self):
        """Let MCP bridges (pyltspice-mcp, started by AI assistants) attach to this window."""
        from .mcp_host import McpHost
        self.mcp_host = McpHost(self)
        if not self.mcp_host.start():
            self.mcp_host = None
        return self.mcp_host

    def close_everything(self):
        self.mdi.closeAllSubWindows()

    def arrange_icons(self):
        """Window > Arrange Icons: line up minimized windows along the bottom."""
        x = 0
        for sub in self.mdi.subWindowList():
            if sub.isMinimized():
                sub.move(x, self.mdi.viewport().height() - sub.height())
                x += sub.width()

    def float_window(self):
        """Float Window: move the active window out of the main frame, or back in."""
        w = self.active_widget()
        if w is None:
            return
        if w in self.floating:
            self.floating.remove(w)
            w.setWindowFlags(Qt.Widget)
            self._add_window(w, w.title)
            return
        sub = self.mdi.activeSubWindow()
        if sub is None:
            return
        w.setParent(None)
        self.mdi.removeSubWindow(sub)
        sub.deleteLater()
        w.setWindowFlags(Qt.Window)
        w.setWindowTitle(f"{w.title} - {APP_NAME}")
        w.addActions(list(self.actions.values()))       # keep the shortcuts working out there
        w.installEventFilter(self)
        self.floating.append(w)
        w.destroyed.connect(lambda *_, w=w: w in self.floating and self.floating.remove(w))
        w.resize(900, 600)
        w.show()
        self._update_actions()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if ev.type() == QEvent.WindowActivate and obj in getattr(self, "floating", []):
            self._update_actions()
        return super().eventFilter(obj, ev)

    def apply_settings(self):
        """Push Settings values into open windows."""
        from .settings_dialog import get
        self.actions["view_grid"].setChecked(get("view/grid"))
        self.actions["view_unconnected"].setChecked(get("drafting/mark_unconnected"))
        self.actions["view_anchors"].setChecked(get("view/mark_anchors"))
        self.apply_toolbar_size()
        self._apply_search_paths()
        from . import render
        render.set_font_settings(get("drafting/font"), get("drafting/font_bold"), get("drafting/font_size"),
                                 get("drafting/pen_thickness"))
        for w in self._all_widgets():
            if isinstance(w, SchematicWindow):
                w.view.show_grid = get("view/grid")
                w.view.reverse_wheel = get("drafting/reverse_wheel")
                w.view.mark_unconnected = get("drafting/mark_unconnected")
                w.view.mark_anchors = get("view/mark_anchors")
                w.doc.undo.setUndoLimit(get("drafting/undo_size")) if w.doc.undo.count() == 0 else None
                w.doc.scene.rebuild()
                w.view.viewport().update()
            elif isinstance(w, PlotWindow):
                w.viewer.apply_settings()
        self.mdi.viewport().update()

    @staticmethod
    def _apply_search_paths():
        """Settings the model layer reads: symbol search paths, subfolder search, pin shorts."""
        from ..model import edit, library
        from .settings_dialog import get, paths
        user = get("paths/user_dir")
        library.set_extra_roots(paths("paths/symbol_paths") + ([str(Path(user).expanduser())] if user else []))
        library.SEARCH_SUBDIRS = not get("paths/no_subdirs")
        edit.ALLOW_PIN_SHORTS = get("drafting/allow_pin_shorts")

    def _all_widgets(self):
        return [s.widget() for s in self.mdi.subWindowList()] + list(getattr(self, "floating", []))


def sw_tools_place_text(sw, cmd):
    from ..model import asc as _asc
    from .tools import PlaceTool
    return PlaceTool(sw, lambda: [_asc.Text(0, 0, "Left", 2, "!" + cmd)], repeat=False,
                     label="SPICE Analysis")
