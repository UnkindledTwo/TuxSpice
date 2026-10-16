"""MCP configuration of AI tools on Linux (Tools > Configure Third-Party AI Assistants).

LTspice (Windows) configures GitHub Copilot in VS Code (and Insiders), Claude Code, Claude Desktop
and Cursor. These are the same tools with their Linux config files. Each entry is a stdio server
named "tuxspice" that runs this Python with ``-m pyltspice.mcp``. Writing keeps every other key
in the file and replaces the file atomically.
"""
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import SERVER_NAME


def server_command():
    """(command, args) that start the MCP server with this installation's Python."""
    # normalized but not resolved: resolving a venv's python symlink would leave the venv
    return os.path.normpath(os.path.abspath(sys.executable)), ["-m", "pyltspice.mcp"]


@dataclass
class Client:
    key: str
    name: str
    user_file: str           # relative to $HOME; may contain {config}
    workspace_file: str      # relative to the workspace folder ('' = no workspace scope)
    servers_key: str         # "mcpServers" or "servers" (VS Code)
    detect: tuple            # executables or $HOME-relative paths whose presence means "installed"

    def path(self, scope="user", workspace=None) -> Path | None:
        if scope == "workspace":
            if not self.workspace_file or not workspace:
                return None
            return Path(workspace) / self.workspace_file
        cfg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(self.user_file.format(config=cfg, home=str(Path.home())))

    def installed(self) -> bool:
        for d in self.detect:
            if "/" not in d and shutil.which(d):
                return True
            if "/" in d and Path(d.format(config=os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")),
                                          home=str(Path.home()))).exists():
                return True
        return False

    def entry(self):
        cmd, args = server_command()
        e = {"command": cmd, "args": args}
        if self.servers_key == "servers" or self.key == "claude-code":
            e = {"type": "stdio", **e}
        return e

    def status(self, scope="user", workspace=None) -> str:
        """Configured / Stale / Not configured / Not detected / No workspace scope."""
        p = self.path(scope, workspace)
        if p is None:
            return "No workspace scope" if scope == "workspace" else "Not detected"
        cur = _read(p).get(self.servers_key, {}).get(SERVER_NAME)
        if cur is None:
            return "Not configured" if (self.installed() or scope == "workspace") else "Not detected"
        want = self.entry()
        same = cur.get("command") == want["command"] and list(cur.get("args", [])) == want["args"]
        return "Configured" if same and Path(cur.get("command", "")).exists() else "Stale"

    def configure(self, scope="user", workspace=None) -> Path:
        p = self.path(scope, workspace)
        if p is None:
            raise ValueError(f"{self.name} has no {scope} configuration")
        data = _read(p)
        data.setdefault(self.servers_key, {})[SERVER_NAME] = self.entry()
        _write(p, data)
        return p

    def remove(self, scope="user", workspace=None) -> bool:
        p = self.path(scope, workspace)
        if p is None or not p.exists():
            return False
        data = _read(p)
        servers = data.get(self.servers_key, {})
        if SERVER_NAME not in servers:
            return False
        del servers[SERVER_NAME]
        _write(p, data)
        return True


CLIENTS = [
    Client("vscode", "GitHub Copilot (VS Code)", "{config}/Code/User/mcp.json", ".vscode/mcp.json", "servers",
           ("code", "{config}/Code")),
    Client("vscode-insiders", "GitHub Copilot (VS Code Insiders)", "{config}/Code - Insiders/User/mcp.json",
           ".vscode/mcp.json", "servers", ("code-insiders", "{config}/Code - Insiders")),
    Client("claude-code", "Claude Code", "{home}/.claude.json", ".mcp.json", "mcpServers",
           ("claude", "{home}/.claude")),
    Client("claude-desktop", "Claude Desktop", "{config}/Claude/claude_desktop_config.json", "", "mcpServers",
           ("claude-desktop", "{config}/Claude")),
    Client("cursor", "Cursor", "{home}/.cursor/mcp.json", ".cursor/mcp.json", "mcpServers",
           ("cursor", "{home}/.cursor")),
]


def _read(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise ValueError(f"{p} is not valid JSON ({e}); fix or remove it first") from e
    if not isinstance(data, dict):
        raise ValueError(f"{p} does not hold a JSON object")
    return data


def _write(p: Path, data: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = p.stat().st_mode & 0o777 if p.exists() else 0o600
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, p)


def chat_prompt():
    """What to paste into an assistant so it configures itself (as LTspice's dialog suggests)."""
    cmd, args = server_command()
    return (f'Add a local stdio MCP server named "{SERVER_NAME}" that runs the command "{cmd}" with the '
            f'arguments {json.dumps(args)}, in my user-level configuration so it is available in every project.')
