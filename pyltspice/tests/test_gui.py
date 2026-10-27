import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from pyltspice.model import asc

from .conftest import needs_lib


def _dispose(widget):
    """Free a parentless dialog now; left for interpreter exit it outlives QApplication."""
    from shiboken6 import delete
    delete(widget)


def _click(view, x, y, button=Qt.LeftButton):
    p = view.mapFromScene(x, y)
    QTest.mouseMove(view.viewport(), p)
    QTest.mouseClick(view.viewport(), button, Qt.NoModifier, p)


@needs_lib
def test_place_wire_delete_undo(qapp):
    from pyltspice.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    win.new_schematic()
    sw = win.schematic()
    view = sw.view
    view.resetTransform()
    view.centerOn(0, 0)
    qapp.processEvents()

    sw.place_symbol("res")
    _click(view, 0, 0)
    _click(view, 0, 0, Qt.RightButton)        # leave placing mode
    syms = sw.doc.sch.symbols
    assert len(syms) == 1 and syms[0].name == "R1"
    # LTspice carries a new part by its middle: res is 16..96 tall, so the origin lands at (-16, -64)
    r = syms[0]
    assert (r.x, r.y) == (-16, -64)
    bottom = (r.x + 16, r.y + 96)

    sw.start_wire()
    _click(view, *bottom)                      # from the bottom pin...
    _click(view, 96, 160)                      # ...to a free point: only the first leg is committed
    assert len(sw.doc.sch.wires) == 1
    w = sw.doc.sch.wires[0]
    assert (w.x1, w.y1, w.x2, w.y2) == (bottom[0], bottom[1], bottom[0], 160)
    _click(view, 96, 160)                      # clicking again finishes the second leg
    _click(view, 0, 0, Qt.RightButton)
    _click(view, 0, 0, Qt.RightButton)
    assert len(sw.doc.sch.wires) == 2

    sw.start_delete()
    _click(view, r.x + 16, r.y + 50)           # on the resistor body
    assert not sw.doc.sch.symbols
    sw.doc.undo.undo()
    assert len(sw.doc.sch.symbols) == 1
    sw.doc.undo.setClean()                     # avoid the modal "save changes?" prompt
    win.close()


def test_waveform_cursors(qapp, tmp_path):
    from pyltspice.config import ngspice_path
    if not ngspice_path():
        return
    from pyltspice.sim.runner import Simulator
    from pyltspice.ui.waveform import WaveformViewer
    res = Simulator("* rc\nV1 in 0 PULSE(0 1 0 1n 1n 1 2)\nR1 in out 1k\nC1 out 0 1u\n.tran 5m\n",
                    tmp_path / "rc").run()
    v = WaveformViewer(res.main_plot())
    v.add_trace("V(out)")
    tr = v.panes[0].traces[0]
    v.attach_cursor(tr, 1)
    v.attach_cursor(tr, 2)
    c1, c2 = sorted(v.cursors, key=lambda c: c.index)
    c1.vline.setValue(1e-3)
    c2.vline.setValue(2e-3)
    assert abs(c1.y - 0.632) < 0.01 and abs(c2.y - 0.865) < 0.01
    assert "Diff" in v.readout.label.text()
    v.panes[0].remove_trace(tr)
    assert not v.cursors


@needs_lib
def test_op_data_flags(qapp):
    from pyltspice.config import ngspice_path
    if not ngspice_path():
        return
    from pyltspice.ui.main_window import MainWindow
    from pyltspice.ui.items import DataFlagItem
    from .test_netlist import rc_lowpass
    win = MainWindow()
    win.new_schematic()
    sw = win.schematic()
    sch = sw.doc.sch
    sch.items[:] = rc_lowpass().items
    for t in sch.texts:
        t.text = "!.op"
    sch.symbols[0].attrs["Value"] = "5"
    sch.items.append(asc.DataFlag(128, 0, '""'))
    sw.doc.scene.rebuild()
    win.run_simulation()
    while win.sim_thread is not None:
        qapp.processEvents()
    qapp.processEvents()
    items = [i for i in sw.doc.scene.items() if isinstance(i, DataFlagItem)]
    assert items and items[0].label() == "5V"
    sw.doc.undo.setClean()
    for w in qapp.topLevelWidgets():
        if w is not win and w.isVisible():
            w.close()
    win.close()


@needs_lib
def test_draw_rectangle_and_zoom_back(qapp):
    from pyltspice.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    win.new_schematic()
    sw = win.schematic()
    view = sw.view
    view.resetTransform()
    view.centerOn(0, 0)
    qapp.processEvents()
    sw.start_draw("RECTANGLE")
    _click(view, 0, 0)
    _click(view, 64, 32)
    g = sw.doc.sch.of(asc.Graphic)
    assert len(g) == 1 and g[0].coords == [0, 0, 64, 32]
    before = view.transform().m11()
    view.zoom(2.0)
    view.zoom_back()
    assert view.transform().m11() == before
    _click(view, 0, 0, Qt.RightButton)
    sw.doc.undo.setClean()
    win.close()


def test_export_text(qapp, tmp_path):
    from pyltspice.config import ngspice_path
    if not ngspice_path():
        return
    from pyltspice.sim.runner import Simulator
    from pyltspice.ui.waveform import WaveformViewer
    res = Simulator("* rc\nV1 in 0 1\nR1 in out 1k\nC1 out 0 1u\n.tran 1m\n", tmp_path / "rc").run()
    v = WaveformViewer(res.main_plot())
    v.add_trace("V(out)")
    v.export_text(tmp_path / "d.txt")
    lines = (tmp_path / "d.txt").read_text().splitlines()
    assert lines[0] == "time\tV(out)" and len(lines) > 10


def test_shortcut_editor(qapp):
    from PySide6.QtCore import QSettings
    from pyltspice.ui import shortcuts
    from pyltspice.ui.main_window import MainWindow
    QSettings("pyltspice", "pyltspice").remove(shortcuts.KEY)
    win = MainWindow()
    dlg = shortcuts.ShortcutDialog(win.actions, win)
    r = dlg.keys.index("edit_wire")
    dlg.table.selectRow(r)
    QTest.keyClick(dlg.table, Qt.Key_Q, Qt.ControlModifier)
    assert dlg.current["edit_wire"] == ["Ctrl+Q"]
    dlg._ok()
    assert win.actions["edit_wire"].shortcut().toString() == "Ctrl+Q"
    win2 = MainWindow()                       # persisted
    assert win2.actions["edit_wire"].shortcut().toString() == "Ctrl+Q"
    QSettings("pyltspice", "pyltspice").remove(shortcuts.KEY)
    win.close()
    win2.close()


@needs_lib
def test_ltspice_toolbar_menus_tabs_search(qapp):
    """LTspice 26 layout: toolbar order, menu bar swaps for waveform windows, window tabs, Z and Ctrl+F."""
    from PySide6.QtCore import QRectF
    from pyltspice.ui.main_window import MainWindow, PlotWindow
    from pyltspice.ui.waveform import WaveformViewer
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    acts = [a for a in win.toolbar.actions() if not a.isSeparator()]
    assert acts[0] is win.actions["tools_settings"] and acts[-1] is win.actions["edit_find"]
    assert win.actions["edit_directive"].shortcut().toString() == "."
    assert win.actions["edit_drag"].shortcut().toString() == "S"

    win.new_schematic()
    sw = win.schematic()
    sw.place_symbol("res")
    _click(sw.view, 0, 0)
    _click(sw.view, 0, 0, Qt.RightButton)
    visible = [m.title() for m in win.menu_sets["schematic"] if m.menuAction().isVisible()]
    assert "&Hierarchy" in visible
    assert win.tabs.count() == 1

    # Edit > Search highlights the match
    assert sw.find_text("r1") == 1
    item = sw.doc.scene.item_of[id(sw.doc.sch.symbols[0])]
    assert item.highlight

    # View > Zoom Area: drag a box, the view zooms in on it and the tool ends
    sw.view.resetTransform()
    before = sw.view.transform().m11()
    sw.start_zoom_area()
    view = sw.view
    a, b = view.mapFromScene(-20, -20), view.mapFromScene(40, 40)
    QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, b)
    assert view.transform().m11() > before
    assert type(sw.tool).__name__ == "IdleTool"
    assert QRectF(-20, -20, 60, 60).contains(view.mapToScene(view.viewport().rect().center()))

    # a waveform window gets the waveform menus and its own tab
    import numpy as np
    from pyltspice.sim.rawfile import Plot, Variable
    plot = Plot(title="t", plotname="Transient Analysis", flags={"real"},
                variables=[Variable(0, "time", "time"), Variable(1, "V(a)", "voltage")],
                data=np.array([[0.0, 1.0], [0.0, 1.0]]))
    pw = PlotWindow(WaveformViewer(plot, "t"), sw)
    win._add_window(pw, "t")
    qapp.processEvents()
    visible = [m.title() for m in win.menu_sets["waveform"] if m.menuAction().isVisible()]
    assert "&Plot Settings" in visible
    assert not any(m.menuAction().isVisible() for m in win.menu_sets["schematic"])
    assert win.tabs.count() == 2
    assert not pw.viewer.show_grid
    win.toggle_grid(True)
    assert pw.viewer.show_grid
    win.tabs.setCurrentIndex(0)
    qapp.processEvents()
    assert win.schematic() is sw
    sw.doc.undo.setClean()
    win.close()


@needs_lib
def test_rotate_keeps_labels_upright(qapp):
    """Rotating a two-pin part rewrites its WINDOW lines like LTspice (checked against 1600+
    rotated resistors in the examples)."""
    from pyltspice.model import edit as ed
    from pyltspice.model.library import SymbolLibrary
    lib = SymbolLibrary()
    r = asc.SymbolInst("res", 0, 0, "R0", {}, {"InstName": "R1"})
    ed.rotate([r], 0, 0)
    ed.relayout_windows(r, lib.get("res"))
    assert r.orient == "R90"
    assert [(i, w.x, w.y, w.just) for i, w in r.windows.items()] == [(0, 0, 56, "VBottom"), (3, 32, 56, "VTop")]
    ed.rotate([r], 0, 0)
    ed.relayout_windows(r, lib.get("res"))
    assert [(i, w.x, w.y, w.just) for i, w in sorted(r.windows.items())] == [(0, 36, 76, "Left"), (3, 36, 40, "Left")]
    v = asc.SymbolInst("voltage", 0, 0, "R270", {}, {"InstName": "V1"})
    ed.relayout_windows(v, lib.get("voltage"))
    assert [(i, w.x, w.y, w.just) for i, w in sorted(v.windows.items())] == [(0, 32, 56, "VTop"), (3, -32, 56, "VBottom")]
    q = asc.SymbolInst("npn", 0, 0, "R90", {}, {})
    ed.relayout_windows(q, lib.get("npn"))       # not a two-pin part: left alone
    assert not q.windows


@needs_lib
def test_component_dialog_search_jumps_to_folder(qapp):
    from pyltspice.model.library import SymbolLibrary
    from pyltspice.ui.component_dialog import ComponentDialog
    dlg = ComponentDialog(SymbolLibrary())
    dlg._search("npn")
    assert dlg.folder == "" and dlg.list.currentItem().text() == "npn"
    lib = dlg.lib
    folder = next(f for f in dlg.tree if f and dlg.tree[f])
    name = sorted(dlg.tree[folder])[0]
    dlg._search(name)
    assert dlg.folder == folder
    dlg._ok()
    assert dlg.selected.lower().replace("\\\\", "/") == f"{folder}/{name}"
    assert lib.get(dlg.selected) is not None
    _dispose(dlg)


def test_net_label_dialog(qapp):
    from pyltspice.ui.dialogs import NetLabelDialog
    dlg = NetLabelDialog()
    dlg.name.setEditText("out")
    dlg.port.setCurrentIndex(1)
    f = asc.Flag(0, 0, "x")
    dlg.apply_to(f)
    assert (f.name, f.iopin) == ("out", "In")
    dlg.opts["gnd"].setChecked(True)
    dlg.apply_to(f)
    assert (f.name, f.iopin) == ("0", None)
    _dispose(dlg)


def test_simple_source_dialog(qapp):
    from pyltspice.ui.dialogs import SimpleSourceDialog
    v = asc.SymbolInst("voltage", 0, 0, "R0", {}, {"InstName": "V1", "Value": "5 Rser=1"})
    assert SimpleSourceDialog.handles(v)
    dlg = SimpleSourceDialog(None, v)
    assert dlg.dc.text() == "5" and dlg.rser.text() == "1"
    dlg.dc.setText("12")
    dlg.apply()
    assert v.attrs["Value"] == "12 Rser=1"
    assert not SimpleSourceDialog.handles(asc.SymbolInst("voltage", 0, 0, "R0", {}, {"Value": "PULSE(0 1 0)"}))
    _dispose(dlg)


@needs_lib
def test_part_picker_reads_ltspice_tables(qapp):
    from pyltspice.ui.dialogs import PartPicker
    dlg = PartPicker(None, "C", "1µ")
    assert dlg.rows                                   # standard_cap.db
    row = dlg.chosen()
    assert row is not None and row["C"] >= 0.999e-6
    _dispose(dlg)


@needs_lib
def test_click_unconnected_pin_starts_wire(qapp):
    from pyltspice.ui.main_window import MainWindow
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    win.new_schematic()
    sw = win.schematic()
    view = sw.view
    view.resetTransform()
    view.centerOn(0, 0)
    sw.place_symbol("res")
    _click(view, 0, 0)
    _click(view, 0, 0, Qt.RightButton)
    r = sw.doc.sch.symbols[0]
    _click(view, r.x + 16, r.y + 96)              # LTspice 26: clicking an open pin starts wiring
    assert type(sw.tool).__name__ == "WireTool"
    assert (sw.tool.start.x(), sw.tool.start.y()) == (r.x + 16, r.y + 96)
    assert not win.actions["edit_rotate"].isEnabled()
    _click(view, 0, 0, Qt.RightButton)
    _click(view, 0, 0, Qt.RightButton)
    sw.doc.undo.setClean()
    win.close()


@needs_lib
def test_pz_and_disto_results_shown(qapp, tmp_path):
    from pyltspice.config import ngspice_path
    if not ngspice_path():
        return
    from pyltspice.sim.runner import Simulator
    from pyltspice.ui.main_window import MainWindow, PlotWindow
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    win.new_schematic()
    sw = win.schematic()
    # .pz: a table of poles and zeros
    res = Simulator("* rc\nV1 in 0 AC 1\nR1 in out 1k\nC1 out 0 1u\n.pz in 0 out 0 vol pz\n.end\n",
                    tmp_path / "pz").run()
    win.sim_owner = sw
    win._sim_done(res)
    t = win.pz_dialog.findChild(type(win.pz_dialog.layout().itemAt(0).widget()))
    assert t.item(0, 0).text() == "Pole 1" and t.item(0, 3).text().startswith("159.15")
    win.pz_dialog.close()
    # .disto: one plot window per harmonic, probes reach both
    res = Simulator("* amp\nV1 in 0 DC 0.7 AC 1 DISTOF1 1\nR1 in b 1k\nQ1 c b 0 qn\nRC vcc c 1k\n"
                    "VCC vcc 0 5\n.model qn npn\n.disto dec 5 1k 1Meg\n.end\n", tmp_path / "d").run()
    win.sim_owner = sw
    win._sim_done(res)
    pws = win.plot_windows(sw)
    assert sorted(pw.slot for pw in pws) == [0, 1]
    win._probe(sw, "V(c)")
    assert all(pw.viewer.trace_names() == ["V(c)"] for pws_ in [pws] for pw in pws_)
    assert all(isinstance(pw, PlotWindow) for pw in pws)
    sw.doc.undo.setClean()
    win.close()


def _tran_plot():
    import numpy as np
    from pyltspice.sim.rawfile import Plot, Variable
    t = np.linspace(0, 1e-3, 50)
    return Plot(title="t", plotname="Transient Analysis", flags={"real"},
                variables=[Variable(0, "time", "time"), Variable(1, "V(a)", "voltage"),
                           Variable(2, "V(b)", "voltage")],
                data=np.array([t, np.sin(t * 1e4), np.cos(t * 1e4)]))


def test_ltspice26_menu_bars(qapp):
    """Three menu bars as in LTspice 26: nothing open, schematic, waveform."""
    from pyltspice.ui.main_window import MainWindow, PlotWindow
    win = MainWindow()
    win.show()
    shown = lambda kind: [m.title().replace("&", "") for m in win.menu_sets[kind] if m.menuAction().isVisible()]
    assert shown("empty") == ["File", "View", "Tools", "Help"]
    win.new_schematic()
    qapp.processEvents()
    assert shown("schematic") == ["File", "Edit", "Hierarchy", "View", "Simulate", "Tools", "Window", "Help"]
    sw = win.schematic()
    pw = PlotWindow(win._new_viewer(_tran_plot(), "t.raw"), sw)
    win._add_window(pw, "t.raw")
    qapp.processEvents()
    assert shown("waveform") == ["File", "View", "Plot Settings", "Simulation", "Tools", "Window", "Help"]
    # plot-only commands are off for schematics and vice versa, so shared keys never clash
    assert win.actions["plot_add_trace"].isEnabled() and not win.actions["sim_edit_cmd"].isEnabled()
    sw.doc.undo.setClean()
    win.close()


def test_shared_keys_follow_active_window(qapp):
    """C places a capacitor on a schematic but a cursor on a plot; Esc clears cursors;
    P/D add and move panes; Ctrl+Z undoes trace changes (Plot Settings > Undo)."""
    from pyltspice.ui.main_window import MainWindow, PlotWindow
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    win.new_schematic()
    sw = win.schematic()
    qapp.processEvents()
    QTest.keyClick(sw.view, Qt.Key_C)
    assert type(sw.tool).__name__ == "PlaceTool"
    sw.set_tool(None)
    v = win._new_viewer(_tran_plot(), "t.raw")
    v.add_trace("V(a)")
    win._add_window(PlotWindow(v, sw), "t.raw")
    qapp.processEvents()
    target = v.panes[0].plot
    QTest.keyClick(target, Qt.Key_C)
    assert len(v.cursors) == 1
    QTest.keyClick(target, Qt.Key_Escape)
    assert not v.cursors
    QTest.keyClick(target, Qt.Key_P)                 # new pane above the active one
    assert len(v.panes) == 2 and v.panes.index(v.active) == 0
    v.add_trace("V(b)")
    QTest.keyClick(target, Qt.Key_D)                 # move it below
    assert v.layout() == [["V(a)"], ["V(b)"]]
    QTest.keyClick(target, Qt.Key_Z, Qt.ControlModifier)
    assert v.layout() == [["V(b)"], ["V(a)"]]
    QTest.keyClick(target, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    assert v.layout() == [["V(a)"], ["V(b)"]]
    QTest.keyClick(target, Qt.Key_Delete)            # delete mode: click a label to remove it
    assert v.mode == "delete"
    v.panes[1]._label_clicked("0")
    assert v.layout() == [["V(a)"], []]
    sw.doc.undo.setClean()
    win.close()


def test_settings_remembered_only_when_starred(qapp):
    """Like LTspice, only [*] settings persist; SPICE tolerances last for the session."""
    from pyltspice.ui import settings_dialog as sd
    sd.put("spice/reltol", "0.002")              # not [*]
    sd.put("spice/trtol", "7")                   # [*]
    assert sd.get("spice/reltol") == "0.002"
    assert sd._settings().value("spice/reltol") is None
    assert sd._settings().value("spice/trtol") == "7"
    sd.put("spice/method", "Gear")
    assert sd.spice_options() == ".options method=gear reltol=0.002 trtol=7"
    for k in ("spice/reltol", "spice/trtol", "spice/method"):
        sd.put(k, sd.DEFAULTS[k])
    assert sd.spice_options() == ""
    dlg = sd.SettingsDialog(None, "Hacks")
    assert dlg.tabs.tabText(dlg.tabs.currentIndex()) == "Hacks" and dlg.tabs.count() == 10
    _dispose(dlg)


def test_waveform_expressions_degrees_and_plot_defs():
    from pyltspice.sim.vectors import VectorSet
    plot = _tran_plot()
    v = VectorSet(plot, radians=False, defs=".func Pythag(x,y) {sqrt(x*x+y*y)}\n.param twopi = 2*pi\n")
    assert abs(v.eval("sin(90)") - 1) < 1e-12           # Settings > Waveforms: radians off
    assert abs(v.eval("Pythag(3,4)") - 5) < 1e-12
    assert abs(v.eval("twopi") - 6.283185307) < 1e-6
    assert abs(VectorSet(plot).eval("sin(90)") - 0.8939966636) < 1e-9


@needs_lib
def test_subckt_and_pcb_netlists():
    from pyltspice.model.netlist import subckt_netlist
    from pyltspice.model.pcbnetlist import export
    sch = asc.parse_asc("Version 4\nSHEET 1 880 680\nWIRE 0 0 0 16\nWIRE 0 96 0 128\n"
                        "FLAG 0 0 in\nIOPIN 0 0 In\nFLAG 0 128 0\n"
                        "SYMBOL res -16 0 R0\nSYMATTR InstName R1\nSYMATTR Value 1k\n"
                        "TEXT 0 200 Left 2 !.tran 1m\n")
    text, _ = subckt_netlist(sch, name="blk")
    assert ".subckt blk in" in text and "R1 in 0 1k" in text and ".tran" not in text
    tango = export(sch, fmt="Tango")
    assert "[\nR1\nres\n1k" in tango and "(\nin\nR1-1\n)" in tango


def test_decimate_keeps_each_columns_extremes():
    """Uneven steps, as transient output has: the decimated trace has the same first/last,
    low and high point in every pixel column as the full one."""
    import numpy as np
    from pyltspice.ui.waveform import decimate
    rng = np.random.default_rng(1)
    x = np.cumsum(rng.exponential(1.0, 200_000) * np.repeat([0.01, 1.0, 0.1], [100_000, 20_000, 80_000]))
    y = np.sign(np.sin(x)) + rng.normal(0, 0.1, len(x))
    x0, x1, cols = x[1000], x[-1000], 500
    idx = decimate(x, y, x0, x1, cols)
    assert len(idx) <= 4 * cols + 4 and np.all(np.diff(idx) > 0)
    col = np.floor((x - x0) * cols / (x1 - x0)).astype(int)
    inside = (x >= x0) & (x <= x1)
    for c in (0, 7, 250, 499):
        full, kept = (col == c) & inside, np.isin(np.arange(len(x)), idx) & (col == c)
        assert y[full].min() == y[kept].min() and y[full].max() == y[kept].max()
    # zoomed in to a few points, every point is drawn
    assert list(decimate(x, y, x[5000], x[5010], cols)) == list(range(4999, 5012))


def test_dense_trace_draws_quickly_and_fits_whole_range(qapp):
    """A 1 MHz square wave over 10 ms (~300k points) once took ~25 s per repaint and froze
    the window: only what fits on screen is drawn, and zoom-to-fit still sees all of it."""
    import time
    import numpy as np
    from pyltspice.sim.rawfile import Plot, Variable
    from pyltspice.ui.waveform import WaveformViewer
    t = np.sort(np.random.default_rng(2).uniform(0, 1e-2, 300_000))
    plot = Plot(title="t", plotname="Transient Analysis", flags={"real"},
                variables=[Variable(0, "time", "time"), Variable(1, "V(a)", "voltage")],
                data=np.array([t, 5.0 * (np.sin(2 * np.pi * 1e6 * t) > 0)]))
    v = WaveformViewer(plot, "t")
    v.resize(1000, 400)
    v.show()
    v.add_trace("V(a)")
    qapp.processEvents()
    item = v.panes[0].traces[0].items[0][1]
    vb = item.getViewBox()
    assert len(item.curve.xData) < 10_000
    start = time.time()
    v.grab()
    assert time.time() - start < 3
    vb.setXRange(5e-3, 5.002e-3, padding=0)
    qapp.processEvents()
    assert len(item.curve.xData) == np.count_nonzero((t >= 5e-3) & (t <= 5.002e-3)) + 2
    v.autorange()
    qapp.processEvents()
    lo, hi = vb.viewRange()[0]
    assert lo <= t[0] and hi >= t[-1]
    v.close()


@needs_lib
def test_duplicate_then_paste_into_another_schematic(qapp):
    """LTspice: start Duplicate in one schematic, then Ctrl+V in another pastes it there."""
    from PySide6.QtWidgets import QApplication
    from pyltspice.ui import tools
    from pyltspice.ui.main_window import MainWindow
    QApplication.clipboard().clear()
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    win.new_schematic()
    a = win.schematic()
    a.view.resetTransform()
    a.view.centerOn(0, 0)
    a.place_symbol("res")
    _click(a.view, 0, 0)
    _click(a.view, 0, 0, Qt.RightButton)
    win._update_actions()
    assert not win.actions["edit_paste"].isEnabled()      # nothing duplicated yet

    a.start_move("duplicate")
    _click(a.view, 0, -10)                                # pick R1: it is now on the clipboard
    _click(a.view, 0, 0, Qt.RightButton)                  # drop the carried copy
    _click(a.view, 0, 0, Qt.RightButton)                  # leave Duplicate
    assert len(a.doc.sch.symbols) == 1 and tools.clipboard_has_objects()

    win.new_schematic()
    b = win.schematic()
    assert b is not a
    b.view.resetTransform()
    b.view.centerOn(0, 0)
    qapp.processEvents()
    assert win.actions["edit_paste"].isEnabled()
    win.actions["edit_paste"].trigger()
    assert isinstance(b.tool, tools.PasteTool)
    _click(b.view, 160, 160)
    assert [s.name for s in b.doc.sch.symbols] == ["R1"]
    pasted = b.doc.sch.symbols[0]
    assert (pasted.x, pasted.y) == (160 - 16, 160 - 64)  # carried by its middle, like a new part
    assert not isinstance(b.tool, tools.PasteTool)        # one paste per Ctrl+V
    win.actions["edit_paste"].trigger()
    _click(b.view, 320, 160)
    assert [s.name for s in b.doc.sch.symbols] == ["R1", "R2"]
    b.doc.undo.undo()
    assert len(b.doc.sch.symbols) == 1
    for sw in (a, b):
        sw.doc.undo.setClean()
    win.close()


def test_clipboard_carries_wires_flags_and_text(qapp):
    from pyltspice.ui import tools
    objs = [asc.Wire(0, 0, 64, 0), asc.Flag(64, 0, "out"), asc.Text(0, 32, "Left", 2, "!.tran 1m"),
            asc.SymbolInst("res", 0, 0, "R90", {}, {"InstName": "R7", "Value": "1k"})]
    tools.copy_to_clipboard(objs)
    back = tools.clipboard_objects()
    assert asc.Schematic(items=back).to_text() == asc.Schematic(items=objs).to_text()


def test_phase_and_gain_margin_math():
    """Analytic loops: K/(s(1+s/p)) crossing 0 dB at its pole has 45° of phase margin and no
    -180° crossing; 4/(1+s/p)^3 crosses -180° at p√3, where its gain is 4/8 (6.02 dB margin)."""
    import numpy as np
    from pyltspice.ui.waveform import gain_margin, phase_margin
    f = np.logspace(0, 6, 2001)
    s, p = 2j * np.pi * f, 2 * np.pi * 1e3
    fc, pm = phase_margin(f, p * np.sqrt(2) / (s * (1 + s / p)))
    assert abs(fc / 1e3 - 1) < 1e-3 and abs(pm - 45) < 0.05
    assert gain_margin(f, p * np.sqrt(2) / (s * (1 + s / p))) is None
    fg, gm = gain_margin(f, 4 / (1 + s / p) ** 3)
    assert abs(fg / (1e3 * np.sqrt(3)) - 1) < 1e-3 and abs(gm - 20 * np.log10(2)) < 0.01
    # 4/(1+s/p)^3 crosses 0 dB at f/p = sqrt(4^(2/3) - 1): PM = 180 - 3 atan(1.2328) = 27.14°
    fc, pm = phase_margin(f, 4 / (1 + s / p) ** 3)
    assert abs(fc / 1232.8 - 1) < 1e-3 and abs(pm - 27.14) < 0.05
    assert phase_margin(f, 0.5 / (1 + s / p)) is None     # never above 0 dB


def test_annotate_margins_and_steps(qapp):
    import numpy as np
    from pyltspice.sim.rawfile import Plot, Variable
    from pyltspice.ui.main_window import MainWindow, PlotWindow
    f = np.logspace(0, 6, 601)
    s, p = 2j * np.pi * f, 2 * np.pi * 1e3
    loops = [4 / (1 + s / p) ** 3, 2 / (1 + s / p) ** 3]
    plot = Plot(title="t", plotname="AC Analysis", flags={"complex"},
                variables=[Variable(0, "frequency", "frequency"), Variable(1, "V(loop)", "voltage")],
                data=np.array([np.r_[f, f], np.r_[loops[0], loops[1]]]),
                step_bounds=[(0, 601), (601, 1202)], step_labels=["Step 1: K=4", "Step 2: K=2"])
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    v = win._new_viewer(plot, "t.raw")
    v.add_trace("V(loop)")
    win._add_window(PlotWindow(v, None), "t.raw")
    qapp.processEvents()
    win._update_actions()
    texts = lambda: [n.text for n in v.notes]
    win.actions["notes_gm"].trigger()
    assert texts() == ["Gain Margin: 6.0dB @ 1.732kHz", "Gain Margin: 12.0dB @ 1.732kHz"]
    win.actions["notes_pm"].trigger()
    assert sum(t.startswith("Phase Margin") for t in texts()) == 2
    win.actions["notes_steps"].trigger()
    assert texts()[-2:] == ["Step 1: K=4", "Step 2: K=2"]
    win.close()


def test_move_stretch_duplicate_delete_annotations(qapp):
    """Plot right-click > Edit works on annotations: M moves one, S drags the nearest end,
    Ctrl+C copies, Del deletes; right-click cancels a carry; Ctrl+Z undoes each step."""
    from PySide6.QtCore import QPointF
    from pyltspice.ui.main_window import MainWindow, PlotWindow
    from pyltspice.ui.waveform import Note
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    v = win._new_viewer(_tran_plot(), "t.raw")
    v.add_trace("V(a)")
    win._add_window(PlotWindow(v, None), "t.raw")
    qapp.processEvents()
    pane = v.panes[0]
    vb = pane.plot.getPlotItem().getViewBox()
    vb.setRange(xRange=(0, 1e-3), yRange=(-1, 1), padding=0)
    qapp.processEvents()
    line = v.add_note(Note("line", pane, [(2e-4, 0), (4e-4, 0)], "red"))
    scene = lambda x, y: vb.mapViewToScene(QPointF(x, y))

    def click(x, y, button=Qt.LeftButton):
        view = pane.plot
        p = view.mapFromScene(scene(x, y))
        QTest.mouseMove(view.viewport(), p)
        QTest.mouseClick(view.viewport(), button, Qt.NoModifier, p)
        qapp.processEvents()

    win._update_actions()
    assert win.actions["ctx_plot_move"].isEnabled() and not win.actions["edit_move"].isEnabled()
    win.actions["ctx_plot_move"].trigger()
    click(3e-4, 0)                                   # pick the line in its middle...
    click(3e-4, 0.5)                                 # ...and drop it 0.5 V higher
    (x0, y0), (x1, y1) = line.pts
    assert abs(y0 - 0.5) < 0.02 and abs(y1 - 0.5) < 0.02 and abs(x1 - x0 - 2e-4) < 1e-9
    click(3e-4, 0.5)                                 # pick again, drag, right-click: back where it was
    v.note_drag(scene(3e-4, -0.5))
    assert abs(line.pts[0][1] + 0.5) < 0.02
    v.context_menu(pane, QPoint())
    assert abs(line.pts[0][1] - 0.5) < 0.02 and v.mode is None and v.carry is None

    win.actions["ctx_plot_stretch"].trigger()
    click(4e-4, 0.5)                                 # grab the right end
    click(8e-4, -0.5)
    assert abs(line.pts[0][0] - 2e-4) < 1e-5 and abs(line.pts[1][0] - 8e-4) < 1e-5
    assert abs(line.pts[1][1] + 0.5) < 0.02
    v.end_mode()

    win.actions["ctx_plot_duplicate"].trigger()
    click(2e-4, 0.5)
    click(2e-4, -0.8)
    assert len(v.notes) == 2 and abs(v.notes[1].pts[0][1] + 0.8) < 0.02
    v.end_mode()

    win.actions["plot_delete_traces"].trigger()
    click(2e-4, 0.5)                                 # the original line's left end
    assert v.notes == [v.notes[0]] and v.notes[0].pts[0][1] < -0.7
    assert len(pane.traces) == 1                     # clicking an annotation leaves traces alone
    v.end_mode()
    v.undo()                                         # deleted line comes back
    assert len(v.notes) == 2
    v.undo()                                         # the duplicate goes
    v.undo()                                         # the stretch is undone
    assert len(v.notes) == 1 and abs(v.notes[0].pts[1][0] - 4e-4) < 1e-5
    v.redo()
    assert abs(v.notes[0].pts[1][0] - 8e-4) < 1e-5
    win.close()


def test_pick_new_device_lists_both_libraries(qapp):
    """Right-click on an npn/zener/pmos: Pick New Transistor/Diode/MOSFET lists LTspice's
    standard.* parts (when extracted) and TuxSpice's own, filtered to the symbol."""
    from pyltspice.ui import dialogs
    npn = dialogs.DevicePicker(None, *dialogs.DEVICE_SYMBOLS["npn"], current="BC337")
    names = {r["name"] for r in npn.shown}
    assert "BC337" in names and "BC327" not in names and npn.selected() == "BC337"
    npn.part.setText("tip")
    npn._fill()
    assert {r["name"] for r in npn.shown} >= {"TIP31C", "TIP41C"} and npn.selected().startswith("TIP")
    pnp = dialogs.DevicePicker(None, *dialogs.DEVICE_SYMBOLS["pnp"])
    pnp.part.setText("germanium")
    pnp._fill()
    assert {"AC128", "OC71"} <= {r["name"] for r in pnp.shown} and all(r["type"] == "germanium" for r in pnp.shown)
    _dispose(pnp)
    zen = dialogs.DevicePicker(None, *dialogs.DEVICE_SYMBOLS["zener"])
    assert zen.shown and all(r["type"].lower() == "zener" for r in zen.shown)
    pm = dialogs.DevicePicker(None, *dialogs.DEVICE_SYMBOLS["pmos"])
    assert {"IRF9540", "BS250"} <= {r["name"] for r in pm.shown} and all(r["channel"] == "P" for r in pm.shown)
    inst = asc.SymbolInst("npn", 0, 0, "R0", {}, {"InstName": "Q1", "Value": "NPN"})
    ed = dialogs.AttributeEditor(None, inst, None, pick=dialogs.DEVICE_SYMBOLS["npn"])
    ed.table.item(ed.KEYS.index("Value"), 1).setText("2N5551")
    ed.apply()
    assert inst.attrs["Value"] == "2N5551"
    for d in (npn, zen, pm, ed):
        _dispose(d)


@needs_lib
def test_ortho_stretch_and_cut_angled_wires(qapp):
    """Settings > Schematic: Ortho stretch keeps a stretched horizontal wire horizontal with an
    elbow (Ctrl flips it); Cut angled wires splits an angled wire where Stretch clicks it."""
    from pyltspice.ui.main_window import MainWindow
    from pyltspice.ui.settings_dialog import put
    win = MainWindow()
    win.resize(1000, 800)
    win.show()
    win.new_schematic()
    sw = win.schematic()
    view = sw.view
    view.resetTransform()
    view.centerOn(0, 0)
    sch = sw.doc.sch
    sch.items += [asc.Wire(-160, 0, 0, 0), asc.Wire(96, 96, 224, 224)]
    sw.doc.commit("setup")
    qapp.processEvents()
    try:
        put("drafting/ortho_stretch", True)
        sw.start_move("drag")
        for fn, (x, y) in ((QTest.mouseMove, (32, 32)), (QTest.mousePress, (32, 32)),
                           (QTest.mouseMove, (-16, -16)), (QTest.mouseRelease, (-16, -16))):
            args = (view.viewport(),) if fn is QTest.mouseMove else (view.viewport(), Qt.LeftButton, Qt.NoModifier)
            fn(*args, view.mapFromScene(x, y))
        _click(view, -48, -80)                 # the box held the right end: 32 left, 64 up...
        segs = sorted((w.x1, w.y1, w.x2, w.y2) for w in sch.wires if w.y1 <= 0 and w.y2 <= 0)
        assert segs == [(-160, 0, -32, 0), (-32, 0, -32, -64)]      # ...through an elbow
        _click(view, 0, 0, Qt.RightButton)

        put("drafting/cut_angled", True)
        sw.start_move("drag")
        _click(view, 160, 160)                 # middle of the angled wire
        _click(view, 160, 64)
        angled = sorted((w.x1, w.y1, w.x2, w.y2) for w in sch.wires if w.y1 > 0 or w.y2 > 0)
        assert angled == [(96, 96, 160, 64), (160, 64, 224, 224)]
        _click(view, 0, 0, Qt.RightButton)
    finally:
        put("drafting/ortho_stretch", False)
        put("drafting/cut_angled", True)
    sw.doc.undo.setClean()
    win.close()


def test_pin_shorts_and_subfolder_symbols(tmp_path):
    from pyltspice.model import edit, library
    from pyltspice.model.netlist import connectivity
    # a wire straight across a resistor's pins: cut (the default) or kept as a short
    lib = library.default_library()
    if lib.get("res") is None:
        pytest.skip("needs the LTspice library")
    sch = asc.parse_asc("Version 4\nSHEET 1 880 680\nWIRE 16 0 16 128\nSYMBOL res 0 0 R0\nSYMATTR InstName R1\n")
    edit.cleanup_wires(sch, lib)
    assert [(w.y1, w.y2) for w in sch.wires] == [(0, 16), (96, 128)]
    try:
        edit.ALLOW_PIN_SHORTS = True
        sch = asc.parse_asc("Version 4\nSHEET 1 880 680\nWIRE 16 0 16 128\nSYMBOL res 0 0 R0\nSYMATTR InstName R1\n")
        edit.cleanup_wires(sch, lib)
        assert (16, 96) in [(w.y1, w.y2) for w in sch.wires]
        assert len({connectivity(sch, lib).net_at(16, 16), connectivity(sch, lib).net_at(16, 96)}) == 1
    finally:
        edit.ALLOW_PIN_SHORTS = False
    # LTspice also finds symbols in the schematic's subfolders, unless told not to
    (tmp_path / "parts" / "deep").mkdir(parents=True)
    (tmp_path / ".hidden").mkdir()
    sch_path = tmp_path / "top.asc"
    assert library.schematic_dirs(sch_path) == [tmp_path, tmp_path / "parts", tmp_path / "parts" / "deep"]
    try:
        library.SEARCH_SUBDIRS = False
        assert library.schematic_dirs(sch_path) == [tmp_path]
    finally:
        library.SEARCH_SUBDIRS = True


def _rgba(img):
    import numpy as np
    from PySide6.QtGui import QImage
    img = (img if hasattr(img, "constBits") else img.toImage()).convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4).copy()
    return a[..., 2::-1].astype(float) / 255, a[..., 3]         # copied: img's buffer dies with it


def _ink_failures(dark, light, bg):
    """Fraction of an icon's ink (pixels that are dark or coloured in its light-toolbar version:
    outlines, glyphs, accents) with less than 3:1 contrast against bg on the dark toolbar.
    White fills are left out: on a dark toolbar they are meant to sink in."""
    import numpy as np
    from pyltspice.ui.appearance import luminance
    lin = lambda c: np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4) @ [0.2126, 0.7152, 0.0722]
    (rgb_l, alpha), (rgb_d, _) = _rgba(light), _rgba(dark)
    sat = rgb_l.max(-1) - rgb_l.min(-1)
    ink = (alpha > 200) & ((lin(rgb_l) < 0.2) | (sat > 0.3))
    y, yb = lin(rgb_d), luminance(bg)
    ratio = (np.maximum(y, yb) + 0.05) / (np.minimum(y, yb) + 0.05)
    return float((ink & (ratio < 3)).sum()) / max(1, ink.sum())


def test_dark_theme_icons_readable_and_restorable(qapp):
    """On a dark palette (Settings > Application theme, a dark GTK theme, or the desktop's dark
    preference) toolbar icons are lightened until they read against the toolbar; switching
    back restores the light look exactly."""
    from PySide6.QtGui import QColor, QPalette
    from pyltspice.ui import appearance, icons
    from pyltspice.ui.main_window import MainWindow
    # the transform: black and navy strokes become light, light backgrounds are left alone
    pm = icons.icon("resistor").pixmap(32, 32)
    dark_bg = QColor("#2b2b2b")
    assert appearance.adapt_icon(pm, QColor("#efefef")).toImage() == pm.toImage()
    assert _ink_failures(appearance.adapt_icon(pm, dark_bg), pm, dark_bg) < 0.02
    win = MainWindow()
    win.show()
    light_bg = qapp.palette().color(QPalette.Window)
    shown = {k: a for k, a in win.actions.items() if a in win.toolbar.actions()}     # what sits on the toolbar
    before = {k: a.icon().pixmap(32, 32).toImage() for k, a in shown.items()}
    try:
        appearance.apply(qapp, "Dark")
        qapp.processEvents()
        assert appearance.is_dark()
        bg = qapp.palette().color(QPalette.Window)
        bad = {k: f for k, a in shown.items()
               if a.isEnabled() and (f := _ink_failures(a.icon().pixmap(32, 32), before[k], bg)) > 0.05}
        assert not bad, bad
        assert "rgba(" in win.toolbar.styleSheet()
    finally:
        appearance.apply(qapp, "System")
        qapp.processEvents()
    assert qapp.palette().color(QPalette.Window) == light_bg
    after = {k: a.icon().pixmap(32, 32).toImage() for k, a in shown.items()}
    assert after == before
    win.close()


def test_paste_brings_symbols_from_the_source_folder(qapp, tmp_path, monkeypatch):
    """A part whose symbol sits next to its schematic, pasted into a schematic elsewhere:
    untitled targets search the source folder, saved ones get the .asy copied next to them."""
    from PySide6.QtWidgets import QMessageBox
    from pyltspice.ui import tools
    from pyltspice.ui.main_window import MainWindow
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir(), dst.mkdir()
    (src / "widget.asy").write_text("Version 4\nSymbolType CELL\nRECTANGLE Normal -16 -16 16 16\n"
                                    "SYMATTR Prefix X\nPIN -16 0 LEFT 8\nPINATTR PinName a\nPINATTR SpiceOrder 1\n")
    part = asc.SymbolInst("widget", 0, 0, "R0", {}, {"InstName": "U1"})
    tools.copy_to_clipboard([part], [src])
    win = MainWindow()
    win.show()
    win.new_schematic()
    sw = win.schematic()
    sw.start_paste()                                           # untitled: search src as well
    assert src in sw.doc.local_dirs and sw.doc.lib.find("widget", sw.doc.local_dirs) is not None
    sw.set_tool(None)
    sw.doc.undo.setClean()
    (dst / "b.asc").write_text("Version 4\nSHEET 1 880 680\n")
    win.open_file(str(dst / "b.asc"))
    sw = win.schematic()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    sw.start_paste()
    assert (dst / "widget.asy").exists() and sw.doc.lib.get("widget", sw.doc.local_dirs) is not None
    sw.set_tool(None)
    for s in win.mdi.subWindowList():
        s.widget().doc.undo.setClean()
    win.close()


def test_annotations_saved_with_plot_settings(qapp, tmp_path):
    """Save Plot Settings keeps the notes (in <name>.plt.notes, leaving the .plt LTspice's own);
    reloading the settings brings them back in their panes."""
    from pyltspice.sim import pltfile
    from pyltspice.ui.main_window import MainWindow, PlotWindow
    from pyltspice.ui.waveform import Note
    win = MainWindow()
    win.show()
    v = win._new_viewer(_tran_plot(), "t.raw")
    v.add_trace("V(a)")
    v.add_pane()
    v.add_trace("V(b)", v.panes[1])
    pw = PlotWindow(v, None)
    win._add_window(pw, "t.raw")
    v.add_note(Note("arrow", v.panes[1], [(1e-4, 0.5), (2e-4, 0.9)], "#ff0000"))
    v._add_text(v.panes[0], 3e-4, 0.2, "peak")
    plt = tmp_path / "t.plt"
    v.plt_path = plt
    win.save_plot_settings(pw)
    assert pltfile.read_plt(plt)["transient analysis"] == [["V(a)"], ["V(b)"]]
    assert "notes" not in plt.read_text().lower() and len(pltfile.read_notes(plt)) == 2
    v.load_notes([])
    assert not v.notes
    win._load_plt(pw, plt)
    kinds = sorted((n.kind, v.panes.index(n.pane), n.text) for n in v.notes)
    assert kinds == [("arrow", 1, ""), ("text", 0, "peak")]
    assert v.notes[0].items                                      # drawn again
    v.load_notes([])
    win.save_plot_settings(pw)
    assert not pltfile.notes_path(plt).exists()                  # no notes: no sidecar left behind
    win.close()


def test_stats_box_cheat_sheet_and_port_shapes(qapp):
    """Ctrl+click on a trace label: average/RMS over what's on screen; the shortcut cheat sheet
    is an always-on-top window; I/O ports point in, out or both ways."""
    import numpy as np
    from PySide6.QtCore import QPointF
    from pyltspice.sim.rawfile import Plot, Variable
    from pyltspice.ui.items import FlagItem
    from pyltspice.ui.main_window import MainWindow, PlotWindow
    t = np.linspace(0, 2e-3, 4001)
    plot = Plot(title="t", plotname="Transient Analysis", flags={"real"},
                variables=[Variable(0, "time", "time"), Variable(1, "V(s)", "voltage")],
                data=np.array([t, 1 + 2 * np.sin(2 * np.pi * 1e3 * t)]))
    win = MainWindow()
    win.show()
    v = win._new_viewer(plot, "t.raw")
    v.add_trace("V(s)")
    win._add_window(PlotWindow(v, None), "t.raw")
    pane = v.panes[0]
    pane.plot.getPlotItem().getViewBox().setXRange(0, 1e-3, padding=0)    # one period on screen
    qapp.processEvents()
    s = v._stats(pane.traces[0])
    assert abs(s["x1"] - 1e-3) < 1e-9 and abs(s["avg"] - 1) < 1e-3 and abs(s["rms"] - np.sqrt(3)) < 1e-3
    from unittest import mock
    from PySide6.QtWidgets import QLabel
    with mock.patch("PySide6.QtWidgets.QApplication.keyboardModifiers", return_value=Qt.ControlModifier):
        pane._label_clicked("0")                                 # Ctrl+click on the label
    box = v._stats_dialog
    assert box.isVisible() and "V(s)" in box.windowTitle()
    texts = [w.text() for w in box.findChildren(QLabel)]
    assert texts == ["Interval Start:", "0s", "Interval End:", "1ms", "Average:", "1V", "RMS:", "1.7321V"]
    box.close()
    win.show_shortcuts()
    sheet = win._cheat_sheet
    assert sheet.isVisible() and sheet.windowFlags() & Qt.WindowStaysOnTopHint
    sheet.close()
    win.close()
    shapes = {}
    for kind in ("In", "Out", "BiDir"):
        item = FlagItem(asc.Flag(0, 0, "port", kind), free_dir="right")    # label right of its pin
        poly = item._port_outline(item.boundingRect().adjusted(40, 0, 0, 0))
        b = poly.boundingRect()
        shapes[kind] = (poly.contains(QPointF(b.left() + 0.5, b.top() + 0.5)),
                        poly.contains(QPointF(b.right() - 0.5, b.top() + 0.5)))
    # a tip leaves that corner of the bounding box empty: In's points at the pin, Out's away
    assert shapes == {"In": (False, True), "Out": (True, False), "BiDir": (False, False)}
