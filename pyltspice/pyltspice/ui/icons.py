"""Toolbar icons and cursors, drawn with QPainter (no bitmaps shipped)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

S = 24


def _canvas(size=S):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    return pm, p


def _pen(color="#202020", w=1.6):
    pen = QPen(QColor(color))
    pen.setWidthF(w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _resistor(p):
    p.setPen(_pen())
    pts = [QPointF(12, 2), QPointF(12, 5)]
    for i in range(6):
        pts.append(QPointF(7 if i % 2 == 0 else 17, 7 + i * 2.2))
    pts += [QPointF(12, 19), QPointF(12, 22)]
    p.drawPolyline(QPolygonF(pts))


def _capacitor(p):
    p.setPen(_pen())
    p.drawLine(12, 2, 12, 10)
    p.drawLine(12, 14, 12, 22)
    p.setPen(_pen(w=2.2))
    p.drawLine(5, 10, 19, 10)
    p.drawLine(5, 14, 19, 14)


def _inductor(p):
    p.setPen(_pen())
    p.drawLine(12, 1, 12, 4)
    p.drawLine(12, 20, 12, 23)
    for i in range(4):
        p.drawArc(QRectF(8, 4 + i * 4, 8, 4), -90 * 16, 180 * 16)


def _diode(p):
    p.setPen(_pen())
    p.drawLine(12, 2, 12, 8)
    p.drawLine(12, 16, 12, 22)
    p.setBrush(QColor("#202020"))
    p.drawPolygon(QPolygonF([QPointF(6, 8), QPointF(18, 8), QPointF(12, 16)]))
    p.drawLine(6, 16, 18, 16)


def _ground(p):
    p.setPen(_pen())
    p.drawLine(12, 3, 12, 10)
    p.drawPolygon(QPolygonF([QPointF(4, 10), QPointF(20, 10), QPointF(12, 19)]))


def _wire(p):
    p.setPen(_pen("#0000ff", 2))
    p.drawPolyline(QPolygonF([QPointF(3, 20), QPointF(3, 6), QPointF(21, 6)]))
    p.setPen(_pen("#202020", 1.2))
    p.drawLine(15, 13, 21, 19)
    p.drawLine(18, 22, 23, 17)


def _label(p):
    p.setPen(_pen())
    p.setFont(QFont("Arial", 9, QFont.Bold))
    p.drawText(QRectF(0, 0, S, 14), Qt.AlignCenter, "A")
    p.setPen(_pen("#0000ff", 2))
    p.drawLine(3, 18, 21, 18)
    p.setBrush(QColor("#0000ff"))
    p.drawRect(QRectF(10, 16, 4, 4))


def _component(p):
    p.setPen(_pen())
    path = QPainterPath(QPointF(5, 5))
    path.lineTo(12, 5)
    path.arcTo(QRectF(5, 5, 14, 14), 90, -180)
    path.lineTo(5, 19)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(1, 9, 5, 9)
    p.drawLine(1, 15, 5, 15)
    p.drawLine(19, 12, 23, 12)


def _text(p, s, bold=False, color="#202020", size=10):
    p.setPen(_pen(color))
    f = QFont("Arial", size)
    f.setBold(bold)
    p.setFont(f)
    p.drawText(QRectF(0, 0, S, S), Qt.AlignCenter, s)


def _run(p):
    # a running figure
    p.setPen(_pen("#202020", 2))
    p.setBrush(QColor("#202020"))
    p.drawEllipse(QPointF(14, 4), 2.2, 2.2)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(13, 7), QPointF(10, 14))          # torso
    p.drawPolyline(QPolygonF([QPointF(10, 14), QPointF(14, 17), QPointF(13, 22)]))
    p.drawPolyline(QPolygonF([QPointF(10, 14), QPointF(7, 18), QPointF(3, 18)]))
    p.drawPolyline(QPolygonF([QPointF(12, 9), QPointF(16, 11), QPointF(19, 9)]))
    p.drawPolyline(QPolygonF([QPointF(12, 9), QPointF(8, 9), QPointF(6, 12)]))


def _halt(p):
    p.setPen(_pen("#a00000", 1.5))
    p.setBrush(QColor("#e02020"))
    pts = [QPointF(12 + 9 * math.cos(math.radians(22.5 + 45 * i)),
                   12 + 9 * math.sin(math.radians(22.5 + 45 * i))) for i in range(8)]
    p.drawPolygon(QPolygonF(pts))


def _zoom(p, sign):
    p.setPen(_pen(w=2))
    p.drawEllipse(QPointF(10, 10), 6.5, 6.5)
    p.drawLine(15, 15, 21, 21)
    p.setPen(_pen(w=1.6))
    p.drawLine(7, 10, 13, 10)
    if sign == "+":
        p.drawLine(10, 7, 10, 13)
    elif sign == "fit":
        p.drawRect(QRectF(7, 7, 6, 6))


def _hand(p, closed=False):
    p.setPen(_pen(w=1.3))
    p.setBrush(QColor("#ffe0c0"))
    if closed:
        p.drawRoundedRect(QRectF(5, 8, 14, 12), 4, 4)
        for i in range(4):
            p.drawLine(QPointF(7.5 + i * 3, 8), QPointF(7.5 + i * 3, 12))
    else:
        for i in range(4):
            p.drawRoundedRect(QRectF(5.5 + i * 3.4, 3 + (i % 3 == 0) * 2, 3, 11), 1.5, 1.5)
        p.drawRoundedRect(QRectF(5, 11, 14, 10), 4, 4)
        p.drawRoundedRect(QRectF(1.5, 10, 4, 7), 2, 2)


def _scissors(p):
    p.setPen(_pen(w=1.6))
    p.drawEllipse(QPointF(6, 18), 3.5, 3.5)
    p.drawEllipse(QPointF(18, 18), 3.5, 3.5)
    p.drawLine(8, 15, 17, 2)
    p.drawLine(16, 15, 7, 2)


def _copy(p):
    p.setPen(_pen(w=1.3))
    p.setBrush(QColor("white"))
    p.drawRect(QRectF(3, 3, 11, 13))
    p.drawRect(QRectF(9, 8, 11, 13))


def _rotate(p):
    p.setPen(_pen(w=1.8))
    p.drawArc(QRectF(4, 4, 16, 16), 90 * 16, 270 * 16)
    p.setBrush(QColor("#202020"))
    p.drawPolygon(QPolygonF([QPointF(12, 1), QPointF(16, 4), QPointF(12, 7)]))


def _mirror(p):
    p.setPen(_pen(w=1.2))
    p.setBrush(QColor("#202020"))
    p.drawPolygon(QPolygonF([QPointF(10, 5), QPointF(10, 19), QPointF(3, 19)]))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(QPolygonF([QPointF(14, 5), QPointF(14, 19), QPointF(21, 19)]))
    pen = _pen(w=1)
    pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    p.drawLine(12, 2, 12, 22)


def _undo(p, redo=False):
    p.setPen(_pen(w=2))
    if redo:
        p.translate(S, 0)
        p.scale(-1, 1)
    p.drawArc(QRectF(5, 7, 15, 12), 90 * 16, -200 * 16)
    p.setBrush(QColor("#202020"))
    p.drawPolygon(QPolygonF([QPointF(3, 9), QPointF(9, 4), QPointF(9, 13)]))


def _doc(p, kind):
    p.setPen(_pen(w=1.2))
    p.setBrush(QColor("white"))
    p.drawPolygon(QPolygonF([QPointF(5, 2), QPointF(15, 2), QPointF(19, 6), QPointF(19, 22), QPointF(5, 22)]))
    if kind == "open":
        p.setBrush(QColor("#f0c040"))
        p.drawPolygon(QPolygonF([QPointF(2, 10), QPointF(20, 10), QPointF(22, 22), QPointF(4, 22)]))
    elif kind == "save":
        p.setBrush(QColor("#4060c0"))
        p.drawRect(QRectF(5, 12, 14, 10))
    elif kind == "print":
        p.setBrush(QColor("#c0c0c0"))
        p.drawRect(QRectF(2, 11, 20, 8))
    elif kind == "netlist":
        for i in range(5):
            p.drawLine(8, 7 + i * 3, 16, 7 + i * 3)


def _settings(p):
    p.setPen(_pen(w=1.4))
    p.setBrush(QColor("#c0c0c0"))
    pts = []
    for i in range(16):
        r = 10 if i % 2 == 0 else 7
        a = math.radians(i * 22.5)
        pts.append(QPointF(12 + r * math.cos(a), 12 + r * math.sin(a)))
    p.drawPolygon(QPolygonF(pts))
    p.setBrush(QColor("white"))
    p.drawEllipse(QPointF(12, 12), 3, 3)


def _probe(p, kind):
    p.setPen(_pen("#ff0000" if kind == "voltage" else "#202020", 1.6))
    p.setBrush(QColor("#ff4040") if kind == "voltage" else Qt.NoBrush)
    if kind == "voltage":
        p.drawPolygon(QPolygonF([QPointF(1, 1), QPointF(8, 4), QPointF(4, 8)]))
        p.drawLine(5, 5, 20, 20)
    else:
        # current clamp
        p.drawEllipse(QPointF(10, 10), 7, 7)
        p.drawLine(15, 15, 22, 22)
        p.setPen(_pen("#ff0000", 1.6))
        p.drawLine(4, 10, 16, 10)
        p.drawLine(13, 7, 16, 10)
        p.drawLine(13, 13, 16, 10)


ICONS = {
    "new": lambda p: _doc(p, "new"), "open": lambda p: _doc(p, "open"),
    "save": lambda p: _doc(p, "save"), "print": lambda p: _doc(p, "print"),
    "netlist": lambda p: _doc(p, "netlist"),
    "run": _run, "halt": _halt,
    "zoom_in": lambda p: _zoom(p, "+"), "zoom_out": lambda p: _zoom(p, "-"),
    "zoom_fit": lambda p: _zoom(p, "fit"), "pan": _hand,
    "wire": _wire, "ground": _ground, "label": _label,
    "resistor": _resistor, "capacitor": _capacitor, "inductor": _inductor, "diode": _diode,
    "component": _component, "rotate": _rotate, "mirror": _mirror,
    "text": lambda p: _text(p, "Aa", size=11), "directive": lambda p: _text(p, ".op", True, size=10),
    "delete": _scissors, "duplicate": _copy, "move": _hand,
    "drag": lambda p: _hand(p, True), "undo": _undo, "redo": lambda p: _undo(p, True),
    "settings": _settings, "find": lambda p: _zoom(p, ""),
}


def icon(name) -> QIcon:
    pm, p = _canvas()
    ICONS.get(name, lambda p: _text(p, "?"))(p)
    p.end()
    return QIcon(pm)


def make_cursors():
    """Mode cursors (LTspice shows scissors, hands, probes...)."""
    def cur(fn, hx, hy):
        pm, p = _canvas(32)
        p.scale(32 / S, 32 / S)
        fn(p)
        p.end()
        return QCursor(pm, hx, hy)
    return {
        "scissors": cur(_scissors, 12, 4),
        "move": cur(_hand, 12, 12),
        "drag": cur(lambda p: _hand(p, True), 12, 12),
        "voltage": cur(lambda p: _probe(p, "voltage"), 1, 1),
        "current": cur(lambda p: _probe(p, "current"), 13, 13),
    }
