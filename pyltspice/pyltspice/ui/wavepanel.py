"""Side panel of a waveform window (TuxSpice extras; LTspice has neither).

Measurements: rise/fall time, overshoot, frequency, duty cycle, RMS... of one trace over the
x range on screen, updated while zooming (sim.wavemeasure). For AC data: peak gain, -3 dB
points, unity-gain frequency, phase and gain margin.

Steps: a legend of the .step runs with check boxes (the same selection as Plot Settings >
Select Steps), optional colour per run, and a histogram of any .meas result over the runs
(Monte Carlo and worst-case sweeps)."""
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)
from shiboken6 import isValid

from ..sim.spicenum import fmt
from ..sim.vectors import unit_of
from ..sim.wavemeasure import ac_measures, time_measures


def _swatch(color):
    pm = QPixmap(14, 14)
    pm.fill(QColor(color))
    return QIcon(pm)


def format_value(value, kind, yunit="", xunit="s"):
    if value is None or not np.isfinite(value):
        return "—"
    if kind == "y":
        return fmt(value, yunit, 5)
    if kind == "x":
        return fmt(value, xunit, 5)
    if kind == "Hz":
        return fmt(value, "Hz", 5)
    if kind == "%":
        return f"{value:.3g} %"
    if kind == "dB":
        return f"{value:.4g} dB"
    if kind == "°":
        return f"{value:.4g}°"
    return f"{value:.5g}"


def trace_window(viewer, trace, step):
    """(x, y) of one .step run of a trace, cut to the x range shown in its pane."""
    run = next((r for r in trace.runs if r[0] == step), None)
    if run is None:
        return None, None
    _, xs, ys = run
    xs = np.real(np.asarray(xs))
    pane = trace.pane or viewer.panes[0]
    x0, x1 = pane.plot.getPlotItem().getViewBox().viewRange()[0]
    if viewer.is_ac:
        x0, x1 = 10 ** x0, 10 ** x1
        keep = (xs >= x0) & (xs <= x1)
        return xs[keep], np.asarray(ys)[keep]
    ys = np.real(np.asarray(ys))
    if len(xs) < 2 or not np.all(np.diff(xs) >= 0):
        return xs, ys                    # e.g. a DC sweep that runs backwards: use all of it
    x0, x1 = max(x0, xs[0]), min(x1, xs[-1])
    if x1 <= x0:
        return None, None
    inside = (xs > x0) & (xs < x1)
    return (np.r_[x0, xs[inside], x1],
            np.r_[np.interp(x0, xs, ys), ys[inside], np.interp(x1, xs, ys)])


def measure_trace(viewer, trace, step):
    """[(label, text)] for the panel."""
    x, y = trace_window(viewer, trace, step)
    if x is None or len(x) < 2:
        return []
    if viewer.is_ac:
        rows = ac_measures(x, y)
    else:
        rows = time_measures(x, y)
        if viewer.analysis != "tran":         # DC sweeps, noise: levels only
            rows = rows[:5]
    xunit = {"tran": "s", "dc": "V"}.get(viewer.analysis, "")
    yunit = unit_of(trace.expr)
    return [(label, format_value(v, kind, yunit, xunit)) for label, v, kind in rows]


class MeasTab(QWidget):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.trace_box = QComboBox()
        self.step_box = QComboBox()
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Measurement", "Value"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 6)
        self.note = QLabel("Over the x range on screen: zoom in to measure one part.")
        self.note.setWordWrap(True)
        lay.addWidget(self.trace_box)
        lay.addWidget(self.step_box)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.note)
        self.trace_box.currentIndexChanged.connect(lambda *_: self.recompute())
        self.step_box.currentIndexChanged.connect(lambda *_: self.recompute())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.recompute)
        viewer.traces_changed.connect(self.refresh)
        viewer.range_changed.connect(self._timer.start)
        self.refresh()

    def traces(self):
        return [t for p in self.viewer.panes for t in p.traces]

    def refresh(self):
        """Trace and step lists changed: rebuild the choosers, keeping the selection."""
        if not isValid(self):
            return
        cur = self.trace_box.currentText()
        self.trace_box.blockSignals(True)
        self.trace_box.clear()
        for t in self.traces():
            self.trace_box.addItem(_swatch(t.color), t.expr)
        i = self.trace_box.findText(cur)
        self.trace_box.setCurrentIndex(i if i >= 0 else 0)
        self.trace_box.blockSignals(False)
        labels = self.viewer.step_labels()
        self.step_box.blockSignals(True)
        k = self.step_box.currentIndex()
        self.step_box.clear()
        self.step_box.addItems(labels)
        self.step_box.setCurrentIndex(k if 0 <= k < len(labels) else 0)
        self.step_box.setVisible(len(labels) > 1)
        self.step_box.blockSignals(False)
        self.recompute()

    def recompute(self):
        if not isValid(self) or not self.isVisible() and self.table.rowCount():
            return
        traces = self.traces()
        i = self.trace_box.currentIndex()
        rows = []
        if 0 <= i < len(traces):
            try:
                rows = measure_trace(self.viewer, traces[i], max(self.step_box.currentIndex(), 0))
            except Exception as e:  # noqa: BLE001 - odd data must not break the plot window
                rows = [("Error", str(e))]
        self.table.setRowCount(len(rows))
        for r, (label, text) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(label))
            val = QTableWidgetItem(text)
            val.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, val)
        if not traces:
            self.note.setText("Add a trace to measure it.")
        else:
            self.note.setText("Over the x range on screen: zoom in to measure one part.")

    def showEvent(self, ev):
        super().showEvent(ev)
        self.recompute()


class StepsTab(QWidget):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._checked)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, on in (("All", True), ("None", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, on=on: self._all(on))
            row.addWidget(b)
        lay.addLayout(row)
        self.color = QCheckBox("Colour each step")
        self.color.setChecked(viewer.color_steps)
        self.color.toggled.connect(self._color)
        lay.addWidget(self.color)
        self.hist = QPushButton("Histogram of .meas...")
        self.hist.clicked.connect(lambda: HistogramDialog(self.viewer, self).show())
        lay.addWidget(self.hist)
        viewer.steps_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        if not isValid(self):
            return
        v = self.viewer
        self.list.blockSignals(True)
        self.list.clear()
        for k, lab in enumerate(v.step_labels()):
            it = QListWidgetItem(lab)
            if v.color_steps:
                it.setIcon(_swatch(v.step_color(k)))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if v.visible_steps is None or k in v.visible_steps else Qt.Unchecked)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.color.blockSignals(True)
        self.color.setChecked(v.color_steps)
        self.color.blockSignals(False)
        self.hist.setEnabled(bool(histogram_data(v)))

    def _checked(self, _item):
        on = {i for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.Checked}
        self.viewer.set_visible_steps(None if len(on) == self.list.count() else on)

    def _all(self, on):
        self.viewer.set_visible_steps(None if on else set())

    def _color(self, on):
        from .settings_dialog import put
        put("tux/color_steps", on)
        self.viewer.set_color_steps(on)


class SidePanel(QTabWidget):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.meas = MeasTab(viewer)
        self.steps = StepsTab(viewer)
        self.has_meas = self.has_legend = False
        self.setMinimumWidth(200)

    def show_tabs(self, meas, legend):
        self.clear()
        if meas:
            self.addTab(self.meas, "Measurements")
        if legend:
            self.addTab(self.steps, "Steps")
        self.has_meas, self.has_legend = meas, legend
        self.setVisible(meas or legend)
        if meas:
            self.meas.refresh()
        if legend:
            self.steps.refresh()


def histogram_data(viewer):
    """{.meas name: (step labels, values)} for measurements with numbers in 2+ runs."""
    out = {}
    for name, rows in (viewer.meas_table or {}).items():
        vals = [(lab, v) for lab, v in rows if v is not None and np.isfinite(v)]
        if len(vals) >= 2:
            out[name] = ([lab for lab, _ in vals], np.array([v for _, v in vals], float))
    return out


def bins_for(values):
    """Histogram bin edges: sqrt rule, at least 5, at most 50 bins."""
    n = int(np.clip(np.ceil(np.sqrt(len(values))), 5, 50))
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi <= lo:
        span = abs(lo) * 1e-3 or 1.0
        lo, hi = lo - span, hi + span
    return np.linspace(lo, hi, n + 1)


class HistogramDialog(QDialog):
    """Histogram of one .meas result over the .step runs, with its statistics."""

    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        import pyqtgraph as pg
        from .theme import theme
        self.setWindowTitle(f"Histogram - {viewer.title}")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.data = histogram_data(viewer)
        lay = QVBoxLayout(self)
        self.box = QComboBox()
        self.box.addItems(list(self.data))
        lay.addWidget(self.box)
        self.plot = pg.PlotWidget(background=theme().color("plot_background"))
        self.plot.getPlotItem().setMenuEnabled(False)
        self.plot.getPlotItem().hideButtons()
        lay.addWidget(self.plot, 1)
        self.stats = QFormLayout()
        self.stat_labels = {}
        for key in ("Runs", "Mean", "Std. deviation", "Minimum", "Maximum", "Min run", "Max run"):
            lab = QLabel()
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.stat_labels[key] = lab
            self.stats.addRow(key + ":", lab)
        lay.addLayout(self.stats)
        self.box.currentTextChanged.connect(self.show_meas)
        self.resize(560, 480)
        if self.data:
            self.show_meas(self.box.currentText())

    def show_meas(self, name):
        import pyqtgraph as pg
        if name not in self.data:
            return
        labels, vals = self.data[name]
        edges = bins_for(vals)
        counts, _ = np.histogram(vals, edges)
        self.plot.clear()
        width = edges[1] - edges[0]
        self.plot.addItem(pg.BarGraphItem(x=(edges[:-1] + edges[1:]) / 2, height=counts, width=width * 0.9,
                                          brush=QColor("#00c000"), pen=QColor("#00ff00")))
        self.plot.setLabel("bottom", name)
        self.plot.setLabel("left", "runs")
        i0, i1 = int(np.argmin(vals)), int(np.argmax(vals))
        for key, text in (("Runs", str(len(vals))), ("Mean", f"{np.mean(vals):.6g}"),
                          ("Std. deviation", f"{np.std(vals, ddof=1):.6g}"),
                          ("Minimum", f"{vals[i0]:.6g}"), ("Maximum", f"{vals[i1]:.6g}"),
                          ("Min run", labels[i0] or f"run {i0 + 1}"), ("Max run", labels[i1] or f"run {i1 + 1}")):
            self.stat_labels[key].setText(text)
