"""Toolbar icons and cursors, drawn with QPainter (no bitmaps shipped or copied)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


def _pen(color="#202020", w=1.6):
    pen = QPen(QColor(color))
    pen.setWidthF(w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


# ---------------------------------------------------------------------------------------------
# Toolbar / menu icons in the style of LTspice 26's default toolbar: bold black glyphs, blue
# accents, hollow blue pin circles on component buttons. Drawn from observation, in a 32-unit
# box, rendered at 2x for crisp hi-dpi toolbars.

K, B, W, NAVY = "#000000", "#0000ff", "#ffffff", "#000080"
GREEN, GREY, TEAL = "#00e000", "#9a9a9e", "#00a8a8"
U = 32


def _fill(p, color, pen=None):
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen if pen is None else pen)


def _poly(*pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _pin(p, x, y):
    """Hollow blue pin circle."""
    p.setPen(_pen(B, 1.7))
    p.setBrush(QColor(W))
    p.drawEllipse(QPointF(x, y), 2.3, 2.3)


def _gear(p, hole=True):
    pts = []
    for i in range(32):
        a = math.radians(i * 360 / 32 + 5.6)
        r = 13.5 if (i // 2) % 2 == 0 else 10.2
        pts.append(QPointF(16 + r * math.cos(a), 16 + r * math.sin(a)))
    _fill(p, K)
    p.drawPolygon(QPolygonF(pts))
    p.drawEllipse(QPointF(16, 16), 11, 11)
    if hole:
        _fill(p, W)
        p.drawEllipse(QPointF(16, 16), 4.6, 4.6)


def i_settings(p):
    _gear(p)


def i_analysis(p):
    _gear(p, hole=False)
    _label_text(p, ".ac", GREEN, 11.5, QRectF(0, 7, U, 16))


def _label_text(p, s, color, px, rect, family="DejaVu Sans"):
    f = QFont(family)
    f.setPixelSize(round(px))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(rect, Qt.AlignCenter, s)


def _page(p, x0=9, x1=28, y0=2, y1=29):
    _fill(p, K)
    p.drawPolygon(_poly((x0, y0), (x1 - 6, y0), (x1, y0 + 6), (x1, y1), (x0, y1)))
    p.setPen(_pen(W, 1.2))
    p.drawPolyline(_poly((x1 - 6, y0 + 1), (x1 - 6, y0 + 6), (x1 - 1, y0 + 6)))


def _badge(p, x, y, color=B, sym="+"):
    _fill(p, color, _pen(W, 1.2))
    p.drawEllipse(QPointF(x, y), 7.6, 7.6)
    p.setPen(_pen(W, 2.6))
    if sym == "+":
        p.drawLine(QPointF(x - 4, y), QPointF(x + 4, y))
        p.drawLine(QPointF(x, y - 4), QPointF(x, y + 4))
    elif sym == "x":
        p.drawLine(QPointF(x - 3.2, y - 3.2), QPointF(x + 3.2, y + 3.2))
        p.drawLine(QPointF(x - 3.2, y + 3.2), QPointF(x + 3.2, y - 3.2))
    elif sym == "<":
        p.drawPolyline(_poly((x + 2, y - 4), (x - 2.5, y), (x + 2, y + 4)))


def i_new(p):
    _page(p)
    _badge(p, 10, 22)


def i_netlist(p):
    _page(p)
    _badge(p, 10, 22, B, "")
    _label_text(p, "n", W, 12, QRectF(2, 13, 16, 17))


def i_new_symbol(p):
    _fill(p, K)
    p.drawRect(QRectF(9, 4, 14, 24))
    for y in (8, 16, 24):
        _pin(p, 6, y)
        _pin(p, 26, y)
    p.setPen(_pen(W, 2.4))
    p.drawLine(QPointF(16, 11), QPointF(16, 21))
    p.drawLine(QPointF(11, 16), QPointF(21, 16))


def _folder(p, front=B):
    _fill(p, K)
    p.drawPolygon(_poly((2, 6), (11, 6), (13, 9), (27, 9), (27, 14), (2, 14)))
    _fill(p, front, _pen(K, 1))
    p.drawPolygon(_poly((6, 13), (31, 13), (26, 28), (1, 28)))


def i_open(p):
    _folder(p)
    _fill(p, W)
    p.drawPolygon(_poly((16, 14.5), (22, 20.5), (18.5, 20.5), (18.5, 25), (13.5, 25), (13.5, 20.5), (10, 20.5)))


def i_examples(p):
    _folder(p)
    _label_text(p, "e", W, 13, QRectF(6, 12, 22, 17))


def _floppy(p):
    _fill(p, K)
    p.drawPolygon(_poly((3, 3), (25, 3), (29, 7), (29, 29), (3, 29)))
    _fill(p, W)
    p.drawRect(QRectF(9, 3, 12, 8))
    _fill(p, K)
    p.drawRect(QRectF(16, 4, 3, 6))
    _fill(p, W)
    p.drawRect(QRectF(6.5, 16, 19, 11))
    _fill(p, B)
    p.drawRect(QRectF(6.5, 22, 19, 5))


def i_save(p):
    _floppy(p)


def i_save_as(p):
    _floppy(p)
    p.setPen(_pen("#ffd000", 3))
    p.drawLine(QPointF(14, 26), QPointF(28, 12))
    p.setPen(_pen(K, 1))
    p.drawLine(QPointF(12, 28), QPointF(14, 26))


def i_print(p):
    _fill(p, B)
    p.drawPolygon(_poly((9, 1), (19, 1), (23, 5), (23, 10), (9, 10)))
    _fill(p, K)
    p.drawRoundedRect(QRectF(2, 10, 28, 12), 2.5, 2.5)
    _fill(p, B, _pen(K, 1))
    p.drawRect(QRectF(8, 17, 16, 13))
    p.setPen(_pen(W, 1.8))
    for y in (21.5, 25.5):
        p.drawLine(QPointF(10.5, y), QPointF(21.5, y))


def i_run(p):
    p.setPen(_pen(K, 2.2))
    p.setBrush(QColor(GREEN))
    p.drawPolygon(_poly((7, 4), (28, 16), (7, 28)))


def i_halt(p):
    # the button is greyed out (disabled) whenever no simulation runs; red while one does
    _fill(p, "#d02020")
    p.drawRoundedRect(QRectF(5, 5, 22, 22), 3.5, 3.5)


def _win(p, r: QRectF):
    _fill(p, W, _pen(B, 2))
    p.drawRect(r)
    _fill(p, B)
    p.drawRect(QRectF(r.left(), r.top(), r.width(), 4))
    _fill(p, W)
    p.drawRect(QRectF(r.left() + 1.5, r.top() + 1.2, 1.8, 1.6))


def i_tile_v(p):
    _win(p, QRectF(3, 3, 12, 26))
    _win(p, QRectF(17, 3, 12, 26))


def i_tile_h(p):
    _win(p, QRectF(2, 3, 28, 12))
    _win(p, QRectF(2, 17, 28, 12))


def i_cascade(p):
    for k in range(3):
        _win(p, QRectF(2 + 5 * k, 3 + 6 * k, 17, 11))


def i_close_all(p):
    i_cascade(p)
    _badge(p, 24, 10, "#e02020", "x")


def _lens(p, glass=K):
    p.setPen(_pen(K, 4.5))
    p.drawLine(QPointF(21, 21), QPointF(29, 29))
    _fill(p, glass, _pen(K, 3) if glass != K else None)
    p.drawEllipse(QPointF(13, 13), 10.5 if glass == K else 9, 10.5 if glass == K else 9)


def i_zoom_in(p):
    _lens(p)
    p.setPen(_pen(W, 3.4))
    p.drawLine(QPointF(8, 13), QPointF(18, 13))
    p.drawLine(QPointF(13, 8), QPointF(13, 18))


def i_zoom_out(p):
    _lens(p)
    p.setPen(_pen(W, 3.4))
    p.drawLine(QPointF(8, 13), QPointF(18, 13))


def i_zoom_fit(p):
    _lens(p)
    p.setPen(_pen(W, 2.4))
    p.drawLine(QPointF(9.5, 16.5), QPointF(16.5, 9.5))
    _fill(p, W)
    p.drawPolygon(_poly((7.5, 18.5), (7.5, 12.5), (13.5, 18.5)))
    p.drawPolygon(_poly((18.5, 7.5), (12.5, 7.5), (18.5, 13.5)))


def i_find(p):
    _lens(p, TEAL)
    p.setPen(_pen("#80ffff", 1.6))
    p.drawArc(QRectF(8, 8, 10, 10), 100 * 16, 70 * 16)


def i_recenter(p):
    _lens(p, TEAL)
    p.setPen(_pen(B, 1.4))
    p.drawLine(QPointF(13, 7), QPointF(13, 19))
    p.drawLine(QPointF(7, 13), QPointF(19, 13))


def _screen(p):
    _fill(p, K)
    p.drawRoundedRect(QRectF(3, 3, 26, 26), 3, 3)


def _arrow(p, x, y, up):
    s = -1 if up else 1
    _fill(p, W)
    p.drawPolygon(_poly((x, y + 6 * s), (x - 5, y), (x - 2, y), (x - 2, y - 5 * s), (x + 2, y - 5 * s),
                        (x + 2, y), (x + 5, y)))


def i_autorange(p):
    _screen(p)
    _arrow(p, 11, 10, True)
    _arrow(p, 21, 22, False)


def _sine(p, y, color):
    path = QPainterPath(QPointF(5, y))
    for k in range(1, 23):
        x = 5 + k
        path.lineTo(x, y - 3.5 * math.sin((x - 5) / 22 * 2 * math.pi))
    p.setPen(_pen(color, 2.4))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


def i_waves(p):
    _screen(p)
    _sine(p, 11, W)
    _sine(p, 21, "#00e0e0")


def i_fft(p):
    _screen(p)
    p.setPen(_pen("#ff3030", 2.2))
    for x, h in ((8, 18), (12, 10), (16, 14), (20, 6), (24, 9)):
        p.drawLine(QPointF(x, 26), QPointF(x, 26 - h))


def i_wire(p):
    p.setPen(_pen(B, 2.6))
    p.drawPolyline(_poly((6, 5), (14, 5), (14, 27), (26, 27)))
    _fill(p, B)
    p.drawEllipse(QPointF(5, 5), 3.2, 3.2)
    _pin(p, 27, 27)


def i_ground(p):
    p.setPen(_pen(K, 2.8))
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(16, 6), QPointF(16, 14))
    p.drawPolygon(_poly((4, 14), (28, 14), (16, 27)))
    _pin(p, 16, 4)


def i_voltage(p):
    p.setPen(_pen(K, 2.8))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(16, 16), 10, 10)
    _fill(p, K)
    p.drawPolygon(_poly((11, 11), (14, 11), (16, 15.5), (18, 11), (21, 11), (16, 22)))
    _pin(p, 16, 4)
    _pin(p, 16, 28)


def i_resistor(p):
    p.setPen(_pen(K, 2.8))
    pts = [(16, 6), (16, 8)] + [(11 if k % 2 == 0 else 21, 9.5 + k * 3) for k in range(5)] + [(16, 24), (16, 26)]
    p.setBrush(Qt.NoBrush)
    p.drawPolyline(_poly(*pts))
    _pin(p, 16, 4)
    _pin(p, 16, 28)


def i_capacitor(p):
    p.setPen(_pen(K, 2.4))
    p.drawLine(QPointF(16, 6), QPointF(16, 13))
    p.drawLine(QPointF(16, 19), QPointF(16, 26))
    p.setPen(_pen(K, 3.6))
    p.drawLine(QPointF(5, 13), QPointF(27, 13))
    p.drawLine(QPointF(5, 19), QPointF(27, 19))
    _pin(p, 16, 4)
    _pin(p, 16, 28)


def i_inductor(p):
    p.setPen(_pen(K, 3))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(10, 5.5, 10, 10.5), 120 * 16, -240 * 16)
    p.drawArc(QRectF(10, 15.5, 10, 10.5), 120 * 16, -240 * 16)
    _pin(p, 13, 4)
    _pin(p, 13, 28)


def i_diode(p):
    p.setPen(_pen(K, 2.4))
    p.drawLine(QPointF(16, 6), QPointF(16, 26))
    _fill(p, K, _pen(K, 2))
    p.drawPolygon(_poly((6, 11), (26, 11), (16, 21)))
    _fill(p, W)
    p.drawPolygon(_poly((11.5, 13.5), (20.5, 13.5), (16, 18)))
    p.setPen(_pen(K, 3.4))
    p.drawLine(QPointF(5, 22), QPointF(27, 22))
    _pin(p, 16, 4)
    _pin(p, 16, 28)


def i_component(p):
    _fill(p, K)
    p.drawRect(QRectF(8, 3, 16, 26))
    _fill(p, W)
    p.drawPolygon(_poly((12.5, 10), (21, 16), (12.5, 22)))
    for y in (5, 16, 27):
        _pin(p, 5, y)
        _pin(p, 27, y)


def i_label(p):
    _label_text(p, "net", B, 15, QRectF(-2, -1, U + 4, 20))
    p.setPen(_pen(NAVY, 3.4))
    p.drawLine(QPointF(5, 25), QPointF(27, 25))
    _fill(p, NAVY)
    p.drawEllipse(QPointF(4.5, 25), 3, 3)
    p.drawEllipse(QPointF(27.5, 25), 3, 3)


def i_bustap(p):
    p.setPen(_pen(K, 2.6))
    p.drawLine(QPointF(6, 4), QPointF(6, 28))
    p.drawLine(QPointF(6, 16), QPointF(18, 16))
    _fill(p, B)
    p.drawPolygon(_poly((16, 10), (25, 16), (16, 22)))
    _pin(p, 6, 4)
    _pin(p, 6, 28)
    _pin(p, 27, 16)


def i_text(p):
    _label_text(p, "t", B, 29, QRectF(0, -2, U, U + 2))


def i_directive(p):
    _label_text(p, ".t", K, 29, QRectF(0, -2, U, U + 2))


def i_delete(p):
    _fill(p, K)
    p.drawEllipse(QPointF(16, 16), 13.5, 13.5)
    p.setPen(_pen(W, 4.6))
    p.drawLine(QPointF(11, 11), QPointF(21, 21))
    p.drawLine(QPointF(11, 21), QPointF(21, 11))


def i_close(p):
    _fill(p, "#e02020")
    p.drawEllipse(QPointF(16, 16), 12.5, 12.5)
    p.setPen(_pen(W, 4))
    p.drawLine(QPointF(11.5, 11.5), QPointF(20.5, 20.5))
    p.drawLine(QPointF(11.5, 20.5), QPointF(20.5, 11.5))


def _corners(p, src_filled):
    """Source corner (bottom-left) and destination corner (top-right) of the move glyphs."""
    if src_filled:
        _fill(p, B)
    else:
        p.setPen(_pen(GREY, 1.8))
        p.setBrush(Qt.NoBrush)
    p.drawPolygon(_poly((3, 19), (3, 29), (13, 29)))
    _fill(p, B if src_filled else GREY)
    for c in (11.5, 16, 20.5):
        p.drawEllipse(QPointF(c, 32 - c), 2.2, 2.2)
    _fill(p, B)
    p.drawPolygon(_poly((19, 3), (29, 3), (29, 13)))


def i_duplicate(p):
    _corners(p, True)


def i_move(p):
    _corners(p, False)


def i_drag(p):
    _corners(p, False)
    p.setPen(_pen(B, 2.4))
    p.drawPolyline(_poly((6, 4), (27, 4), (27, 26)))
    _pin(p, 5, 4)
    _pin(p, 27, 27)


def i_rotate(p):
    p.setPen(_pen(K, 2.2))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(_poly((4, 29), (22, 29), (13, 20)))
    pen = _pen(K, 2)
    pen.setStyle(Qt.DotLine)
    p.setPen(pen)
    p.drawArc(QRectF(3, 3, 26, 26), 180 * 16, -100 * 16)
    _fill(p, B)
    p.drawPolygon(_poly((19, 4), (30, 13), (19, 22)))


def i_mirror(p):
    p.setPen(_pen(K, 2.2))
    p.setBrush(Qt.NoBrush)
    p.drawPolygon(_poly((3, 6), (13, 16), (3, 26)))
    pen = _pen(K, 2)
    pen.setStyle(Qt.DotLine)
    p.setPen(pen)
    p.drawLine(QPointF(16, 2), QPointF(16, 30))
    _fill(p, B)
    p.drawPolygon(_poly((29, 6), (19, 16), (29, 26)))


def i_undo(p, redo=False):
    if redo:
        p.translate(U, 0)
        p.scale(-1, 1)
    p.setPen(_pen(K, 5.5))
    p.setBrush(Qt.NoBrush)
    path = QPainterPath(QPointF(11, 12))
    path.cubicTo(QPointF(24, 9), QPointF(30, 20), QPointF(20, 28))
    p.drawPath(path)
    _fill(p, K)
    p.drawPolygon(_poly((2, 12), (12, 3), (12, 21)))


def i_redo(p):
    i_undo(p, True)


def i_help(p):
    _fill(p, B)
    p.drawEllipse(QPointF(16, 16), 13, 13)
    _label_text(p, "?", W, 20, QRectF(0, 0, U, U))


def i_about(p):
    _fill(p, K)
    p.drawEllipse(QPointF(16, 16), 13, 13)
    _label_text(p, "i", W, 19, QRectF(0, 0, U, U))


def i_keyboard(p):
    _fill(p, K)
    p.drawRoundedRect(QRectF(3, 3, 26, 26), 3, 3)
    _fill(p, W)
    p.drawRoundedRect(QRectF(7, 6, 18, 18), 2, 2)
    _label_text(p, "a", K, 17, QRectF(7, 4, 18, 20))


def i_colors(p):
    _fill(p, K)
    p.drawEllipse(QPointF(16, 16), 14, 13)
    for (x, y), c in zip(((9, 11), (16, 7), (23, 11), (23, 20), (10, 20)),
                         ("#ff2020", "#20e020", "#2040ff", "#ffe020", "#00e0e0")):
        _fill(p, c)
        p.drawEllipse(QPointF(x, y), 3.3, 3.3)


def i_copy_bitmap(p):
    _fill(p, K)
    p.drawRoundedRect(QRectF(2, 8, 28, 20), 3, 3)
    p.drawRect(QRectF(10, 4, 12, 5))
    _fill(p, W)
    p.drawEllipse(QPointF(16, 18), 7, 7)
    _fill(p, B)
    p.drawEllipse(QPointF(16, 18), 4.5, 4.5)


def i_line(p):
    p.setPen(_pen(K, 3))
    p.drawLine(QPointF(6, 6), QPointF(26, 26))


def i_rectangle(p):
    p.setPen(_pen(K, 3))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(5, 7, 22, 18))


def i_ellipse(p):
    p.setPen(_pen(K, 3))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(4, 7, 24, 18))


def i_arc(p):
    p.setPen(_pen(K, 3.4))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(6, 6, 20, 20), 300 * 16, 240 * 16)


def i_bom(p):
    _page(p, 6, 26, 2, 30)
    p.setPen(_pen(W, 1.8))
    for y in (11, 16, 21, 26):
        p.drawLine(QPointF(10, y), QPointF(22, y))


def i_log(p):
    _page(p)
    _badge(p, 10, 22, "#e02020", "")
    _label_text(p, "L", W, 12, QRectF(2, 13, 16, 17))


def i_schematic_doc(p):
    """Small transistor glyph used for schematic windows and tabs."""
    p.setPen(_pen(B, 2.4))
    p.drawLine(QPointF(14, 6), QPointF(14, 26))
    p.drawLine(QPointF(4, 16), QPointF(14, 16))
    p.drawLine(QPointF(14, 11), QPointF(24, 4))
    p.drawLine(QPointF(14, 21), QPointF(24, 28))
    _fill(p, B)
    p.drawPolygon(_poly((25, 29), (17, 26.5), (21, 21)))


def i_waveform_doc(p):
    """Small plot glyph used for waveform windows and tabs."""
    p.setPen(_pen(K, 2))
    p.setBrush(QColor(W))
    p.drawRect(QRectF(3, 5, 26, 22))
    p.setPen(_pen("#e02020", 2.2))
    path = QPainterPath(QPointF(5, 22))
    for k in range(1, 23):
        path.lineTo(5 + k, 16 - 7 * math.sin(k / 22 * 2 * math.pi) * (1 - k / 40))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)


# -- menu icons (LTspice 26 menus put a glyph on most items; drawn from observation)
def i_print_preview(p):
    i_print(p)
    p.save()
    p.translate(12, 12)
    p.scale(0.6, 0.6)
    _lens(p, TEAL)
    p.restore()


def i_print_setup(p):
    _page(p)
    p.save()
    p.translate(0, 13)
    p.scale(0.55, 0.55)
    _gear(p)
    p.restore()


def i_export(p):
    _page(p)
    _badge(p, 10, 22, B, "<")


def i_write_image(p):
    i_export(p)


def i_view_netlist(p):
    i_netlist(p)


def i_meas(p):
    _page(p)
    _fill(p, "#ffd000", _pen(B, 2))
    p.drawEllipse(QPointF(10, 21), 7.6, 7.6)
    _fill(p, B)
    p.drawPolygon(_poly((8, 17), (14, 21), (8, 25)))


def i_fast_access(p):
    _floppy(p)
    _fill(p, "#ffd000", _pen(K, 1))
    p.drawPolygon(_poly((20, 8), (14, 19), (18, 19), (15, 29), (24, 16), (19.5, 16), (23, 8)))


def i_current(p):
    p.setPen(_pen(K, 2.8))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(16, 16), 10, 10)
    p.setPen(_pen(K, 2.4))
    p.drawLine(QPointF(16, 10), QPointF(16, 22))
    _fill(p, K)
    p.drawPolygon(_poly((11.5, 18), (20.5, 18), (16, 24)))
    _pin(p, 16, 4)
    _pin(p, 16, 28)


def i_paste(p):
    _fill(p, "#a0a0a0", _pen(K, 1.5))
    p.drawRoundedRect(QRectF(5, 5, 22, 25), 2, 2)
    _fill(p, K)
    p.drawRect(QRectF(11, 2, 10, 6))
    _fill(p, W, _pen(K, 1))
    p.drawRect(QRectF(10, 12, 13, 15))


def i_dataflag(p):
    _label_text(p, "1.8", "#ff2020", 17, QRectF(0, 4, 32, 24), "DejaVu Sans Mono")


def i_blank_sheet(p):
    _win(p, QRectF(3, 5, 26, 22))


def i_probe_ref(p):
    p.setPen(_pen("#707070", 2.6))
    p.drawLine(QPointF(6, 27), QPointF(24, 6))
    p.setPen(_pen(K, 1.2))
    p.drawLine(QPointF(4, 29), QPointF(7, 26))
    p.drawLine(QPointF(15, 25), QPointF(27, 25))


def i_add_trace(p):
    _screen(p)
    _sine(p, 21, "#00e0e0")
    p.setPen(_pen(W, 2.6))
    p.drawLine(QPointF(10, 6), QPointF(10, 14))
    p.drawLine(QPointF(6, 10), QPointF(14, 10))


def i_select_steps(p):
    _screen(p)
    for y, c in ((9, W), (16, "#00e0e0"), (23, "#00e000")):
        _sine(p, y, c)


def i_cursor(p):
    p.setPen(_pen("#707070", 1.6))
    p.drawLine(QPointF(16, 3), QPointF(16, 29))
    p.drawLine(QPointF(3, 16), QPointF(29, 16))


def i_clear_cursors(p):
    i_cursor(p)
    _badge(p, 23, 24, "#e02020", "x")


def i_redraw(p):
    p.setPen(_pen(K, 4))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(5, 5, 22, 22), 60 * 16, 290 * 16)
    _fill(p, K)
    p.drawPolygon(_poly((17, 1), (26, 6), (17, 12)))


def i_reload(p):
    _folder(p)
    p.setPen(_pen(W, 2.4))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(10, 15, 11, 11), 60 * 16, 290 * 16)


def _two_panes(p):
    for y in (2, 17):
        _fill(p, W, _pen("#707070", 1.2))
        p.drawRect(QRectF(3, y, 26, 13))
        p.setPen(_pen("#909090", 1.6))
        p.drawLine(QPointF(5, y + 8), QPointF(27, y + 5))


def i_pane_above(p):
    _two_panes(p)
    _fill(p, B)
    p.drawRect(QRectF(3, 2, 26, 13))
    p.setPen(_pen(W, 2.6))
    p.drawLine(QPointF(10, 8.5), QPointF(18, 8.5))
    p.drawLine(QPointF(14, 4.5), QPointF(14, 12.5))


def i_pane_below(p):
    _two_panes(p)
    _fill(p, B)
    p.drawRect(QRectF(3, 17, 26, 13))
    p.setPen(_pen(W, 2.6))
    p.drawLine(QPointF(10, 23.5), QPointF(18, 23.5))
    p.drawLine(QPointF(14, 19.5), QPointF(14, 27.5))


def i_pane_up(p):
    _two_panes(p)
    _fill(p, B)
    p.drawPolygon(_poly((16, 4), (10, 12), (22, 12)))


def i_pane_down(p):
    _two_panes(p)
    _fill(p, B)
    p.drawPolygon(_poly((16, 28), (10, 20), (22, 20)))


def i_pane_delete(p):
    _two_panes(p)
    p.setPen(_pen("#e02020", 2.6))
    p.drawLine(QPointF(10, 5), QPointF(20, 13))
    p.drawLine(QPointF(10, 13), QPointF(20, 5))


def i_colors_reset(p):
    _screen(p)
    for y, c in ((9, "#00e000"), (16, "#ff2020"), (23, "#3060ff")):
        p.setPen(_pen(c, 3.2))
        p.drawLine(QPointF(7, y), QPointF(25, y))


def i_manual_limits(p):
    _fill(p, "#00b000")
    p.drawRoundedRect(QRectF(3, 3, 26, 26), 3, 3)
    p.setPen(_pen(K, 2.6))
    p.drawPolyline(_poly((9, 7), (9, 24), (26, 24)))
    _arrow(p, 18, 13, False)


def i_cursor_pos(p):
    _fill(p, "#a0a0a0")
    p.drawRect(QRectF(3, 3, 26, 26))
    _label_text(p, "x,y", W, 11, QRectF(3, 3, 26, 14))


def i_arrow(p):
    p.setPen(_pen("#707070", 2.6))
    p.drawLine(QPointF(5, 5), QPointF(24, 24))
    _fill(p, "#707070")
    p.drawPolygon(_poly((28, 28), (16, 25), (25, 16)))


def i_line_style(p):
    p.setPen(_pen(K, 3))
    p.drawLine(QPointF(3, 8), QPointF(29, 8))
    pen = _pen(K, 3)
    pen.setCapStyle(Qt.FlatCap)
    pen.setDashPattern([2, 1])
    p.setPen(pen)
    p.drawLine(QPointF(3, 16), QPointF(29, 16))
    pen.setDashPattern([0.7, 1])
    p.setPen(pen)
    p.drawLine(QPointF(3, 24), QPointF(29, 24))


def i_plot_defs(p):
    _page(p)
    p.setPen(_pen("#ffd000", 3.4))
    p.drawLine(QPointF(5, 28), QPointF(17, 14))
    p.setPen(_pen(B, 2))
    p.drawLine(QPointF(3, 30), QPointF(5, 28))


def _log_page(p, color):
    _page(p)
    _fill(p, color, _pen(W, 1.2))
    p.drawEllipse(QPointF(10, 22), 7.6, 7.6)
    _fill(p, W)
    p.drawPolygon(_poly((10, 17), (14.5, 25.5), (5.5, 25.5)))
    _fill(p, color)
    p.drawPolygon(_poly((10, 20.5), (12, 24.2), (8, 24.2)))


def i_ltspice_log(p):
    _log_page(p, B)


def i_model_log(p):
    _log_page(p, "#e02020")


def i_arrange(p):
    _win(p, QRectF(3, 3, 26, 26))
    _fill(p, B)
    for x in (6, 14, 22):
        p.drawRect(QRectF(x, 22, 6, 4))


def i_clear_waves(p):
    _screen(p)
    _sine(p, 16, "#00e000")
    p.setPen(_pen("#e02020", 2.4))
    p.drawLine(QPointF(7, 7), QPointF(25, 25))


def i_ai(p):
    """Four-pointed sparkle (Tools > Configure Third-Party AI Assistants)."""
    def star(cx, cy, r, color):
        _fill(p, color)
        k = r * 0.28
        p.drawPolygon(_poly((cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k), (cx, cy + r),
                            (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)))
    star(14, 16, 12, K)
    star(25, 7, 5.5, TEAL)
    star(25, 25, 4, B)


ICONS = {name[2:]: fn for name, fn in list(globals().items()) if name.startswith("i_") and callable(fn)}


def icon(name) -> QIcon:
    pm = QPixmap(2 * U, 2 * U)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    # LTspice's glyphs run almost edge to edge
    p.translate(U / 2, U / 2)
    p.scale(1.07, 1.07)
    p.translate(-U / 2, -U / 2)
    ICONS.get(name, lambda p: _label_text(p, "?", K, 20, QRectF(0, 0, U, U)))(p)
    p.end()
    # drawn for a light toolbar; on a dark one, dark strokes are lightened (appearance.adapt_icon)
    from PySide6.QtGui import QGuiApplication, QPalette
    from .appearance import adapt_icon, is_dark
    ic = QIcon(adapt_icon(pm, QGuiApplication.palette().color(QPalette.Window)))
    ic.addPixmap(_greyed(pm, is_dark()), QIcon.Disabled)
    return ic


def _greyed(pm: QPixmap, dark=False) -> QPixmap:
    """LTspice greys a disabled button as a flat silhouette: dark parts turn mid grey and white
    details stay white (Qt's default is a washed-out copy instead). On a dark toolbar the
    silhouette is a dim grey, so disabled buttons still look disabled."""
    import numpy as np
    from PySide6.QtGui import QImage
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4).copy()
    lum = a[..., :3].astype(int).mean(-1)
    grey = np.array([92, 92, 96] if dark else [160, 160, 164], np.uint8)   # BGR: same for grey
    light = lum > 200
    a[..., :3] = np.where(light[..., None], 128 if dark else 255, grey)
    out = QImage(a.data, w, h, w * 4, QImage.Format_ARGB32).copy()
    out.setDevicePixelRatio(pm.devicePixelRatio())
    return QPixmap.fromImage(out)


# ---------------------------------------------------------------------------------------------
# Mouse cursors, 32x32, modelled on the ones LTspice shows in each mode (captured under Wine):
# a thin black crosshair with a white halo, plus a small badge for move/stretch/duplicate.

def _halo_line(p, a, b, w=1.6):
    p.setPen(_pen(W, w + 2.2))
    p.drawLine(a, b)
    p.setPen(_pen(K, w))
    p.drawLine(a, b)


def _crosshair(p, c=11, arm=10, gap=2):
    for a, b in (((c - arm, c), (c - gap, c)), ((c + gap, c), (c + arm, c)),
                 ((c, c - arm), (c, c - gap)), ((c, c + gap), (c, c + arm))):
        _halo_line(p, QPointF(*a), QPointF(*b))


def _square(p, x, y, filled=False):
    p.setPen(_pen(K, 1.4))
    p.setBrush(QColor(K if filled else W))
    p.drawRect(QRectF(x - 2.5, y - 2.5, 5, 5))


def c_move(p):
    _crosshair(p)
    pen = _pen(K, 1.4)
    pen.setStyle(Qt.DotLine)
    p.setPen(pen)
    p.drawLine(QPointF(19, 27), QPointF(27, 19))
    _square(p, 18, 28)
    _square(p, 28, 18)


def c_drag(p):
    _crosshair(p)
    p.setPen(_pen(K, 1.2))
    p.drawLine(QPointF(19, 19), QPointF(28, 19))
    p.drawLine(QPointF(28, 19), QPointF(28, 28))
    pen = _pen(K, 1.2)
    pen.setStyle(Qt.DotLine)
    p.setPen(pen)
    p.drawLine(QPointF(19, 27), QPointF(27, 19))
    _square(p, 18, 19, True)
    _square(p, 28, 28, True)
    _square(p, 18, 28)
    _square(p, 28, 19)


def c_duplicate(p):
    _crosshair(p)
    p.setPen(_pen(W, 6.4))
    p.drawLine(QPointF(19, 25), QPointF(29, 25))
    p.drawLine(QPointF(24, 20), QPointF(24, 30))
    p.setPen(_pen(K, 3))
    p.drawLine(QPointF(19, 25), QPointF(29, 25))
    p.drawLine(QPointF(24, 20), QPointF(24, 30))


def c_cross(p):
    _crosshair(p, 15, 15, 2)


def c_scissors(p):
    p.setPen(_pen(W, 5))
    p.drawLine(QPointF(4, 3), QPointF(21, 21))
    p.drawLine(QPointF(4, 21), QPointF(21, 3))
    p.setPen(_pen(K, 2.6))
    p.drawLine(QPointF(4, 3), QPointF(19, 19))
    p.drawLine(QPointF(4, 21), QPointF(19, 5))
    p.setPen(_pen(W, 4.5))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(24, 24), 4.5, 4.5)
    p.drawEllipse(QPointF(24, 1), 4.5, 4.5)
    p.setPen(_pen(K, 2.2))
    p.drawEllipse(QPointF(24, 24), 4.5, 4.5)
    p.drawEllipse(QPointF(23, 5), 4.5, 4.5)


def c_zoom(p):
    p.setPen(_pen(W, 7))
    p.drawLine(QPointF(19, 19), QPointF(28, 28))
    p.setPen(_pen(K, 4.5))
    p.drawLine(QPointF(19, 19), QPointF(28, 28))
    p.setPen(_pen(W, 1.6))
    p.setBrush(QColor(K))
    p.drawEllipse(QPointF(12, 12), 9.5, 9.5)
    p.setPen(_pen(W, 3))
    p.drawLine(QPointF(7, 12), QPointF(17, 12))
    p.drawLine(QPointF(12, 7), QPointF(12, 17))


def c_voltage(p):
    """Red voltage probe, tip at the bottom-left corner (the hotspot)."""
    p.setPen(_pen("#606060", 1.6))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(17, 2, 13, 11), 30 * 16, 300 * 16)
    p.setPen(_pen(K, 1.8))
    p.drawLine(QPointF(0.8, 31.2), QPointF(7, 25))
    body = _poly((6, 22.5), (9.5, 26), (27, 8.5), (23.5, 5))
    p.setPen(_pen("#600000", 1.2))
    p.setBrush(QColor("#e81010"))
    p.drawPolygon(body)
    p.setPen(_pen("#ff9090", 1.2))
    p.drawLine(QPointF(8.5, 22.5), QPointF(23.5, 7.5))


def c_current(p):
    """Current clamp with a cyan arrow; the hotspot is the clamp's centre."""
    p.setPen(_pen(K, 4.5))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(13, 18), 6.5, 6.5)
    p.drawLine(QPointF(18, 13), QPointF(27, 4))
    _fill(p, "#00d8f0", _pen(K, 1.2))
    p.drawPolygon(_poly((10.5, 2), (15.5, 2), (15.5, 21), (21, 21), (13, 30), (5, 21), (10.5, 21)))


def make_cursors():
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    dpr = max(1.0, screen.devicePixelRatio() if screen else 1.0)

    def cur(fn, hx, hy):
        # 32 logical pixels; a 2x pixmap would show as a 64 px cursor on a 1x screen
        pm = QPixmap(round(32 * dpr), round(32 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        fn(p)
        p.end()
        return QCursor(pm, hx, hy)
    return {
        "scissors": cur(c_scissors, 12, 12),
        "move": cur(c_move, 11, 11),
        "drag": cur(c_drag, 11, 11),
        "duplicate": cur(c_duplicate, 11, 11),
        "zoom": cur(c_zoom, 12, 12),
        "cross": cur(c_cross, 15, 15),
        "voltage": cur(c_voltage, 0, 31),
        "current": cur(c_current, 13, 18),
    }
