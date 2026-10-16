"""Painting helpers shared by the schematic view, symbol preview and printing."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from ..model.geometry import FONT_SCALE, TextFrame, apply

# LTspice's default schematic font is Tahoma 28, bold (Settings > Schematic > Font Properties).
# Measured under Wine, size index 2 has a 22.4-unit em. Tahoma is missing on most Linux systems,
# so fall back to DejaVu Sans (same Verdana lineage), condensed to roughly Tahoma's width.
FONT_FAMILIES = ["Tahoma", "DejaVu Sans", "Verdana", "Arial"]
BASE_FONT_PX = 14.93         # em of a size-1 font in schematic units
_family = None

_DASH = {1: Qt.DashLine, 2: Qt.DotLine, 3: Qt.DashDotLine, 4: Qt.DashDotDotLine}


def _font_family():
    global _family
    if _family is None:
        from PySide6.QtGui import QFontDatabase
        have = set(QFontDatabase.families())
        _family = next((f for f in FONT_FAMILIES if f in have), FONT_FAMILIES[0])
    return _family


def font_for(size: int) -> QFont:
    family = _font_family()
    f = QFont(family)
    f.setBold(True)
    if family != "Tahoma":
        f.setStretch(90)
    f.setPixelSize(max(1, round(BASE_FONT_PX * FONT_SCALE.get(size, 1.5))))
    return f


def make_pen(color, width=0.0, style=0) -> QPen:
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCosmetic(width == 0.0)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    if style in _DASH:
        pen.setStyle(_DASH[style])
    return pen


def text_rect(x, y, frame: TextFrame, size: int, text: str) -> tuple[QRectF, QFont]:
    """Bounding rect of text in its own (unrotated) frame, with the anchor at origin."""
    font = font_for(size)
    fm = QFontMetricsF(font)
    lines = text.split("\n")
    w = max((fm.horizontalAdvance(l) for l in lines), default=0.0)
    h = fm.height() * len(lines)
    return QRectF(-frame.ax * w, -frame.ay * h, w, h), font


def draw_text(p: QPainter, x, y, frame: TextFrame, size: int, text: str, align_lines=None):
    if not text:
        return
    rect, font = text_rect(x, y, frame, size, text)
    p.save()
    p.translate(x, y)
    if frame.vertical:
        p.rotate(-90)
    p.setFont(font)
    if align_lines is None:
        align_lines = Qt.AlignLeft if frame.ax == 0 else Qt.AlignRight if frame.ax == 1 else Qt.AlignHCenter
    p.drawText(rect, align_lines | Qt.AlignVCenter, text)
    p.restore()


def text_bounds(x, y, frame: TextFrame, size: int, text: str) -> QRectF:
    rect, _ = text_rect(x, y, frame, size, text)
    if frame.vertical:
        rect = QRectF(rect.top(), -rect.right(), rect.height(), rect.width())
    return rect.translated(x, y)


def shape_path(kind, c, m=(1, 0, 0, 1), ox=0, oy=0) -> QPainterPath:
    """Path for a LINE/RECTANGLE/CIRCLE/ARC with transform m and offset."""
    path = QPainterPath()

    def tp(x, y):
        tx, ty = apply(m, x, y)
        return QPointF(tx + ox, ty + oy)

    if kind == "LINE":
        path.moveTo(tp(c[0], c[1]))
        path.lineTo(tp(c[2], c[3]))
        return path
    p1, p2 = tp(c[0], c[1]), tp(c[2], c[3])
    rect = QRectF(p1, p2).normalized()
    if kind == "RECTANGLE":
        path.addRect(rect)
    elif kind == "CIRCLE":
        path.addEllipse(rect)
    elif kind == "ARC":
        s, e = tp(c[4], c[5]), tp(c[6], c[7])
        center = rect.center()
        a0 = math.degrees(math.atan2(-(s.y() - center.y()), s.x() - center.x()))
        a1 = math.degrees(math.atan2(-(e.y() - center.y()), e.x() - center.x()))
        sweep = (a1 - a0) % 360 or 360
        # mirroring reverses the drawing direction
        if m[0] * m[3] - m[1] * m[2] < 0:
            sweep = sweep - 360
        path.arcMoveTo(rect, a0)
        path.arcTo(rect, a0, sweep)
    return path
