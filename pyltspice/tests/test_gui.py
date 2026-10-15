from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from pyltspice.model import asc

from .conftest import needs_lib


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

    sw.start_wire()
    _click(view, 16, 96)                       # from the bottom pin...
    _click(view, 96, 160)                      # ...L-route to a free point
    _click(view, 0, 0, Qt.RightButton)
    _click(view, 0, 0, Qt.RightButton)
    assert len(sw.doc.sch.wires) == 2

    sw.start_delete()
    _click(view, 16, 50)                       # on the resistor body
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
