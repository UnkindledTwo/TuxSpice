"""Schematic scene (model -> items) and the zoom/pan view."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen, QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ..model import asc
from ..model.geometry import GRID, apply, orient_matrix
from ..model.library import default_library, schematic_dirs
from ..model.netlist import connectivity
from .items import (DataFlagItem, FlagItem, GraphicItem, JunctionItem, SymbolItem,
                    TextItem, WireItem)
from .theme import theme

_DIRS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
_OPP = {"up": "down", "down": "up", "left": "right", "right": "left"}


def _dir_of(dx, dy):
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "down" if dy > 0 else "up"


class SchematicScene(QGraphicsScene):
    changed_model = Signal()

    def __init__(self, sch: asc.Schematic, lib=None, parent=None):
        super().__init__(parent)
        self.sch = sch
        self.lib = lib or default_library()
        self.conn = None
        self.item_of = {}          # id(model obj) -> item
        self.op_values = {}        # 'v(out)' -> value, from the last .op run
        self.show_op_flags = True  # View > Show .op Data Flags
        self.rebuild()

    @property
    def local_dirs(self):
        return schematic_dirs(self.sch.path)

    def rebuild(self):
        self.clear()
        self.item_of = {}
        self.conn = connectivity(self.sch, self.lib)
        touching = self._touching_dirs()
        for obj in self.sch.items:
            item = self._make_item(obj, touching)
            if item is not None:
                self.addItem(item)
                self.item_of[id(obj)] = item
        self.addItem(JunctionItem(self.conn.junctions))
        r = self.itemsBoundingRect()
        self.setSceneRect(r.adjusted(-2000, -2000, 2000, 2000))
        self.changed_model.emit()

    def _make_item(self, obj, touching):
        if isinstance(obj, asc.Wire):
            return WireItem(obj)
        if isinstance(obj, asc.SymbolInst):
            return SymbolItem(obj, self.lib.get(obj.symbol, self.local_dirs))
        if isinstance(obj, asc.Flag):
            return FlagItem(obj, self._label_dir(touching.get((obj.x, obj.y), [])))
        if isinstance(obj, asc.Text):
            return TextItem(obj)
        if isinstance(obj, asc.Graphic):
            return GraphicItem(obj)
        if isinstance(obj, asc.DataFlag):
            return DataFlagItem(obj, self.data_flag_text(obj))
        return None

    def _touching_dirs(self):
        """Point -> directions in which wires/symbols leave that point."""
        out = {}
        for w in self.sch.wires:
            for (x, y), (ox, oy) in (((w.x1, w.y1), (w.x2, w.y2)), ((w.x2, w.y2), (w.x1, w.y1))):
                if (x, y) != (ox, oy):
                    out.setdefault((x, y), []).append(_dir_of(ox - x, oy - y))
        for pr in self.conn.pins:
            inst = pr.inst
            dx, dy = inst.x - pr.point[0], inst.y - pr.point[1]
            sym = self.lib.get(inst.symbol, self.local_dirs)
            if sym is not None:
                # head toward the body centre of the symbol
                x0, y0, x1, y1 = sym.bbox()
                cx, cy = apply(orient_matrix(inst.orient), (x0 + x1) / 2, (y0 + y1) / 2)
                dx, dy = inst.x + cx - pr.point[0], inst.y + cy - pr.point[1]
            if dx or dy:
                out.setdefault(pr.point, []).append(_dir_of(dx, dy))
        return out

    def data_flag_text(self, d: asc.DataFlag):
        """Value shown by a data flag: the node voltage there (empty expression) or
        the named quantity, after an .op run."""
        from ..sim.spicenum import fmt
        expr = d.expr.strip().strip('"')
        if not self.op_values or not self.show_op_flags:
            return None
        if not expr:
            net = self.conn.net_at(d.x, d.y) if self.conn else None
            if net is None:
                return None
            v = 0.0 if net == "0" else self.op_values.get(f"v({net})".lower())
            return None if v is None else fmt(v, "V", 4)
        v = self.op_values.get(expr.lower())
        return None if v is None else f"{expr} = {fmt(v, '', 4)}"

    @staticmethod
    def _label_dir(dirs):
        if not dirs:
            return "up"
        prefs = [_OPP[dirs[0]], "up", "right", "left", "down"]
        for d in prefs:
            if d not in dirs:
                return d
        return "up"

    # -- picking
    def model_items_at(self, pos: QPointF, kinds=None):
        out = []
        for it in self.items(pos):
            obj = getattr(it, "obj", None)
            if obj is not None and (kinds is None or isinstance(obj, kinds)):
                out.append(obj)
        return out

    def model_items_in(self, rect: QRectF, kinds=None):
        out = []
        for it in self.items(rect, Qt.IntersectsItemShape):
            obj = getattr(it, "obj", None)
            if obj is not None and (kinds is None or isinstance(obj, kinds)):
                out.append(obj)
        return out

    def set_highlight(self, objs):
        ids = {id(o) for o in objs}
        for key, item in self.item_of.items():
            item.set_highlight(key in ids)


class SchematicView(QGraphicsView):
    """Wheel zooms about the cursor, left-drag on empty paper pans (as in LTspice)."""
    mouse_moved = Signal(float, float)
    ZOOM_STEP = 1.25

    def __init__(self, scene: SchematicScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.show_grid = False
        self.mark_unconnected = False
        self.mark_anchors = False  # View > Mark Anchors (text justification anchor points)
        self.reverse_wheel = False
        self._scroll = (0, 0)      # Settings > Automatically scroll the view
        from PySide6.QtCore import QTimer
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(40)
        self._scroll_timer.timeout.connect(self._auto_scroll)
        self._history = []         # previous view transforms, for Zoom Back
        self._pan_from = None
        self.tool = None           # active editing tool (see tools.py)

    # -- view helpers
    def remember_view(self):
        center = self.mapToScene(self.viewport().rect().center())
        self._history.append((self.transform(), center))
        del self._history[:-50]

    def zoom_back(self):
        if self._history:
            t, center = self._history.pop()
            self.setTransform(t)
            self.centerOn(center)

    def zoom_to_fit(self):
        self.remember_view()
        sc = self.scene()
        rect = QRectF()
        for it in sc.items():
            rect = rect.united(it.sceneBoundingRect())
        if rect.isEmpty():
            rect = QRectF(-400, -300, 800, 600)
        self.fitInView(rect.adjusted(-48, -48, 48, 48), Qt.KeepAspectRatio)

    def zoom(self, factor, about: QPointF | None = None):
        self.remember_view()
        if about is None:
            about = self.mapToScene(self.viewport().rect().center())
        s = self.transform().m11() * factor
        if not 0.02 < s < 50:
            return
        vp = self.mapFromScene(about)
        self.scale(factor, factor)
        delta = self.mapToScene(vp) - about
        self.translate(delta.x(), delta.y())

    def pan_by(self, dx, dy):
        """Move the paper by (dx, dy) screen pixels."""
        s = self.transform().m11()
        self.translate(dx / s, dy / s)

    def snap(self, p: QPointF) -> QPointF:
        return QPointF(round(p.x() / GRID) * GRID, round(p.y() / GRID) * GRID)

    # -- painting
    def drawBackground(self, p: QPainter, rect: QRectF):
        p.fillRect(rect, theme().color("background"))
        if not self.show_grid:
            return
        s = self.transform().m11()
        step = GRID
        while step * s < 6:
            step *= 2
        p.setPen(theme().color("grid"))
        x0 = int(rect.left() // step) * step
        y0 = int(rect.top() // step) * step
        pts = []
        y = y0
        while y <= rect.bottom():
            x = x0
            while x <= rect.right():
                pts.append(QPointF(x, y))
                x += step
            y += step
        p.drawPoints(pts)

    # -- events
    def wheelEvent(self, ev):
        d = ev.angleDelta().y()
        if not d:
            return
        zoom_in = (d < 0) != self.reverse_wheel   # pulling the wheel toward you zooms in
        about = self.mapToScene(ev.position().toPoint())
        self.zoom(self.ZOOM_STEP if zoom_in else 1 / self.ZOOM_STEP, about)

    def mousePressEvent(self, ev):
        if self.tool and self.tool.press(self, ev):
            return
        if ev.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._pan_from = ev.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)

    def _auto_scroll(self):
        dx, dy = self._scroll
        if not (dx or dy) or not self.underMouse():
            self._scroll_timer.stop()
            return
        self.pan_by(-dx, -dy)
        if self.tool:
            self.tool.mouse = self.mapToScene(self.mapFromGlobal(self.cursor().pos()))
        self.viewport().update()

    def _check_edge(self, pos):
        """While a command is active, the view scrolls when the mouse nears an edge."""
        from .settings_dialog import get
        busy = self.tool is not None and type(self.tool).__name__ not in ("IdleTool", "ZoomAreaTool")
        if not busy or not get("drafting/autoscroll"):
            self._scroll = (0, 0)
            return
        r, m, step = self.viewport().rect(), 10, 12
        dx = -step if pos.x() < m else step if pos.x() > r.width() - m else 0
        dy = -step if pos.y() < m else step if pos.y() > r.height() - m else 0
        self._scroll = (dx, dy)
        if (dx or dy) and not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def mouseMoveEvent(self, ev):
        sp = self.mapToScene(ev.position().toPoint())
        self.mouse_moved.emit(sp.x(), sp.y())
        self._check_edge(ev.position())
        if self._pan_from is not None:
            d = ev.position() - self._pan_from
            self._pan_from = ev.position()
            self.pan_by(d.x(), d.y())
            return
        if self.tool:
            self.tool.move(self, ev)

    def mouseReleaseEvent(self, ev):
        if self._pan_from is not None:
            self._pan_from = None
            self.viewport().unsetCursor()
            if self.tool:
                self.tool.restore_cursor(self)
            return
        if self.tool:
            self.tool.release(self, ev)

    def mouseDoubleClickEvent(self, ev):
        if self.tool:
            self.tool.double_click(self, ev)

    def keyPressEvent(self, ev):
        if self.tool and self.tool.key(self, ev):
            return
        super().keyPressEvent(ev)

    def drawForeground(self, p, rect):
        if self.mark_unconnected and self.scene().conn is not None:
            pen = QPen(theme().color("unconnected"))
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            hidden = self.tool.carried_pins() if hasattr(self.tool, "carried_pins") else set()
            for x, y in self.scene().conn.unconnected:
                if (x, y) not in hidden:
                    p.drawRect(QRectF(x - 4, y - 4, 8, 8))
        if self.mark_anchors:
            self._paint_anchors(p)
        if self.tool:
            self.tool.paint_overlay(self, p)

    def _paint_anchors(self, p):
        """Small circles at the justification anchor of every text."""
        from .items import SymbolItem
        pen = QPen(theme().color("comment"))
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r = 3.0
        pts = []
        sch = self.scene().sch
        pts += [(t.x, t.y) for t in sch.texts]
        pts += [(f.x, f.y) for f in sch.flags if f.name != "0"]
        for it in self.scene().items():
            if isinstance(it, SymbolItem):
                pts += [(x, y) for x, y, _f, _s, _t, kind in it._layout_texts() if kind == "attribute"]
        for x, y in pts:
            p.drawEllipse(QPointF(x, y), r, r)
