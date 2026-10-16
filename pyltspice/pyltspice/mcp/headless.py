"""MCP backend without a window: works on files, simulates in a worker thread.

Like LTspice's background instance it starts with nothing open. Unlike a window, there is no undo
history, so set_design_content rewrites the file on disk (keeping its encoding and line endings).
"""
import threading
from pathlib import Path

from ..model import asc
from ..model.textio import read_text, write_text
from .tools import NO_RAW_WINDOW, ToolError, asc_errors, doc_type, load_results, raw_path_for


def simulate_file(path: Path, text: str):
    """Netlist (for a schematic) and simulate; returns (SimResult, log text). Writes <name>.net."""
    from ..model.netlist import generate_netlist
    from ..sim.runner import Simulator, _with_options
    dirs = [path.parent]
    if doc_type(path) == "schematic":
        sch = asc.parse_asc(text)
        sch.path = path
        nl = generate_netlist(sch)
        netlist = nl.text
        try:
            path.with_suffix(".net").write_text(netlist, encoding="latin-1", errors="replace")
        except OSError:
            pass
    else:
        netlist = text
    try:                       # Settings > SPICE and Search Paths, when the user changed them
        from ..ui.settings_dialog import get, paths, spice_options
        opts = spice_options()
        if opts:
            netlist = _with_options(netlist, opts)
        dirs += [Path(p) for p in paths("paths/lib_paths")]
        if get("paths/user_dir"):
            dirs.append(Path(get("paths/user_dir")).expanduser())
    except Exception:  # noqa: BLE001 - settings are optional here
        pass
    res = Simulator(netlist, path.with_suffix(""), dirs).run()
    return res, sim_log(res)


def sim_log(res) -> str:
    log = "\n".join(res.errors + res.warnings) + ("\n\n" if res.errors or res.warnings else "") + res.log
    if res.measurements:
        log = "Measurements:\n" + "\n".join(f"{k}: {v}" for k, v in res.measurements) + "\n\n" + log
    return log


class HeadlessBackend:
    mode = "headless"

    def __init__(self):
        self.docs = {}            # path -> text (as loaded or last set)
        self.active_path = ""
        self._runs = {}           # path -> SimResult of the last run
        self._last = ""           # design simulated last
        self.logs = {}
        self.threads = {}

    # -- documents
    def _doc(self, path):
        p = path or self.active_path
        if not p or p not in self.docs:
            raise ToolError("document not found")
        return p

    def doc_path(self, path):
        return self._doc(path)

    def list_open(self):
        return list(self.docs)

    def open_design(self, path):
        already = path in self.docs
        if not already:
            self.docs[path] = read_text(Path(path))[0]
        self.active_path = path
        return {"path": path, "type": doc_type(path), "already_open": already, "message": ""}

    def active(self):
        return (self.active_path, doc_type(self.active_path)) if self.active_path else ("", "")

    def content(self, path):
        p = self._doc(path)
        return p, self.docs[p]

    def set_content(self, path, text):
        self._doc(path)
        if doc_type(path) == "schematic":
            err = asc_errors(text)
            if err:
                raise ToolError(err)
            asc.parse_asc(text)            # raises on malformed text before anything is written
        try:
            _, enc, nl = read_text(Path(path))
        except OSError:
            enc, nl = "latin-1", "\n"
        write_text(Path(path), text, enc, nl)
        self.docs[path] = text
        return ""

    def netlist(self, path):
        from ..model.netlist import generate_netlist
        p = self._doc(path)
        if doc_type(p) != "schematic":
            raise ToolError("path is not a schematic")
        sch = asc.parse_asc(self.docs[p])
        sch.path = Path(p)
        nl = generate_netlist(sch)
        return p, nl.text, "\n".join(nl.errors), 0

    # -- simulation
    def start_sim(self, path):
        p = self._doc(path)
        if self.sim_running(p):
            return False, "a simulation of this design is already running"

        def work():
            try:
                res, log = simulate_file(Path(p), self.docs[p])
                self._runs[p] = res
                self._last = p
                self.logs[p] = log
            except Exception as e:  # noqa: BLE001
                self.logs[p] = f"Simulation failed: {e}"
                self._runs.pop(p, None)
        t = threading.Thread(target=work, daemon=True)
        self.threads[p] = t
        self.logs[p] = "Simulation running..."
        t.start()
        return True, ""

    def sim_running(self, path):
        if path:
            t = self.threads.get(path)
            return bool(t and t.is_alive())
        return any(t.is_alive() for t in self.threads.values())

    def wait(self, timeout=None):
        for t in list(self.threads.values()):
            t.join(timeout)

    def spice_log(self, path):
        p = self._doc(path)
        if p in self.logs:
            return self.logs[p]
        log = Path(p).with_suffix(".log")
        return log.read_text(errors="replace") if log.exists() else ""

    def bring_to_front(self, path):
        if path:
            self._doc(path)
            self.active_path = path
        return "headless session: there is no window to show"

    def results(self, path):
        """(raw path, plots): this session's last run of the design, else its .raw on disk. Without a
        path, the last run (a headless session has no waveform windows to be 'active')."""
        if not path:
            if not self._last:
                raise ToolError(NO_RAW_WINDOW)
            path = self._last
        res = self._runs.get(path)
        if res is not None and res.plots:
            return str(raw_path_for(path)), res.plots
        return load_results(path)
