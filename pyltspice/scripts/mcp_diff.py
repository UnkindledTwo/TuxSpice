#!/usr/bin/env python3
"""Differential MCP test: the same scripted session against LTspice's ltspice-mcp-bridge (under Wine)
and TuxSpice's pyltspice-mcp, then a field-by-field comparison of the replies.

    mcp_diff.py run tux OUT.json [--dir DIR]
    mcp_diff.py run lt  OUT.json --wineprefix PREFIX [--display :5] [--dir DIR]
    mcp_diff.py compare LT.json TUX.json

'run' copies four small test designs into DIR (default ./mcp_diff_<server>) and drives every tool,
including error cases. For 'lt', LTspice must already be running on DISPLAY in that Wine prefix
(the bridge attaches to it); see CLAUDE.md "Comparing with LTspice under Wine". To compare
TuxSpice's GUI-attached mode, start pyltspice first with the same XDG_RUNTIME_DIR as this script.
Expected differences: 'precision' (ngspice data is double), point counts (different time steps),
ping (TuxSpice implements it, as MCP requires) and the product name in attach errors.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

RC = """Version 4
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
SYMATTR Value {V}
SYMBOL res 208 80 R90
WINDOW 0 0 56 VBottom 2
WINDOW 3 32 56 VTop 2
SYMATTR InstName R1
SYMATTR Value {R}
SYMBOL cap 208 128 R0
SYMATTR InstName C1
SYMATTR Value 1µ
"""


def make_designs(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    rc = RC.replace("{V}", "PULSE(0 1 0 1n 1n 2m 4m)").replace("{R}", "1k") + "TEXT 32 280 Left 2 !.tran 8m\n"
    ac = (RC.replace("{V}", "AC 1") + "TEXT 32 280 Left 2 !.ac dec 5 10 100k\n"
          "TEXT 32 320 Left 2 !.step param R list 1k 2k\n")
    (d / "rc.asc").write_bytes(rc.replace("\n", "\r\n").encode("latin-1"))
    (d / "ac.asc").write_bytes(ac.replace("\n", "\r\n").encode("latin-1"))
    (d / "net.cir").write_text("* rc net\nV1 in 0 PULSE(0 1 0 1n 1n 2m 4m)\nR1 in out 1k\nC1 out 0 1u\n"
                               ".tran 8m\n.end\n")
    (d / "notes.txt").write_text("x\n")


def run(which, out, D, wineprefix=None, display=":5"):
    if which == "lt":
        argv = ["wine", r"C:\Program Files\ADI\LTspice\ltspice-mcp-bridge.exe"]
        env = dict(os.environ, DISPLAY=display, WINEPREFIX=wineprefix, WINEDEBUG="-all")
        P = lambda name: "Z:" + (D + "/" + name).replace("/", "\\")   # noqa: E731
    else:
        argv = [sys.executable, "-m", "pyltspice.mcp"]
        env = dict(os.environ)
        P = lambda name: D + "/" + name                                  # noqa: E731
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, env=env)
    log, nid = [], [0]

    def send(method, params=None, label=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            nid[0] += 1
            msg["id"] = nid[0]
        print(">>", label or method, file=sys.stderr, flush=True)
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        if notify:
            return None
        notes = []
        while True:
            line = proc.stdout.readline()
            if not line:
                r = {"EOF": True}
                break
            r = json.loads(line)
            if r.get("id") == msg["id"]:
                break
            notes.append(r)
        lab = label or method
        while any(e["label"] == lab for e in log):
            lab += "+"
        log.append({"label": lab, "request": msg, "response": r, "notifications": notes})
        json.dump(log, open(out, "w"), indent=1)
        return r

    def tool(label, _name, **args):
        return send("tools/call", {"name": _name, "arguments": args}, label)

    def wait(path=None):
        for _ in range(200):
            a = {"path": path} if path else {}
            r = send("tools/call", {"name": "is_simulation_running", "arguments": a}, "_poll")
            log.pop()
            try:
                if json.loads(r["result"]["content"][0]["text"]).get("result") == "false":
                    return
            except Exception:  # noqa: BLE001
                return
            time.sleep(0.3)

    send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "diff", "version": "1"}})
    send("notifications/initialized", notify=True)
    send("initialize", {"protocolVersion": "1999-01-01", "capabilities": {}, "clientInfo": {"name": "d", "version": "1"}},
         "initialize_again_old_version")
    send("ping")
    send("tools/list")
    send("resources/list", None, "resources/list_start")
    send("prompts/list")
    send("bogus/method")
    tool("unknown_tool", "no_such_tool")
    tool("open_missing_path_arg", "open_design")
    tool("open_nonexistent", "open_design", path=P("missing.asc"))
    tool("open_bad_ext", "open_design", path=P("notes.txt"))
    tool("open_rc", "open_design", path=P("rc.asc"))
    tool("open_rc_again", "open_design", path=P("rc.asc"))
    tool("open_ac", "open_design", path=P("ac.asc"))
    tool("open_net", "open_design", path=P("net.cir"))
    tool("list_open", "list_open_designs")
    tool("active", "get_active_design_path")
    tool("content_active_net", "get_design_content")
    tool("content_rc", "get_design_content", path=P("rc.asc"))
    tool("content_not_open", "get_design_content", path=P("missing.asc"))
    tool("netlist_ac", "get_schematic_netlist", path=P("ac.asc"))
    tool("netlist_of_netlist", "get_schematic_netlist", path=P("net.cir"))
    tool("log_before_sim", "get_spice_log", path=P("ac.asc"))
    tool("running_idle", "is_simulation_running")
    tool("sim_ac", "start_simulation", path=P("ac.asc"))
    wait()
    tool("running_after", "is_simulation_running", path=P("ac.asc"))
    tool("log_ac", "get_spice_log", path=P("ac.asc"))
    tool("log_file", "get_spice_log", path=P("ac.log"))
    tool("info_ac", "get_raw_info", path=P("ac.asc"))
    tool("read_ac_cart", "read_raw_waveforms", path=P("ac.asc"), signals=["V(out)"], steps=[1], x_min=100, x_max=1000)
    tool("read_ac_polar", "read_raw_waveforms", path=P("ac.asc"), signals=["V(out)", "I(R1)"], complex_format="polar",
         x_max=20)
    tool("read_ac_all_steps", "read_raw_waveforms", path=P("ac.asc"), signals=["V(out)"], x_max=20)
    tool("read_too_big", "read_raw_waveforms", path=P("ac.asc"), signals=["V(out)"], max_values=10)
    tool("read_unknown_only", "read_raw_waveforms", path=P("ac.asc"), signals=["V(nope)"])
    tool("read_no_signals", "read_raw_waveforms", path=P("ac.asc"), signals=[])
    tool("read_bad_step", "read_raw_waveforms", path=P("ac.asc"), signals=["V(out)"], steps=[7])
    tool("read_empty_window", "read_raw_waveforms", path=P("ac.asc"), signals=["V(out)"], x_min=1e9)
    tool("read_x_signal", "read_raw_waveforms", path=P("ac.asc"), signals=["frequency", "V(out)"], x_max=12)
    for f in ("ac.db",):
        try:
            os.unlink(D + "/" + which + "_" + f)
        except OSError:
            pass
    tool("export_ac", "export_raw_waveforms", path=P("ac.asc"), signals=["V(out)", "V(nope)"],
         db_path=P(which + "_ac.db"))
    tool("export_no_overwrite", "export_raw_waveforms", path=P("ac.asc"), signals=["V(out)"],
         db_path=P(which + "_ac.db"), no_overwrite=True)
    tool("export_polar", "export_raw_waveforms", path=P("ac.asc"), signals=["V(out)"], complex_format="polar",
         db_path=P(which + "_acp.db"), steps=[0])
    tool("sim_rc", "start_simulation", path=P("rc.asc"))
    wait()
    tool("info_rc", "get_raw_info", path=P("rc.asc"))
    tool("info_rc_rawfile", "get_raw_info", path=P("rc.raw"))
    tool("read_rc", "read_raw_waveforms", path=P("rc.asc"), signals=["V(out)", "I(C1)"], x_min=0.002, x_max=0.00201)
    tool("export_rc", "export_raw_waveforms", path=P("rc.asc"), signals=["V(out)"], db_path=P(which + "_rc.db"),
         x_max=0.0001)
    tool("sim_net", "start_simulation", path=P("net.cir"))
    wait()
    tool("log_net", "get_spice_log", path=P("net.cir"))
    tool("info_net", "get_raw_info", path=P("net.cir"))
    txt = open(D + "/rc.asc", encoding="latin-1").read().replace("SYMATTR Value 1k", "SYMATTR Value 2k")
    tool("set_rc", "set_design_content", path=P("rc.asc"), text=txt)
    tool("content_rc_after_set", "get_design_content", path=P("rc.asc"))
    tool("netlist_rc_after_set", "get_schematic_netlist", path=P("rc.asc"))
    if which != "lt":           # LTspice 26.1.1 crashes on this one
        tool("set_garbage", "set_design_content", path=P("ac.asc"), text="garbage text")
    tool("content_ac_after_garbage", "get_design_content", path=P("ac.asc"))
    tool("set_not_open", "set_design_content", path=P("missing.asc"), text="Version 4\n")
    tool("set_net", "set_design_content", path=P("net.cir"), text=open(D + "/net.cir").read().replace("1k", "3k"))
    tool("set_missing_text", "set_design_content", path=P("net.cir"))
    tool("front_rc", "bring_to_front", path=P("rc.asc"))
    tool("front", "bring_to_front")
    tool("front_missing", "bring_to_front", path=P("missing.asc"))
    tool("active_after_front", "get_active_design_path")
    tool("docs", "list_ltspice_reference_docs")
    tool("doc_schematic", "get_ltspice_reference", name="SCHEMATIC-REFERENCE.md")
    tool("doc_readme", "get_ltspice_reference", name="README.md")
    tool("doc_bad", "get_ltspice_reference", name="nope.md")
    tool("doc_noarg", "get_ltspice_reference")
    send("resources/list", None, "resources/list_end")
    send("resources/read", {"uri": "ltspice-ref:///MEAS-REFERENCE.md"}, "res_read_ref")
    send("resources/read", {"uri": "ltspice-ref:///nope.md"}, "res_read_bad")
    r = send("resources/read", {"uri": "ltspice-design:///" + P("rc.asc")}, "res_read_design")
    tool("status", "status")
    tool("attach_bad", "attach", pid=1)
    tool("open_rc", "open_design", path=P("rc.asc"))
    tool("open_relative", "open_design", path="rc.asc")
    tool("set_same", "set_design_content", path=P("rc.asc"), text=json.loads(send("tools/call", {"name": "get_design_content", "arguments": {"path": P("rc.asc")}}, "_get")["result"]["content"][0]["text"])["text"])
    tool("log_missing_logfile", "get_spice_log", path=P("nothere.log"))
    tool("running_unknown_path", "is_simulation_running", path=P("missing.asc"))
    tool("info_no_results", "get_raw_info", path=P("net.cir"))
    tool("info_missing_raw", "get_raw_info", path=P("nothere.raw"))
    tool("sim_rc", "start_simulation", path=P("rc.asc"))
    wait()
    tool("read_polar_on_real", "read_raw_waveforms", path=P("rc.asc"), signals=["V(out)"], complex_format="polar", x_max=1e-9)
    tool("read_xmin_only", "read_raw_waveforms", path=P("rc.asc"), signals=["V(out)"], x_min=0.00799)
    tool("read_step0_unstepped", "read_raw_waveforms", path=P("rc.asc"), signals=["V(out)"], steps=[0], x_max=1e-9)
    tool("read_step1_unstepped", "read_raw_waveforms", path=P("rc.asc"), signals=["V(out)"], steps=[1])
    tool("read_case", "read_raw_waveforms", path=P("rc.asc"), signals=["v(OUT)", "TIME"], x_max=1e-9)
    tool("export_cap", "export_raw_waveforms", path=P("rc.asc"), signals=["V(out)"], db_path=P(which + "_cap.db"), max_values=5)
    tool("export_baddir", "export_raw_waveforms", path=P("rc.asc"), signals=["V(out)"], db_path=P("nodir/x.db"))
    tool("export_nodb", "export_raw_waveforms", path=P("rc.asc"), signals=["V(out)"])
    tool("info_active_noarg", "get_raw_info")
    send("resources/read", {"uri": "ltspice-design:///" + P("missing.asc")}, "res_read_design_missing")
    send("resources/read", {"uri": "bogus://x"}, "res_read_bogus")
    tool("attach_noarg", "attach")
    tool("status_after_attach", "status")
    tool("headless", "start_headless")
    tool("status_headless", "status")
    tool("active_headless", "get_active_design_path")
    tool("list_headless", "list_open_designs")
    tool("open_headless", "open_design", path=P("rc.asc"))
    tool("front_headless", "bring_to_front")
    tool("status_headless2", "status")
    proc.stdin.close()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        proc.kill()
    json.dump(log, open(out, "w"), indent=1)
    print("saved", len(log), "exchanges to", out)


def norm(s):
    """Map both sides to one spelling: Wine paths to POSIX, per-server folder and file names."""
    if isinstance(s, str):
        s = re.sub(r"Z:((?:\\[^\\\"\n ]+)+)", lambda m: m.group(1).replace("\\", "/"), s)
        s = re.sub(r"mcp_diff_(lt|tux)", "mcp_diff_X", s).replace("/lt_", "/X_").replace("/tux_", "/X_")
    return s


def payload(e):
    r = e["response"]
    if "error" in r:
        return ("rpc-error", r["error"].get("code"), norm(r["error"].get("message")))
    res = r.get("result", {})
    if "content" in res:
        text = norm(res["content"][0]["text"]) if res["content"] else ""
        try:
            body = json.loads(text)
        except ValueError:
            body = text
        return ("tool-error" if res.get("isError") else "tool-ok", body)
    return ("result", json.loads(norm(json.dumps(res))))


def diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in b:
                out.append(f"  missing in tux: {path}{k} = {json.dumps(a[k])[:120]}")
            elif k not in a:
                out.append(f"  extra in tux:   {path}{k} = {json.dumps(b[k])[:120]}")
            else:
                out += diff(a[k], b[k], f"{path}{k}.")
    elif isinstance(a, list) and isinstance(b, list):
        if a and b:
            out += diff(a[0], b[0], path + "[0].")
    elif type(a) is not type(b):
        out.append(f"  type {path}: lt {type(a).__name__} {json.dumps(a)[:80]} vs tux {type(b).__name__} "
                   f"{json.dumps(b)[:80]}")
    return out


def compare(lt_file, tux_file):
    lt = {e["label"]: e for e in json.load(open(lt_file))}
    tx = {e["label"]: e for e in json.load(open(tux_file))}
    n = 0
    for label in lt:
        if label not in tx:
            print(f"## {label}: missing in tux")
            n += 1
            continue
        pa, pb = payload(lt[label]), payload(tx[label])
        lines = []
        if pa[0] != pb[0]:
            lines.append(f"  status: lt {pa[0]} vs tux {pb[0]}")
        if "error" in pa[0] or "error" in pb[0] or isinstance(pa[-1], str):
            if pa[-1] != pb[-1]:
                lines.append(f"  lt:  {json.dumps(pa[-1])[:400]}")
                lines.append(f"  tux: {json.dumps(pb[-1])[:400]}")
        elif pa[0] == pb[0]:
            lines += diff(pa[-1], pb[-1])
        if pa[0] == pb[0] == "tool-ok" and isinstance(pa[-1], dict) and isinstance(pb[-1], dict):
            for k, v in pa[-1].items():
                if isinstance(v, str) and k in pb[-1] and pb[-1][k] != v and len(v) < 100 and k != "path":
                    lines.append(f"  value {k}: lt {v!r} vs tux {pb[-1][k]!r}")
        if lines:
            n += 1
            print(f"## {label}")
            print("\n".join(lines))
    print(f"{n} of {len(lt)} exchanges differ")


def main(argv):
    if len(argv) >= 3 and argv[0] == "compare":
        compare(argv[1], argv[2])
        return 0
    if len(argv) < 3 or argv[0] != "run" or argv[1] not in ("lt", "tux"):
        print(__doc__)
        return 2
    which, out = argv[1], argv[2]
    opt = dict(zip(argv[3::2], argv[4::2]))
    d = Path(opt.get("--dir", f"mcp_diff_{which}")).resolve()
    if d.name != f"mcp_diff_{which}":
        d = d / f"mcp_diff_{which}"
    make_designs(d)
    if which == "lt" and "--wineprefix" not in opt:
        print("--wineprefix is required for lt")
        return 2
    run(which, out, str(d), opt.get("--wineprefix"), opt.get("--display", ":5"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
