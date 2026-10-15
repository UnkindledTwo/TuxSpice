"""Waveform viewer: stacked plot panes with LTspice-style trace labels."""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMenu, QSplitter, QVBoxLayout, QWidget)

from ..sim.spicenum import fmt
from ..sim.vectors import VectorSet, unit_of
from .theme import TRACE_COLORS, theme

pg.setConfigOptions(antialias=True)


class EngAxis(pg.AxisItem):
    """Axis with LTspice-style engineering labels (1ms, 10KHz, -20dB)."""

    def __init__(self, orientation, unit="", log=False, **kw):
        super().__init__(orientation, **kw)
        self.unit = unit
        self.is_log = log
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            if self.is_log:
                # label decades only, like LTspice
                if abs(v - round(v)) > 1e-6:
                    out.append("")
                    continue
                v = 10 ** round(v)
            out.append(fmt(v, self.unit, 3))
        return out


class Trace:
    def __init__(self, expr, color):
        self.expr = expr
        self.color = QColor(color)
        self.items = []
        self.cx = self.cy = None     # data the cursors follow (first .step run)
        self.vb = None
        self.pane = None


class Cursor:
    """A draggable crosshair locked onto one trace (LTspice: click a trace label)."""

    def __init__(self, viewer, trace, index):
        self.viewer, self.trace, self.index = viewer, trace, index
        log = viewer.is_ac
        pen = QPen(QColor("#808080"))
        pen.setCosmetic(True)
        pen.setStyle(Qt.DashLine)
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
        lay.addWidget(self.labels)
        is_ac = viewer.is_ac
        xunit = "Hz" if is_ac else ("s" if viewer.analysis == "tran" else "V")
        self.bottom = EngAxis("bottom", xunit, log=is_ac)
        self.left = EngAxis("left", "dB" if is_ac else "")
        self.plot = pg.PlotWidget(axisItems={"bottom": self.bottom, "left": self.left},
                                  background=theme().color("plot_background"))
        self.plot.showGrid(x=True, y=True, alpha=0.35)
        pi = self.plot.getPlotItem()
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.getViewBox().setMouseMode(pg.ViewBox.RectMode)
        for ax in ("left", "bottom"):
            a = pi.getAxis(ax)
            a.setPen(theme().color("plot_axis"))
            a.setTextPen(theme().color("plot_text"))
        self.phase_vb = None          # right-hand axis: phase (AC) or a second unit
        self.right = None
        self.left_unit = None
        if is_ac:
            pi.setLogMode(x=True, y=False)
            if viewer.show_phase:
                self._ensure_right("°")
        self.plot.scene().sigMouseMoved.connect(self._mouse_moved)
        self.plot.setContextMenuPolicy(Qt.CustomContextMenu)
        self.plot.customContextMenuRequested.connect(lambda p: viewer.context_menu(self, self.plot.mapToGlobal(p)))
        self.plot.scene().sigMouseClicked.connect(lambda ev: self.activated.emit(self))
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
        pi.getViewBox().sigResized.connect(self._sync_phase)
        self._sync_phase()

    def _sync_phase(self):
        vb = self.plot.getPlotItem().getViewBox()
        self.phase_vb.setGeometry(vb.sceneBoundingRect())
        self.phase_vb.linkedViewChanged(vb, self.phase_vb.XAxis)

    def _mouse_moved(self, pos):
        vb = self.plot.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(pos):
            return
        pt = vb.mapSceneToView(pos)
        x = 10 ** pt.x() if self.viewer.is_ac else pt.x()
        xu = self.bottom.unit
        self.viewer.status.emit(f"x = {fmt(x, xu, 5)}    y = {fmt(pt.y(), self.left.unit, 5)}")

    def _label_clicked(self, link):
        i = int(link)
        if 0 <= i < len(self.traces):
            self.viewer.trace_menu(self, self.traces[i])

    def refresh_labels(self):
        parts = []
        for i, t in enumerate(self.traces):
            parts.append(f'<a href="{i}" style="color:{t.color.name()}; text-decoration:none">{t.expr}</a>')
        self.labels.setText("&nbsp;&nbsp;&nbsp;".join(parts) or "&nbsp;")

    def add_trace(self, trace: Trace, x, y, steps):
        pi = self.plot.getPlotItem()
        pen = QPen(trace.color)
        pen.setCosmetic(True)
        pen.setWidthF(1.2)
        a0, b0 = steps[0]
        trace.cx = x[a0:b0]
        trace.cy = (20 * np.log10(np.maximum(np.abs(y[a0:b0]), 1e-300)) if self.viewer.is_ac
                    else np.real(y[a0:b0]))
        trace.pane = self
        for a, b in steps:
            xs = x[a:b]
            if self.viewer.is_ac:
                z = y[a:b]
                mag = 20 * np.log10(np.maximum(np.abs(z), 1e-300))
                item = pi.plot(xs, mag, pen=pen)
                trace.items.append((pi, item))
                if not self.viewer.show_phase:
                    continue
                ph = np.degrees(np.unwrap(np.angle(z)))
                dpen = QPen(pen)
                dpen.setStyle(Qt.DashLine)
                pitem = pg.PlotCurveItem(np.log10(xs), ph, pen=dpen)
                self.phase_vb.addItem(pitem)
                trace.items.append((self.phase_vb, pitem))
            else:
                ys = np.real(y[a:b])
                unit = unit_of(trace.expr)
                if self.left_unit is None:
                    self.left_unit = unit
                    self.left.unit = unit
                if unit == self.left_unit:
                    item = pi.plot(xs, ys, pen=pen)
                    trace.items.append((pi, item))
                    trace.vb = pi.getViewBox()
                else:
                    # LTspice puts a second unit (e.g. currents) on a right-hand axis
                    self._ensure_right(unit)
                    item = pg.PlotCurveItem(xs, ys, pen=pen)
                    self.phase_vb.addItem(item)
                    trace.items.append((self.phase_vb, item))
                    trace.vb = self.phase_vb
        if self.viewer.is_ac:
            trace.vb = pi.getViewBox()
        self.traces.append(trace)
        self.refresh_labels()
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
        self.vectors = VectorSet(plot)
        self.title = title
        self.analysis = plot.analysis
        self.is_ac = plot.is_complex
        self.show_phase = plot.plotname != "FFT"
        self.panes = []
        self.active = None
        self.color_i = 0
        self.cursors = []
        self.readout = None
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
        if self.panes:
            p.plot.setXLink(self.panes[0].plot)
        self.panes.append(p)
        self.split.addWidget(p)
        self.active = p
        return p

    def _set_active(self, pane):
        self.active = pane

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
        grid = QAction("Grid", m, checkable=True, checked=True)
        grid.toggled.connect(lambda on: [p.plot.showGrid(x=on, y=on, alpha=0.35) for p in self.panes])
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

    def detach_cursor(self, index):
        for c in [c for c in self.cursors if c.index == index]:
            c.remove()
            self.cursors.remove(c)
        self.update_readout()

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
        for t in list(pane.traces):
            pane.remove_trace(t)
        self.traces_changed.emit()

    def delete_pane(self, pane):
        if len(self.panes) <= 1:
            return
        self.panes.remove(pane)
        pane.setParent(None)
        pane.deleteLater()
        self.active = self.panes[-1]

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
