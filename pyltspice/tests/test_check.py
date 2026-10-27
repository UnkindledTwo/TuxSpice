"""Circuit check before a run, and explained ngspice errors (TuxSpice extras)."""
from pyltspice.model.asc import Flag, SymbolInst, Text, Wire
from pyltspice.model.check import check_schematic
from pyltspice.sim.diagnose import explain

from .conftest import needs_lib, needs_ngspice
from .test_netlist import rc_lowpass


def _msgs(sch):
    return [(i.severity, i.message) for i in check_schematic(sch)]


@needs_lib
def test_clean_circuit_has_no_issues():
    assert _msgs(rc_lowpass()) == []


@needs_lib
def test_suffix_traps_and_placeholder_values():
    sch = rc_lowpass()
    r1, c1 = sch.symbols[1], sch.symbols[2]
    r1.attrs["Value"] = "1M"
    c1.attrs["Value"] = "10F"
    msgs = _msgs(sch)
    assert ("warning", "R1 = 1M is 1 milliohm(s)") in msgs
    assert ("warning", "C1 = 10F is 10 femtofarad(s)") in msgs
    r1.attrs["Value"], c1.attrs["Value"] = "1Meg", "700f"      # deliberate: no warning
    assert _msgs(sch) == []
    r1.attrs["Value"] = "R"                                     # never edited after placing
    assert ("error", "R1 has no value") in _msgs(sch)


@needs_lib
def test_no_ground_duplicate_names_and_source_loop():
    sch = rc_lowpass()
    sch.items[:] = [i for i in sch.items if not (isinstance(i, Flag) and i.name == "0")]
    assert ("error", "The circuit has no ground") in _msgs(sch)
    sch = rc_lowpass()
    sch.symbols[2].attrs["InstName"] = "R1"         # nets as CR1: no clash
    assert not any("named" in m for _, m in _msgs(sch))
    sch.items.append(SymbolInst("cap", 300, 0, "R0", {}, {"InstName": "R1", "Value": "1n"}))
    assert ("error", "2 parts are named R1") in _msgs(sch)
    # a second source straight across V1
    sch = rc_lowpass()
    sch.items.append(SymbolInst("voltage", -96, 0, "R0", {}, {"InstName": "V2", "Value": "1"}))
    sch.items += [Wire(-96, 16, -96, 0), Wire(-96, 0, 0, 0), Flag(-96, 96, "0")]
    issues = check_schematic(sch)
    loop = [i for i in issues if "loop" in i.message]
    assert loop and set(loop[0].parts) == {"V1", "V2"}
    sch.symbols[-1].attrs["SpiceLine"] = "Rser=0.1"             # not ideal any more
    assert not any("loop" in i.message for i in check_schematic(sch))


@needs_lib
def test_floating_node_and_open_pin():
    # C1 in series between out and a new node that only another capacitor reaches
    sch = rc_lowpass()
    sch.items.append(SymbolInst("cap", 208, 0, "R0", {}, {"InstName": "C2", "Value": "1n"}))
    sch.items.append(Wire(128, 0, 224, 0))
    issues = check_schematic(sch)
    assert any(i.message == "C2: pin 2 isn't connected to anything" for i in issues)
    sch.items.append(SymbolInst("cap", 208, 96, "R0", {}, {"InstName": "C3", "Value": "1n"}))
    sch.items += [Wire(224, 64, 224, 112), Flag(224, 160, "0")]
    issues = check_schematic(sch)
    floating = [i for i in issues if i.message.startswith("No DC path")]
    assert floating and floating[0].severity == "warning" and set(floating[0].parts) >= {"C2", "C3"}
    # a .tran with uic skips the operating point, so floating nodes are fine
    sch.items.append(Text(0, 200, "Left", 2, "!.tran 1m uic"))
    assert not any(i.message.startswith("No DC path") for i in check_schematic(sch))


@needs_lib
def test_directive_elements_count_as_connections():
    sch = rc_lowpass()
    sch.items.append(SymbolInst("res", 200, 0, "R0", {}, {"InstName": "R2", "Value": "1k"}))
    sch.items += [Wire(216, 16, 216, -32), Flag(216, -32, "x"), Wire(216, 96, 216, 128), Flag(216, 128, "0")]
    assert _msgs(sch) == []                    # labelled single-pin net: a probe point, not flagged
    sch.items.append(Text(0, 220, "Left", 2, "!C9 x 0 1n"))
    assert _msgs(sch) == []


def test_explain_ngspice_messages():
    log = ("Warning: singular matrix:  check node n003\n"
           "Warning: singular matrix:  check node v1#branch\n"
           "Error: unknown subckt: xu1 in out 0 lt9999\n"
           "warning, can't find model 'foo' from line\n"
           "doAnalyses: TRAN:  Timestep too small; time = 1.5e-06, timestep = 1.25e-19: "
           "trouble with node \"xu2.n005\"\n")
    issues = explain(log, [], "* x\nD1 a 0 FOO\n")
    by = {i.message: i for i in issues}
    assert by["Node N003 has no DC path to ground"].nets == ["n003"]
    assert by["Voltage source or inductor V1 is in a loop or shorted"].parts == ["v1"]
    assert by["XU1 uses subcircuit LT9999, which isn't defined"].parts == ["xu1"]
    assert [p.lower() for p in by["D1 uses model FOO, which isn't defined"].parts] == ["d1"]
    stall = next(i for i in issues if i.message.startswith("The simulation stalled"))
    assert "1.5e-06" in stall.message and stall.parts == ["xu2"]


@needs_ngspice
def test_explain_real_failure(tmp_path):
    from pyltspice.sim.runner import Simulator
    res = Simulator("* x\nV1 a 0 1\nX1 a 0 NOSUCH\n.op\n.end\n", tmp_path / "x").run()
    assert not res.ok
    assert [i.message for i in explain(res.log, res.errors)] == \
        ["X1 uses subcircuit NOSUCH, which isn't defined"]


@needs_lib
def test_autosave_and_recovery(qapp, tmp_path, monkeypatch):
    """A modified schematic is copied to the autosave folder, the copy goes away once saved, and
    a copy left by a dead process reopens under its original path, modified, Undo = disk."""
    import json
    from pyltspice.model import asc
    from pyltspice.ui import autosave
    from pyltspice.ui.main_window import MainWindow
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    win = MainWindow()
    win.new_schematic()
    sw = win.schematic()
    path = tmp_path / "a.asc"
    sw.doc.save(path)
    sw.doc.begin()
    sw.doc.sch.items[:] = rc_lowpass().items
    sw.doc.commit("edit")
    win.autosaver.save_all()
    copies = list(autosave.autosave_dir().glob("*.asc"))
    assert len(copies) == 1 and "SYMBOL res" in copies[0].read_text()
    assert autosave.pending() == []                  # our own process is alive: not offered
    sw.doc.save()                                    # clean again: copy removed
    assert not list(autosave.autosave_dir().glob("*"))
    # a copy left behind by a process that is gone
    d = autosave.autosave_dir()
    newer = rc_lowpass()
    newer.items.append(SymbolInst("res", 300, 0, "R0", {}, {"InstName": "R9", "Value": "1k"}))
    (d / "x.asc").write_text(newer.to_text())
    (d / "x.json").write_text(json.dumps({"original": str(path), "title": "a.asc", "time": 0, "pid": 999999999}))
    (meta, a, m), = autosave.pending()
    rec = win.recover_document(a.read_text(), meta["original"])
    assert rec.doc.path == path and rec.doc.modified and len(rec.doc.sch.symbols) == 4
    rec.doc.undo.undo()                              # back to the 3 parts saved on disk
    assert len(rec.doc.sch.symbols) == 3 and not rec.doc.modified
    for w in (sw, rec):
        w.doc.undo.setClean()
    win.close()
    assert len(asc.load_asc(path).symbols) == 3      # recovery never writes the file itself


@needs_lib
@needs_ngspice
def test_check_blocks_run_and_failure_is_explained(qapp, monkeypatch):
    """A check error asks before running (No: nothing runs); a failed run lists its explained
    errors in the Problems panel; clicking one highlights the part on the schematic."""
    from PySide6.QtWidgets import QMessageBox
    from pyltspice.ui.main_window import MainWindow
    from pyltspice.ui.problems import objects_for
    asked = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    win = MainWindow()
    win.new_schematic()
    sw = win.schematic()
    sw.doc.sch.items[:] = rc_lowpass().items
    sw.doc.sch.symbols[1].attrs["Value"] = "R"                   # never given a value
    sw.doc.scene.rebuild()
    started, why = win.run_simulation()
    assert not started and why == "stopped by the circuit check" and "R1 has no value" in asked[0]
    assert win.problems.list.count() == 1
    iss = win.problems.issues[0]
    assert objects_for(sw, iss) == [sw.doc.sch.symbols[1]]
    # a run that fails in ngspice: a subcircuit nobody defined
    sw.doc.sch.symbols[1].attrs["Value"] = "1k"
    sw.doc.sch.items.append(Text(0, 300, "Left", 2, "!X9 out 0 NOSUCH"))
    sw.doc.scene.rebuild()
    started, _ = win.run_simulation()
    assert started
    while win.sim_thread is not None:
        qapp.processEvents()
    msgs = [i.message for i in win.problems.issues]
    assert "X9 uses subcircuit NOSUCH, which isn't defined" in msgs
    win.problems.list.setCurrentRow(0)
    sw.doc.undo.setClean()
    win.close()
