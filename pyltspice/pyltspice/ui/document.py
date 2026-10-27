"""A schematic open in the editor: model + undo history + scene."""
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from ..model import asc
from ..model.edit import cleanup_wires
from ..model.library import default_library, schematic_dirs
from .schematic_view import SchematicScene


class _Snapshot(QUndoCommand):
    """Undo step holding the schematic text before and after an edit."""

    def __init__(self, doc, before, after, label):
        super().__init__(label)
        self.doc, self.before, self.after = doc, before, after
        self._first = True

    def redo(self):
        if self._first:
            self._first = False
            return
        self.doc._restore(self.after)

    def undo(self):
        self.doc._restore(self.before)


class SchematicDocument(QObject):
    changed = Signal()

    def __init__(self, sch: asc.Schematic | None = None, lib=None):
        super().__init__()
        self.sch = sch or asc.Schematic(items=[])
        self.lib = lib or default_library()
        self.scene = SchematicScene(self.sch, self.lib)
        self.undo = QUndoStack(self)
        from .settings_dialog import get
        self.undo.setUndoLimit(get("drafting/undo_size"))
        self._before = None

    @classmethod
    def open(cls, path):
        return cls(asc.load_asc(path))

    @property
    def path(self) -> Path | None:
        return self.sch.path

    @property
    def title(self):
        return self.sch.path.name if self.sch.path else "Draft1.asc"

    @property
    def modified(self):
        return not self.undo.isClean()

    @property
    def local_dirs(self):
        return schematic_dirs(self.sch.path)

    # -- editing protocol: begin() ... mutate self.sch ... commit(label)
    def begin(self):
        if self._before is None:
            self._before = self.sch.to_text()

    def commit(self, label="Edit", cleanup=True):
        if cleanup:
            cleanup_wires(self.sch, self.lib, self.local_dirs)
        before, self._before = self._before, None
        after = self.sch.to_text()
        if before is not None and before != after:
            self.undo.push(_Snapshot(self, before, after, label))
        self.scene.rebuild()
        self.changed.emit()

    def abort(self):
        if self._before is not None:
            self._restore(self._before)
            self._before = None

    def _restore(self, text):
        fresh = asc.parse_asc(text)
        self.sch.items[:] = fresh.items
        self.sch.sheet = fresh.sheet
        self.scene.rebuild()
        self.changed.emit()

    def save(self, path=None):
        self.sch.save(path)
        self.undo.setClean()
        self.changed.emit()
