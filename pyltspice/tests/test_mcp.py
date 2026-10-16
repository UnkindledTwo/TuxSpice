"""MCP server: LTspice-compatible tools, headless and attached to a TuxSpice window."""
import json
import sqlite3
import threading
import time

import numpy as np
import pytest

from pyltspice.mcp import clients, tools
from pyltspice.mcp.bridge import Session
from pyltspice.sim.rawfile import Plot, Variable

from .conftest import needs_lib, needs_ngspice

RC_ASC = """Version 4
SHEET 1 880 680
WIRE 112 96 32 96
WIRE 224 96 192 96
WIRE 32 128 32 96
WIRE 224 128 224 96
WIRE 32 224 32 208
WIRE 224 224 224 192
FLAG 32 224 0
FLAG 224 224 0
FLAG 224 96 out
SYMBOL voltage 32 112 R0
SYMATTR InstName V1
SYMATTR Value PULSE(0 1 0 1n 1n 10m 20m)
SYMBOL res 208 80 R90
WINDOW 0 0 56 VBottom 2
WINDOW 3 32 56 VTop 2
SYMATTR InstName R1
SYMATTR Value 1k
SYMBOL cap 208 128 R0
SYMATTR InstName C1
SYMATTR Value 1u
TEXT 32 280 Left 2 !.tran 4m
"""


def _call(session, name, **args):
    r = session.call(name, args)
    text = r["content"][0]["text"]
    if r.get("isError"):
        raise tools.ToolError(text)
    return json.loads(text)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    return tmp_path


def test_tool_list_matches_ltspice_bridge():
    """Same 17 tools as LTspice 26.1's ltspice-mcp-bridge, same required arguments."""
    names = {t["name"]: t["inputSchema"].get("required", []) for t in tools.tool_list()}
    assert names == {
        "list_open_designs": [], "open_design": ["path"], "get_active_design_path": [], "get_spice_log": [],
        "get_design_content": [], "get_schematic_netlist": [], "start_simulation": [],
        "is_simulation_running": [], "set_design_content": ["path", "text"], "bring_to_front": [],
        "get_raw_info": [], "read_raw_waveforms": ["signals"], "export_raw_waveforms": ["signals", "db_path"],
        "list_ltspice_reference_docs": [], "get_ltspice_reference": ["name"], "status": [], "attach": [],
        "start_headless": []}


def test_protocol_handshake_and_errors(runtime):
    out = []
    s = Session(out.append, attach=False)
    r = s.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-03-26", "capabilities": {}}})
    assert r["result"]["protocolVersion"] == "2025-03-26"
    assert r["result"]["capabilities"]["tools"]["listChanged"]
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert s.handle({"jsonrpc": "2.0", "id": 2, "method": "prompts/list"})["error"]["code"] == -32601
    r = s.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "get_design_content", "arguments": {}}})
    assert r["result"]["isError"]
    notes = s.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/read",
                      "params": {"uri": "ltspice-ref:///TUXSPICE-NOTES.md"}})
    assert "ngspice" in notes["result"]["contents"][0]["text"]


def _stepped_ac_plot():
    f = np.array([1.0, 10, 100, 1, 10, 100])
    v = np.array([1, 0.5j, 0.1, 2, 1j, 0.2], complex)
    p = Plot(title="t", plotname="AC Analysis", flags={"complex"},
             variables=[Variable(0, "frequency", "frequency"), Variable(1, "v(out)", "voltage")],
             data=np.array([f + 0j, v]), step_bounds=[(0, 3), (3, 6)], step_labels=["R=1k", "R=2k"])
    return p


def test_raw_tools_steps_complex_and_sqlite(tmp_path):
    p = _stepped_ac_plot()
    info = tools.raw_info("x.raw", [p])
    assert info["signals"] == ["V(out)"] and info["stepped"] == "true" and info["n_steps"] == "2"
    # LTspice: index as a string, parameter names lowercased with numeric values
    assert info["steps"][1] == {"index": "1", "params": {"r": 2000.0}, "n_points": "3"}
    r = tools.read_raw("x.raw", [p], {"signals": ["V(out)", "V(x)"], "steps": [1], "x_min": 5,
                                      "complex_format": "polar"})
    assert r["unknown_signals"] == ["V(x)"]
    (step,) = r["steps"]
    assert step["data"]["x"] == [10.0, 100.0]
    assert step["data"]["signals"]["V(out)"]["mag_db20"] == pytest.approx([0.0, 20 * np.log10(0.2)])
    assert step["data"]["signals"]["V(out)"]["phase_deg"][0] == pytest.approx(90)
    with pytest.raises(tools.ToolError, match=r"needs 9 values \(3 points x 3 series\) but max_values is 5"):
        tools.read_raw("x.raw", [p], {"signals": ["V(out)"], "max_values": 5, "steps": [0]})
    db = tmp_path / "w.db"
    summary = tools.export_raw("x.raw", [p], {"signals": ["V(out)"], "db_path": str(db)})
    assert summary["n_rows"] == "6"
    con = sqlite3.connect(db)
    cols = [c[1] for c in con.execute("PRAGMA table_info(samples)")]
    assert cols == ["step", "point", "frequency", "V(out)|real", "V(out)|imag"]
    assert con.execute("SELECT value FROM step_params WHERE step=1").fetchone() == (2000.0,)
    assert [r[0] for r in con.execute("SELECT name FROM sqlite_master")] == [
        "run", "steps", "step_params", "signals", "samples", "sqlite_autoindex_samples_1"]
    con.close()
    with pytest.raises(tools.ToolError, match="no_overwrite"):
        tools.export_raw("x.raw", [p], {"signals": ["V(out)"], "db_path": str(db), "no_overwrite": True})


@needs_lib
@needs_ngspice
def test_headless_open_edit_simulate_read(runtime):
    asc = runtime / "rc.asc"
    asc.write_text(RC_ASC, encoding="latin-1")
    s = Session(lambda m: None, attach=False)
    assert _call(s, "get_active_design_path") == {"path": "", "type": ""}
    r = _call(s, "open_design", path=str(asc))
    assert r["type"] == "schematic" and r["already_open"] == "false"
    with pytest.raises(tools.ToolError, match="Version 4"):
        _call(s, "set_design_content", path=str(asc), text="not a schematic")
    assert _call(s, "set_design_content", path=str(asc), text=RC_ASC) == {"status": "ok", "unchanged": "true"}
    assert _call(s, "set_design_content", path=str(asc), text=RC_ASC.replace("Value 1k", "Value 2k")) == \
        {"message": "", "status": "ok", "unchanged": "false"}
    with pytest.raises(tools.ToolError, match="^file not found$"):
        _call(s, "open_design", path="rc.asc")                  # LTspice takes absolute paths only
    with pytest.raises(tools.ToolError, match="^no active raw waveform window"):
        _call(s, "get_raw_info")
    assert "R1 out N001 2k" in _call(s, "get_schematic_netlist")["text"]
    assert "Value 2k" in asc.read_text()                     # headless edits go to disk
    assert _call(s, "start_simulation") == {"message": "", "path": str(asc.resolve()), "result": "true"}
    for _ in range(300):
        if _call(s, "is_simulation_running")["result"] == "false":
            break
        time.sleep(0.05)
    assert "Simulation running" not in _call(s, "get_spice_log")["text"]
    info = _call(s, "get_raw_info")
    assert "V(out)" in info["signals"] and info["analysis"] == "Transient Analysis"
    assert info["path"] == str(asc.resolve().with_suffix(".raw")) and "n_steps" not in info
    r = _call(s, "read_raw_waveforms", signals=["V(out)"], x_min=1.99e-3, x_max=2.01e-3)
    v = r["data"]["signals"]["V(out)"]["values"]
    assert v and abs(v[0] - (1 - np.exp(-1))) < 0.02           # tau = 2k * 1u = 2 ms
    assert s.committed


def test_client_configuration_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    cc = next(c for c in clients.CLIENTS if c.key == "claude-code")
    vs = next(c for c in clients.CLIENTS if c.key == "vscode")
    (tmp_path / ".claude.json").write_text(json.dumps({"keep": 1, "mcpServers": {"other": {"command": "x"}}}))
    assert cc.status() == "Not configured"
    cc.configure()
    data = json.loads((tmp_path / ".claude.json").read_text())
    assert data["keep"] == 1 and "other" in data["mcpServers"]
    assert data["mcpServers"]["tuxspice"]["args"] == ["-m", "pyltspice.mcp"]
    assert cc.status() == "Configured"
    data["mcpServers"]["tuxspice"]["command"] = "/gone/python"
    (tmp_path / ".claude.json").write_text(json.dumps(data))
    assert cc.status() == "Stale"
    assert cc.remove() and "tuxspice" not in json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]
    vs.configure("workspace", tmp_path / "proj")
    ws = json.loads((tmp_path / "proj/.vscode/mcp.json").read_text())
    assert ws["servers"]["tuxspice"]["type"] == "stdio"


@needs_lib
@needs_ngspice
def test_gui_attached_edit_is_undoable(qapp, runtime):
    from pyltspice.ui.main_window import MainWindow
    asc = runtime / "rc.asc"
    asc.write_text(RC_ASC, encoding="latin-1")
    win = MainWindow()
    win.show()
    win.open_file(asc)
    assert win.start_mcp_host()
    sw = win.schematic()
    replies = {}

    def bridge():
        s = Session(lambda m: None)
        replies["mode"] = s.mode()
        replies["open"] = _call(s, "list_open_designs")
        _call(s, "set_design_content", path=str(asc), text=RC_ASC.replace("Value 1k", "Value 3k"))
        replies["netlist"] = _call(s, "get_schematic_netlist")["text"]
        replies["sim"] = _call(s, "start_simulation")
        for _ in range(300):
            if _call(s, "is_simulation_running")["result"] == "false":
                break
            time.sleep(0.05)
        try:                     # as in LTspice: without a path only the active waveform window counts
            _call(s, "get_raw_info")
            replies["no_window"] = False
        except tools.ToolError as e:
            replies["no_window"] = str(e).startswith("no active raw waveform window")
        replies["info"] = _call(s, "get_raw_info", path=str(asc))
        s.conn.close()

    t = threading.Thread(target=bridge)
    t.start()
    deadline = time.time() + 60
    while t.is_alive() and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    t.join(1)
    assert replies["mode"] == "gui-attached"
    assert replies["open"]["paths"] == str(asc.resolve())
    assert "R1 out N001 3k" in replies["netlist"]
    assert replies["sim"]["result"] == "true" and "V(out)" in replies["info"]["signals"]
    assert replies["no_window"]
    assert "Value 1k" in asc.read_text()                       # not saved: the user decides
    assert sw.doc.undo.undoText() == "AI Assistant Edit"
    sw.doc.undo.undo()
    assert [s.attrs.get("Value") for s in sw.doc.sch.symbols if s.name == "R1"] == ["1k"]
    win.mcp_host.stop()
    sw.doc.undo.setClean()
    win.close()


def test_annotations_and_reply_format():
    """Annotations and the compact, key-sorted JSON replies of LTspice's bridge."""
    ann = {t["name"]: t["annotations"] for t in tools.tool_list()}
    assert ann["set_design_content"] == {"title": "Set Design Content", "readOnlyHint": False,
                                         "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}
    assert ann["status"] == {"title": "Bridge: session status", "readOnlyHint": True}
    r = tools.run_tool(None, "get_ltspice_reference", {})
    assert r == {"content": [{"type": "text", "text": "Missing reference document name"}], "isError": True}
    ok = tools.run_tool(None, "get_ltspice_reference", {"name": "TUXSPICE-NOTES.md"})
    assert "isError" not in ok and ok["content"][0]["text"].startswith('{"docname":"TUXSPICE-NOTES.md","text":')
