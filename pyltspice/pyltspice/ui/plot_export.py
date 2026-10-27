"""File > Export Plot (a TuxSpice extra): a waveform window as a high-resolution PNG, an SVG,
or CSV data, optionally in a report style (white background, dark text, LTspice's bright
trace colours darkened to print well). LTspice's own exports are a screen-sized bitmap, an
.emf, and tab-separated text of the first .step run."""
import csv
from contextlib import contextmanager

import numpy as np
from PySide6.QtCore import QPoint, QRectF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QRadioButton, QWidget)

from .theme import theme


def print_color(c: QColor) -> QColor:
    """A trace colour that reads on white: luminance capped at 0.35, hue kept."""
    c = QColor(c)
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    if lum <= 0.35:
        return c
    k = 0.35 / lum
    return QColor.fromRgbF(c.redF() * k, c.greenF() * k, c.blueF() * k)


def _style_pane(pane, bg, fg, grid_alpha):
    pane.plot.setBackground(bg)
    pane.labels.setStyleSheet(f"background:{QColor(bg).name()}; padding:2px;")
    vb = pane.plot.getPlotItem().getViewBox()
    vb.setBorder(pg_pen(fg))
    for ax in (pane.left, pane.bottom, pane.right):
        if ax is not None:
            ax.setPen(fg)
            ax.setTextPen(fg)
    if pane.viewer.show_grid:
        pane.plot.showGrid(x=True, y=True, alpha=grid_alpha)


def pg_pen(color):
    import pyqtgraph as pg
    return pg.mkPen(color)


@contextmanager
def report_style(viewer, on=True, width_scale=1.0):
    """Temporarily restyle a WaveformViewer for export; everything is put back afterwards."""
    if not on and width_scale == 1.0:
        yield
        return
    from .waveform import GRID_ALPHA
    saved_pens, saved_colors, saved_notes = [], [], []
    try:
        for p in viewer.panes:
            if on:
                _style_pane(p, "#ffffff", QColor("#000000"), 0.2)
            for t in p.traces:
                saved_colors.append((t, QColor(t.color)))
                if on:
                    t.color = print_color(t.color)
                for _, it in t.items:
                    if hasattr(it, "opts") and isinstance(it.opts.get("pen"), QPen):
                        old = QPen(it.opts["pen"])
                        saved_pens.append((it, old))
                        pen = QPen(old)
                        if on:
                            pen.setColor(print_color(pen.color()))
                        pen.setWidthF(pen.widthF() * width_scale)
                        it.setPen(pen)
            p.refresh_labels()
        if on:
            for n in viewer.notes:
                if QColor(n.color).lightnessF() > 0.6:
                    saved_notes.append((n, QColor(n.color)))
                    n.color = QColor("#000000")
                    n.erase()
                    n.draw()
        QApplication.processEvents()
        yield
    finally:
        for it, pen in saved_pens:
            it.setPen(pen)
        for t, c in saved_colors:
            t.color = c
        for n, c in saved_notes:
            n.color = c
            n.erase()
            n.draw()
        for p in viewer.panes:
            if on:
                _style_pane(p, theme().color("plot_background"), theme().color("plot_axis"), GRID_ALPHA)
                for ax in (p.left, p.bottom, p.right):
                    if ax is not None:
                        ax.setTextPen(theme().color("plot_text"))
            p.refresh_labels()


def render_image(viewer, scale=2, report=False) -> QImage:
    """The plot panes (not the side panel) at `scale` times their size on screen: crisp text
    and lines, not an upscaled bitmap."""
    area = viewer.split
    img = QImage(int(area.width() * scale), int(area.height() * scale), QImage.Format_ARGB32)
    img.fill(Qt.white if report else theme().color("plot_background"))
    img.setDevicePixelRatio(scale)
    with report_style(viewer, report, width_scale=max(1.0, scale / 1.5)):
        area.render(img)
    return img


def write_svg(viewer, path, report=False):
    from PySide6.QtSvg import QSvgGenerator
    area = viewer.split
    gen = QSvgGenerator()
    gen.setFileName(str(path))
    gen.setSize(area.size())
    gen.setViewBox(QRectF(0, 0, area.width(), area.height()))
    gen.setTitle(viewer.title)
    p = QPainter(gen)
    with report_style(viewer, report):
        area.render(p, QPoint())
    p.end()


def write_csv(viewer, path, all_steps=True):
    """Comma-separated data of every trace on the plot. With several .step runs: one block of
    rows per run and a leading 'step' column (long format, as pandas and spreadsheets like).
    AC data gives magnitude in dB and phase in degrees, as File > Export does."""
    names = viewer.trace_names()
    steps = viewer.steps() if all_steps else viewer.steps()[:1]
    labels = viewer.step_labels()
    stepped = len(steps) > 1
    ys = [np.broadcast_to(np.asarray(viewer.vectors.eval(n)), viewer.x.shape) for n in names]
    header = (["step"] if stepped else []) + [viewer.plot.xname]
    for n in names:
        header += [f"{n} dB", f"{n} deg"] if viewer.is_ac else [n]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for k, (a, b) in enumerate(steps):
            cols = [np.real(viewer.x[a:b])]
            for y in ys:
                seg = y[a:b]
                if viewer.is_ac:
                    cols += [20 * np.log10(np.maximum(np.abs(seg), 1e-300)), np.degrees(np.angle(seg))]
                else:
                    cols.append(np.real(seg))
            for row in zip(*cols):
                w.writerow(([labels[k]] if stepped else []) + [f"{v:.9g}" for v in row])


class ExportDialog(QDialog):
    FORMATS = [("PNG image", "png"), ("SVG vector image", "svg"), ("CSV data", "csv")]

    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        self.setWindowTitle("Export Plot")
        s = QSettings("pyltspice", "pyltspice")
        form = QFormLayout(self)
        self.fmt = QComboBox()
        for text, ext in self.FORMATS:
            self.fmt.addItem(text, ext)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(s.value("export/format", "png"))))
        form.addRow("Format:", self.fmt)
        self.scale = QComboBox()
        for k in (1, 2, 3, 4):
            self.scale.addItem(f"{k}x  ({viewer.split.width() * k} × {viewer.split.height() * k} px)", k)
        self.scale.setCurrentIndex(max(0, self.scale.findData(int(s.value("export/scale", 2)))))
        form.addRow("Resolution:", self.scale)
        style = QWidget()
        h = QHBoxLayout(style)
        h.setContentsMargins(0, 0, 0, 0)
        self.screen = QRadioButton("Screen colours")
        self.report = QRadioButton("Report (white background)")
        grp = QButtonGroup(self)
        grp.addButton(self.screen)
        grp.addButton(self.report)
        (self.report if s.value("export/report", "true") in (True, "true") else self.screen).setChecked(True)
        h.addWidget(self.screen)
        h.addWidget(self.report)
        form.addRow("Style:", style)
        self.all_steps = QCheckBox("All .step runs")
        self.all_steps.setChecked(True)
        self.all_steps.setEnabled(len(viewer.steps()) > 1)
        form.addRow("Data:", self.all_steps)
        form.addRow(QLabel("Resize the window to change the image's proportions."))
        bb = QDialogButtonBox()
        self.save_btn = bb.addButton("Save...", QDialogButtonBox.AcceptRole)
        self.copy_btn = bb.addButton("Copy Image", QDialogButtonBox.ActionRole)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        self.copy_btn.clicked.connect(self._copy)
        form.addRow(bb)
        self.fmt.currentIndexChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        ext = self.fmt.currentData()
        self.scale.setEnabled(ext == "png")
        self.screen.setEnabled(ext != "csv")
        self.report.setEnabled(ext != "csv")
        self.all_steps.setVisible(ext == "csv")
        self.copy_btn.setEnabled(ext != "csv")

    def _remember(self):
        s = QSettings("pyltspice", "pyltspice")
        s.setValue("export/format", self.fmt.currentData())
        s.setValue("export/scale", self.scale.currentData())
        s.setValue("export/report", self.report.isChecked())

    def _copy(self):
        self._remember()
        img = render_image(self.viewer, self.scale.currentData(), self.report.isChecked())
        QApplication.clipboard().setImage(img)
        self.accept()

    def _save(self):
        from pathlib import Path
        ext = self.fmt.currentData()
        stem = Path(self.viewer.title.rstrip("*")).stem or "plot"
        path, _ = QFileDialog.getSaveFileName(self, "Export Plot", f"{stem}.{ext}",
                                              f"{self.fmt.currentText()} (*.{ext})")
        if not path:
            return
        if not path.lower().endswith("." + ext):
            path += "." + ext
        self._remember()
        self.export(path)
        self.accept()

    def export(self, path):
        ext = self.fmt.currentData()
        if ext == "png":
            render_image(self.viewer, self.scale.currentData(), self.report.isChecked()).save(path)
        elif ext == "svg":
            write_svg(self.viewer, path, self.report.isChecked())
        else:
            write_csv(self.viewer, path, self.all_steps.isChecked())
