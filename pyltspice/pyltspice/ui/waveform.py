"""Waveform viewer: stacked plot panes with LTspice-style trace labels."""
import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMenu, QSplitter, QVBoxLayout, QWidget)
from shiboken6 import isValid

from ..sim.spicenum import fmt
from ..sim.vectors import VectorSet, unit_of
from .theme import TRACE_COLORS, theme

pg.setConfigOptions(antialias=True)

GRID_ALPHA = 0.55      # grid lines in the axis color at this alpha come out near LTspice's grey grid


def _setting(key):
    from .settings_dialog import get
    return get(key)


def plot_font():
    """Settings > Waveforms > Font; LTspice's default is Arial 10 pt, bold."""
    f = QFont(_setting("waveform/font"), _setting("waveform/font_size"))
    f.setBold(_setting("waveform/font_bold"))
    return f


def trace_width():
    """Settings > Waveforms > Data trace width (1 = LTspice's thin default)."""
    return 1.2 * _setting("waveform/trace_width")


def decimate(x, y, x0, x1, cols):
    """Indices of the points of (x, y) that draw the same picture as all of them over
    [x0, x1] at `cols` columns: per column the first, lowest, highest and last point.
    x must be non-decreasing; it need not be evenly spaced (transient steps aren't)."""
    i0 = max(int(np.searchsorted(x, x0, "left")) - 1, 0)
    i1 = min(int(np.searchsorted(x, x1, "right")) + 1, len(x))
    if i1 - i0 <= 4 * cols or x1 <= x0:
        return np.arange(i0, i1)
    xs, ys = x[i0:i1], y[i0:i1]
    col = np.floor((xs - x0) * (cols / (x1 - x0))).astype(np.int64)
    starts = np.flatnonzero(np.r_[True, col[1:] != col[:-1]])
    ends = np.r_[starts[1:], len(xs)] - 1
    seg = np.repeat(np.arange(len(starts)), ends - starts + 1)
    keep = [starts, ends]
    for red in (np.minimum, np.maximum):
        hit = np.flatnonzero(ys == red.reduceat(ys, starts)[seg])
        keep.append(hit[np.r_[True, seg[hit][1:] != seg[hit][:-1]]])   # first hit per column
    return i0 + np.unique(np.concatenate(keep))


def _crossing(f, v, i, level):
    """Frequency (interpolated in log f) and fraction where v crosses level between i and i+1."""
    t = (level - v[i]) / (v[i + 1] - v[i])
    return 10 ** (np.log10(f[i]) + t * (np.log10(f[i + 1]) - np.log10(f[i]))), t


def phase_margin(f, z):
    """(frequency, degrees) at the first downward 0 dB crossing of the loop gain z, or None.
    LTspice doesn't document its Annotate Phase Margin; this is the textbook definition,
    180 deg + phase there, wrapped to (-180, 180] so it doesn't matter which multiple of
    360 deg the unwrapped phase starts at."""
    mag = 20 * np.log10(np.maximum(np.abs(z), 1e-300))
    ph = np.degrees(np.unwrap(np.angle(z)))
    hits = np.flatnonzero((mag[:-1] > 0) & (mag[1:] <= 0))
    if not len(hits):
        return None
    i = hits[0]
    fc, t = _crossing(f, mag, i, 0.0)
    pm = (ph[i] + t * (ph[i + 1] - ph[i]) + 360) % 360 - 180
    return fc, (180.0 if pm == -180 else pm)


def gain_margin(f, z):
    """(frequency, dB) at the first phase crossing of -180 deg (mod 360), or None.
    Gain margin is minus the loop gain there (undocumented in LTspice, as phase_margin)."""
    mag = 20 * np.log10(np.maximum(np.abs(z), 1e-300))
    ph = np.degrees(np.unwrap(np.angle(z)))
    turn = np.floor((ph + 180) / 360)          # which odd multiple of 180 deg lies below
    hits = np.flatnonzero(turn[1:] != turn[:-1])
    if not len(hits):
        return None
    i = hits[0]
    level = 360 * max(turn[i], turn[i + 1]) - 180
    fc, t = _crossing(f, ph, i, level)
    return fc, -(mag[i] + t * (mag[i + 1] - mag[i]))


class TraceCurve(pg.PlotDataItem):
    """A trace that draws only what the screen can show. A switching circuit easily gives
    10^5..10^7 points; Qt stroking them all took tens of seconds per repaint, which froze the
    window. pyqtgraph's own downsampling assumes evenly spaced x, which transient data isn't,
    so this decimates per pixel column instead (`decimate`), redone on every x-range change.
    Hooks pyqtgraph's (private) _getDisplayDataset; the full data stays in its cache.
    Even decimated, Qt strokes an antialiased path wider than 1 px (the default 1.2 px trace)
    very slowly: ~10 s for 10k points of a switching waveform. Separate segments take 0.3 s."""

    MIN_POINTS = 2000         # below this, drawing everything is cheap

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._shown_key = None
        self._shown = None
        self._monotonic = {}
        self._stroke_mode()

    def setPen(self, *args, **kw):
        super().setPen(*args, **kw)
        self._stroke_mode()

    def _stroke_mode(self):
        pen = self.opts["pen"]
        wide = isinstance(pen, QPen) and pen.widthF() > 1 and pen.style() == Qt.SolidLine
        self.curve.setSegmentedLineMode("on" if wide else "auto")

    def _cols(self, vb):
        return max(int(vb.width() * 2), 1)

    def _getDisplayDataset(self):
        full = super()._getDisplayDataset()
        vb = self.getViewBox()
        if full is None or vb is None or len(full.x) <= self.MIN_POINTS:
            return full
        if id(full) not in self._monotonic:
            with np.errstate(invalid="ignore"):
                self._monotonic = {id(full): bool(np.all(np.diff(full.x) >= 0) and np.isfinite(full.y).all())}
        if not self._monotonic[id(full)]:
            return full
        r = vb.viewRect()
        key = (id(full), r.left(), r.right(), self._cols(vb))
        if key != self._shown_key:
            idx = decimate(full.x, full.y, r.left(), r.right(), key[3])
            self._shown = type(full)(full.x[idx], full.y[idx], full.xAllFinite, full.yAllFinite)
            self._shown_key = key
        return self._shown

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        # the drawn curve is only the visible slice; autorange needs the whole trace
        full = super()._getDisplayDataset()
        if full is None or not self.curve.isVisible() or len(full.x) <= self.MIN_POINTS:
            return super().dataBounds(ax, frac, orthoRange)
        d, o = (full.x, full.y) if ax == 0 else (full.y, full.x)
        if orthoRange is not None:
            d = d[(o >= orthoRange[0]) & (o <= orthoRange[1])]
        d = d[np.isfinite(d)]
        return (float(d.min()), float(d.max())) if len(d) else (None, None)

    def viewRangeChanged(self, vb=None, ranges=None, changed=None):
        super().viewRangeChanged(vb, ranges, changed)
        if changed is None or changed[0]:
            self.updateItems(styleUpdate=False)

    def viewTransformChanged(self):
        super().viewTransformChanged()
        vb = self.getViewBox()
        if vb is not None and self._shown_key is not None and self._shown_key[3] != self._cols(vb):
            self.updateItems(styleUpdate=False)


class EngAxis(pg.AxisItem):
    """Axis with LTspice-style engineering labels (1ms, 10KHz, -20dB)."""

    def __init__(self, orientation, unit="", log=False, **kw):
        super().__init__(orientation, **kw)
        self.unit = unit
        self.is_log = log
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        if not self.is_log:
            return self._linear_ticks(values, spacing)
        out = []
        for v in values:
            # label decades only, like LTspice
            if abs(v - round(v)) > 1e-6:
                out.append("")
                continue
            out.append(fmt(10 ** round(v), self.unit, 3))
        return out

    _PREFIX = {12: "T", 9: "G", 6: "M", 3: "K", 0: "", -3: "m", -6: "µ", -9: "n", -12: "p", -15: "f"}

    def _linear_ticks(self, values, spacing):
        """LTspice labels every tick of an axis with one prefix and one precision:
        0ms 3ms 6ms ..., 0.5V 1.0V ... 5.0V."""
        import math
        big = max((abs(v) for v in values), default=0.0) or abs(spacing) or 1.0
        exp = int(math.floor(math.log10(big) / 3) * 3)
        exp = max(-15, min(12, exp))
        scale = 10.0 ** exp
        step = abs(spacing) / scale if spacing else 1.0
        dec = max(0, -int(math.floor(math.log10(step) + 1e-9))) if step > 0 else 0
        prefix = self._PREFIX[exp]
        if prefix == "M" and not self.unit:
            prefix = "Meg"
        out = []
        for v in values:
            x = v / scale
            if abs(x) < step * 1e-6:
                x = 0.0
            out.append(f"{x:.{dec}f}{prefix}{self.unit}")
        return out


class Trace:
    def __init__(self, expr, color):
        self.expr = expr
        self.color = QColor(color)
        self.items = []
        self.item_steps = []         # .step run of each entry in items
        self.cx = self.cy = None     # data the cursors follow (first .step run)
        self.runs = []               # (step, x, y) per .step run; y is complex for AC
        self.vb = None
        self.pane = None


class Note:
    """A plot annotation (Notes & Annotations), kept as data so Edit > Move/Stretch/Duplicate/
    Delete and Plot Settings > Undo work on it; `items` are the graphics that draw it.
    pts are view coordinates (log10 f on AC plots): one for text and markers, two otherwise."""

    def __init__(self, kind, pane, pts, color, text="", anchor=(0, 1)):
        self.kind, self.pane, self.pts = kind, pane, [tuple(p) for p in pts]
        self.color, self.text, self.anchor = QColor(color), text, anchor
        self.items = []

    def copy(self):
        return Note(self.kind, self.pane, self.pts, self.color, self.text, self.anchor)

    @property
    def vb(self):
        return self.pane.plot.getPlotItem().getViewBox()

    @property
    def label(self):
        return self.items[-1] if self.kind in ("text", "marker") and self.items else None

    def draw(self):
        from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsRectItem
        self.erase()
        vb = self.vb
        pen = QPen(self.color)
        pen.setCosmetic(True)
        pen.setWidthF(1.5)
        (x0, y0), (x1, y1) = self.pts[0], self.pts[-1]
        if self.kind in ("text", "marker"):
            if self.kind == "marker":
                self.items.append(pg.ScatterPlotItem([x0], [y0], size=7, symbol="o",
                                                     pen=pg.mkPen(self.color), brush=None))
            label = pg.TextItem(self.text, color=self.color, anchor=self.anchor)
            label.setFont(plot_font())
            label.setPos(x0, y0)
            self.items.append(label)
        elif self.kind in ("line", "arrow"):
            self.items.append(pg.PlotCurveItem([x0, x1], [y0, y1], pen=pen))
            if self.kind == "arrow":
                # pyqtgraph arrows point along -angle in screen space; aim from tail to head
                a, b = vb.mapViewToScene(QPointF(x0, y0)), vb.mapViewToScene(QPointF(x1, y1))
                ang = math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x())) + 180
                self.items.append(pg.ArrowItem(pos=(x1, y1), angle=ang, headLen=12, pen=pen,
                                               brush=self.color))
        else:
            cls = QGraphicsRectItem if self.kind == "rect" else QGraphicsEllipseItem
            item = cls(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            item.setPen(pen)
            self.items.append(item)
        for it in self.items:
            vb.addItem(it, ignoreBounds=True)

    def erase(self):
        for it in self.items:
            if isValid(it) and it.scene() is not None:
                it.scene().removeItem(it)
        self.items = []

    def _scene_pts(self):
        return [self.vb.mapViewToScene(QPointF(*p)) for p in self.pts]

    def hit(self, pos, tol=5):
        """Is scene point pos on this note (within tol pixels)?"""
        pts = self._scene_pts()
        if self.kind in ("text", "marker"):
            near_dot = self.kind == "marker" and (pts[0] - pos).manhattanLength() <= 2 * tol
            return near_dot or self.label.sceneBoundingRect().adjusted(-tol, -tol, tol, tol).contains(pos)
        if self.kind in ("line", "arrow"):
            a, b = pts
            d = b - a
            n2 = d.x() ** 2 + d.y() ** 2
            t = 0.0 if n2 == 0 else max(0.0, min(1.0, QPointF.dotProduct(pos - a, d) / n2))
            q = a + d * t - pos
            return math.hypot(q.x(), q.y()) <= tol
        return QRectF(pts[0], pts[1]).normalized().adjusted(-tol, -tol, tol, tol).contains(pos)

    def nearest_point(self, pos):
        """Index of the end (or corner) nearest to scene point pos, for Stretch."""
        return min(range(len(self.pts)), key=lambda i: (self._scene_pts()[i] - pos).manhattanLength())


class Cursor:
    """A draggable crosshair locked onto one trace (LTspice: click a trace label)."""

    def __init__(self, viewer, trace, index):
        self.viewer, self.trace, self.index = viewer, trace, index
        log = viewer.is_ac
        pen = QPen(QColor("#808080"))
        pen.setCosmetic(True)
        pen.setStyle(Qt.DashLine)
        pen.setWidthF(_setting("waveform/cursor_width"))
        label = str(index)
        self.vline = pg.InfiniteLine(angle=90, movable=True, pen=pen,
                                     label=label, labelOpts={"position": 0.95, "color": "#000"})
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        x = trace.cx
        mid = x[len(x) // (3 if index == 1 else 2 if len(x) > 2 else 1)] if len(x) else 0
        self.vline.setValue(np.log10(mid) if log and mid > 0 else mid)
        trace.vb.addItem(self.vline, ignoreBounds=True)
        trace.vb.addItem(self.hline, ignoreBounds=True)
        self.vline.sigPositionChanged.connect(self._moved)
        self._moved()

    @property
    def x(self):
        v = self.vline.value()
        return 10 ** v if self.viewer.is_ac else v

    @property
    def y(self):
        return float(np.interp(self.x, self.trace.cx, self.trace.cy))

    def _moved(self, *_):
        self.hline.setValue(self.y)
        self.viewer.update_readout()

    def remove(self):
        for it in (self.vline, self.hline):
            vb = it.getViewBox()
            if vb is not None:
                vb.removeItem(it)


class CursorReadout(QWidget):
    """Floating readout of cursor positions and their difference."""

    def __init__(self, viewer):
        super().__init__(viewer, Qt.Tool)
        self.setWindowTitle("Cursors")
        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        f = self.label.font()
        f.setFamily("Monospace")
        self.label.setFont(f)
        lay = QVBoxLayout(self)
        lay.addWidget(self.label)

    def show_values(self, viewer):
        xu = "Hz" if viewer.is_ac else ("s" if viewer.analysis == "tran" else "V")
        rows = []
        cur = {c.index: c for c in viewer.cursors}
        for i in (1, 2):
            c = cur.get(i)
            if c is None:
                continue
            yu = "dB" if viewer.is_ac else unit_of(c.trace.expr)
            rows.append(f"<b>Cursor {i}</b> {c.trace.expr}<br>"
                        f"&nbsp;Horz: {fmt(c.x, xu, 6)}&nbsp;&nbsp;Vert: {fmt(c.y, yu, 6)}")
        if 1 in cur and 2 in cur:
            dx = cur[2].x - cur[1].x
            dy = cur[2].y - cur[1].y
            yu = "dB" if viewer.is_ac else unit_of(cur[1].trace.expr)
            line = f"<b>Diff (Cursor2 - Cursor1)</b><br>&nbsp;Horz: {fmt(dx, xu, 6)}&nbsp;&nbsp;Vert: {fmt(dy, yu, 6)}"
            if dx and not viewer.is_ac:
                line += f"<br>&nbsp;Freq: {fmt(1 / abs(dx), 'Hz', 6)}&nbsp;&nbsp;Slope: {fmt(dy / dx, '', 6)}"
            rows.append(line)
        self.label.setText("<br><br>".join(rows))
        self.adjustSize()


class Pane(QWidget):
    """One plot pane: clickable trace labels above a plot."""
    activated = Signal(object)

    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.traces = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.labels = QLabel()
        self.labels.setAlignment(Qt.AlignCenter)
        self.labels.setTextFormat(Qt.RichText)
        self.labels.linkActivated.connect(self._label_clicked)
        bg = theme().color("plot_background").name()
        self.labels.setStyleSheet(f"background:{bg}; padding:2px;")
        self.labels.setFont(plot_font())
        lay.addWidget(self.labels)
        is_ac = viewer.is_ac
        xunit = "Hz" if is_ac else ("s" if viewer.analysis == "tran" else "V")
        self.bottom = EngAxis("bottom", xunit, log=is_ac)
        self.left = EngAxis("left", "dB" if is_ac else "")
        self.plot = pg.PlotWidget(axisItems={"bottom": self.bottom, "left": self.left},
                                  background=theme().color("plot_background"))
        self.plot.showGrid(x=viewer.show_grid, y=viewer.show_grid, alpha=GRID_ALPHA)
        pi = self.plot.getPlotItem()
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        pi.getViewBox().setBorder(pg.mkPen(theme().color("plot_axis")))   # LTspice frames the plot area
        for ax in ("left", "bottom"):
            a = pi.getAxis(ax)
            a.setPen(theme().color("plot_axis"))
            a.setTextPen(theme().color("plot_text"))
            a.setStyle(tickFont=plot_font())
        self.phase_vb = None          # right-hand axis: phase (AC) or a second unit
        self.right = None
        self.left_unit = None
        if is_ac:
            pi.setLogMode(x=True, y=False)
            if viewer.show_phase:
                self._ensure_right("°")
        # an empty pane already spans the simulated range, without Y labels (as in LTspice)
        try:
            x = np.real(viewer.x)
            if len(x) > 1:
                lo, hi = float(np.min(x)), float(np.max(x))
                if is_ac and lo > 0:
                    lo, hi = np.log10(lo), np.log10(hi)
                if hi > lo:
                    pi.setXRange(lo, hi, padding=0)
        except Exception:  # noqa: BLE001 - any odd x vector just keeps the default range
            pass
        self.left.setStyle(showValues=False)
        self.plot.scene().sigMouseMoved.connect(self._mouse_moved)
        self.plot.setContextMenuPolicy(Qt.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(lambda p: viewer.context_menu(self, self.plot.mapToGlobal(p)))
        self.plot.scene().sigMouseClicked.connect(self._clicked)
        lay.addWidget(self.plot, 1)

    def _ensure_right(self, unit):
        if self.phase_vb is not None:
            return
        pi = self.plot.getPlotItem()
        self.phase_vb = pg.ViewBox()
        self.right = EngAxis("right", unit)
        pi.layout.addItem(self.right, 2, 3)
        pi.scene().addItem(self.phase_vb)
        self.right.linkToView(self.phase_vb)
        self.phase_vb.setXLink(pi)
        self.right.setPen(theme().color("plot_axis"))
        self.right.setTextPen(theme().color("plot_text"))
        self.right.setStyle(tickFont=plot_font())
        pi.getViewBox().sigResized.connect(self._sync_phase)
        self._sync_phase()

    def _sync_phase(self):
        vb = self.plot.getPlotItem().getViewBox()
        self.phase_vb.setGeometry(vb.sceneBoundingRect())
        self.phase_vb.linkedViewChanged(vb, self.phase_vb.XAxis)

    def _mouse_moved(self, pos):
        if self.viewer.carry is not None and self.viewer.carry[0].pane is self:
            self.viewer.note_drag(pos)
        vb = self.plot.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(pos):
            return
        pt = vb.mapSceneToView(pos)
        x = 10 ** pt.x() if self.viewer.is_ac else pt.x()
        xu = self.bottom.unit
        self.viewer.status.emit(f"x = {fmt(x, xu, 5)}    y = {fmt(pt.y(), self.left.unit, 5)}")

    def _clicked(self, ev):
        self.activated.emit(self)
        if ev.button() == Qt.LeftButton and self.viewer.mode in ANNOTATIONS:
            vb = self.plot.getPlotItem().getViewBox()
            if vb.sceneBoundingRect().contains(ev.scenePos()):
                self.viewer.annotation_click(self, vb.mapSceneToView(ev.scenePos()))
                ev.accept()
        elif ev.button() == Qt.LeftButton and self.viewer.mode in NOTE_EDIT:
            if self.viewer.note_click(self, ev.scenePos()):
                ev.accept()

    def _label_clicked(self, link):
        i = int(link)
        if 0 <= i < len(self.traces):
            if self.viewer.mode == "delete":
                self.viewer.record()
                self.remove_trace(self.traces[i])
                self.viewer.traces_changed.emit()
                return
            self.viewer.trace_menu(self, self.traces[i])

    def refresh_labels(self):
        parts = []
        for i, t in enumerate(self.traces):
            parts.append(f'<a href="{i}" style="color:{t.color.name()}; text-decoration:none">{t.expr}</a>')
        self.labels.setText("&nbsp;&nbsp;&nbsp;".join(parts) or "&nbsp;")

    def add_trace(self, trace: Trace, x, y, steps):
        self.left.setStyle(showValues=True)
        pi = self.plot.getPlotItem()
        pen = QPen(trace.color)
        pen.setCosmetic(True)
        pen.setWidthF(trace_width())
        a0, b0 = steps[0]
        trace.cx = x[a0:b0]
        trace.cy = (20 * np.log10(np.maximum(np.abs(y[a0:b0]), 1e-300)) if self.viewer.is_ac
                    else np.real(y[a0:b0]))
        trace.pane = self
        for k, (a, b) in enumerate(steps):
            xs = x[a:b]
            trace.runs.append((k, xs, y[a:b]))
            n_before = len(trace.items)
            if self.viewer.is_ac:
                z = y[a:b]
                mag = 20 * np.log10(np.maximum(np.abs(z), 1e-300))
                item = TraceCurve(xs, mag, pen=pen)
                pi.addItem(item)
                trace.items.append((pi, item))
                if self.viewer.show_phase:
                    ph = np.degrees(np.unwrap(np.angle(z)))
                    dpen = QPen(pen)
                    dpen.setStyle(Qt.DashLine)
                    pitem = TraceCurve(np.log10(xs), ph, pen=dpen)
                    self.phase_vb.addItem(pitem)
                    trace.items.append((self.phase_vb, pitem))
            else:
                ys = np.real(y[a:b])
                unit = unit_of(trace.expr)
                if self.left_unit is None:
                    self.left_unit = unit
                    self.left.unit = unit
                if unit == self.left_unit:
                    item = TraceCurve(xs, ys, pen=pen)
                    pi.addItem(item)
                    trace.items.append((pi, item))
                    trace.vb = pi.getViewBox()
                else:
                    # LTspice puts a second unit (e.g. currents) on a right-hand axis
                    self._ensure_right(unit)
                    item = TraceCurve(xs, ys, pen=pen)
                    self.phase_vb.addItem(item)
                    trace.items.append((self.phase_vb, item))
                    trace.vb = self.phase_vb
            trace.item_steps += [k] * (len(trace.items) - n_before)
            for _, it in trace.items[n_before:]:
                it.setVisible(self.viewer.visible_steps is None or k in self.viewer.visible_steps)
                if self.viewer.mark_points and hasattr(it, "setSymbol"):
                    it.setSymbol("o")
                    it.setSymbolSize(4)
                    it.setSymbolPen(trace.color)
                    it.setSymbolBrush(trace.color)
        if self.viewer.is_ac:
            trace.vb = pi.getViewBox()
        self.traces.append(trace)
        self.refresh_labels()
        if self.viewer.autoranging:
            self.autorange()

    def remove_trace(self, trace):
        self.viewer.detach_cursors(trace)
        for owner, item in trace.items:
            owner.removeItem(item)
        self.traces.remove(trace)
        self.refresh_labels()

    def autorange(self):
        self.plot.getPlotItem().enableAutoRange()
        if self.phase_vb is not None:
            self.phase_vb.enableAutoRange()


class WaveformViewer(QWidget):
    status = Signal(str)
    traces_changed = Signal()
    save_plot_settings = Signal()

    def __init__(self, plot, title="", parent=None):
        super().__init__(parent)
        self.plot = plot
        from .settings_dialog import plot_defs_path
        defs = plot_defs_path()
        self.vectors = VectorSet(plot, radians=_setting("waveform/radians"),
                                 defs=defs.read_text(errors="replace") if defs.is_file() else None)
        self.title = title
        self.analysis = plot.analysis
        self.is_ac = plot.is_complex
        self.show_phase = plot.plotname != "FFT"
        self.panes = []
        self.active = None
        self.color_i = 0
        self.cursors = []
        self.readout = None
        self.show_grid = False      # LTspice: Plot Settings > Grid is off by default
        self.sync_x = True          # Plot Settings > Sync. Horiz. Axes
        self.mark_points = False
        self.autoranging = True
        self.visible_steps = None   # None: all .step runs
        self.mode = None            # 'delete' or an annotation kind
        self.menu_provider = None   # main window's right-click menu
        self.plt_path = None        # plot settings file last loaded or saved
        self.notes = []                  # Notes & Annotations
        self.carry = None                # (note, point index or None, grab point, original pts)
        self.annot_color = QColor("#ffffff")
        self._anno_start = None
        self._undo, self._redo, self._quiet = [], [], False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.split = QSplitter(Qt.Vertical)
        lay.addWidget(self.split)
        self.add_pane()

    @property
    def x(self):
        return self.vectors.x

    def steps(self):
        return self.plot.step_bounds or [(0, self.plot.data.shape[1])]

    def add_pane(self):
        p = Pane(self)
        p.activated.connect(self._set_active)
        if self.panes and self.sync_x:
            p.plot.setXLink(self.panes[0].plot)
        self.panes.append(p)
        self.split.addWidget(p)
        self.active = p
        return p

    def set_grid(self, on):
        self.show_grid = on
        for p in self.panes:
            p.plot.showGrid(x=on, y=on, alpha=GRID_ALPHA)

    def _set_active(self, pane):
        if self.active is not pane:
            self.active = pane
            self.traces_changed.emit()        # pane up/down, delete pane... depend on it

    def next_color(self):
        c = TRACE_COLORS[self.color_i % len(TRACE_COLORS)]
        self.color_i += 1
        return c

    def has_trace(self, expr):
        return any(t.expr.lower() == expr.lower() for p in self.panes for t in p.traces)

    def add_trace(self, expr, pane=None):
        """Plot an expression such as 'V(out)' or 'V(out)/V(in)'. Returns error text or ''."""
        expr = expr.strip()
        if not expr:
            return ""
        try:
            y = self.vectors.eval(expr)
        except KeyError as e:
            return f"Unknown data: {e.args[0]}"
        except Exception as e:  # noqa: BLE001 - user expression errors
            return str(e)
        y = np.broadcast_to(np.asarray(y), self.x.shape)
        pane = pane or self.active or self.panes[0]
        self.record()
        pane.add_trace(Trace(expr, self.next_color()), self.x, y, self.steps())
        self.traces_changed.emit()
        return ""

    def export_text(self, path):
        """Write x and every trace as tab-separated columns (complex as dB,deg)."""
        names = self.trace_names()
        a, b = self.steps()[0]
        cols = [self.x[a:b]]
        header = [self.plot.xname]
        for n in names:
            y = np.broadcast_to(np.asarray(self.vectors.eval(n)), self.x.shape)[a:b]
            if self.is_ac:
                cols += [20 * np.log10(np.maximum(np.abs(y), 1e-300)), np.degrees(np.angle(y))]
                header += [f"{n} dB", f"{n} deg"]
            else:
                cols.append(np.real(y))
                header.append(n)
        with open(path, "w") as f:
            f.write("\t".join(header) + "\n")
            for row in zip(*cols):
                f.write("\t".join(f"{v:.9g}" for v in row) + "\n")

    def apply_layout(self, panes):
        """Show traces pane by pane, e.g. from a .plt file (top pane first)."""
        for k, exprs in enumerate(panes):
            pane = self.panes[k] if k < len(self.panes) else self.add_pane()
            for e in exprs:
                err = self.add_trace(e, pane)
                if err:
                    self.status.emit(err)

    def visible_x_range(self):
        (x0, x1), _ = self.panes[0].plot.getPlotItem().getViewBox().viewRange()
        if self.is_ac:
            x0, x1 = 10 ** x0, 10 ** x1
        lo, hi = float(np.min(self.x)), float(np.max(self.x))
        return max(x0, lo), min(x1, hi)

    def layout(self):
        return [[t.expr for t in p.traces] for p in self.panes]

    def trace_names(self):
        return [t.expr for p in self.panes for t in p.traces]

    def clear(self):
        for p in self.panes:
            for t in list(p.traces):
                p.remove_trace(t)

    # -- menus
    def context_menu(self, pane, global_pos):
        self.active = pane
        if self.mode is not None:          # right-click ends a mode, as in LTspice
            self.end_mode()
            return
        if self.menu_provider is not None:
            self.menu_provider(global_pos)
            return
        m = QMenu(self)
        m.addAction("Add Traces", lambda: self.add_traces_dialog(pane))
        m.addAction("Delete Traces", lambda: self._delete_all(pane))
        m.addSeparator()
        m.addAction("Add Plot Pane", self.add_pane)
        if len(self.panes) > 1:
            m.addAction("Delete this Pane", lambda: self.delete_pane(pane))
        m.addSeparator()
        m.addAction("Zoom to Fit", self.autorange)
        m.addAction("Save Plot Settings", self.save_plot_settings.emit)
        grid = QAction("Grid", m, checkable=True, checked=self.show_grid)
        grid.toggled.connect(self.set_grid)
        m.addAction(grid)
        m.exec(global_pos)

    # -- cursors
    def attach_cursor(self, trace, index):
        self.detach_cursor(index)
        if trace.vb is None or trace.cx is None or not len(trace.cx):
            return
        self.cursors.append(Cursor(self, trace, index))
        if self.readout is None:
            self.readout = CursorReadout(self)
        self.update_readout()
        self.readout.show()
        self.traces_changed.emit()

    def detach_cursor(self, index):
        gone = [c for c in self.cursors if c.index == index]
        for c in gone:
            c.remove()
            self.cursors.remove(c)
        self.update_readout()
        if gone:
            self.traces_changed.emit()

    def detach_cursors(self, trace):
        for c in [c for c in self.cursors if c.trace is trace]:
            self.detach_cursor(c.index)

    def update_readout(self):
        if self.readout is None:
            return
        if not self.cursors:
            self.readout.hide()
            return
        self.readout.show_values(self)

    def trace_menu(self, pane, trace):
        m = QMenu(self)
        m.addAction("Attach Cursor 1", lambda: self.attach_cursor(trace, 1))
        m.addAction("Attach Cursor 2", lambda: self.attach_cursor(trace, 2))
        if self.cursors:
            m.addAction("Remove Cursors", lambda: (self.detach_cursor(1), self.detach_cursor(2)))
        m.addSeparator()
        m.addAction(f"Delete {trace.expr}", lambda: (pane.remove_trace(trace), self.traces_changed.emit()))
        stats = self._stats(trace)
        if stats:
            m.addAction(stats).setEnabled(False)
        m.exec(pane.labels.mapToGlobal(pane.labels.rect().bottomLeft()))

    def _stats(self, trace):
        """Average and RMS over the displayed interval (LTspice: Ctrl+click label)."""
        if self.is_ac:
            return ""
        try:
            y = np.real(self.vectors.eval(trace.expr))
        except Exception:  # noqa: BLE001
            return ""
        x = self.x
        a, b = self.steps()[0]
        x, y = x[a:b], y[a:b]
        if len(x) < 2 or x[-1] == x[0]:
            return ""
        T = x[-1] - x[0]
        avg = np.trapezoid(y, x) / T
        rms = np.sqrt(np.trapezoid(y * y, x) / T)
        u = unit_of(trace.expr)
        return f"Average: {fmt(avg, u, 5)}   RMS: {fmt(rms, u, 5)}"

    def _delete_all(self, pane):
        self.record()
        for t in list(pane.traces):
            pane.remove_trace(t)
        self.traces_changed.emit()

    def delete_pane(self, pane):
        if len(self.panes) <= 1:
            return
        self.record()
        self._drop_notes(pane)
        self.panes.remove(pane)
        pane.setParent(None)
        pane.deleteLater()
        self.active = self.panes[-1]

    def _drop_notes(self, pane):
        for n in [n for n in self.notes if n.pane is pane]:
            n.erase()
            self.notes.remove(n)

    def autorange(self):
        for p in self.panes:
            p.autorange()

    def add_traces_dialog(self, pane=None):
        dlg = AddTracesDialog(self.vectors.names(), self)
        if dlg.exec() == QDialog.Accepted:
            for expr in dlg.expressions():
                err = self.add_trace(expr, pane)
                if err:
                    self.status.emit(err)

    # -- Plot Settings commands (LTspice 26 menu)
    def record(self):
        """Remember traces and annotations for Plot Settings > Undo."""
        if self._quiet:
            return
        self._undo.append(self._state())
        del self._undo[:-50]
        self._redo.clear()

    def _state(self):
        notes = [(self.panes.index(n.pane), n.copy()) for n in self.notes if n.pane in self.panes]
        return self.layout(), notes

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def _restore(self, state):
        layout, notes = state
        self._quiet = True
        try:
            for n in self.notes:
                n.erase()
            self.notes = []
            self.clear_panes()
            self.apply_layout(layout)
        finally:
            self._quiet = False
        for i, n in notes:
            if i < len(self.panes):
                n = n.copy()
                n.pane = self.panes[i]
                self.notes.append(n)
                n.draw()
        self.traces_changed.emit()

    def undo(self):
        if self._undo:
            self._redo.append(self._state())
            self._restore(self._undo.pop())

    def redo(self):
        if self._redo:
            self._undo.append(self._state())
            self._restore(self._redo.pop())

    def clear_panes(self):
        """Back to one empty pane."""
        for c in list(self.cursors):
            self.detach_cursor(c.index)
        for p in self.panes[1:]:
            self._drop_notes(p)
            p.setParent(None)
            p.deleteLater()
        self.panes = self.panes[:1]
        self.active = self.panes[0]
        for t in list(self.panes[0].traces):
            self.panes[0].remove_trace(t)

    def start_delete_mode(self):
        self.mode = "delete"
        self.traces_changed.emit()
        self.setCursor(icons_cursor("scissors"))
        self.status.emit("Click on a trace label or an annotation to delete it.  Right-click or Esc to quit.")

    def end_mode(self):
        if self.carry is not None:
            self._cancel_carry()
        self.mode = None
        self._anno_start = None
        self.unsetCursor()
        self.traces_changed.emit()
        self.status.emit("")

    def place_cursor(self):
        """Plot Settings > Place Cursor on Active Trace: cursor 1, then cursor 2."""
        pane = self.active if self.active in self.panes and self.active.traces else \
            next((p for p in self.panes if p.traces), None)
        if pane is None:
            return
        have = {c.index for c in self.cursors}
        self.attach_cursor(pane.traces[0], 1 if 1 not in have else 2)

    def clear_cursors(self):
        if self.mode is not None:
            self.end_mode()
        for i in (1, 2):
            self.detach_cursor(i)

    def redraw(self):
        for p in self.panes:
            p.plot.update()
            p.refresh_labels()
        self.update()

    def add_pane_at(self, above=True):
        self.record()
        i = self.panes.index(self.active) if self.active in self.panes else len(self.panes) - 1
        p = self.add_pane()
        self.panes.remove(p)
        at = i if above else i + 1
        self.panes.insert(at, p)
        self.split.insertWidget(at, p)
        self.active = p
        self.traces_changed.emit()

    def move_active_pane(self, d):
        if self.active not in self.panes:
            return
        i = self.panes.index(self.active)
        j = i + d
        if not 0 <= j < len(self.panes):
            return
        self.record()
        self.panes.insert(j, self.panes.pop(i))
        self.split.insertWidget(j, self.active)
        self.traces_changed.emit()

    def set_sync_x(self, on):
        self.sync_x = on
        first = self.panes[0].plot
        for p in self.panes[1:]:
            p.plot.setXLink(first if on else None)

    def reset_colors(self):
        self.color_i = 0
        for p in self.panes:
            for t in p.traces:
                t.color = QColor(self.next_color())
                for _, it in t.items:
                    pen = QPen(it.opts["pen"]) if hasattr(it, "opts") and "pen" in it.opts else QPen()
                    pen.setColor(t.color)
                    it.setPen(pen)
            p.refresh_labels()

    def set_mark_points(self, on):
        self.mark_points = on
        for p in self.panes:
            for t in p.traces:
                for _, it in t.items:
                    if hasattr(it, "setSymbol"):
                        it.setSymbol("o" if on else None)
                        it.setSymbolSize(4)
                        it.setSymbolPen(t.color)
                        it.setSymbolBrush(t.color)

    def select_steps_dialog(self):
        """Plot Settings > Select Steps: choose which .step runs are drawn."""
        steps = self.steps()
        labels = list(self.plot.step_labels) or [f"Step {i + 1}" for i in range(len(steps))]
        dlg = QDialog(self)
        dlg.setWindowTitle("Select Steps")
        lay = QVBoxLayout(dlg)
        lst = QListWidget()
        from PySide6.QtWidgets import QListWidgetItem
        for i, lab in enumerate(labels):
            it = QListWidgetItem(lab or f"Step {i + 1}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if self.visible_steps is None or i in self.visible_steps else Qt.Unchecked)
            lst.addItem(it)
        lay.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        on = {i for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked}
        self.set_visible_steps(None if len(on) == lst.count() else on)

    def set_visible_steps(self, steps):
        self.visible_steps = steps
        for p in self.panes:
            for t in p.traces:
                for (_, it), k in zip(t.items, t.item_steps):
                    it.setVisible(steps is None or k in steps)

    def manual_limits_dialog(self):
        """Plot Settings > Manual Limits for the active pane."""
        pane = self.active if self.active in self.panes else self.panes[0]
        vb = pane.plot.getPlotItem().getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        if self.is_ac:
            x0, x1 = 10 ** x0, 10 ** x1
        xu, yu = pane.bottom.unit, pane.left.unit
        dlg = QDialog(self)
        dlg.setWindowTitle("Manual Limits")
        from PySide6.QtWidgets import QFormLayout
        form = QFormLayout(dlg)
        edits = {}
        for key, label, val, u in (("x0", "Horizontal Left:", x0, xu), ("x1", "Horizontal Right:", x1, xu),
                                   ("y1", "Vertical Top:", y1, yu), ("y0", "Vertical Bottom:", y0, yu)):
            e = QLineEdit(fmt(val, u, 5))
            edits[key] = e
            form.addRow(label, e)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        from ..sim.spicenum import parse
        v = {k: parse(e.text().strip().rstrip("sVAdBHz°")) for k, e in edits.items()}
        if any(x is None for x in v.values()):
            self.status.emit("Manual Limits: not a number")
            return
        if self.is_ac:
            if v["x0"] <= 0 or v["x1"] <= 0:
                return
            v["x0"], v["x1"] = np.log10(v["x0"]), np.log10(v["x1"])
        self.autoranging = False
        vb.setRange(xRange=(v["x0"], v["x1"]), yRange=(v["y0"], v["y1"]), padding=0)

    def recenter(self):
        """View > Recenter: put the middle of the data in the middle, keeping the zoom."""
        lo, hi = float(np.min(np.real(self.x))), float(np.max(np.real(self.x)))
        if self.is_ac and lo > 0:
            lo, hi = np.log10(lo), np.log10(hi)
        vb = self.panes[0].plot.getPlotItem().getViewBox()
        (x0, x1), _ = vb.viewRange()
        mid, half = (lo + hi) / 2, (x1 - x0) / 2
        vb.setXRange(mid - half, mid + half, padding=0)

    # -- Notes & Annotations
    def start_annotation(self, kind):
        self.mode = kind
        self._anno_start = None
        self.setCursor(Qt.CrossCursor)
        self.traces_changed.emit()
        what = {"text": "Click where the text goes.", "arrow": "Click the tail, then the head of the arrow.",
                "line": "Click the two ends of the line.", "rect": "Click two corners of the rectangle.",
                "ellipse": "Click two corners of the ellipse's bounding box."}[kind]
        self.status.emit(what + "  Right-click to quit.")

    def annotation_click(self, pane, pt):
        from PySide6.QtWidgets import QInputDialog
        if self.mode == "text":
            text, ok = QInputDialog.getText(self, "Text", "Enter text:")
            if ok and text:
                self._add_text(pane, pt.x(), pt.y(), text)
            return
        if self._anno_start is None:
            self._anno_start = (pane, pt)
            return
        _, p0 = self._anno_start
        self._anno_start = None
        self.add_note(Note(self.mode, pane, [(p0.x(), p0.y()), (pt.x(), pt.y())], self.annot_color))

    def add_note(self, note):
        self.record()
        self.notes.append(note)
        note.draw()
        return note

    def _add_text(self, pane, x, y, text, color=None, anchor=(0, 1)):
        return self.add_note(Note("text", pane, [(x, y)], color or self.annot_color, text, anchor))

    # Edit > Move / Stretch / Duplicate / Delete on annotations (plot right-click menu)
    def start_note_edit(self, mode):
        self.mode = mode
        self.carry = None
        self.setCursor(icons_cursor({"note_move": "move", "note_stretch": "drag",
                                     "note_dup": "duplicate"}[mode]))
        self.traces_changed.emit()
        what = {"note_move": "move", "note_stretch": "stretch (drag an end or corner)",
                "note_dup": "duplicate"}[mode]
        self.status.emit(f"Click an annotation to {what}.  Right-click or Esc to quit.")

    def note_at(self, pane, pos):
        return next((n for n in reversed(self.notes) if n.pane is pane and n.hit(pos)), None)

    def note_click(self, pane, pos):
        """A left click in an annotation-editing mode (or Delete Traces). True if it was used."""
        if self.carry is not None:
            self.note_drag(pos)                     # drop what's carried right here
            self.carry = None
            self.status.emit("")
            return True
        note = self.note_at(pane, pos)
        if note is None:
            return False
        self.record()
        if self.mode == "delete":
            note.erase()
            self.notes.remove(note)
            self.traces_changed.emit()
            return True
        if self.mode == "note_dup":
            note = note.copy()
            self.notes.append(note)
            note.draw()
        which = note.nearest_point(pos) if self.mode == "note_stretch" and len(note.pts) > 1 else None
        self.carry = (note, which, note.vb.mapSceneToView(pos), list(note.pts))
        self.traces_changed.emit()
        return True

    def note_drag(self, pos):
        note, which, start, orig = self.carry
        p = note.vb.mapSceneToView(pos)
        dx, dy = p.x() - start.x(), p.y() - start.y()
        note.pts = [(x + dx, y + dy) if which is None or i == which else (x, y)
                    for i, (x, y) in enumerate(orig)]
        note.draw()

    def _cancel_carry(self):
        note, _, _, orig = self.carry
        self.carry = None
        if self.mode == "note_dup":
            note.erase()
            self.notes.remove(note)
        else:
            note.pts = orig
            note.draw()
        if self._undo:
            self._undo.pop()                        # nothing changed after all

    def annotate_cursor(self):
        """Notes & Annotations > Cursor Position: label cursor 1 with its coordinates."""
        if not self.cursors:
            return
        c = min(self.cursors, key=lambda c: c.index)
        xu = "Hz" if self.is_ac else ("s" if self.analysis == "tran" else "V")
        yu = "dB" if self.is_ac else unit_of(c.trace.expr)
        pane = c.trace.pane
        x = np.log10(c.x) if self.is_ac else c.x
        self._add_text(pane, x, c.y, f"({fmt(c.x, xu, 5)}, {fmt(c.y, yu, 5)})")

    def annotate_margin(self, kind):
        """Notes & Annotations > Annotate Phase/Gain Margin: mark each AC trace of the active
        pane (every shown .step run) at its 0 dB or -180 deg crossover."""
        pane = self.active if self.active in self.panes else self.panes[0]
        shown = self.visible_steps
        found = 0
        for t in pane.traces:
            for k, f, z in t.runs:
                if shown is not None and k not in shown:
                    continue
                r = (phase_margin if kind == "pm" else gain_margin)(f, z)
                if r is None:
                    continue
                fc, val = r
                if kind == "pm":
                    y, label = 0.0, f"Phase Margin: {val:.1f}° @ {fmt(fc, 'Hz', 4)}"
                else:
                    y, label = -val, f"Gain Margin: {val:.1f}dB @ {fmt(fc, 'Hz', 4)}"
                self._add_marker(pane, np.log10(fc), y, label, t.color)
                found += 1
        if not found:
            what = "0 dB crossing" if kind == "pm" else "-180° phase crossing"
            self.status.emit(f"No trace in the active pane has a {what}")

    def annotate_steps(self):
        """Notes & Annotations > Annotate Steps: name each shown .step run at the right end of
        its curve in the active pane (undocumented in LTspice; labels as in Select Steps)."""
        pane = self.active if self.active in self.panes else self.panes[0]
        labels = list(self.plot.step_labels)
        vb = pane.plot.getPlotItem().getViewBox()
        x1 = vb.viewRange()[0][1]
        for t in pane.traces:
            if t.vb is not None and t.vb is not vb:
                continue                    # on the right-hand axis: different y scale
            for k, xs, ys in t.runs:
                if self.visible_steps is not None and k not in self.visible_steps:
                    continue
                if self.is_ac:
                    xs, ys = np.log10(xs), 20 * np.log10(np.maximum(np.abs(ys), 1e-300))
                else:
                    xs, ys = np.real(xs), np.real(ys)
                i = min(int(np.searchsorted(xs, x1, "right")), len(xs)) - 1
                if i < 0 or k >= len(labels) or not labels[k]:
                    continue
                self._add_text(pane, xs[i], ys[i], labels[k], t.color, (1, 1))

    def _add_marker(self, pane, x, y, text, color):
        self.add_note(Note("marker", pane, [(x, y)], color, text, (-0.05, 1.1)))
        self._restack(pane)
        if not getattr(pane, "_restack_hooked", False):
            # rows are worked out in pixels: redo them when the pane is resized or zoomed
            from PySide6.QtCore import QTimer
            vb = pane.plot.getPlotItem().getViewBox()
            later = lambda *_: QTimer.singleShot(0, lambda: self._restack(pane))
            vb.sigResized.connect(later)
            vb.sigRangeChanged.connect(later)
            pane._restack_hooked = True

    def _restack(self, pane):
        """Margin labels of several traces/steps land close together: each takes the row nearest
        its point (above, then below...) that clears the labels before it and stays in the plot."""
        if not isValid(pane) or pane not in self.panes:
            return
        placed = []
        area = pane.plot.getPlotItem().getViewBox().sceneBoundingRect()
        # anchor y: 1.1 = just above the point, -0.1 = just below, each step one more line
        rows = [1.1] + [y for n in range(1, 6) for y in (1.1 + n, -0.1 - (n - 1))]
        for note in [n for n in self.notes if n.kind == "marker" and n.pane is pane and n.label is not None]:
            for ay in rows + [1.1]:
                note.anchor = (-0.05, ay)
                note.label.setAnchor(note.anchor)
                r = note.label.sceneBoundingRect()
                if area.contains(r) and not any(r.intersects(o) for o in placed):
                    break
            placed.append(note.label.sceneBoundingRect())

    def annotation_style_dialog(self):
        from PySide6.QtWidgets import QColorDialog
        col = QColorDialog.getColor(self.annot_color, self, "Line Style/Color")
        if col.isValid():
            self.annot_color = col

    def apply_settings(self):
        """Settings > Waveforms changed: trace width, font, radians."""
        self.vectors.radians = _setting("waveform/radians")
        for p in self.panes:
            for ax in (p.bottom, p.left, p.right):
                if ax is not None:
                    ax.setStyle(tickFont=plot_font())
            p.labels.setFont(plot_font())
            for t in p.traces:
                for _, it in t.items:
                    if hasattr(it, "opts") and "pen" in it.opts:
                        pen = QPen(it.opts["pen"])
                        pen.setWidthF(trace_width())
                        it.setPen(pen)
        self.redraw()


def icons_cursor(name):
    from .icons import make_cursors
    global _CURSORS
    if _CURSORS is None:
        _CURSORS = make_cursors()
    return _CURSORS.get(name, Qt.ArrowCursor)


_CURSORS = None
ANNOTATIONS = ("text", "arrow", "line", "rect", "ellipse")
NOTE_EDIT = ("delete", "note_move", "note_stretch", "note_dup")


class AddTracesDialog(QDialog):
    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Traces to Plot")
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Only list traces matching"))
        self.filter = QLineEdit()
        self.filter.textChanged.connect(self._filter)
        row.addWidget(self.filter)
        lay.addLayout(row)
        lay.addWidget(QLabel("Available data:"))
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.addItems(names)
        self.list.itemSelectionChanged.connect(self._sync)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        lay.addWidget(self.list, 1)
        lay.addWidget(QLabel("Expression(s) to add:"))
        self.expr = QLineEdit()
        lay.addWidget(self.expr)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(420, 480)

    def _filter(self, text):
        t = text.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(t not in it.text().lower())

    def _sync(self):
        self.expr.setText(" ".join(it.text() for it in self.list.selectedItems()))

    def expressions(self):
        """Split on spaces that are not inside parentheses."""
        out, depth, cur = [], 0, ""
        for ch in self.expr.text():
            depth += (ch == "(") - (ch == ")")
            if ch == " " and depth == 0:
                if cur:
                    out.append(cur)
                cur = ""
            else:
                cur += ch
        if cur:
            out.append(cur)
        return out
