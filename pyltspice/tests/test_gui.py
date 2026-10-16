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
