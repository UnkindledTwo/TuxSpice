#!/usr/bin/env python3
"""Render a schematic to PNG without opening a window (for visual checks)."""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyltspice.model.asc import load_asc  # noqa: E402
from pyltspice.ui.schematic_view import SchematicScene  # noqa: E402
from pyltspice.ui.theme import theme  # noqa: E402


def render(asc_path, png_path, width=1600):
    sc = SchematicScene(load_asc(asc_path))
    rect = QRectF()
    for it in sc.items():
        rect = rect.united(it.sceneBoundingRect())
    rect = rect.adjusted(-32, -32, 32, 32)
    h = int(width * rect.height() / max(rect.width(), 1))
    img = QImage(width, h, QImage.Format_ARGB32)
    img.fill(theme().color("background"))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    sc.render(p, QRectF(0, 0, width, h), rect, Qt.KeepAspectRatio)
    p.end()
    img.save(str(png_path))


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    render(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1600)
