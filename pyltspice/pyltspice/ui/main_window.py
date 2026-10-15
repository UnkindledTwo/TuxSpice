"""Main window: LTspice-style menus, toolbar and MDI area."""
from pathlib import Path

import numpy as np

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from shiboken6 import isValid
from PySide6.QtGui import QAction, QImage, QKeySequence, QPainter
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHeaderView, QLabel,
                               QMainWindow, QMdiArea, QMessageBox, QPlainTextEdit,
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
ANALYSES = (".tran", ".ac", ".dc", ".op", ".noise", ".tf")


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

    def __init__(self, viewer: WaveformViewer, source=None):
        super().__init__()
        self.viewer = viewer
        self.source = source
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("pyltspice", "pyltspice")
        self.cursors = icons.make_cursors()
        self.setWindowTitle(APP_NAME)
        self.mdi = QMdiArea()
        self.mdi.setViewMode(QMdiArea.SubWindowView)
        self.mdi.setDocumentMode(True)
        self.mdi.subWindowActivated.connect(self._update_actions)
        self.setCentralWidget(self.mdi)
        self.sim_thread = None
        self.sim_owner = None
        self.untitled = 0
        self.actions = {}
        self._build_actions()
        shortcuts.apply_saved(self.actions)
        self._build_menus()
        self._build_toolbar()
        self.status_label = QLabel()
        self.statusBar().addWidget(self.status_label, 1)
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
        A = self._act
        sw = self.schematic
        # File
        A("file_new", "&New Schematic", self.new_schematic, "Ctrl+N", "new")
        A("file_open", "&Open...", self.open_dialog, "Ctrl+O", "open")
        A("file_examples", "Open &Examples...", self.open_examples)
        A("file_close", "&Close", self.close_active, "Ctrl+W")
        A("file_save", "&Save", self.save, "Ctrl+S", "save")
        A("file_save_as", "Save &As...", self.save_as)
        A("file_save_all", "Save A&ll", self.save_all)
        A("file_print", "&Print...", self.print_active, "Ctrl+P", "print")
        A("file_export", "Export as Image...", self.export_image)
        A("file_exit", "E&xit", self.close)
        # Edit (LTspice default keys)
        A("edit_undo", "&Undo", lambda: self._undo(True), ["F9", "Ctrl+Z"], "undo")
        A("edit_redo", "&Redo", lambda: self._undo(False), ["Shift+F9", "Ctrl+Y"], "redo")
        A("edit_text", "&Text", lambda: sw() and sw().place_text(False), "T", "text")
        A("edit_directive", "SPICE &Directive", lambda: sw() and sw().place_text(True), "S", "directive")
        A("sim_edit_cmd", "SPICE &Analysis", self.edit_sim_command, None)
        A("edit_resistor", "&Resistor", lambda: sw() and sw().place_symbol("res"), "R", "resistor")
        A("edit_capacitor", "&Capacitor", lambda: sw() and sw().place_symbol("cap"), "C", "capacitor")
        A("edit_inductor", "&Inductor", lambda: sw() and sw().place_symbol("ind"), "L", "inductor")
        A("edit_diode", "D&iode", lambda: sw() and sw().place_symbol("diode"), "D", "diode")
        A("edit_component", "C&omponent", self.pick_component, ["F2", "P"], "component")
        A("edit_rotate", "Rotate", lambda: sw() and sw().rotate_or_mirror(False), "Ctrl+R", "rotate")
        A("edit_mirror", "Mirror", lambda: sw() and sw().rotate_or_mirror(True), "Ctrl+E", "mirror")
        A("edit_wire", "Draw &Wire", lambda: sw() and sw().start_wire(), ["F3", "W"], "wire")
        A("edit_label", "Label &Net", lambda: sw() and sw().place_label(), ["F4", "N"], "label")
        A("edit_ground", "Place &GND", lambda: sw() and sw().place_ground(), "G", "ground")
        A("edit_delete", "&Delete", lambda: sw() and sw().start_delete(), ["F5", "Del"], "delete")
        A("edit_duplicate", "D&uplicate", lambda: sw() and sw().start_move("duplicate"), ["F6", "Ctrl+C"], "duplicate")
        for kind, label in (("LINE", "&Line"), ("RECTANGLE", "&Rectangle"), ("CIRCLE", "&Circle"),
                            ("ARC", "&Arc")):
            A(f"draw_{kind.lower()}", label, lambda _=False, k=kind: sw() and sw().start_draw(k))
        A("edit_dataflag", "Place .op Data Label", lambda: sw() and sw().place_data_flag())
        A("edit_move", "&Move", lambda: sw() and sw().start_move("move"), ["F7", "M"], "move")
        A("edit_drag", "Dr&ag", lambda: sw() and sw().start_move("drag"), "F8", "drag")
        # Hierarchy
        A("hier_symbol", "Open this Sheet's Symbol", self.open_sheet_symbol)
        # View
        A("view_fit", "&Zoom to Fit", self.zoom_fit, "Space", "zoom_fit")
        A("view_zoom_in", "Zoom &In", lambda: self._zoom(1.5), "Ctrl+=", "zoom_in")
        A("view_zoom_out", "Zoom &Out", lambda: self._zoom(1 / 1.5), "Ctrl+-", "zoom_out")
        A("view_grid", "Show &Grid", self.toggle_grid, "Ctrl+G", checkable=True)
        A("view_unconnected", "Mark &Unconnected Pins", self.toggle_unconnected, "U", checkable=True)
        self.actions["view_unconnected"].setChecked(self.settings_bool("drafting/mark_unconnected", False))
        A("view_zoom_back", "Zoom &Back", lambda: sw() and sw().view.zoom_back(), "Ctrl+B")
        A("file_export_data", "Export data as text...", self.export_waveform_data)
        self.actions["view_grid"].setChecked(self.settings_bool("view/grid", False))
        A("view_netlist", "SPICE &Netlist", self.show_netlist, None, "netlist")
        A("view_bom", "&Bill of Materials", self.show_bom)
        A("view_log", "SPICE &Error Log", self.show_log, "Ctrl+L")
        A("view_fft", "&FFT...", self.show_fft)
        # Simulate
        A("sim_run", "&Run", self.run_simulation, None, "run")
        A("sim_halt", "&Halt", self.halt_simulation, None, "halt")
        A("sim_add_trace", "Add &Traces", self.add_traces, None)
        # Tools
        A("tools_settings", "&Settings...", self.open_settings, None, "settings")
        A("tools_colors", "&Color Preferences...", self.color_prefs)
        A("tools_copy_bitmap", "Copy bitmap to Clipboard", self.copy_bitmap)
        # Window
        A("win_tile_h", "Tile &Horizontally", self.tile_horizontal)
        A("win_tile_v", "Tile &Vertically", self.tile_vertical)
        A("win_cascade", "&Cascade", self.mdi.cascadeSubWindows)
        A("win_tabs", "Tabbed Windows", self.toggle_tabs, checkable=True)
        A("win_close_all", "Close &All", self.mdi.closeAllSubWindows)
        # Help
        A("help_shortcuts", "&Keyboard Shortcut Cheat Sheet", self.show_shortcuts)
        A("help_edit_shortcuts", "&Edit Keyboard Shortcuts...", self.edit_shortcuts)
        A("help_topics", "Help &Topics", self.open_help, "F1")
        A("help_changelog", "Show LTspice Change Log", lambda: self._show_help_text("LTspiceChangeLog.txt"))
        A("help_model_changelog", "Show Model Change Log", lambda: self._show_help_text("ChangeLog.txt"))
        A("help_about", "&About", self.about)

    def _build_menus(self):
        mb = self.menuBar()
        a = self.actions
        layout = [
            ("&File", ["file_new", "file_open", "file_examples", "file_close", None, "file_save",
                       "file_save_as", "file_save_all", None, "file_print", "file_export", "file_export_data", None,
                       "@recent", None, "file_exit"]),
            ("&Edit", ["edit_undo", "edit_redo", None, "edit_text", "edit_directive", "sim_edit_cmd", None,
                       "edit_resistor", "edit_capacitor", "edit_inductor", "edit_diode", "edit_component",
                       None, "edit_rotate", "edit_mirror", None, "edit_wire", "edit_label", "edit_ground",
                       "edit_dataflag", None, "edit_delete", "edit_duplicate", "edit_move", "edit_drag",
                       None, "@draw"]),
            ("&Hierarchy", []),
            ("&View", ["view_fit", "view_zoom_in", "view_zoom_out", "view_zoom_back", None,
                       "view_grid", "view_unconnected", None,
                       "view_netlist", "view_bom", "view_log", "view_fft"]),
            ("&Simulate", ["sim_run", "sim_halt", None, "sim_edit_cmd", "sim_add_trace"]),
            ("&Tools", ["tools_settings", "tools_colors", "tools_copy_bitmap"]),
            ("&Window", ["win_tile_h", "win_tile_v", "win_cascade", "win_tabs", None, "win_close_all"]),
            ("&Help", ["help_topics", "help_shortcuts", "help_edit_shortcuts", None,
                       "help_changelog", "help_model_changelog", None, "help_about"]),
        ]
        for title, keys in layout:
            m = mb.addMenu(title)
            if title == "&Hierarchy":
                m.addAction(a["hier_symbol"])
            for k in keys:
                if k is None:
                    m.addSeparator()
                elif k == "@draw":
                    dm = m.addMenu("Draw")
                    for d in ("draw_line", "draw_rectangle", "draw_circle", "draw_arc"):
                        dm.addAction(a[d])
                    dm.addAction(a["edit_text"])
                elif k == "@recent":
                    self.recent_menu = m.addMenu("Recent Files")
                    self._refresh_recent()
                else:
                    m.addAction(a[k])

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        for k in ["file_new", "file_open", "file_save", None, "sim_run", "sim_halt", None,
                  "view_zoom_in", "view_zoom_out", "view_fit", None, "edit_undo", "edit_redo", None,
                  "edit_wire", "edit_ground", "edit_label", "edit_resistor", "edit_capacitor",
                  "edit_inductor", "edit_diode", "edit_component", None, "edit_move", "edit_drag",
                  "edit_duplicate", "edit_delete", "edit_rotate", "edit_mirror", None, "edit_text",
                  "edit_directive", None, "file_print", "tools_settings"]:
            if k is None:
                tb.addSeparator()
            else:
                tb.addAction(self.actions[k])

    def _update_actions(self, *_):
        sw = self.schematic()
        for k, a in self.actions.items():
            if k.startswith(("edit_", "draw_")) or k in ("view_netlist", "view_bom", "sim_edit_cmd",
                                                         "view_zoom_back"):
                a.setEnabled(sw is not None)
        running = self.sim_thread is not None
        self.actions["sim_halt"].setEnabled(running)
        self.actions["sim_run"].setEnabled(not running and self.active_widget() is not None)
        self.actions["sim_add_trace"].setEnabled(self.plot_window() is not None)
        w = self.active_widget()
        if w is not None:
            self.setWindowTitle(f"{APP_NAME} - [{w.title}]")
        else:
            self.setWindowTitle(APP_NAME)

    # ------------------------------------------------------------ windows
    def active_widget(self):
        sub = self.mdi.activeSubWindow()
        return sub.widget() if sub else None

    def schematic(self) -> SchematicWindow | None:
        w = self.active_widget()
        return w if isinstance(w, SchematicWindow) else None

    def plot_window(self, for_schematic=None) -> PlotWindow | None:
        w = self.active_widget()
        if for_schematic is None and isinstance(w, PlotWindow):
            return w
        target = for_schematic or self.schematic()
        for sub in self.mdi.subWindowList():
            pw = sub.widget()
            if isinstance(pw, PlotWindow) and (target is None or pw.source is target):
                return pw
        return None

    def _add_window(self, widget, title):
        sub = self.mdi.addSubWindow(widget)
        sub.setWindowTitle(title)
        sub.setWindowIcon(icons.icon("component" if isinstance(widget, SchematicWindow) else "netlist"))
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
        self.recent_menu.clear()
        for p in self._recent():
            self.recent_menu.addAction(p, lambda p=p: self.open_file(p))

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
            (sw.doc.undo.undo if undo else sw.doc.undo.redo)()

    def pick_component(self):
        sw = self.schematic()
        if sw is None:
            return
        dlg = ComponentDialog(sw.doc.lib, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected:
            sw.place_symbol(dlg.selected)

    def zoom_fit(self):
        sw = self.schematic()
        if sw:
            sw.view.zoom_to_fit()
        pw = self.plot_window()
        if pw and self.active_widget() is pw:
            pw.viewer.autorange()

    def _zoom(self, f):
        sw = self.schematic()
        if sw:
            sw.view.zoom(f)

    def toggle_grid(self, on):
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
        self.mdi.setViewMode(QMdiArea.TabbedView if on else QMdiArea.SubWindowView)
        self.mdi.setTabsClosable(True)

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
        title = f"{owner.title.rstrip('*')} - {plot.plotname}" if owner else plot.plotname
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

    def _show_plot(self, owner, plot, title):
        viewer = WaveformViewer(plot, title)
        viewer.status.connect(self.status_label.setText)
        pw = self.plot_window(owner) if owner is not None else None
        if pw is not None:
            old = pw.viewer.trace_names()
            pw.replace_viewer(viewer)
            for expr in old:
                viewer.add_trace(expr)
        else:
            pw = PlotWindow(viewer, owner)
            sub = self._add_window(pw, title)
            if owner is not None:
                self._tile_with(owner, sub)
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
        """LTspice layout: waveform pane above the schematic."""
        osub = next((s for s in self.mdi.subWindowList() if s.widget() is owner), None)
        if osub is None or self.mdi.viewMode() == QMdiArea.TabbedView:
            return
        w = self.mdi.viewport().width()
        h = self.mdi.viewport().height()
        osub.showNormal()
        plot_sub.showNormal()
        plot_sub.setGeometry(0, 0, w, h // 2)
        osub.setGeometry(0, h // 2, w, h - h // 2)

    def _probe(self, sw, expr):
        pw = self.plot_window(sw)
        if pw is None:
            return
        if pw.viewer.has_trace(expr):
            return
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
