"""QGraphicsItems that draw schematic objects. Each wraps one model object."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QPainterPath, QPainterPathStroker, QPolygonF
from PySide6.QtWidgets import QGraphicsItem

from ..model import asc
from ..model.asy import WINDOW_ATTR
from ..model.geometry import TextFrame, apply, orient_matrix
from .render import draw_text, make_pen, shape_path, text_bounds
from .theme import theme

PICK_WIDTH = 6.0   # hit-test tolerance around lines, in schematic units


def _stroke(path: QPainterPath, width=PICK_WIDTH) -> QPainterPath:
    s = QPainterPathStroker()
    s.setWidth(width)
    return s.createStroke(path) | path


class SchItem(QGraphicsItem):
    """Base: knows its model object and whether it is highlighted (sprited)."""

    def __init__(self, obj):
        super().__init__()
        self.obj = obj
        self.highlight = False
        self._path = QPainterPath()
        self._bounds = QRectF()

    def set_highlight(self, on):
        if on != self.highlight:
            self.highlight = on
            self.update()

    def color(self, key):
        return theme().color("selected" if self.highlight else key)

    def boundingRect(self):
        return self._bounds

    def shape(self):
        return self._path


class WireItem(SchItem):
    def __init__(self, w: asc.Wire):
        super().__init__(w)
        path = QPainterPath(QPointF(w.x1, w.y1))
        path.lineTo(w.x2, w.y2)
        self._path = _stroke(path)
        self._bounds = self._path.boundingRect().adjusted(-2, -2, 2, 2)
        self.setZValue(1)

    def paint(self, p, opt, widget=None):
        p.setPen(make_pen(self.color("wire")))
        w = self.obj
        p.drawLine(QPointF(w.x1, w.y1), QPointF(w.x2, w.y2))


class JunctionItem(QGraphicsItem):
    """All junction dots of the sheet in one item."""
    R = 3.5

    def __init__(self, points):
        super().__init__()
        self.points = list(points)
        if self.points:
            xs = [x for x, _ in self.points]
            ys = [y for _, y in self.points]
            self._b = QRectF(min(xs) - 5, min(ys) - 5, max(xs) - min(xs) + 10, max(ys) - min(ys) + 10)
        else:
            self._b = QRectF()
        self.setZValue(2)

    def boundingRect(self):
        return self._b

    def paint(self, p, opt, widget=None):
        c = theme().color("junction")
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        for x, y in self.points:
            p.drawRect(QRectF(x - self.R, y - self.R, 2 * self.R, 2 * self.R))


class SymbolItem(SchItem):
    def __init__(self, inst: asc.SymbolInst, sym):
        super().__init__(inst)
        self.sym = sym
        self.m = orient_matrix(inst.orient)
        self.setZValue(3)
        body = QPainterPath()
        if sym is None:
            body.addRect(QRectF(inst.x - 16, inst.y - 16, 64, 64))
        else:
            for s in sym.shapes:
                body.addPath(shape_path(s.kind, s.coords, self.m, inst.x, inst.y))
        self._body = body
        hit = _stroke(body)
        if sym is not None:
            x0, y0, x1, y1 = sym.bbox()
            a = apply(self.m, x0, y0)
            b = apply(self.m, x1, y1)
            hit.addRect(QRectF(QPointF(a[0] + inst.x, a[1] + inst.y),
                               QPointF(b[0] + inst.x, b[1] + inst.y)).normalized())
        self._path = hit
        self._texts = list(self._layout_texts())
        bounds = hit.boundingRect()
        for t in self._texts:
            bounds = bounds.united(text_bounds(*t[:4], t[4]))
        self._bounds = bounds.adjusted(-4, -4, 4, 4)

    # -- attribute windows
    def attr_value(self, key):
        v = self.obj.attrs.get(key)
        if v is None and self.sym is not None:
            v = self.sym.attrs.get(key, "")
        return v or ""

    def _layout_texts(self):
        """Yield (x, y, frame, size, text, kind) in scene coordinates."""
        inst, sym = self.obj, self.sym
        if sym is None:
            yield (inst.x, inst.y - 20, TextFrame.from_just("Left"), 2, inst.symbol, "attribute")
            yield (inst.x, inst.y + 60, TextFrame.from_just("Left"), 2, inst.name, "attribute")
            return
        windows = dict(sym.windows)
        windows.update(inst.windows)
        for idx, w in windows.items():
            if w.just == "Invisible":
                continue
            key = WINDOW_ATTR.get(idx)
            if key is None:
                continue
            text = self.attr_value(key)
            if not text:
                continue
            x, y = apply(self.m, w.x, w.y)
            frame = TextFrame.from_just(w.just).transformed(self.m)
            yield (x + inst.x, y + inst.y, frame, w.size, text, "attribute")
        for t in sym.texts:
            x, y = apply(self.m, t.x, t.y)
            frame = TextFrame.from_just(t.just).transformed(self.m)
            yield (x + inst.x, y + inst.y, frame, t.size, t.text, "component")
        for pin in sym.pins:
            j = pin.just.upper()
            if j == "NONE" or not pin.name:
                continue
            off = pin.offset
            # the label sits inside the symbol body, offset away from the pin
            dx, dy, just = {
                "LEFT": (off, 0, "Left"), "RIGHT": (-off, 0, "Right"),
                "TOP": (0, off, "Top"), "BOTTOM": (0, -off, "Bottom"),
                "VLEFT": (0, -off, "VLeft"), "VRIGHT": (0, off, "VRight"),
                "VTOP": (off, 0, "VTop"), "VBOTTOM": (-off, 0, "VBottom"),
            }.get(j, (off, 0, "Left"))
            x, y = apply(self.m, pin.x + dx, pin.y + dy)
            frame = TextFrame.from_just(just).transformed(self.m)
            yield (x + inst.x, y + inst.y, frame, 1, pin.name, "component")

    def pin_points(self):
        if self.sym is None:
            return []
        out = []
        for pin in self.sym.pins:
            x, y = apply(self.m, pin.x, pin.y)
            out.append((x + self.obj.x, y + self.obj.y))
        return out

    def paint(self, p, opt, widget=None):
        p.setPen(make_pen(self.color("component")))
        p.setBrush(Qt.NoBrush)
        if self.sym is None:
            p.setPen(make_pen(theme().color("unconnected")))
            p.drawPath(self._body)
        else:
            for s in self.sym.shapes:
                p.setPen(make_pen(self.color("component"), style=s.style))
                p.drawPath(shape_path(s.kind, s.coords, self.m, self.obj.x, self.obj.y))
        for x, y, frame, size, text, kind in self._texts:
            p.setPen(self.color(kind))
            draw_text(p, x, y, frame, size, text)


class FlagItem(SchItem):
    """Net label, ground (name '0') or I/O port."""
    GAP = 6

    def __init__(self, f: asc.Flag, free_dir="up"):
        super().__init__(f)
        self.setZValue(3)
        self.free_dir = free_dir
        path = QPainterPath()
        if f.name == "0":
            path.addPolygon(QPolygonF([QPointF(f.x - 16, f.y), QPointF(f.x + 16, f.y),
                                       QPointF(f.x, f.y + 16), QPointF(f.x - 16, f.y)]))
            self._text = None
        else:
            just, dx, dy = {"up": ("Bottom", 0, -self.GAP), "down": ("Top", 0, self.GAP),
                            "right": ("Left", self.GAP, 0), "left": ("Right", -self.GAP, 0)}[free_dir]
            if f.iopin:
                dx, dy = dx * 3, dy * 3
            frame = TextFrame.from_just(just)
            self._text = (f.x + dx, f.y + dy, frame, 2, f.name)
            r = text_bounds(*self._text)
            path.addRect(r)
            if f.iopin:
                path.addPath(self._port_outline(r))
            path.moveTo(f.x, f.y)
        self._path = _stroke(path)
        self._bounds = self._path.boundingRect().adjusted(-4, -4, 4, 4)

    def _port_outline(self, r: QRectF) -> QPainterPath:
        """Pentagon/box drawn around I/O port labels."""
        path = QPainterPath()
        path.addRect(r.adjusted(-4, -2, 4, 2))
        return path

    def paint(self, p, opt, widget=None):
        f = self.obj
        p.setPen(make_pen(self.color("flag")))
        p.setBrush(Qt.NoBrush)
        if self._text is None:
            p.drawLine(QPointF(f.x - 16, f.y), QPointF(f.x + 16, f.y))
            p.drawLine(QPointF(f.x + 16, f.y), QPointF(f.x, f.y + 16))
            p.drawLine(QPointF(f.x, f.y + 16), QPointF(f.x - 16, f.y))
            return
        r = text_bounds(*self._text)
        if f.iopin:
            p.drawPath(self._port_outline(r))
        elif f.name.startswith("$G_"):
            p.drawRect(r.adjusted(-2, 0, 2, 0))
        draw_text(p, *self._text)


class TextItem(SchItem):
    def __init__(self, t: asc.Text):
        super().__init__(t)
        self.setZValue(4)
        self.frame = TextFrame.from_just(t.just)
        r = text_bounds(t.x, t.y, self.frame, t.size, t.body)
        path = QPainterPath()
        path.addRect(r)
        self._path = path
        self._bounds = r.adjusted(-2, -2, 2, 2)

    def paint(self, p, opt, widget=None):
        t = self.obj
        p.setPen(self.color("directive" if t.is_directive else "comment"))
        draw_text(p, t.x, t.y, self.frame, t.size, t.body)


class GraphicItem(SchItem):
    def __init__(self, g: asc.Graphic):
        super().__init__(g)
        self.setZValue(0)
        self._shape = shape_path(g.kind, g.coords)
        self._path = _stroke(self._shape)
        self._bounds = self._path.boundingRect().adjusted(-2, -2, 2, 2)

    def paint(self, p, opt, widget=None):
        p.setPen(make_pen(self.color("graphic"), style=self.obj.style))
        p.setBrush(QBrush(Qt.NoBrush))
        p.drawPath(self._shape)


class DataFlagItem(SchItem):
    """Shows an expression (typically a node voltage) evaluated at the cursor."""

    def __init__(self, d: asc.DataFlag, value_text=None):
        super().__init__(d)
        self.setZValue(4)
        self.value_text = value_text
        self._frame = TextFrame.from_just("Left")
        r = text_bounds(d.x + 8, d.y - 8, self._frame, 2, self.label())
        path = QPainterPath()
        path.addRect(r)
        self._path = path
        self._bounds = r.united(QRectF(d.x - 4, d.y - 4, 8, 8)).adjusted(-2, -2, 2, 2)

    def label(self):
        return self.value_text or self.obj.expr.strip('"')

    def paint(self, p, opt, widget=None):
        d = self.obj
        p.setPen(self.color("attribute"))
        p.drawEllipse(QPointF(d.x, d.y), 2, 2)
        draw_text(p, d.x + 8, d.y - 8, self._frame, 2, self.label())
