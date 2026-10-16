"""MCP host inside the TuxSpice window: bridges (pyltspice-mcp) attach here.

Listens on 127.0.0.1 only, with a random token published in a user-only file (mcp/registry.py).
Tool calls run on the Qt main thread against the open windows, so an assistant's edit to a
schematic is an ordinary undo step the user can reverse with Ctrl+Z, as in LTspice.
"""
import json
import os
import secrets
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QHostAddress, QTcpServer
from shiboken6 import isValid

from ..mcp import registry, tools
from ..mcp.tools import NO_RAW_WINDOW, ToolError, asc_errors, doc_type, load_results, raw_path_for


class GuiBackend:
    mode = "gui"

    def __init__(self, main):
        self.main = main

    # -- windows
    def _windows(self):
        return [w for w in self.main._all_widgets() if w is not None]

    def _path_of(self, w):
        from .main_window import PlotWindow, TextWindow
        from .schematic_window import SchematicWindow
        if isinstance(w, SchematicWindow):
            return str(w.doc.path.resolve()) if w.doc.path else ""
        if isinstance(w, TextWindow):
            return str(Path(w.path).resolve()) if w.path else ""
        if isinstance(w, PlotWindow) and w.source is not None:
            return self._path_of(w.source)
        return ""

    def _find(self, path):
        from .main_window import PlotWindow
        for w in self._windows():
            if not isinstance(w, PlotWindow) and self._path_of(w) == path:
                return w
        return None

    def _doc(self, path):
        """The window of a design: the given path, else the active design."""
        from .main_window import PlotWindow
        if path:
            w = self._find(path)
            if w is None:
                raise ToolError("document not found")
            return w
        w = self.main.active_widget()
        if isinstance(w, PlotWindow):
            w = w.source
        if w is None or not self._path_of(w):
            # the most recent design window, if the active one isn't a design
            w = next((x for x in reversed(self._windows()) if self._path_of(x) and not isinstance(x, PlotWindow)),
                     None)
        if w is None:
            raise ToolError("document not found")
        return w

    def doc_path(self, path):
        return self._path_of(self._doc(path))

    def list_open(self):
        from .main_window import PlotWindow
        return [p for p in (self._path_of(w) for w in self._windows() if not isinstance(w, PlotWindow)) if p]

    def open_design(self, path):
        already = self._find(path) is not None
        if not already and doc_type(path) == "schematic":
            from ..model import asc
            try:                    # open_file reports errors in a modal box; the assistant gets text
                asc.load_asc(path)
            except Exception as e:  # noqa: BLE001
                raise ToolError(f"could not read {path}: {e}") from e
        self.main.open_file(path)
        w = self._find(path)
        if w is None:
            raise ToolError(f"could not open {path}")
        self._activate(w)
        return {"path": path, "type": doc_type(path), "already_open": already, "message": ""}

    def active(self):
        try:
            w = self._doc(None)
        except ToolError:
            return "", ""
        p = self._path_of(w)
        return p, doc_type(p)

    def content(self, path):
        from .schematic_window import SchematicWindow
        w = self._doc(path)
        text = w.doc.sch.to_text() if isinstance(w, SchematicWindow) else w.toPlainText()
        return self._path_of(w), text

    def set_content(self, path, text):
        from PySide6.QtGui import QTextCursor
        from ..model import asc
        from .schematic_window import SchematicWindow
        w = self._doc(path)
        if isinstance(w, SchematicWindow):
            err = asc_errors(text)
            if err:
                raise ToolError(err)
            fresh = asc.parse_asc(text)
            doc = w.doc
            doc.begin()
            doc.sch.items[:] = fresh.items
            doc.sch.sheet = fresh.sheet
            doc.commit("AI Assistant Edit", cleanup=False)
        else:
            cur = QTextCursor(w.document())
            cur.select(QTextCursor.Document)
            cur.insertText(text)               # one undo step in the editor
        self.main.status_label.setText(f"AI assistant edited {Path(path).name} (Ctrl+Z undoes it)")
        return ""

    def netlist(self, path):
        from ..model.netlist import generate_netlist
        from .schematic_window import SchematicWindow
        w = self._doc(path)
        if not isinstance(w, SchematicWindow):
            raise ToolError("path is not a schematic")
        nl = generate_netlist(w.doc.sch, w.doc.lib)
        return self._path_of(w), nl.text, "\n".join(nl.errors), 0

    # -- simulation
    def start_sim(self, path):
        w = self._doc(path)
        if self.main.sim_thread is not None:
            return False, "a simulation is already running"
        return self.main.run_simulation(target=w, interactive=False)

    def sim_running(self, path):
        if self.main.sim_thread is None:
            return False
        if not path:
            return True
        return self._path_of(self.main.sim_owner) == path

    def spice_log(self, path):
        w = self._doc(path)
        log = getattr(w, "sim_log", None)
        if self.main.sim_thread is not None and self.main.sim_owner is w:
            return "Simulation running..."
        if log is not None:
            return log
        p = Path(self._path_of(w)).with_suffix(".log")
        return p.read_text(errors="replace") if p.exists() else ""

    def bring_to_front(self, path):
        if path:
            self._activate(self._doc(path))
        self.main.showNormal() if self.main.isMinimized() else None
        self.main.raise_()
        self.main.activateWindow()
        return "ok"

    def _activate(self, w):
        for sub in self.main.mdi.subWindowList():
            if sub.widget() is w:
                self.main.mdi.setActiveSubWindow(sub)
                return
        if w in self.main.floating:
            w.raise_()
            w.activateWindow()

    def results(self, path):
        from .main_window import PlotWindow
        if path and path.lower().endswith(".raw"):
            return load_results(path)
        if not path:                       # LTspice: only the active waveform window
            w = self.main.active_widget()
            if not isinstance(w, PlotWindow):
                raise ToolError(NO_RAW_WINDOW)
            src = w.raw_path or (raw_path_for(self._path_of(w)) if self._path_of(w) else w.title)
            return str(src), [w.viewer.plot]
        w = self._find(path)
        plots = getattr(w, "sim_plots", None) if w is not None else None
        if plots:
            return str(raw_path_for(path)), plots
        return load_results(path)


class McpHost(QObject):
    def __init__(self, main):
        super().__init__(main)
        self.backend = GuiBackend(main)
        self.server = QTcpServer(self)
        self.token = secrets.token_hex(16)
        self.buffers = {}
        self.server.newConnection.connect(self._accept)
        self.file = None

    def start(self):
        if not self.server.listen(QHostAddress.LocalHost, 0):
            return False
        from ..mcp.bridge import _version
        self.file = registry.register(os.getpid(), self.server.serverPort(), self.token, _version())
        return True

    def stop(self):
        self.server.close()
        registry.unregister(os.getpid())

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self.buffers[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))

    def _drop(self, sock):
        self.buffers.pop(sock, None)
        if isValid(sock):
            sock.deleteLater()

    def _read(self, sock):
        self.buffers[sock] = self.buffers.get(sock, b"") + bytes(sock.readAll())
        while b"\n" in self.buffers.get(sock, b""):
            line, self.buffers[sock] = self.buffers[sock].split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                sock.disconnectFromHost()
                return
            if not secrets.compare_digest(str(msg.get("token", "")), self.token):
                sock.write((json.dumps({"id": msg.get("id"), "error": "bad token"}) + "\n").encode())
                sock.disconnectFromHost()
                return
            reply = {"id": msg.get("id"), "result": self.handle(msg)}
            sock.write((json.dumps(reply) + "\n").encode())
            sock.flush()

    def handle(self, msg):
        op = msg.get("op")
        if op == "info":
            from ..mcp.bridge import _version
            return {"pid": os.getpid(), "version": _version(), "open": self.backend.list_open()}
        if op == "call":
            return tools.run_tool(self.backend, msg.get("name", ""), msg.get("arguments") or {})
        if op == "hello":
            client = msg.get("client") or "assistant"
            self.backend.main.status_label.setText(f"MCP Connected: {client}")
            return {"ok": True}
        if op == "resources":
            return tools.resources(self.backend)
        if op == "read_resource":
            try:
                return {"contents": tools.read_resource(self.backend, msg.get("uri", ""))}
            except ToolError as e:
                return {"error": str(e)}
        return {"error": f"unknown op {op}"}


