"""pyltspice-mcp: the stdio MCP server an AI tool launches (LTspice: ltspice-mcp-bridge.exe).

It attaches to a running TuxSpice window when there is one (the assistant then shares the user's
session and its edits are undoable there). Otherwise it serves the tools itself, headless. While
headless and before the first state-changing call it keeps looking for a window to hand off to, as
LTspice's bridge does; once committed it stays. If the attached window goes away, the next call
re-resolves: another window, or headless.

Protocol: MCP over stdio, newline-delimited JSON-RPC 2.0. No third-party MCP library is needed.
"""
import json
import os
import sys

from . import SERVER_NAME, registry, tools

PROTOCOLS = ("2025-03-26",)


def _version():
    try:
        from importlib.metadata import version
        return version("pyltspice")
    except Exception:  # noqa: BLE001
        return "0"


class Session:
    def __init__(self, write, attach=True):
        self.write = write                 # function(message dict)
        self.conn = None                   # registry.Connection when gui-attached
        self.headless = None               # HeadlessBackend when headless
        self.committed = False             # first state-changing call made while headless
        self.pinned = False                # start_headless: never switch to a window
        self.auto_attach = attach
        if attach:
            self._try_attach()

    # -- backend selection
    def _try_attach(self, pid=None):
        for info in registry.instances():
            if pid is not None and int(info["pid"]) != pid:
                continue
            try:
                conn = registry.Connection(info)
                conn.request("info")
            except (OSError, ValueError, ConnectionError):
                continue
            if self.conn is not None:
                self.conn.close()
            self.conn = conn
            return True
        return False

    def _headless(self):
        if self.headless is None:
            from .headless import HeadlessBackend
            self.headless = HeadlessBackend()
        return self.headless

    def _changed(self):
        self.write({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})

    def mode(self):
        return "gui-attached" if self.conn is not None else "headless"

    def _before_call(self, name):
        if self.conn is None and self.auto_attach and not self.pinned and not self.committed:
            if self._try_attach():
                self._changed()
        if self.conn is None and name in tools.STATE_CHANGING:
            self.committed = True

    # -- MCP methods
    def handle(self, msg):
        method = msg.get("method", "")
        mid = msg.get("id")
        params = msg.get("params") or {}
        if mid is None:                       # notification
            return None
        try:
            result = self._dispatch(method, params)
        except _RpcError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": str(e)}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _server_info(self):
        return {"name": SERVER_NAME, "version": _version(),
                "mode": "attached" if self.conn is not None else "headless",
                "autoStarted": False, "backendActive": True, "headlessLaunchAvailable": True}

    def _dispatch(self, method, params):
        if method == "initialize":
            # LTspice's bridge always answers 2025-03-26, whatever the client asks for
            self.client = (params.get("clientInfo") or {}).get("name", "")
            self._hello()
            return {"protocolVersion": PROTOCOLS[0], "capabilities": {"resources": {}, "tools": {"listChanged": True}},
                    "serverInfo": self._server_info(),
                    "instructions": tools.INSTRUCTIONS + f"\nStarting mode: {self.mode()}."}
        if method == "ping":                  # required by MCP (LTspice's bridge lacks it)
            return {}
        if method == "tools/list":
            return {"tools": tools.tool_list()}
        if method == "tools/call":
            return self.call(params.get("name", ""), params.get("arguments") or {})
        if method == "resources/list":
            return {"resources": self._resources()}
        if method == "resources/read":
            try:
                return {"contents": self._read_resource(params.get("uri", ""))}
            except tools.ToolError as e:      # LTspice reports these as tool-style errors
                return self._error(str(e))
        raise _RpcError(-32601, f"Method not found: {method}")

    def _hello(self):
        """Tell the window which assistant is connected (status bar: 'MCP Connected: <client>')."""
        if self.conn is not None:
            try:
                self.conn.request("hello", client=getattr(self, "client", ""))
            except (OSError, ValueError, ConnectionError):
                pass

    def call(self, name, args):
        if name == "status":
            return self._text(self._status())
        if name == "attach":
            pid = args.get("pid")
            if not self._try_attach(int(pid) if pid is not None else None):
                return self._error(json.dumps({"error": "no live TuxSpice instance with that pid" if pid is not None
                                               else "no live TuxSpice instance", "ok": False}, indent=2,
                                              sort_keys=True))
            self.pinned = False
            self.committed = False
            self._hello()
            self._changed()
            return self._text({"attachedPid": self.conn.pid, "ok": True, "port": int(self.conn.info["port"])})
        if name == "start_headless":
            if self.conn is not None:
                self.conn.close()
                self.conn = None
            self.headless = None              # a fresh private backend, like a new hidden instance
            self._headless()
            self.pinned = True
            self.committed = False
            self._changed()
            return self._text({"headlessPid": os.getpid(), "ok": True})
        self._before_call(name)
        if self.conn is not None:
            try:
                return self.conn.request("call", name=name, arguments=args)
            except (OSError, ValueError, ConnectionError):
                self.conn.close()
                self.conn = None              # the window went away: re-resolve
                if self.auto_attach and self._try_attach():
                    self._hello()
                    self._changed()
                    return self.conn.request("call", name=name, arguments=args)
                self._changed()
        return tools.run_tool(self._headless(), name, args)

    def _status(self):
        inst = [{"mode": "gui", "pid": int(i["pid"]), "port": int(i["port"]), "version": i.get("version", "")}
                for i in registry.instances()]
        if self.conn is not None:
            cur = {"backendPid": self.conn.pid, "committed": self.committed, "state": "gui-attached"}
        else:
            cur = {"backendPid": os.getpid(), "committed": self.committed,
                   "state": "headless-owned" if self.pinned else "headless"}
            inst.append({"mode": "headless", "pid": os.getpid(), "port": 0, "version": _version()})
        return {"current": cur, "instances": inst}

    def _resources(self):
        if self.conn is not None:
            try:
                return self.conn.request("resources")
            except (OSError, ValueError, ConnectionError):
                pass
        return tools.resources(self.headless)

    def _read_resource(self, uri):
        if self.conn is not None and uri.startswith("ltspice-design:///"):
            r = self.conn.request("read_resource", uri=uri)
            if "error" in r:
                raise tools.ToolError(r["error"])
            return r["contents"]
        return tools.read_resource(self.headless, uri)

    @staticmethod
    def _text(obj):
        return {"content": [{"type": "text", "text": json.dumps(obj, indent=2, sort_keys=True)}]}

    @staticmethod
    def _error(text):
        return {"content": [{"type": "text", "text": text}], "isError": True}


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def serve(stdin=None, stdout=None, attach=True):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    if stdout is sys.stdout:
        sys.stdout = sys.stderr       # stray prints must never reach the protocol stream

    def write(obj):
        stdout.write(json.dumps(obj) + "\n")
        stdout.flush()

    session = Session(write, attach=attach)
    print(f"[{SERVER_NAME}-mcp] session started, mode {session.mode()}", file=sys.stderr)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            write({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        batch = msg if isinstance(msg, list) else [msg]
        replies = [r for r in (session.handle(m) for m in batch if isinstance(m, dict)) if r is not None]
        for r in replies:
            write(r)
    if session.headless is not None:
        session.headless.wait(timeout=1)
    print(f"[{SERVER_NAME}-mcp] session ended", file=sys.stderr)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--help" in argv or "-h" in argv:
        print("pyltspice-mcp: TuxSpice MCP server (stdio). Register it in an AI tool as a stdio server "
              "named 'tuxspice' with this command and no arguments.\n  --headless  never attach to a "
              "running TuxSpice window")
        return 0
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # settings are read through Qt, never shown
    serve(attach="--headless" not in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
