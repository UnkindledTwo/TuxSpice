"""LTspice-style "verb-noun" editing modes.

The user picks a command first (wire, move, delete...) and then the objects.
A mode stays active until right-click or Esc, exactly as in LTspice.
"""
import atexit

from PySide6.QtCore import QLineF, QMimeData, QPointF, QRectF, Qt
from PySide6.QtGui import QCursor, QPen
from PySide6.QtWidgets import QApplication

from ..model import asc
from ..model import edit as ed
from ..model.netlist import symbol_pins
from .theme import theme


ROTATE_HINT = "Type Ctrl+R to rotate or Ctrl+E to mirror."   # LTspice status text


def _box_pen():
    """LTspice draws selection boxes as a thin black dotted rectangle."""
    pen = QPen(Qt.black)
    pen.setCosmetic(True)
    pen.setStyle(Qt.DotLine)
    return pen


class Tool:
    cursor = Qt.ArrowCursor
    status = ""

    def __init__(self, win):
        self.win = win              # SchematicWindow
        self.doc = win.doc
        self.view = win.view
        self.mouse = QPointF()

    @property
    def scene(self):
        return self.doc.scene

    def activate(self):
        self.restore_cursor(self.view)

    def deactivate(self):
        pass

    def restore_cursor(self, view):
        view.viewport().setCursor(self.cursor)

    def exit(self):
        self.win.set_tool(None)

    def scene_pos(self, ev):
        return self.view.mapToScene(ev.position().toPoint())

    # event hooks: return True when handled
    def press(self, view, ev):
        if ev.button() == Qt.RightButton:
            self.exit()
            return True
        return False

    def move(self, view, ev):
        self.mouse = self.scene_pos(ev)

    def release(self, view, ev):
        pass

    def double_click(self, view, ev):
        pass

    def key(self, view, ev):
        if ev.key() == Qt.Key_Escape:
            self.exit()
            return True
        return False

    def paint_overlay(self, view, p):
        pass


# ---------------------------------------------------------------- idle / probe

class IdleTool(Tool):
    """No command active: right-click edits, left-drag pans (or drags an object),
    and after a simulation left-click probes nets and components."""
    cursor = Qt.ArrowCursor

    def press(self, view, ev):
        pos = self.scene_pos(ev)
        if ev.button() == Qt.RightButton:
            objs = self.scene.model_items_at(pos)
            if objs:
                self.win.edit_object(objs[0], ctrl=bool(ev.modifiers() & Qt.ControlModifier),
                                     at=pos)
            else:
                self.win.context_menu(ev.globalPosition().toPoint())
            return True
        if ev.button() == Qt.LeftButton and not self.win.probe_active():
            # LTspice 26: left-clicking an unconnected pin starts a wire from it
            p = self.view.snap(pos)
            pin = (int(p.x()), int(p.y()))
            near = (self.view.mapFromScene(p) - self.view.mapFromScene(pos)).manhattanLength() <= 8
            if near and self.scene.conn is not None and pin in self.scene.conn.unconnected:
                wire = WireTool(self.win)
                self.win.set_tool(wire)
                wire.start = p
                wire.horizontal_first = None
                wire._locked_dir = False
                return True
        if ev.button() == Qt.LeftButton and self.win.probe_active():
            objs = self.scene.model_items_at(pos)
            if objs or self.scene.conn.net_at(*self._snap(pos)):
                self.win.probe(pos, objs, alt=bool(ev.modifiers() & Qt.AltModifier))
                return True
        return False

    def _snap(self, p):
        q = self.view.snap(p)
        return int(q.x()), int(q.y())

    def move(self, view, ev):
        super().move(view, ev)
        ops = self.scene.op_values
        if ops:
            objs = self.scene.model_items_at(self.mouse)
            net = None
            for o in objs:
                if isinstance(o, asc.Wire):
                    net = self.scene.conn.net_at(o.x1, o.y1)
                elif isinstance(o, asc.Flag):
                    net = self.scene.conn.net_at(o.x, o.y)
                if net:
                    break
            if net and net != "0" and f"v({net})".lower() in ops:
                from ..sim.spicenum import fmt
                self.win.status.emit(f"V({net}) = {fmt(ops[f'v({net})'.lower()], 'V', 6)}")
        if self.win.probe_active():
            pos = self.mouse
            objs = self.scene.model_items_at(pos)
            if objs and isinstance(objs[0], asc.SymbolInst):
                view.viewport().setCursor(self.win.cursors["current"])
                self.win.status.emit(self.win.probe_hint(objs[0]))
            elif objs and isinstance(objs[0], (asc.Wire, asc.Flag)):
                view.viewport().setCursor(self.win.cursors["voltage"])
                self.win.status.emit(self.win.probe_hint(objs[0]))
            else:
                # LTspice shows a crosshair over a schematic that has simulation results
                view.viewport().setCursor(self.win.cursors["cross"])

    def double_click(self, view, ev):
        objs = self.scene.model_items_at(self.scene_pos(ev), (asc.SymbolInst,))
        if objs:
            self.win.descend(objs[0])


# ---------------------------------------------------------------- placing

class PlaceTool(Tool):
    """Carries new objects with the mouse; each click drops a copy.

    factory() returns fresh model objects positioned around (0, 0)."""
    cursor = Qt.BlankCursor

    def __init__(self, win, factory, repeat=True, label="Place"):
        super().__init__(win)
        self.factory = factory
        self.repeat = repeat
        self.label = label
        self.objs = []
        self.items = []
        self.orient_ops = []        # rotations/mirrors applied, replayed on new copies

    def activate(self):
        super().activate()
        self._new_sprite()
        self.view.setFocus()

    def deactivate(self):
        self._clear_items()

    def _clear_items(self):
        for it in self.items:
            if it.scene():
                self.scene.removeItem(it)
        self.items = []

    status = ROTATE_HINT

    def _new_sprite(self):
        self.objs = self.factory()
        for op in self.orient_ops:
            op(self.objs, 0, 0)
        self._relayout()
        for o in self.objs:
            # the sprite already shows the name it will get (R1, R2...)
            if isinstance(o, asc.SymbolInst) and not o.attrs.get("InstName"):
                sym = self.doc.lib.get(o.symbol, self.doc.local_dirs)
                o.attrs = {"InstName": ed.next_name(self.doc.sch, ed.name_prefix(sym, o)), **o.attrs}
        self._make_items()

    def _relayout(self):
        for o in self.objs:
            if isinstance(o, asc.SymbolInst):
                ed.relayout_windows(o, self.doc.lib.get(o.symbol, self.doc.local_dirs))

    def _grab_offset(self) -> QPointF:
        """LTspice carries a new part by its middle: the origin is snapped to the grid point
        that puts the part's centre nearest the cursor."""
        pts = []
        for o in self.objs:
            if isinstance(o, asc.SymbolInst):
                sym = self.doc.lib.get(o.symbol, self.doc.local_dirs)
                if sym is not None:
                    x0, y0, x1, y1 = sym.bbox()
                    from ..model.geometry import apply, orient_matrix
                    m = orient_matrix(o.orient)
                    for x, y in ((x0, y0), (x1, y1)):
                        rx, ry = apply(m, x, y)
                        pts.append((o.x + rx, o.y + ry))
                    continue
            pts += ed.points_of(o)
        if not pts:
            return QPointF()
        xs = [x for x, _ in pts]
        ys = [y for _, y in pts]
        return QPointF((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)

    def _pin_points(self):
        out = []
        for o in self.objs:
            if isinstance(o, asc.SymbolInst):
                sym = self.doc.lib.get(o.symbol, self.doc.local_dirs)
                out += [QPointF(*pr.point) for pr in symbol_pins(o, sym)]
        return out

    def _make_items(self):
        self._clear_items()
        for o in self.objs:
            it = self.scene._make_item(o, {})
            if it is not None:
                it.set_highlight(False)
                self.scene.addItem(it)
                self.items.append(it)
        self._follow()

    def _follow(self):
        p = self.view.snap(self.mouse - self._grab_offset())
        for it in self.items:
            it.setPos(p)

    def move(self, view, ev):
        super().move(view, ev)
        self._follow()
        view.viewport().update()

    def press(self, view, ev):
        if ev.button() == Qt.RightButton:
            self.exit()
            return True
        if ev.button() != Qt.LeftButton:
            return False
        p = self.view.snap(self.scene_pos(ev) - self._grab_offset())
        self.doc.begin()
        for o in self.objs:
            ed.translate(o, int(p.x()), int(p.y()))
        # re-number in case the sheet changed meanwhile
        ed.rename_copies(self.doc.sch, self.objs, self.doc.lib, self.doc.local_dirs)
        self.doc.sch.items += self.objs
        self._clear_items()
        self.doc.commit(self.label)
        if self.repeat:
            self._new_sprite()
        else:
            self.exit()
        return True

    def key(self, view, ev):
        ctrl = ev.modifiers() & Qt.ControlModifier
        if ctrl and ev.key() in (Qt.Key_R, Qt.Key_E):
            self.orient(ev.key() == Qt.Key_E)
            return True
        return super().key(view, ev)

    def orient(self, mirror=False):
        """Ctrl+R / Ctrl+E (or the toolbar buttons) while carrying the new part."""
        op = ed.mirror if mirror else ed.rotate
        self.orient_ops.append(op)
        op(self.objs, 0, 0)
        self._relayout()
        self._make_items()
        self.view.viewport().update()

    def paint_overlay(self, view, p):
        # unconnected pins of the part being placed get LTspice's little squares
        d = self.view.snap(self.mouse - self._grab_offset())
        pen = QPen(theme().color("unconnected"))
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for pt in self._pin_points():
            c = pt + d
            p.drawRect(QRectF(c.x() - 4, c.y() - 4, 8, 8))


# ---------------------------------------------------------------- wires

class WireTool(Tool):
    cursor = Qt.BlankCursor      # the full-view crosshair is the cursor, as in LTspice
    status = ""

    def __init__(self, win):
        super().__init__(win)
        self.start = None
        self.horizontal_first = None

    def _ortho(self):
        from PySide6.QtWidgets import QApplication
        from .settings_dialog import get
        ortho = get("drafting/ortho_wires")
        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            ortho = not ortho          # Ctrl momentarily toggles the setting
        return ortho

    def _route(self, a: QPointF, b: QPointF):
        """Orthogonal L-route from a to b (or a straight segment when snapping is off)."""
        if a.x() == b.x() or a.y() == b.y() or not self._ortho():
            return [(a, b)]
        if self.horizontal_first is None:
            # on a diagonal first move LTspice leaves vertically
            self.horizontal_first = abs(b.x() - a.x()) > abs(b.y() - a.y())
        corner = QPointF(b.x(), a.y()) if self.horizontal_first else QPointF(a.x(), b.y())
        return [(a, corner), (corner, b)]

    def _is_connection(self, p: QPointF):
        x, y = int(p.x()), int(p.y())
        sch = self.doc.sch
        for w in sch.wires:
            if (x, y) in ((w.x1, w.y1), (w.x2, w.y2)):
                return True
            from ..model.netlist import _on_segment
            if _on_segment(x, y, w):
                return True
        for f in sch.flags:
            if (f.x, f.y) == (x, y):
                return True
        return any(pr.point == (x, y) for pr in self.scene.conn.pins)

    def press(self, view, ev):
        p = self.view.snap(self.scene_pos(ev))
        if ev.button() == Qt.RightButton:
            if self.start is not None:
                self.start = None
                view.viewport().update()
            else:
                self.exit()
            return True
        if ev.button() != Qt.LeftButton:
            return False
        if self.start is None:
            self.start = p
            self.horizontal_first = None
            self._locked_dir = False
            return True
        if p == self.start:
            return True
        connected = self._is_connection(p)     # check before adding the new segments
        route = [(a, b) for a, b in self._route(self.start, p) if a != b]
        if not connected and len(route) == 2:
            # LTspice commits only the first leg of the L; the corner becomes the new start
            # and the second leg stays live, so the next click can still bend it.
            route = route[:1]
            next_start, next_dir = route[0][1], route[0][0].y() == route[0][1].y()
        else:
            next_start, next_dir = (None if connected else p), None
        self.doc.begin()
        for a, b in route:
            self.doc.sch.items.append(asc.Wire(int(a.x()), int(a.y()), int(b.x()), int(b.y())))
        self.doc.commit("Draw Wire")
        self.start = next_start
        # after a horizontal leg the live wire leaves vertically (and vice versa)
        self.horizontal_first = None if next_dir is None else not next_dir
        self._locked_dir = next_dir is not None
        return True

    def move(self, view, ev):
        super().move(view, ev)
        if self.start is not None:
            d = self.view.snap(self.mouse) - self.start
            if self.horizontal_first is not None and abs(d.x()) < 1 and abs(d.y()) < 1:
                if not getattr(self, "_locked_dir", False):
                    self.horizontal_first = None
            elif self.horizontal_first is None and (abs(d.x()) >= 1 or abs(d.y()) >= 1):
                # the first move away from the start point sets which leg comes first
                self.horizontal_first = abs(d.x()) > abs(d.y())
        view.viewport().update()

    def key(self, view, ev):
        if ev.key() == Qt.Key_Escape and self.start is not None:
            self.start = None
            view.viewport().update()
            return True
        return super().key(view, ev)

    def paint_overlay(self, view, p):
        cur = self.view.snap(self.mouse)
        pen = QPen(theme().color("wire"))
        pen.setCosmetic(True)
        pen.setWidthF(2)             # the wire being drawn is bold until it is committed
        p.setPen(pen)
        if self.start is not None:
            for a, b in self._route(self.start, cur):
                p.drawLine(QLineF(a, b))
        # crosshair cursor spanning the view, like LTspice
        r = view.mapToScene(view.viewport().rect()).boundingRect()
        pen.setWidthF(0)
        pen.setColor(Qt.black)
        pen.setStyle(Qt.DotLine)
        p.setPen(pen)
        p.drawLine(QLineF(r.left(), cur.y(), r.right(), cur.y()))
        p.drawLine(QLineF(cur.x(), r.top(), cur.x(), r.bottom()))


# ---------------------------------------------------------------- selection-based tools

class _BoxSelectTool(Tool):
    """Click an object or drag a box; subclasses act on the selection."""

    def __init__(self, win):
        super().__init__(win)
        self.box_from = None
        self.hover = []

    def picked(self, objs, box: QRectF | None):
        raise NotImplementedError

    def press(self, view, ev):
        if ev.button() == Qt.RightButton:
            self.exit()
            return True
        if ev.button() != Qt.LeftButton:
            return False
        self.box_from = self.scene_pos(ev)
        return True

    def move(self, view, ev):
        super().move(view, ev)       # LTspice doesn't highlight what's under the cursor
        view.viewport().update()

    def release(self, view, ev):
        if self.box_from is None or ev.button() != Qt.LeftButton:
            return
        a, b = self.box_from, self.scene_pos(ev)
        self.box_from = None
        if (view.mapFromScene(a) - view.mapFromScene(b)).manhattanLength() < 4:
            objs = self.scene.model_items_at(a)[:1]
            box = None
        else:
            box = QRectF(a, b).normalized()
            objs = self.scene.model_items_in(box)
        self.scene.set_highlight([])
        self.hover = []
        if objs:
            self.picked(objs, box)
        view.viewport().update()

    def paint_overlay(self, view, p):
        if self.box_from is not None:
            p.setPen(_box_pen())
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self.box_from, self.mouse).normalized())

    def deactivate(self):
        self.scene.set_highlight([])


class ZoomAreaTool(Tool):
    """View > Zoom Area: drag a box and zoom in on it, then return to idle."""
    status = "Drag a box and zoom in"

    def __init__(self, win):
        super().__init__(win)
        self.cursor = win.cursors["zoom"]
        self.box_from = None

    def press(self, view, ev):
        if ev.button() != Qt.LeftButton:
            return super().press(view, ev)
        self.box_from = self.scene_pos(ev)
        return True

    def move(self, view, ev):
        super().move(view, ev)
        if self.box_from is not None:
            view.viewport().update()

    def release(self, view, ev):
        if self.box_from is None or ev.button() != Qt.LeftButton:
            return
        box = QRectF(self.box_from, self.scene_pos(ev)).normalized()
        self.box_from = None
        if box.width() > 2 and box.height() > 2:
            view.remember_view()
            view.fitInView(box, Qt.KeepAspectRatio)
        self.exit()

    def paint_overlay(self, view, p):
        if self.box_from is not None:
            p.setPen(_box_pen())
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self.box_from, self.mouse).normalized())


class DeleteTool(_BoxSelectTool):
    status = "Click or drag a box to delete"

    def __init__(self, win):
        super().__init__(win)
        self.cursor = win.cursors["scissors"]

    def picked(self, objs, box):
        self.doc.begin()
        ids = {id(o) for o in objs}
        self.doc.sch.items[:] = [i for i in self.doc.sch.items if id(i) not in ids]
        self.doc.commit("Delete")


CLIP_MIME = "application/x-tuxspice-asc"


def copy_to_clipboard(objs):
    """Duplicate also puts what it picked on the clipboard, as .asc text, so Ctrl+V can
    paste it into another schematic (LTspice: "copy from one schematic to another")."""
    mime = QMimeData()
    mime.setData(CLIP_MIME, asc.Schematic(items=list(objs)).to_text().encode("utf-8"))
    QApplication.clipboard().setMimeData(mime)
    atexit.unregister(_release_clipboard)
    atexit.register(_release_clipboard)


def _release_clipboard():
    """Qt destroys the clipboard in C exit handlers, after Python is gone; deleting a
    Python-made QMimeData then segfaults. Drop ours while the interpreter still runs."""
    app = QApplication.instance()
    if app is not None and clipboard_has_objects():
        app.clipboard().clear()


def clipboard_has_objects():
    mime = QApplication.clipboard().mimeData()
    return mime is not None and mime.hasFormat(CLIP_MIME)


def clipboard_objects():
    """Objects last picked with Duplicate (in any TuxSpice window), or [] if none."""
    if not clipboard_has_objects():
        return []
    mime = QApplication.clipboard().mimeData()
    return asc.parse_asc(bytes(mime.data(CLIP_MIME)).decode("utf-8", "replace")).items


class PasteTool(PlaceTool):
    """Edit > Paste (Ctrl+V): carries the clipboard's objects by their middle, one click drops
    them. Parts get fresh names; their letter prefix (R, XU...) is kept."""

    def __init__(self, win, objs):
        cx, cy = ed.group_center(objs)
        for o in objs:
            ed.translate(o, -cx, -cy)
        self.template = objs
        super().__init__(win, self._copies, repeat=False, label="Paste")

    def _copies(self):
        objs = ed.clone(self.template)
        ed.rename_copies(self.doc.sch, objs, self.doc.lib, self.doc.local_dirs)
        return objs


class MoveTool(_BoxSelectTool):
    """Move (F7), Drag (F8, wires stay attached) and Duplicate (F6)."""

    def __init__(self, win, mode="move"):
        super().__init__(win)
        self.mode = mode
        self.cursor = win.cursors[{"drag": "drag", "duplicate": "duplicate"}.get(mode, "move")]
        self.carry = None           # list of objects being carried
        self.anchor = None
        self.stretch = []           # (wire, end index 0/1) endpoints dragged along
        self.fixed_wire_items = []

    @property
    def status(self):
        return ROTATE_HINT if self.carry is not None else ""

    @property
    def label(self):
        return {"move": "Move", "drag": "Stretch", "duplicate": "Duplicate"}[self.mode]

    def picked(self, objs, box):
        self.doc.begin()
        if self.mode == "duplicate":
            copy_to_clipboard(objs)
            objs = ed.clone(objs)
            ed.rename_copies(self.doc.sch, objs, self.doc.lib, self.doc.local_dirs)
        self.carry = objs
        self.anchor = self.view.snap(self.mouse)
        self.win.mode_changed.emit()
        self.stretch = []
        if self.mode == "drag":
            self.stretch = self._find_stretch(objs, box)
            # wires with only one end inside the box are stretched, not moved
            if box is not None:
                self.carry = [o for o in objs if not isinstance(o, asc.Wire) or
                              all(box.contains(QPointF(*pt)) for pt in ed.points_of(o))]
                for w in objs:
                    if isinstance(w, asc.Wire) and w not in self.carry:
                        for i, pt in enumerate(ed.points_of(w)):
                            if box.contains(QPointF(*pt)) and (w, i) not in self.stretch:
                                self.stretch.append((w, i))
        self._make_carry_items()

    def _find_stretch(self, objs, box):
        pts = set()
        for o in objs:
            if isinstance(o, asc.SymbolInst):
                sym = self.doc.lib.get(o.symbol, self.doc.local_dirs)
                pts |= {pr.point for pr in symbol_pins(o, sym)}
            else:
                pts |= set(ed.points_of(o))
        out = []
        moving = {id(o) for o in objs}
        for w in self.doc.sch.wires:
            if id(w) in moving:
                continue
            for i, pt in enumerate(ed.points_of(w)):
                if pt in pts:
                    out.append((w, i))
        return out

    def _make_carry_items(self):
        self.items = []
        for o in self.carry:
            it = self.scene.item_of.get(id(o))
            if it is None:
                it = self.scene._make_item(o, {})
                self.scene.addItem(it)
            it.set_highlight(False)     # carried parts keep their colours in LTspice
            self.items.append(it)
        for w, _ in self.stretch:
            it = self.scene.item_of.get(id(w))
            if it is not None:
                it.setVisible(False)
        self._follow()

    def _offset(self):
        return self.view.snap(self.mouse) - self.anchor

    def _follow(self):
        d = self._offset()
        for it in self.items:
            it.setPos(d)

    def move(self, view, ev):
        if self.carry is not None:
            self.mouse = self.scene_pos(ev)
            self._follow()
            view.viewport().update()
            return
        super().move(view, ev)

    def press(self, view, ev):
        if self.carry is None:
            return super().press(view, ev)
        if ev.button() == Qt.RightButton:
            self._cancel()
            return True
        if ev.button() == Qt.LeftButton:
            d = self._offset()
            dx, dy = int(d.x()), int(d.y())
            for o in self.carry:
                ed.translate(o, dx, dy)
            for w, i in self.stretch:
                pts = ed.points_of(w)
                pts[i] = (pts[i][0] + dx, pts[i][1] + dy)
                ed.set_points(w, pts)
            if self.mode == "duplicate":
                self.doc.sch.items += self.carry
            self.carry = None
            self.doc.commit(self.label)
            self.win.status.emit("")
            self.win.mode_changed.emit()
            return True
        return True

    def release(self, view, ev):
        if self.carry is None:
            super().release(view, ev)

    def _cancel(self):
        self.carry = None
        self.doc.abort()
        self.win.mode_changed.emit()

    def key(self, view, ev):
        ctrl = ev.modifiers() & Qt.ControlModifier
        if self.carry is not None and ctrl and ev.key() in (Qt.Key_R, Qt.Key_E):
            self.orient(ev.key() == Qt.Key_E)
            return True
        if ev.key() == Qt.Key_Escape and self.carry is not None:
            self._cancel()
            return True
        return super().key(view, ev)

    def orient(self, mirror=False):
        if self.carry is None:
            return
        cx, cy = ed.group_center(self.carry)
        (ed.mirror if mirror else ed.rotate)(self.carry, cx, cy)
        for o in self.carry:
            if isinstance(o, asc.SymbolInst):
                ed.relayout_windows(o, self.doc.lib.get(o.symbol, self.doc.local_dirs))
        # carried items must be rebuilt from the changed model
        for it in self.items:
            if it.scene():
                self.scene.removeItem(it)
        for o in self.carry:
            self.scene.item_of.pop(id(o), None)
        self._make_carry_items()
        self.view.viewport().update()

    def carried_pins(self):
        """Pin points of the parts being carried (their markers move with them)."""
        if self.carry is None:
            return set()
        pts = set()
        for o in self.carry:
            if isinstance(o, asc.SymbolInst):
                sym = self.doc.lib.get(o.symbol, self.doc.local_dirs)
                pts |= {pr.point for pr in symbol_pins(o, sym)}
        return pts

    def paint_overlay(self, view, p):
        super().paint_overlay(view, p)
        if self.carry is not None and view.mark_unconnected and self.scene.conn is not None:
            d = self._offset()
            pen = QPen(theme().color("unconnected"))
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            open_pins = set(self.scene.conn.unconnected)
            for x, y in self.carried_pins() & open_pins:
                p.drawRect(QRectF(x + d.x() - 4, y + d.y() - 4, 8, 8))
        if self.carry is None or not self.stretch:
            return
        d = self._offset()
        pen = QPen(theme().color("wire"))
        pen.setCosmetic(True)
        p.setPen(pen)
        for w, i in self.stretch:
            pts = [QPointF(*pt) for pt in ed.points_of(w)]
            pts[i] = pts[i] + d
            p.drawLine(QLineF(pts[0], pts[1]))

    def deactivate(self):
        if self.carry is not None:
            self._cancel()
        super().deactivate()


# ---------------------------------------------------------------- drawing (Edit > Draw)

class DrawTool(Tool):
    """Line / Rectangle / Circle: click two corners. Arc: two bbox corners, then the
    start and end points (drawn counter-clockwise from start to end, as in LTspice)."""
    cursor = Qt.CrossCursor

    def __init__(self, win, kind):
        super().__init__(win)
        self.kind = kind
        self.pts = []

    @property
    def status(self):
        need = 4 if self.kind == "ARC" else 2
        return f"Draw {self.kind.title()}: click point {len(self.pts) + 1} of {need}"

    def press(self, view, ev):
        if ev.button() == Qt.RightButton:
            if self.pts:
                self.pts = []
                view.viewport().update()
            else:
                self.exit()
            return True
        if ev.button() != Qt.LeftButton:
            return False
        p = self.view.snap(self.scene_pos(ev))
        self.pts.append((int(p.x()), int(p.y())))
        need = 4 if self.kind == "ARC" else 2
        if len(self.pts) == need:
            coords = [v for pt in self.pts for v in pt]
            self.doc.begin()
            style = getattr(self.win.main, "line_style", 0)
            self.doc.sch.items.append(asc.Graphic(self.kind, coords, style))
            self.doc.commit(f"Draw {self.kind.title()}", cleanup=False)
            self.pts = []
        self.win.status.emit(self.status)
        return True

    def move(self, view, ev):
        super().move(view, ev)
        view.viewport().update()

    def paint_overlay(self, view, p):
        if not self.pts:
            return
        from .render import shape_path
        cur = self.view.snap(self.mouse)
        pts = self.pts + [(int(cur.x()), int(cur.y()))]
        pen = QPen(theme().color("graphic"))
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if self.kind == "ARC" and len(pts) >= 3:
            c = [v for pt in pts[:2] for v in pt]
            start = pts[2]
            end = pts[3] if len(pts) > 3 else pts[2]
            if len(pts) == 3:          # show the full ellipse while choosing the start
                p.drawPath(shape_path("CIRCLE", c))
            else:
                p.drawPath(shape_path("ARC", c + list(start) + list(end)))
            return
        kind = "RECTANGLE" if self.kind == "ARC" else self.kind
        p.drawPath(shape_path(kind, [v for pt in pts[:2] for v in pt]))
