"""Tools > Configure Third-Party AI Assistants (LTspice 26.1 layout, from help/Third_Party_AI_Tools.htm),
and the one-time offer at startup to configure assistants that were found but aren't set up."""
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..mcp import clients


class AiAssistantsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Third-Party AI Assistants")
        lay = QVBoxLayout(self)
        intro = QLabel("Configure third-party AI assistants to work directly with TuxSpice using MCP. Select the "
                       "scope, check the tools you want to configure, then click Configure or Remove. Undetected "
                       "assistants can still be force-configured.\n\nThird-party product names are the trademarks "
                       "of their respective owners. No affiliation or endorsement is implied.\n\nAn assistant "
                       "processes what it reads on its provider's servers: don't connect one to designs you "
                       "aren't free to share with that provider.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        box = QGroupBox("Scope")
        g = QVBoxLayout(box)
        self.user = QRadioButton("User (global)")
        self.user.setChecked(True)
        g.addWidget(self.user)
        row = QHBoxLayout()
        self.ws = QRadioButton("Workspace")
        row.addWidget(self.ws)
        self.ws_path = QLineEdit()
        row.addWidget(self.ws_path, 1)
        self.browse = QPushButton("Browse...")
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.browse)
        g.addLayout(row)
        grp = QButtonGroup(self)
        grp.addButton(self.user)
        grp.addButton(self.ws)
        self.user.toggled.connect(self._scope_changed)
        self.ws_path.editingFinished.connect(self.refresh)
        lay.addWidget(box)
        self.table = QTableWidget(len(clients.CLIENTS), 3)
        self.table.setHorizontalHeaderLabels(["Assistant", "Installed", "Status"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.checks = []
        for r, c in enumerate(clients.CLIENTS):
            cb = QCheckBox(c.name)
            self.checks.append(cb)
            self.table.setCellWidget(r, 0, cb)
        self.table.resizeRowsToContents()
        h = self.table.horizontalHeader().height() + sum(self.table.rowHeight(r) for r in range(self.table.rowCount()))
        self.table.setMinimumHeight(h + 4)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, slot in (("Configure", self._configure), ("Remove", self._remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel("Event log:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        lay.addWidget(self.log)
        lay.addWidget(QLabel("Assistants may also be configurable from the chat itself. For example, copy and "
                             "paste this prompt:"))
        prompt = QPlainTextEdit(clients.chat_prompt())
        prompt.setReadOnly(True)
        prompt.setMaximumHeight(64)
        lay.addWidget(prompt)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)
        self._scope_changed()
        self.resize(560, 680)

    def scope(self):
        return ("user", None) if self.user.isChecked() else ("workspace", self.ws_path.text().strip() or None)

    def _scope_changed(self, *_):
        on = self.ws.isChecked()
        self.ws_path.setEnabled(on)
        self.browse.setEnabled(on)
        self.refresh()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Workspace folder", self.ws_path.text())
        if d:
            self.ws_path.setText(d)
            self.ws.setChecked(True)
            self.refresh()

    def refresh(self):
        scope, ws = self.scope()
        for r, c in enumerate(clients.CLIENTS):
            inst = c.installed()
            try:
                st = c.status(scope, ws) if scope == "user" or ws else "Choose a folder"
            except ValueError as e:
                st = "Unreadable"
                self.log.appendPlainText(str(e))
            self.table.setItem(r, 1, QTableWidgetItem("Yes" if inst else "No"))
            self.table.setItem(r, 2, QTableWidgetItem(st))
            if st == "Configured" and not self.checks[r].isChecked():
                self.checks[r].setChecked(True)

    def _each(self, action):
        scope, ws = self.scope()
        if scope == "workspace" and not ws:
            self.log.appendPlainText("Choose a workspace folder first.")
            return
        for c, cb in zip(clients.CLIENTS, self.checks):
            if not cb.isChecked():
                continue
            try:
                msg = action(c, scope, ws)
            except (OSError, ValueError) as e:
                msg = f"{c.name}: {e}"
            if msg:
                self.log.appendPlainText(msg)
        self.refresh()

    def _configure(self):
        def do(c, scope, ws):
            if c.status(scope, ws) == "Configured":
                return f"{c.name}: already configured"
            p = c.configure(scope, ws)
            return f"{c.name}: configured in {p}. Restart it if it is running."
        self._each(do)

    def _remove(self):
        def do(c, scope, ws):
            return f"{c.name}: removed" if c.remove(scope, ws) else f"{c.name}: was not configured"
        self._each(do)


def offer_at_startup(parent):
    """Like LTspice: once per tool, offer to configure assistants that are installed but not set up."""
    from PySide6.QtWidgets import QDialogButtonBox
    s = QSettings("pyltspice", "pyltspice")
    todo = []
    for c in clients.CLIENTS:
        if s.value(f"mcp/asked/{c.key}", False) in (True, "true"):
            continue
        try:
            if c.installed() and c.status() in ("Not configured", "Stale"):
                todo.append(c)
        except ValueError:
            continue
    if not todo:
        return
    dlg = QDialog(parent)
    dlg.setWindowTitle("TuxSpice")
    lay = QVBoxLayout(dlg)
    text = QLabel("TuxSpice can work with AI assistants through MCP: they can read, edit and simulate your "
                  "open designs, and their edits can be undone with Ctrl+Z. These assistants were found on "
                  "this computer. Configure them to use TuxSpice?\n\nAn assistant sends what it reads to its "
                  "provider. You can change this later in Tools > Configure Third-Party AI Assistants.")
    text.setWordWrap(True)
    lay.addWidget(text)
    boxes = []
    for c in todo:
        cb = QCheckBox(c.name)
        cb.setChecked(True)
        boxes.append((c, cb))
        lay.addWidget(cb)
    bb = QDialogButtonBox()
    bb.addButton("Configure", QDialogButtonBox.AcceptRole)
    bb.addButton("Not now", QDialogButtonBox.RejectRole)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    ok = dlg.exec() == QDialog.Accepted
    for c, cb in boxes:
        s.setValue(f"mcp/asked/{c.key}", True)
        if ok and cb.isChecked():
            try:
                c.configure()
            except (OSError, ValueError):
                pass
