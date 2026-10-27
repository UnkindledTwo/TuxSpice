"""Autosave and crash recovery (a TuxSpice extra; LTspice has neither).

Every few minutes (Settings > TuxSpice) each schematic with unsaved changes is copied to
$XDG_STATE_HOME/pyltspice/autosave as <id>.asc plus <id>.json (original path, title, time,
pid). The copy is deleted when the document becomes clean again (saved, or undone back to the
saved state) and when the user closes TuxSpice choosing not to save. A schematic window closed
with unsaved changes keeps its copy, so that work stays recoverable.

At the next start, copies left by a TuxSpice that is no longer running (it crashed, was killed
by the OOM killer, or the session ended) are offered for recovery. A recovered schematic opens
under its original path, marked modified; Undo shows the version on disk."""
import json
import os
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox


def autosave_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "pyltspice" / "autosave"


def _alive(pid: int) -> bool:
    """True if pid is a running TuxSpice (pids get reused, so check what it runs)."""
    if pid == os.getpid():
        return True
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().lower()
    except OSError:
        return False
    return b"pyltspice" in cmd or b"tuxspice" in cmd


def pending() -> list:
    """[(meta, asc path, json path)] left behind by TuxSpice processes that have ended."""
    out = []
    d = autosave_dir()
    if not d.is_dir():
        return out
    for meta_path in sorted(d.glob("*.json")):
        asc_path = meta_path.with_suffix(".asc")
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            continue
        if not asc_path.exists() or _alive(int(meta.get("pid", 0))):
            continue
        out.append((meta, asc_path, meta_path))
    return sorted(out, key=lambda e: e[0].get("time", 0))


def _remove(*paths):
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass


class Autosaver(QObject):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.save_all)
        self.apply_settings()

    def apply_settings(self):
        from .settings_dialog import get
        minutes = get("tux/autosave_minutes")
        if minutes > 0:
            self.timer.start(int(minutes * 60_000))
        else:
            self.timer.stop()

    def track(self, sw):
        doc = sw.doc
        if not hasattr(doc, "autosave_id"):
            doc.autosave_id = uuid.uuid4().hex
            doc.undo.cleanChanged.connect(lambda clean, d=doc: clean and self.discard(d))
        sw.destroyed.connect(lambda *_, d=doc: self._closed(d))

    def _closed(self, doc):
        try:
            if doc.modified and self.timer.isActive():
                self.save(doc)
            else:
                self.discard(doc)
        except RuntimeError:          # Qt side already gone at exit
            pass

    def _paths(self, doc):
        d = autosave_dir()
        return d / f"{doc.autosave_id}.asc", d / f"{doc.autosave_id}.json"

    def save(self, doc):
        asc_path, meta_path = self._paths(doc)
        try:
            asc_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = asc_path.with_suffix(".tmp")
            tmp.write_text(doc.sch.to_text(), encoding="utf-8")
            tmp.replace(asc_path)
            meta_path.write_text(json.dumps({
                "original": str(doc.path) if doc.path else None, "title": doc.title,
                "time": time.time(), "pid": os.getpid()}))
        except OSError:
            pass

    def save_all(self):
        from .schematic_window import SchematicWindow
        for sub in self.main.mdi.subWindowList():
            w = sub.widget()
            if isinstance(w, SchematicWindow) and w.doc.modified:
                self.save(w.doc)

    def discard(self, doc):
        if hasattr(doc, "autosave_id"):
            _remove(*self._paths(doc))

    def discard_open(self):
        """TuxSpice is closing and the user has answered for every open schematic."""
        from .schematic_window import SchematicWindow
        self.timer.stop()                 # windows destroyed from here on discard their copy
        for sub in self.main.mdi.subWindowList():
            w = sub.widget()
            if isinstance(w, SchematicWindow):
                self.discard(w.doc)


def offer_recovery(main):
    """Ask whether to reopen work a previous TuxSpice left unsaved. Returns how many opened."""
    items = pending()
    if not items:
        return 0
    lines = []
    for meta, _, _ in items:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(meta.get("time", 0)))
        lines.append(f"• {meta.get('original') or meta.get('title', 'untitled')}  ({when})")
    box = QMessageBox(QMessageBox.Question, "Recover Unsaved Work",
                      "TuxSpice found unsaved changes from an earlier session (it may have crashed, "
                      "been killed, or the window was closed without saving):\n\n" + "\n".join(lines),
                      parent=main)
    recover = box.addButton("Recover", QMessageBox.AcceptRole)
    discard = box.addButton("Discard", QMessageBox.DestructiveRole)
    box.addButton("Later", QMessageBox.RejectRole)
    box.setDefaultButton(recover)
    box.exec()
    if box.clickedButton() is discard:
        for _, a, m in items:
            _remove(a, m)
        return 0
    if box.clickedButton() is not recover:
        return 0
    n = 0
    for meta, asc_path, meta_path in items:
        try:
            main.recover_document(asc_path.read_text(encoding="utf-8"), meta.get("original"))
        except (OSError, ValueError) as e:
            QMessageBox.warning(main, "Recover Unsaved Work", f"Could not recover {asc_path.name}: {e}")
            continue
        _remove(asc_path, meta_path)
        n += 1
    return n
