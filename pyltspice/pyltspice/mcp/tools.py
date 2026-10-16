"""MCP tools: schemas and implementation over a backend (GUI or headless).

Names, arguments and reply fields follow LTspice 26.1's MCP bridge, including its habit of
returning numbers and booleans as strings ("true", "1077"), so an assistant's LTspice workflow
carries over. Replies are JSON objects sent as one text block.

A backend implements:
    list_open() -> [path]
    open_design(path) -> dict(path, type, already_open: bool, message)
    active() -> (path, type)                     ('', '') when nothing is open
    content(path|None) -> (path, text)
    set_content(path, text) -> None
    netlist(path|None) -> (path, text, message, code)
    start_sim(path|None) -> (ok: bool, message)
    sim_running(path|None) -> bool
    spice_log(path|None) -> str
    bring_to_front(path|None) -> str
    results(path|None) -> (source_path, [rawfile.Plot])
Methods raise ToolError for user-facing failures.
"""
import json
import math
import re
import sqlite3
from pathlib import Path

import numpy as np

from .. import config

NETLIST_EXT = (".net", ".cir", ".lib", ".sub", ".sp")
DESIGN_EXT = (".asc",) + NETLIST_EXT


class ToolError(Exception):
    pass


def _s(v):
    """LTspice's bridge reports scalars as strings."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def doc_type(path) -> str:
    return "schematic" if str(path).lower().endswith(".asc") else "netlist"


def norm_path(path) -> str:
    """Absolute, normalized path; '' for a relative one (LTspice's bridge only takes absolute paths)."""
    if not path:
        return ""
    p = Path(str(path)).expanduser()
    return str(p.resolve()) if p.is_absolute() else ""


# ---------------------------------------------------------------- schemas
_PATH_OPT_DESIGN = {"type": "string", "description": "Optional file path of the schematic or netlist. "
                                                     "Defaults to the active design."}
_RAW_PATH = {"type": "string", "description":
             "Optional absolute path of a '.raw' results file, or of a design file ('.asc'/'.net'/'.cir'/"
             "'.lib'/'.sub'/'.sp') whose results are resolved automatically. Defaults to the active "
             "waveform window (or the last simulation of the active design)."}
_SIGNALS = {"type": "array", "items": {"type": "string"},
            "description": "Required. Exact names of the signals, e.g. ['V(out)','I(R1)']. Must be non-empty."}
_STEPS = {"type": "array", "items": {"type": "integer"},
          "description": "Optional. Zero-based indices of the steps of a '.step'ped run, e.g. [0,4]. "
                         "Defaults to every step."}
_XMIN = {"type": "number", "description": "Optional. Lower bound of the x-axis window (seconds for transient, "
                                          "Hz for AC). Applied within each step."}
_XMAX = {"type": "number", "description": "Optional. Upper bound of the x-axis window."}
_CFMT = {"type": "string", "enum": ["polar", "cartesian"],
         "description": "Optional. For complex (AC) results: 'cartesian' (default) gives real and imaginary "
                        "parts, 'polar' gives magnitude in dB (20*log10) and phase in degrees."}


def _obj(props=None, required=None):
    o = {"type": "object", "properties": props or {}}
    if required:
        o["required"] = required
    return o


DESIGN_TOOLS = [
    ("list_open_designs", "Returns the file paths of all open schematic and netlist documents, one per line "
     "('paths').", _obj()),
    ("open_design", "Opens a schematic or netlist file from disk so the other tools can operate on it, and makes "
     "it the active design. Required for headless sessions, which start with no open documents. Returns 'path', "
     "'type' ('schematic' or 'netlist'), 'status' ('ok'), 'already_open' ('true' if the file was already open), "
     "and 'message' (warnings while loading, when present). Supported extensions: '.asc' (schematic); '.net', "
     "'.cir', '.lib', '.sub', '.sp' (netlist).",
     _obj({"path": {"type": "string", "description": "Absolute file path of the schematic or netlist to open."}},
          ["path"])),
    ("get_active_design_path", "Returns the active design's file path ('path') and its document 'type' "
     "('schematic' or 'netlist'). 'path' is empty when there is no active design.", _obj()),
    ("get_spice_log", "Returns the SPICE simulation log text for a design. If path is omitted, the active "
     "schematic or netlist is used. A '.log' file path may also be supplied to read it directly.",
     _obj({"path": {"type": "string", "description": "Optional file path of the design or a '.log' file. "
                                                     "Defaults to the active schematic or netlist."}})),
    ("get_design_content", "Returns the file path and text content ('path', 'text') of a schematic or netlist. "
     "If path is omitted, the active schematic or netlist is used. For an open document this is the "
     "in-editor content, including unsaved edits.", _obj({"path": _PATH_OPT_DESIGN})),
    ("get_schematic_netlist", "Generates and returns the SPICE netlist for a schematic. If path is omitted, the "
     "active schematic is used. Returns 'text' (the netlist, empty on error), 'message' (diagnostics) and "
     "'netlist_error_code' ('0' on success). This is TuxSpice's LTspice-dialect netlist, before the "
     "translation for ngspice.", _obj({"path": _PATH_OPT_DESIGN})),
    ("start_simulation", "Starts a simulation (ngspice, through TuxSpice's LTspice compatibility layer) for an "
     "open schematic or netlist. If path is omitted, the active design is used. Returns 'result' ('true' if the "
     "simulation was started) and 'message'. Poll is_simulation_running, then read get_spice_log.",
     _obj({"path": _PATH_OPT_DESIGN})),
    ("is_simulation_running", "Reports whether a simulation is running ('result' 'true'/'false'). Without path, "
     "the application-wide status; with a path, the status for that document.",
     _obj({"path": {"type": "string", "description": "Optional file path of the schematic or netlist."}})),
    ("set_design_content", "Replaces the content of a schematic or netlist document identified by path, with "
     "the COMPLETE new text. In a TuxSpice window the edit is an ordinary undo step and the file is not saved "
     "until the user saves it; in a headless session the file on disk is rewritten.",
     _obj({"path": {"type": "string", "description": "File path of the schematic or netlist document"},
           "text": {"type": "string", "description": "New content to replace the existing document"}},
          ["path", "text"])),
    ("bring_to_front", "Brings the TuxSpice window to the foreground. If path is supplied, the matching document "
     "window is activated.", _obj({"path": {"type": "string",
                                            "description": "Optional file path of the document to activate."}})),
    ("get_raw_info", "Lists the signals in a simulation result without numeric data. Use it to discover exact "
     "signal names before read_raw_waveforms and to size a read. Returns 'path', 'analysis', 'complex', "
     "'x_name', 'n_points' (total over all steps), 'precision', 'signals', 'stepped', 'n_steps' and, for a "
     ".step'ped run, 'steps' ([{index, params, n_points}]).", _obj({"path": _RAW_PATH})),
    ("read_raw_waveforms", "Reads numeric waveform data for the listed 'signals' (required). The x-axis is "
     "always included. Real analyses return {'x': [...], 'signals': {name: {'values': [...]}}} in 'data'; complex "
     "ones return 'real'/'imag' or 'mag_db20'/'phase_deg' arrays per 'complex_format'. A .step'ped run is "
     "returned as 'steps' ([{index, params, n_points, data}]). The reply is capped by 'max_values' (default "
     "10000, counted as points x series); an oversized request fails with an error instead of truncating, so "
     "narrow it with fewer signals, a 'steps' subset or an 'x_min'/'x_max' window.",
     _obj({"path": _RAW_PATH, "signals": _SIGNALS, "steps": _STEPS, "x_min": _XMIN, "x_max": _XMAX,
           "complex_format": _CFMT,
           "max_values": {"type": "integer", "description": "Optional. Upper bound on points x series (x-axis "
                                                            "counts as one series, each complex half as one). "
                                                            "Defaults to 10000."}},
          ["signals"])),
    ("export_raw_waveforms", "Writes waveform data to a SQLite database ('db_path', required) instead of "
     "returning it, for large data sets or SQL queries. Table 'samples' has one row per (step, point) with the "
     "x-axis column named after 'x_name' and one column per signal (complex: '|real'/'|imag' or "
     "'|mag_db20'/'|phase_deg' suffixes); tables 'signals', 'run', 'steps' and 'step_params' describe the run. "
     "An existing file is replaced unless 'no_overwrite' is true. Returns a summary.",
     _obj({"path": _RAW_PATH, "signals": _SIGNALS, "db_path": {"type": "string", "description":
           "Required. Absolute path of the SQLite file to write. The parent directory must exist."},
           "steps": _STEPS, "x_min": _XMIN, "x_max": _XMAX, "complex_format": _CFMT,
           "max_values": {"type": "integer", "description": "Optional runaway guard; -1 (default) is unlimited."},
           "no_overwrite": {"type": "boolean", "description": "Optional. Fail if 'db_path' exists."}},
          ["signals", "db_path"])),
    ("list_ltspice_reference_docs", "Lists the reference documentation available to you: the LTspice reference "
     "from the user's own LTspice installer (when extracted) plus TUXSPICE-NOTES.md, which explains where "
     "TuxSpice differs from LTspice. Consult it before answering questions about LTspice/TuxSpice syntax, "
     "commands or the .asc format, instead of answering from memory. Returns 'docs' ([{docname, summary}]). "
     "Same content as the 'ltspice-ref:///' resources; don't read both.", _obj()),
    ("get_ltspice_reference", "Reads one reference document. Pass 'name' as the 'docname' from "
     "list_ltspice_reference_docs. Returns 'docname' and 'text' (markdown).",
     _obj({"name": {"type": "string", "description": "The docname, e.g. 'SCHEMATIC-REFERENCE.md'."}},
          ["name"])),
]

SESSION_TOOLS = [
    ("status", "Session control (always available). Lists the running TuxSpice windows the bridge can see "
     "(pid, port, open designs) and reports what this session is attached to: a TuxSpice window "
     "('gui-attached') or the bridge's own headless backend ('headless').", _obj()),
    ("attach", "Session control (always available). Binds this session to a running TuxSpice window. Without "
     "arguments, the most recently started one; or pass 'pid' from status.",
     _obj({"pid": {"type": "integer", "description": "Process id of the TuxSpice instance (from status)."}})),
    ("start_headless", "Session control (always available). Switches this session to a private headless "
     "backend that works on files without a window, and stays there (no automatic switch to a window).",
     _obj()),
]


def _ro(title):
    return {"title": title, "readOnlyHint": True, "openWorldHint": False}


def _rw(title, destructive, idempotent):
    return {"title": title, "readOnlyHint": False, "destructiveHint": destructive, "idempotentHint": idempotent,
            "openWorldHint": False}


# MCP tool annotations exactly as LTspice 26.1.1's bridge reports them
ANNOTATIONS = {
    "list_open_designs": _ro("List Open Designs"),
    "open_design": _rw("Open Design", False, True),
    "get_active_design_path": _ro("Determine Active Design"),
    "get_spice_log": _ro("Get SPICE Log"),
    "get_design_content": _ro("Get Design Content"),
    "get_schematic_netlist": _ro("Get Schematic Netlist"),
    "start_simulation": _rw("Run Simulation", False, False),
    "is_simulation_running": _ro("Is Simulation Running"),
    "set_design_content": _rw("Set Design Content", True, True),
    "bring_to_front": _rw("Bring To Front", False, True),
    "get_raw_info": _ro("Get Raw Info"),
    "read_raw_waveforms": _ro("Read Raw Waveforms"),
    "export_raw_waveforms": _rw("Export Raw Waveforms To SQLite", True, True),
    "list_ltspice_reference_docs": _ro("List LTspice Reference Docs"),
    "get_ltspice_reference": _ro("Get LTspice Reference"),
    "status": {"title": "Bridge: session status", "readOnlyHint": True},
    "attach": {"title": "Bridge: attach to instance", "readOnlyHint": False},
    "start_headless": {"title": "Bridge: start headless instance", "readOnlyHint": False},
}


def tool_list(session=True):
    tools = DESIGN_TOOLS + (SESSION_TOOLS if session else [])
    return [{"name": n, "description": d, "inputSchema": s, "annotations": ANNOTATIONS[n]} for n, d, s in tools]


STATE_CHANGING = {"open_design", "set_design_content", "start_simulation"}

INSTRUCTIONS = """\
This server connects you to TuxSpice, a Linux work-alike of LTspice: same .asc schematics, same symbol \
and model libraries, same netlist dialect, but it simulates with ngspice through a translation layer. \
The tools mirror LTspice's own MCP server.

Before answering questions about LTspice/TuxSpice commands, syntax or the .asc format, or before \
writing schematic or netlist text, read the reference documents (list_ltspice_reference_docs / \
get_ltspice_reference, or the ltspice-ref:/// resources) instead of answering from memory. Read \
SCHEMATIC-REFERENCE.md (when present) before writing any .asc text, and TUXSPICE-NOTES.md for what \
differs from LTspice.

Modes: if a TuxSpice window is running, this session shares it (gui-attached): the user's open \
documents are visible to you and your edits appear live as undoable steps. Otherwise the bridge works \
headless, on files, with nothing open until you call open_design. A headless session switches to a \
TuxSpice window the user opens, until your first open, edit or simulation. Call status to see the mode.

Workflow:
1. Call get_active_design_path / list_open_designs; if nothing suitable is open, open_design(path).
2. Read with get_design_content; for a schematic also get_schematic_netlist. Never edit the generated \
netlist: edit the schematic.
3. Edit with set_design_content, sending the COMPLETE text. Then check get_schematic_netlist. Prefer \
text edits (values, parameters, directives, models) over drawing: placing parts and routing wires \
by editing coordinates is error-prone.
4. start_simulation, poll is_simulation_running, then get_spice_log (also holds .meas results).
5. For numbers: get_raw_info for exact signal names, then read_raw_waveforms with an explicit signal \
list and a small window, or export_raw_waveforms to SQLite for large data.

Report numbers from the log or the waveform data, not impressions, and tell the user to verify results.
"""

NOTES = """\
# TuxSpice notes for assistants

TuxSpice opens and saves LTspice files unchanged and uses LTspice's own libraries (extracted from the \
user's LTspice installer), but it is a different program:

- **Simulator**: ngspice, not LTspice. TuxSpice translates the LTspice dialect (Rser/Cpar parasitics, \
A-devices, table(), Laplace sources, LTspice functions, ideal diodes...) before running it. Results \
usually match LTspice closely but not exactly.
- **.step and .meas** are done by TuxSpice itself; .meas results appear in the SPICE log \
(get_spice_log), per step for stepped runs.
- **Encrypted Analog Devices models** (files in lib/sub starting with `<Binary File>`) cannot be \
simulated outside LTspice. A design that uses one fails with an "encrypted model" message; say so \
instead of retrying.
- **Not available**: .machine, .timedomain, .fra, the Transient Frequency Response analysis, \
efficiency reports, .wave. ngspice-only extras are available: .pz (pole-zero) and .disto.
- **Convergence**: ngspice converges differently. TuxSpice retries non-converging runs with relaxed \
options; the log says so ("Converged only with relaxed settings").
- **Waveform names** follow LTspice: V(node), I(R1), Ic(Q1), Id(M1). Use get_raw_info for the exact list.
- **Precision**: results are double precision (ngspice binary .raw).
- **Files**: a run of <name>.asc writes <name>.net (LTspice dialect), <name>.ngspice.cir (what \
ngspice ran), <name>.log and, for unstepped runs, <name>.raw next to the schematic.
"""


# ---------------------------------------------------------------- reference documents
def reference_dir() -> Path:
    return config.LIB_ROOT / "reference"


def reference_docs():
    """[(docname, summary)] sorted by name, as LTspice lists them. Summaries come from the index table
    in the reference README (as LTspice's do), else the file's front matter. README.md itself is
    readable but not listed."""
    docs = {"TUXSPICE-NOTES.md": "How TuxSpice differs from LTspice (simulator, encrypted models, "
                                 "missing commands, file names)"}
    d = reference_dir()
    if d.is_dir():
        index = {}
        readme = d / "README.md"
        if readme.is_file():
            for m in re.finditer(r"^\|\s*\[([^\]]+\.md)\]\([^)]*\)\s*\|\s*(.+?)\s*\|\s*$",
                                 readme.read_text(errors="replace"), re.M):
                index.setdefault(m.group(1), m.group(2))
        for p in d.glob("*.md"):
            if p.name.upper() != "README.MD":
                docs[p.name] = index.get(p.name) or _summary(p)
    return sorted(docs.items())


def _summary(p: Path) -> str:
    try:
        lines = p.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    if lines and lines[0].strip() == "---":          # YAML front matter: use its description
        for l in lines[1:]:
            if l.strip() == "---":
                break
            if l.startswith("description:"):
                return l.split(":", 1)[1].strip().rstrip(".")
    for l in lines:
        s = l.strip().lstrip("#>*- ").strip()
        if s and not l.lstrip().startswith("#") and len(s) > 20:
            return s[:160]
    return next((l.lstrip("# ").strip() for l in lines if l.strip()), p.stem)


def reference_text(name: str) -> str:
    name = Path(str(name)).name
    if name.upper() == "TUXSPICE-NOTES.MD":
        return NOTES
    for p in reference_dir().glob("*.md") if reference_dir().is_dir() else []:
        if p.name.lower() == name.lower():
            return p.read_text(errors="replace")
    raise ToolError(f"Reference document not found: {name}")


# ---------------------------------------------------------------- results (.raw) tools
# Error texts below are LTspice 26.1.1's, word for word (assistants may react to them).
def _signal_names(plot):
    from ..sim.vectors import VectorSet
    return VectorSet(plot).names()


def _get_signal(plot, name):
    from ..sim.vectors import VectorSet
    if name.lower() in (plot.xname.lower(), "time", "frequency") and name.lower() == plot.xname.lower():
        return np.asarray(plot.data[0])
    arr = VectorSet(plot).get(name)
    return None if arr is None else np.asarray(arr)


def _var_index(plot, name):
    """Column of a signal in the .raw file (None for an expression such as V(a,b))."""
    from ..sim.vectors import VectorSet
    if name.lower() == plot.xname.lower():
        return 0
    return VectorSet(plot).by_name.get(name.lower())


def _param_value(v):
    from ..sim.spicenum import parse
    x = parse(v)
    return float(x) if x is not None else v


def _steps_of(plot):
    bounds = plot.step_bounds or [(0, plot.data.shape[1])]
    labels = list(plot.step_labels) + [""] * len(bounds)
    out = []
    for i, (a, b) in enumerate(bounds):
        params = {}
        for tok in (labels[i] or "").split():
            if "=" in tok:
                k, v = tok.split("=", 1)
                params[k.lower()] = _param_value(v)      # LTspice: {"r": 1000.0}
        out.append({"index": i, "params": params, "a": a, "b": b})
    return out


def _main_plot(plots):
    if not plots:
        raise ToolError("file not found")
    return next((p for p in plots if p.analysis != "op"), plots[0])


def _f(x):
    return "%f" % float(x)


def raw_info(src, plots):
    plot = _main_plot(plots)
    steps = _steps_of(plot)
    res = {"path": str(src), "analysis": plot.plotname, "complex": _s(plot.is_complex),
           "x_name": plot.xname.lower(), "n_points": _s(plot.data.shape[1]), "precision": "double",
           "signals": _signal_names(plot), "stepped": _s(len(steps) > 1)}
    if len(steps) > 1:
        res["n_steps"] = _s(len(steps))
        res["steps"] = [{"index": _s(s["index"]), "params": s["params"], "n_points": _s(s["b"] - s["a"])}
                        for s in steps]
    return res


def _clean(a):
    return [None if not math.isfinite(v) else float(v) for v in np.asarray(a, dtype=float)]


def _select(plot, args):
    signals = args.get("signals")
    if not isinstance(signals, list) or not signals:
        raise ToolError("the 'signals' parameter is required and must be a non-empty array of signal names")
    steps = _steps_of(plot)
    want = args.get("steps")
    if want is not None:
        for i in want:
            if not isinstance(i, int) or not 0 <= i < len(steps):
                raise ToolError(f"step index {i} is out of range; this run has {len(steps)} step(s), so valid "
                                f"indices are 0..{len(steps) - 1}")
        steps = [steps[i] for i in want]
    xmin, xmax = args.get("x_min"), args.get("x_max")
    x_all = np.real(np.asarray(plot.data[0]))
    found, unknown = {}, []
    for name in signals:
        arr = _get_signal(plot, name)
        if arr is None:
            unknown.append(name)
        else:
            found[name] = np.broadcast_to(arr, x_all.shape)
    if not found:
        raise ToolError("none of the requested signals exist in this raw file; call get_raw_info to list the "
                        "available signal names")
    sel = []
    for s in steps:
        idx = np.arange(s["a"], s["b"])
        x = x_all[idx]
        m = np.ones(len(idx), bool)
        if xmin is not None:
            m &= x >= float(xmin)
        if xmax is not None:
            m &= x <= float(xmax)
        sel.append((s, idx[m]))
    if sum(len(i) for _, i in sel) == 0:
        raise ToolError("the x_min/x_max window selected no points; check the units of the window against "
                        "'x_name' (seconds for a transient run, Hz for AC/FRA)")
    return found, unknown, sel, x_all


def _series(arr, cplx, fmt):
    """[(suffix, values)] for one signal."""
    if not cplx:
        return [("", np.real(arr))]
    if fmt == "polar":
        return [("mag_db20", 20 * np.log10(np.maximum(np.abs(arr), 1e-300))),
                ("phase_deg", np.degrees(np.angle(arr)))]
    return [("real", np.real(arr)), ("imag", np.imag(arr))]


def _common(src, plot, args, found, unknown, sel, cplx, fmt, cap):
    steps = _steps_of(plot)
    n_series = 1 + len(found) * (2 if cplx else 1)
    n_ret = sum(len(i) for _, i in sel)
    res = {"path": str(src), "analysis": plot.plotname, "complex": _s(cplx), "x_name": plot.xname.lower(),
           "stepped": _s(len(steps) > 1), "n_steps": _s(len(steps)), "n_points": _s(plot.data.shape[1]),
           "n_points_returned": _s(n_ret), "n_series": _s(n_series), "values_required": _s(n_ret * n_series),
           "max_values": _s(cap), "precision": "double", "unknown_signals": unknown}
    if cplx:
        res["complex_format"] = fmt
    for k in ("x_min", "x_max"):
        if args.get(k) is not None:
            res[k] = _f(args[k])
    return res, n_ret, n_series, len(steps)


def read_raw(src, plots, args):
    plot = _main_plot(plots)
    cplx = plot.is_complex
    fmt = args.get("complex_format") or "cartesian"
    found, unknown, sel, x_all = _select(plot, args)
    cap = int(args.get("max_values") or 10000)
    res, n_ret, n_series, n_steps = _common(src, plot, args, found, unknown, sel, cplx, fmt, cap)
    if n_ret * n_series > cap:
        raise ToolError(f"the requested read needs {n_ret * n_series} values ({n_ret} points x {n_series} series) "
                        f"but max_values is {cap}; request fewer signals, select fewer steps via 'steps' (this run "
                        f"has {n_steps}), narrow the x-axis window via 'x_min'/'x_max', or raise 'max_values'")

    def block(idx):
        sigs = {}
        for name, arr in found.items():
            parts = _series(arr[idx], cplx, fmt)
            sigs[name] = {"values": _clean(parts[0][1])} if not cplx else {k: _clean(v) for k, v in parts}
        return {"x": _clean(x_all[idx]), "signals": sigs}

    if n_steps > 1:
        res["steps"] = [{"index": _s(s["index"]), "params": s["params"], "n_points": _s(len(idx)),
                         "data": block(idx)} for s, idx in sel]
    else:
        res["data"] = block(sel[0][1])
    return res


def export_raw(src, plots, args):
    plot = _main_plot(plots)
    cplx = plot.is_complex
    fmt = args.get("complex_format") or "cartesian"
    db = args.get("db_path")
    if not db:
        raise ToolError("the 'db_path' parameter is required and must be the absolute path of the SQLite file "
                        "to write")
    db = Path(str(db))
    found, unknown, sel, x_all = _select(plot, args)
    cap = int(args.get("max_values") if args.get("max_values") is not None else -1)
    res, n_ret, n_series, n_steps = _common(src, plot, args, found, unknown, sel, cplx, fmt, cap)
    if cap > 0 and n_ret * n_series > cap:
        raise ToolError(f"the requested export needs {n_ret * n_series} values ({n_ret} points x {n_series} "
                        f"series) but max_values is {cap}; narrow the export or pass max_values = -1 for unlimited")
    overwritten = db.exists()
    if overwritten and args.get("no_overwrite"):
        raise ToolError(f"the file '{db}' already exists and 'no_overwrite' is true")
    xname = plot.xname.lower()
    cols = []
    for name in found:
        for suf, _ in _series(np.zeros(1, complex if cplx else float), cplx, fmt):
            cols.append(f"{name}|{suf}" if suf else name)
    q = lambda c: '"' + c.replace('"', '""') + '"'   # noqa: E731
    try:
        if overwritten:
            db.unlink()
        con = sqlite3.connect(str(db))
    except (OSError, sqlite3.Error) as e:
        raise ToolError(f"failed to write the SQLite database '{db}'\n{e}") from e
    try:
        # same tables, column types and creation order as LTspice 26.1.1's export
        con.execute("CREATE TABLE run (  source_path TEXT,  analysis    TEXT,  x_name      TEXT,  complex     "
                    "INTEGER,  complex_format TEXT,  precision   TEXT,  stepped     INTEGER,  n_steps     INTEGER,  "
                    "n_points    INTEGER)")
        con.execute("CREATE TABLE steps (  step     INTEGER PRIMARY KEY,  n_points INTEGER)")
        con.execute("CREATE TABLE step_params (  step  INTEGER,  name  TEXT,  value REAL)")
        con.execute("CREATE TABLE signals (  signal    INTEGER PRIMARY KEY,  name      TEXT,  var_index INTEGER)")
        con.execute(f"CREATE TABLE samples (step INTEGER, point INTEGER, {q(xname)} REAL, "
                    + ", ".join(f"{q(c)} REAL" for c in cols) + ", PRIMARY KEY (step, point))")
        con.execute("INSERT INTO run VALUES (?,?,?,?,?,?,?,?,?)",
                    (str(src), plot.plotname, xname, int(cplx), fmt if cplx else "", "double",
                     int(n_steps > 1), n_steps, plot.data.shape[1]))
        for i, name in enumerate(found):
            con.execute("INSERT INTO signals VALUES (?,?,?)", (i, name, _var_index(plot, name)))
        n_rows = 0
        for s, idx in sel:
            columns = [x_all[idx]]
            for name, arr in found.items():
                columns += [v for _, v in _series(arr[idx], cplx, fmt)]
            rows = [(s["index"], k) + tuple(None if not math.isfinite(float(v)) else float(v) for v in vals)
                    for k, vals in enumerate(zip(*columns))]
            con.executemany(f"INSERT INTO samples VALUES ({','.join('?' * (3 + len(cols)))})", rows)
            con.execute("INSERT INTO steps VALUES (?,?)", (s["index"], len(idx)))
            for k, v in s["params"].items():
                con.execute("INSERT INTO step_params VALUES (?,?,?)", (s["index"], k, v))
            n_rows += len(rows)
        con.commit()
    except sqlite3.Error as e:
        raise ToolError(f"failed to write the SQLite database '{db}'\n{e}") from e
    finally:
        con.close()
    res.update({"db_path": str(db), "overwritten": _s(overwritten), "n_signals_exported": _s(len(found)),
                "n_rows": _s(n_rows)})
    return res


def raw_path_for(path) -> Path:
    """Results file of a design: <name>.raw next to it."""
    p = Path(path)
    return p if p.suffix.lower() == ".raw" else p.with_suffix(".raw")


def load_results(path):
    """(raw path, plots) from a .raw file or a design's .raw on disk."""
    from ..sim.rawfile import read_raw as _read
    raw = raw_path_for(path)
    if not raw.is_file():
        raise ToolError("file not found")
    return str(raw), _read(raw)


NO_RAW_WINDOW = "no active raw waveform window; supply a '.raw' file path or design file path"


# ---------------------------------------------------------------- dispatch
def call_tool(backend, name, args) -> dict:
    """Run one design tool; returns the reply object. Raises ToolError."""
    args = args or {}
    raw_arg = args.get("path")
    path = norm_path(raw_arg) if raw_arg else None
    if name == "list_open_designs":
        return {"paths": "\n".join(backend.list_open())}
    if name == "open_design":
        if not raw_arg:
            raise ToolError("missing path parameter")
        if not path or not Path(path).is_file():
            raise ToolError("file not found")
        if not path.lower().endswith(DESIGN_EXT):
            raise ToolError("unsupported file type (expected a '.asc' schematic or a '.net'/'.cir'/'.lib'/"
                            "'.sub'/'.sp' netlist)")
        r = backend.open_design(path)
        out = {"path": r["path"], "type": r["type"], "status": "ok", "already_open": _s(r["already_open"])}
        if r.get("message"):
            out["message"] = r["message"]
        return out
    if name == "get_active_design_path":
        p, t = backend.active()
        return {"path": p, "type": t}
    if name == "get_spice_log":
        if raw_arg and str(raw_arg).lower().endswith(".log"):
            if not path or not Path(path).is_file():
                return {}
            return {"text": Path(path).read_text(errors="replace")}
        if raw_arg and not path:
            raise ToolError("document not found")
        return {"text": backend.spice_log(path)}
    if name == "get_design_content":
        if raw_arg and not path:
            raise ToolError("document not found")
        p, text = backend.content(path)
        return {"path": p, "text": text.replace("\r\n", "\n")}
    if name == "get_schematic_netlist":
        if raw_arg and not path:
            raise ToolError("document not found")
        p, text, msg, code = backend.netlist(path)
        return {"path": p, "text": text, "message": msg, "netlist_error_code": _s(code)}
    if name == "start_simulation":
        if raw_arg and not path:
            raise ToolError("document not found")
        p = backend.doc_path(path)
        ok, msg = backend.start_sim(p)
        return {"path": p, "result": _s(ok), "message": msg}
    if name == "is_simulation_running":
        if raw_arg:
            if not path or path not in backend.list_open():
                raise ToolError("document not found")
            return {"path": path, "result": _s(backend.sim_running(path))}
        return {"result": _s(backend.sim_running(None))}
    if name == "set_design_content":
        if not raw_arg or not isinstance(args.get("text"), str):
            raise ToolError("missing path or text parameter")
        if not path or path not in backend.list_open():
            raise ToolError("document not found")
        _, old = backend.content(path)
        if old.replace("\r\n", "\n") == args["text"].replace("\r\n", "\n"):
            return {"status": "ok", "unchanged": "true"}
        msg = backend.set_content(path, args["text"])
        out = {"status": "ok", "unchanged": "false"}
        if doc_type(path) == "schematic":
            out["message"] = msg or ""
        return out
    if name == "bring_to_front":
        try:
            backend.bring_to_front(path if path in backend.list_open() else None)
        except ToolError:
            pass
        return {"status": "ok"}
    if name in ("get_raw_info", "read_raw_waveforms", "export_raw_waveforms"):
        if raw_arg and not path:
            raise ToolError("file not found")
        src, plots = backend.results(path)
        if name == "get_raw_info":
            return raw_info(src, plots)
        if name == "read_raw_waveforms":
            return read_raw(src, plots, args)
        return export_raw(src, plots, args)
    if name == "list_ltspice_reference_docs":
        return {"docs": [{"docname": n, "summary": s} for n, s in reference_docs()]}
    if name == "get_ltspice_reference":
        if not args.get("name"):
            raise ToolError("Missing reference document name")
        return {"docname": Path(str(args["name"])).name, "text": reference_text(args["name"])}
    raise ToolError("unknown method")


def dumps(obj) -> str:
    """LTspice's bridge writes compact JSON with sorted keys and raw (non-ASCII) characters."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def run_tool(backend, name, args):
    """call_tool wrapped as an MCP tools/call result (no isError key on success, as LTspice)."""
    try:
        return {"content": [{"type": "text", "text": dumps(call_tool(backend, name, args))}]}
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except Exception as e:  # noqa: BLE001 - report anything to the assistant instead of dying
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}


def resources(backend):
    out = [{"uri": f"ltspice-ref:///{n}", "name": n, "description": s, "mimeType": "text/markdown"}
           for n, s in reference_docs()]
    for p in backend.list_open() if backend is not None else []:
        out.append({"uri": "ltspice-design:///" + p, "name": Path(p).name,
                    "description": f"Open TuxSpice design: {p}", "mimeType": "text/plain"})
    return out


def read_resource(backend, uri):
    """resources/read contents; raises ToolError (reported as a tool-style error, as LTspice does)."""
    if uri.startswith("ltspice-ref:///"):
        name = uri[len("ltspice-ref:///"):]
        try:
            text = reference_text(name)
        except ToolError:
            raise ToolError(f"Resource not found: {name}") from None
        return [{"uri": uri, "mimeType": "text/markdown", "text": text}]
    if uri.startswith("ltspice-design:///"):
        p = norm_path(uri[len("ltspice-design:///"):])
        if not p or backend is None or p not in backend.list_open():
            raise ToolError("document not found")
        _, text = backend.content(p)
        return [{"uri": uri, "mimeType": "text/plain", "text": text.replace("\r\n", "\n")}]
    raise ToolError(f"Unknown URI scheme: {uri}")


def asc_errors(text: str) -> str:
    """Quick sanity check of schematic text before it replaces a document. (LTspice 26.1.1 crashes on
    text that isn't a schematic; TuxSpice refuses it instead.)"""
    first = text.lstrip("﻿").lstrip().split("\n", 1)[0]
    if not re.match(r"(?i)version\s+\d", first):
        return "schematic text must start with a 'Version 4' line (read SCHEMATIC-REFERENCE.md)"
    return ""
