"""MCP (Model Context Protocol) support: AI assistants can read, edit and simulate designs.

LTspice 26.1 ships an MCP server (``ltspice-mcp-bridge.exe``) and Tools > Configure Third-Party AI
Assistants. TuxSpice offers the same tool names, arguments and replies (observed by talking to
LTspice's bridge under Wine), so prompts and workflows written for LTspice work here:

- ``bridge.py``: the stdio server an AI tool launches (``pyltspice-mcp``). It attaches to a running
  TuxSpice window if there is one, otherwise it works headless in its own process.
- ``tools.py``: tool schemas and their implementation over a backend.
- ``headless.py``: the backend without a GUI. The GUI backend is ``ui/mcp_host.py``.
- ``registry.py``: how bridges find running TuxSpice windows (localhost port + token).
- ``clients.py``: reading and writing the MCP configuration of AI tools.
"""
SERVER_NAME = "tuxspice"
