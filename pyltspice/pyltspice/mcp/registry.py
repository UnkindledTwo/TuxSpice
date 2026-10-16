"""How MCP bridges find running TuxSpice windows.

Each window listens on 127.0.0.1 (never the network) and writes <runtime dir>/pyltspice/mcp/<pid>.json
with its port and a random token, readable only by the user. A bridge connects, sends the token with
every request, and talks newline-delimited JSON:

    -> {"token": ..., "id": 1, "op": "call", "name": "get_design_content", "arguments": {...}}
    <- {"id": 1, "result": {"content": [...], "isError": false}}
    -> {"token": ..., "id": 2, "op": "info"}
    <- {"id": 2, "result": {"pid": ..., "version": ..., "open": [...]}}
"""
import json
import os
import socket
import time
from pathlib import Path


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    d = Path(base) / "pyltspice" / "mcp" if base else Path.home() / ".cache" / "pyltspice" / "mcp"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def register(pid, port, token, version) -> Path:
    f = runtime_dir() / f"{pid}.json"
    tmp = f.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"pid": pid, "port": port, "token": token, "version": version,
                   "started": time.time()}, fh)
    os.replace(tmp, f)
    return f


def unregister(pid):
    try:
        (runtime_dir() / f"{pid}.json").unlink()
    except OSError:
        pass


def _alive(pid) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def instances():
    """Live TuxSpice windows, newest first; stale files are removed."""
    out = []
    for f in runtime_dir().glob("*.json"):
        try:
            info = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if not _alive(int(info.get("pid", 0))):
            try:
                f.unlink()
            except OSError:
                pass
            continue
        out.append(info)
    out.sort(key=lambda i: i.get("started", 0), reverse=True)
    return out


class Connection:
    """A bridge's link to one TuxSpice window."""

    def __init__(self, info, timeout=120.0):
        self.info = info
        self.pid = int(info["pid"])
        self.sock = socket.create_connection(("127.0.0.1", int(info["port"])), timeout=5)
        self.sock.settimeout(timeout)
        self.reader = self.sock.makefile("r", encoding="utf-8")
        self.next_id = 0

    def request(self, op, **kw):
        self.next_id += 1
        msg = {"token": self.info["token"], "id": self.next_id, "op": op, **kw}
        self.sock.sendall((json.dumps(msg) + "\n").encode())
        line = self.reader.readline()
        if not line:
            raise ConnectionError("TuxSpice closed the connection")
        reply = json.loads(line)
        if "error" in reply:
            raise ConnectionError(reply["error"])
        return reply["result"]

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
