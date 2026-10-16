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
from . import dialogs, icons, shortcuts
from .component_dialog import ComponentDialog
from .document import SchematicDocument
from .schematic_window import SchematicWindow
from .waveform import WaveformViewer

APP_NAME = "pyltspice"
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
        self.setAttribute(Qt.WA_DeleteOnClose)

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
        p = QPainter(self.viewport())
        r = self.viewport().rect()
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
        self.actions = {}
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
    def _act(self, key, text, slot, shortcut=None, icon=None, checkable=False, tip=None):
        a = QAction(text, self)
        seqs = (shortcut if isinstance(shortcut, (list, tuple)) else [shortcut]) if shortcut else []
        a.default_keys = [QKeySequence(s).toString() for s in seqs]
        if seqs:
            a.setShortcuts([QKeySequence(s) for s in seqs])
        a.setShortcutContext(Qt.WindowShortcut)
        if icon:
            a.setIcon(icons.icon(icon))
        a.setCheckable(checkable)
        a.setToolTip(tip or text.replace("&", ""))
        a.triggered.connect(slot)
        self.actions[key] = a
        return a

    def _build_actions(self):
        # Texts, icons and default keys follow LTspice 26's menus and its "new" default shortcuts
        # (observed under Wine). F-key aliases from LTspice XVII are kept as secondary keys.
        A = self._act
        sw = self.schematic
        pv = self._plot_viewer
        # File
        A("file_new", "&New Schematic", self.new_schematic, "Ctrl+N", "new", tip="Start drafting a new schematic")
        A("file_open", "&Open...", self.open_dialog, "Ctrl+O", "open", tip="Open an existing document")
        A("file_examples", "Open E&xamples...", self.open_examples, None, "examples")
        A("file_close", "&Close", self.close_active, "Ctrl+W", "close")
        A("file_save", "&Save", self.save, "Ctrl+S", "save", tip="Save the active document")
        A("file_save_as", "Save &As...", self.save_as, "Ctrl+Shift+S", "save_as")
        A("file_save_all", "Save A&ll", self.save_all)
        A("file_print", "&Print...", self.print_active, "Ctrl+P", "print", tip="Print the active document")
        A("file_export", "Export as Image...", self.export_image)
        A("file_export_data", "Export data as text", self.export_waveform_data, None, "netlist")
        A("plot_save", "Save Plot Settings", lambda: self.save_plot_settings(), None, "save")
        A("file_exit", "E&xit", self.close)
        # Edit (LTspice 26 default keys)
        A("edit_undo", "&Undo", lambda: self._undo(True), ["Ctrl+Z", "F9"], "undo", tip="Undo last edit.")
        A("edit_redo", "&Redo", lambda: self._undo(False), ["Ctrl+Shift+Z", "Shift+F9", "Ctrl+Y"], "redo",
          tip="Re-do last undo.")
        A("edit_text", "&Text", lambda: sw() and sw().place_text(False), "T", "text", tip="Annotate with text.")
        A("edit_directive", "&SPICE Directive", lambda: sw() and sw().place_text(True), ".", "directive",
          tip="Place a SPICE directive on the schematic")
        A("sim_edit_cmd", "Configure SPICE &Analysis", self.edit_sim_command, "A", "analysis",
          tip="Enter or Edit the SPICE analysis command")
        A("edit_resistor", "&Resistor", lambda: sw() and sw().place_symbol("res"), "R", "resistor",
          tip="Place a new Resistor on the schematic.")
        A("edit_capacitor", "&Capacitor", lambda: sw() and sw().place_symbol("cap"), "C", "capacitor",
          tip="Place a new Capacitor on the schematic.")
        A("edit_inductor", "&Inductor", lambda: sw() and sw().place_symbol("ind"), "L", "inductor",
          tip="Place a new Inductor on the schematic.")
        A("edit_diode", "&Diode", lambda: sw() and sw().place_symbol("diode"), "D", "diode",
          tip="Place a new Diode on the schematic.")
        A("edit_voltage", "&Voltage Source", lambda: sw() and sw().place_symbol("voltage"), "V", "voltage",
          tip="Place a voltage source on the schematic.")
        A("edit_component", "Com&ponent", self.pick_component, ["P", "F2"], "component",
          tip="Place a new component on the schematic.")
        A("edit_rotate", "R&otate", lambda: sw() and sw().rotate_or_mirror(False), "Ctrl+R", "rotate",
          tip="Rotate the selected items.")
        A("edit_mirror", "&Mirror", lambda: sw() and sw().rotate_or_mirror(True), "Ctrl+E", "mirror",
          tip="Mirror the selected items.")
        A("edit_wire", "Draw &Wire", lambda: sw() and sw().start_wire(), ["W", "F3"], "wire", tip="Draft wires.")
        A("edit_label", "Label &Net", lambda: sw() and sw().place_label(), ["N", "F4"], "label", tip="Label a node.")
        A("edit_ground", "Place &GND", lambda: sw() and sw().place_ground(), "G", "ground",
          tip="Place a GND symbol on the schematic.")
        A("edit_delete", "D&elete", lambda: sw() and sw().start_delete(), ["Backspace", "Del", "F5"], "delete",
          tip="Delete Mode")
        A("edit_duplicate", "D&uplicate", lambda: sw() and sw().start_move("duplicate"), ["Ctrl+C", "F6"],
          "duplicate", tip="Duplicate Mode")
        A("edit_move", "&Move", lambda: sw() and sw().start_move("move"), ["M", "F7"], "move", tip="Move a section.")
        A("edit_drag", "S&tretch", lambda: sw() and sw().start_move("drag"), ["S", "F8"], "drag",
          tip="Stretch a section.")
        for kind, label, ic in (("LINE", "&Line", "line"), ("RECTANGLE", "&Rectangle", "rectangle"),
                                ("CIRCLE", "&Ellipse", "ellipse"), ("ARC", "&Arc", "arc")):
            A(f"draw_{kind.lower()}", label, lambda _=False, k=kind: sw() and sw().start_draw(k), None, ic)
        A("edit_dataflag", "Place .op Data Label", lambda: sw() and sw().place_data_flag())
        A("edit_find", "Search", self.find_text, "Ctrl+F", "find", tip="Search for text string in deck")
        # Hierarchy
        A("hier_symbol", "Open or Generate this Sheet's &Symbol", self.open_sheet_symbol, None, "component")
        # View
        A("view_zoom_area", "Zoom &Area", self._zoom_area, "Z", "zoom_in", tip="Drag a box and zoom in")
        A("view_zoom_back", "Zoom &Back", self._zoom_back, ["Shift+Z", "Ctrl+B"], "zoom_out",
          tip="Zoom back two fold")
        A("view_fit", "Zoom to &Fit", self.zoom_fit, "Space", "zoom_fit", tip="Zoom the full extent is visible")
        A("view_zoom_in", "Zoom &In", lambda: self._zoom(1.5), "Ctrl+=")
        A("view_zoom_out", "Zoom &Out", lambda: self._zoom(1 / 1.5), "Ctrl+-")
        A("view_grid", "Show &Grid", self.toggle_grid, "Ctrl+G", checkable=True)
        A("view_unconnected", "Mark &Unconn. Pins", self.toggle_unconnected, "Ctrl+U", checkable=True)
        from .settings_dialog import get
        self.actions["view_unconnected"].setChecked(get("drafting/mark_unconnected"))
        self.actions["view_grid"].setChecked(get("view/grid"))
        A("view_netlist", "Update and View SPICE &Netlist", self.show_netlist, None, "netlist")
        A("view_bom", "&Bill of Materials", self.show_bom, None, "bom")
        A("view_log", "SPICE &Output Log", self.show_log, "Ctrl+L", "log")
        A("view_fft", "&FFT", self.show_fft, None, "fft")
        A("view_toolbar", "&Toolbar", lambda on: self.toolbar.setVisible(on), checkable=True)
        A("view_statusbar", "&Status Bar", lambda on: self.statusBar().setVisible(on), checkable=True)
        A("view_tabs", "&Window Tabs", self.toggle_tabs, checkable=True)
        for k in ("view_toolbar", "view_statusbar"):
            self.actions[k].setChecked(True)
        self.actions["view_tabs"].setChecked(self.settings_bool("view/window_tabs", True))
        # Plot settings (waveform window)
        A("plot_autorange", "&Autorange Y-axis", lambda: pv() and pv().autorange(), "Ctrl+Y", "autorange",
          tip="Autorange vertical scale(s)")
        A("sim_add_trace", "&Visible Traces", self.add_traces, None, "waves",
          tip="Select which traces are visible / Open the waveform viewer")
        A("plot_add_trace", "Add &trace", self.add_traces, None, "waves")
        A("plot_delete_traces", "&Delete Traces", lambda: pv() and pv()._delete_all(pv().active), None, "delete")
        A("plot_add_pane", "Add &Plot Pane", lambda: pv() and pv().add_pane())
        A("plot_grid", "&Grid", lambda on: pv() and pv().set_grid(on), checkable=True)
        # Simulate
        A("sim_run", "&Run/Pause", self.run_simulation, "Alt+R", "run", tip="Run/Pause LTspice-compatible simulation")
        A("sim_halt", "S&top", self.halt_simulation, "Alt+S", "halt", tip="Stop the current simulation right now")
        # Tools
        A("tools_settings", "&Settings", self.open_settings, None, "settings",
          tip="Access simulation and operation options")
        A("tools_colors", "&Color Preferences", self.color_prefs, None, "colors")
        A("tools_copy_bitmap", "Copy bitmap to Clipboard", self.copy_bitmap, None, "copy_bitmap")
        # Window
        A("win_tile_h", "Tile &Horizontally", self.tile_horizontal, None, "tile_h",
          tip="Arrange windows as non-overlapping horizontal tiles")
        A("win_tile_v", "Tile &Vertically", self.tile_vertical, None, "tile_v",
          tip="Arrange windows as non-overlapping vertical tiles")
        A("win_cascade", "&Cascade", self.mdi.cascadeSubWindows, None, "cascade",
          tip="Arrange windows so they overlap")
        A("win_close_all", "Close &Everything", self.mdi.closeAllSubWindows, None, "close_all")
        # Help
        A("help_topics", "TuxSpice &Help", self.open_help, "F1", "help")
        A("help_shortcuts", "&Keyboard Shortcut Cheat Sheet", self.show_shortcuts, None, "keyboard")
        A("help_edit_shortcuts", "&Edit Keyboard Shortcuts...", self.edit_shortcuts)
        A("help_changelog", "Show LTspice Change Log", lambda: self._show_help_text("LTspiceChangeLog.txt"),
          None, "netlist")
        A("help_model_changelog", "Show Model Change Log", lambda: self._show_help_text("ChangeLog.txt"),
          None, "netlist")
        A("help_about", "&About TuxSpice", self.about, None, "about")

    # menu layouts: LTspice swaps the menu bar between schematic and waveform windows
    SCHEMATIC_MENUS = [
        ("&File", ["file_new", "file_open", "file_examples", "file_save", "file_save_as", "file_save_all",
                   "file_close", None, "file_print", "file_export", None, "@recent", None, "file_exit"]),
        ("&Edit", ["edit_undo", "edit_redo", "edit_text", "edit_directive", "sim_edit_cmd", "edit_resistor",
                   "edit_capacitor", "edit_inductor", "edit_diode", "edit_voltage", "edit_component",
                   "edit_rotate", "edit_mirror", "edit_wire", "edit_label", "edit_ground", "edit_dataflag",
                   "edit_delete", "edit_duplicate", "edit_move", "edit_drag", "edit_find", "@draw"]),
        ("&Hierarchy", ["hier_symbol"]),
        ("&View", ["view_zoom_area", "view_zoom_back", "view_fit", None, "view_grid", "view_unconnected",
                   None, "view_bom", "view_netlist", "view_log", None, "sim_add_trace", "plot_autorange", None,
                   "view_toolbar", "view_statusbar", "view_tabs"]),
        ("&Simulate", ["sim_run", "sim_halt", None, "tools_settings", None, "sim_edit_cmd"]),
        ("&Tools", ["tools_copy_bitmap", "tools_settings", "tools_colors"]),
        ("&Window", ["win_tile_h", "win_tile_v", "win_cascade", "win_close_all"]),
        ("&Help", ["help_topics", "help_shortcuts", "help_edit_shortcuts", "file_examples", None,
                   "help_model_changelog", "help_changelog", "help_about"]),
    ]
    WAVEFORM_MENUS = [
        ("&File", ["file_new", "file_open", "file_examples", "plot_save", "file_close", None, "file_print",
                   "file_export", None, "file_export_data", None, "@recent", None, "file_exit"]),
        ("&View", ["view_zoom_area", "view_zoom_back", "view_fit", None, "view_log", None, "view_fft", None,
                   "view_toolbar", "view_statusbar", "view_tabs"]),
        ("&Plot Settings", ["sim_add_trace", "plot_add_trace", "plot_delete_traces", None, "plot_add_pane",
                            None, "plot_grid", None, "edit_undo", "edit_redo", None, "plot_autorange", None,
                            "plot_save"]),
        ("Simulatio&n", ["sim_run", "sim_halt"]),
        ("&Tools", ["tools_copy_bitmap", "tools_settings", "tools_colors"]),
        ("&Window", ["win_tile_h", "win_tile_v", "win_cascade", "win_close_all"]),
        ("&Help", ["help_topics", "help_shortcuts", "help_edit_shortcuts", "file_examples", None,
                   "help_model_changelog", "help_changelog", "help_about"]),
    ]

    def _build_menus(self):
        mb = self.menuBar()
        a = self.actions
        self.recent_menus = []
        self.menu_sets = {}
        for kind, layout in (("schematic", self.SCHEMATIC_MENUS), ("waveform", self.WAVEFORM_MENUS)):
            menus = []
            for title, keys in layout:
                m = mb.addMenu(title)
                menus.append(m)
                for k in keys:
                    if k is None:
                        m.addSeparator()
                    elif k == "@draw":
                        dm = m.addMenu("Draw")
                        for d in ("draw_line", "draw_rectangle", "draw_circle", "draw_arc"):
                            dm.addAction(a[d])
                    elif k == "@recent":
                        self.recent_menus.append(m.addMenu("Recent Files"))
                    else:
                        m.addAction(a[k])
            self.menu_sets[kind] = menus
        self.recent_menu = self.recent_menus[0]
        self._refresh_recent()
        self._show_menus("schematic")

    def _show_menus(self, kind):
        for k, menus in self.menu_sets.items():
            for m in menus:
                m.menuAction().setVisible(k == kind)

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(True)                # LTspice's toolbar sits in a rebar with a gripper
        tb.setIconSize(QSize(28, 28))
        # 28 px icons on a 34 px pitch, flat buttons, as in LTspice
        tb.setStyleSheet("QToolBar { spacing: 1px; padding: 2px 2px; }"
                         "QToolButton { padding: 0px; margin: 0px; border: 1px solid transparent; }"
                         "QToolButton:hover { border: 1px solid #a0a0a0; background: #e5f1fb; }"
                         "QToolButton:pressed, QToolButton:checked { background: #cce4f7; }")
        self.toolbar = tb
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
            a.setToolTip(a.text().replace("&", "") + (f" ({keys[0].toString()})" if keys else ""))
            tb.addAction(a)

    def _update_actions(self, *_):
        sw = self.schematic()
        pw = self.plot_window()
        for k, a in self.actions.items():
            if k.startswith(("edit_", "draw_")) or k in ("view_netlist", "view_bom", "sim_edit_cmd",
                                                         "view_zoom_back", "view_zoom_area", "hier_symbol"):
                a.setEnabled(sw is not None)
        on_plot = isinstance(self.active_widget(), PlotWindow)
        for k in ("edit_undo", "edit_redo", "view_zoom_area", "view_zoom_back"):
            self.actions[k].setEnabled(sw is not None or on_plot)
        for k in ("plot_autorange", "plot_add_trace", "plot_delete_traces", "plot_add_pane", "plot_grid",
                  "plot_save", "file_export_data", "view_fft"):
            self.actions[k].setEnabled(on_plot)
        if on_plot:
            self.actions["plot_grid"].setChecked(pw.viewer.show_grid)
        self._show_menus("waveform" if on_plot else "schematic")
        running = self.sim_thread is not None
        self.actions["sim_halt"].setEnabled(running)
        self.actions["sim_run"].setEnabled(not running and self.active_widget() is not None)
        self.actions["sim_add_trace"].setEnabled(self.plot_window() is not None)
        self._sync_tabs()
        self.update_orient_actions()
        w = self.active_widget()
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
        img = self._render_active()
        if img is not None:
            QApplication.clipboard().setImage(img)

    def print_active(self):
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        sw = self.schematic()
        if sw is None:
            return
        printer = QPrinter(QPrinter.HighResolution)
        if QPrintDialog(printer, self).exec() == QDialog.Accepted:
            p = QPainter(printer)
            sw.doc.scene.render(p, source=sw.doc.scene.itemsBoundingRect())
            p.end()

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

    def pick_component(self):
        sw = self.schematic()
        if sw is None:
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
        self.settings.setValue("view/grid", on)
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
        self.settings.setValue("drafting/mark_unconnected", on)
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
        self._add_window(TextWindow(f"{sw.doc.title} netlist", nl.text), f"{Path(sw.doc.title).stem}.net")

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

    def open_settings(self):
        from .settings_dialog import SettingsDialog, get
        if SettingsDialog(self).exec() != QDialog.Accepted:
            return
        self.actions["view_grid"].setChecked(get("view/grid"))
        self.actions["view_unconnected"].setChecked(get("drafting/mark_unconnected"))
        for sub in self.mdi.subWindowList():
            w = sub.widget()
            if isinstance(w, SchematicWindow):
                w.view.show_grid = get("view/grid")
                w.view.reverse_wheel = get("drafting/reverse_wheel")
                w.view.mark_unconnected = get("drafting/mark_unconnected")
                w.view.viewport().update()

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

    def run_simulation(self):
        if self.sim_thread is not None:
            return
        w = self.active_widget()
        if isinstance(w, PlotWindow) and w.source is not None:
            w = w.source
        if isinstance(w, SchematicWindow):
            if not any(t.is_directive and t.body.split() and t.body.split()[0].lower() in ANALYSES
                       for t in w.doc.sch.texts) and not any(
                    l.strip().lower().startswith(ANALYSES) for t in w.doc.sch.texts if t.is_directive
                    for l in t.body.splitlines()):
                self.edit_sim_command()
                return
            nl = generate_netlist(w.doc.sch, w.doc.lib)
            if nl.errors:
                QMessageBox.warning(self, "Netlist", "\n".join(nl.errors))
            base = (w.doc.path.with_suffix("") if w.doc.path
                    else config.DATA_DIR / "untitled" / f"Draft{self.untitled or 1}")
            if w.doc.path:
                nl_path = w.doc.path.with_suffix(".net")
                try:
                    nl_path.write_text(nl.text, encoding="latin-1", errors="replace")
                except OSError:
                    base = config.DATA_DIR / "runs" / w.doc.path.stem
            sim = Simulator(nl.text, base, w.doc.local_dirs)
        elif isinstance(w, TextWindow):
            base = (w.path.with_suffix("") if w.path else config.DATA_DIR / "runs" / "netlist")
            sim = Simulator(w.toPlainText(), base, [w.path.parent] if w.path else [])
        else:
            return
        self.sim_owner = w
        self.sim_thread = SimThread(sim)
        self.sim_thread.done.connect(self._sim_done)
        self.status_label.setText("Simulating...")
        self.sim_thread.start()
        self._update_actions()

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
        self._update_actions()
        if not res.ok:
            self.status_label.setText("Simulation failed")
            msg = QMessageBox(QMessageBox.Critical, APP_NAME, "\n".join(res.errors[:12]) or "Simulation failed",
                              parent=self)
            msg.setDetailedText(res.log[-20000:])
            msg.exec()
            return
        self.status_label.setText("Simulation done" + (f" — {len(res.warnings)} warning(s), see Ctrl+L"
                                                       if res.warnings else ""))
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

    def _show_plot(self, owner, plot, title, slot=0):
        viewer = WaveformViewer(plot, title)
        viewer.status.connect(self.status_label.setText)
        pw = self.plot_window(owner, slot) if owner is not None else None
        if pw is not None:
            old = pw.viewer.trace_names()
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
        viewer.save_plot_settings.connect(lambda pw=pw: self.save_plot_settings(pw))
        if isinstance(owner, SchematicWindow):
            owner.sim_plot = plot
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

    def save_plot_settings(self, pw=None):
        pw = pw or self.plot_window()
        if pw is None:
            return
        src = pw.source.doc.path if isinstance(pw.source, SchematicWindow) else None
        start = str(src.with_suffix(".plt")) if src else ""
        path, _ = QFileDialog.getSaveFileName(self, "Save Plot Settings", start, "Plot settings (*.plt)")
        if path:
            name = pw.viewer.plot.plotname or "Transient Analysis"
            pltfile.write_plt(path, {name: pw.viewer.layout()})

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
        viewer = WaveformViewer(plot, f"FFT of {pw.title}")
        viewer.status.connect(self.status_label.setText)
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
                lines.append(f"{a.text().replace('&', ''):<32}{keys}")
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


def sw_tools_place_text(sw, cmd):
    from ..model import asc as _asc
    from .tools import PlaceTool
    return PlaceTool(sw, lambda: [_asc.Text(0, 0, "Left", 2, "!" + cmd)], repeat=False,
                     label="SPICE Analysis")
