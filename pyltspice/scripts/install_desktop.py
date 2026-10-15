#!/usr/bin/env python3
"""Install a desktop launcher, icon and file associations for pyltspice (current user only).

    ../.venv/bin/python scripts/install_desktop.py            # install
    ../.venv/bin/python scripts/install_desktop.py --remove   # undo

Writes only under ~/.local/share (applications, icons, mime)."""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
APPS = HOME / ".local/share/applications"
ICONS = HOME / ".local/share/icons/hicolor/256x256/apps"
MIME = HOME / ".local/share/mime"
DESKTOP = APPS / "pyltspice.desktop"
ICON = ICONS / "pyltspice.png"
MIME_XML = MIME / "packages" / "pyltspice.xml"

MIME_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-ltspice-schematic">
    <comment>LTspice schematic</comment>
    <glob pattern="*.asc"/>
  </mime-type>
  <mime-type type="application/x-spice-raw">
    <comment>SPICE waveform data</comment>
    <glob pattern="*.raw"/>
  </mime-type>
</mime-info>
"""


def render_icon(path: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841 - needed for painting
    img = QImage(256, 256, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#f4f4f4"))
    p.setPen(QPen(QColor("#303030"), 6))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 36, 36)
    # a resistor in series with a wire, and a green waveform
    p.setPen(QPen(QColor("#0000ff"), 8))
    p.drawLine(40, 96, 84, 96)
    p.drawLine(172, 96, 216, 96)
    p.setPen(QPen(QColor("#000000"), 8))
    pts = [(84, 96), (95, 72), (117, 120), (139, 72), (161, 120), (172, 96)]
    for a, b in zip(pts, pts[1:]):
        p.drawLine(*a, *b)
    p.setPen(QPen(QColor("#00a000"), 8))
    import math
    prev = None
    for i in range(0, 177, 4):
        x, y = 40 + i, 180 - 36 * math.sin(i / 176 * 2 * math.pi)
        if prev:
            p.drawLine(int(prev[0]), int(prev[1]), int(x), int(y))
        prev = (x, y)
    p.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))


def install():
    exe = Path(sys.executable).with_name("pyltspice")
    if not exe.exists():
        sys.exit(f"{exe} not found: run '../.venv/bin/pip install -e .' first")
    render_icon(ICON)
    APPS.mkdir(parents=True, exist_ok=True)
    DESKTOP.write_text(
        "[Desktop Entry]\nType=Application\nName=pyltspice\n"
        "Comment=LTspice-compatible schematic capture and simulation\n"
        f"Exec={exe} %F\nIcon=pyltspice\nTerminal=false\nCategories=Development;Electronics;\n"
        "MimeType=application/x-ltspice-schematic;application/x-spice-raw;\n")
    MIME_XML.parent.mkdir(parents=True, exist_ok=True)
    MIME_XML.write_text(MIME_TYPES)
    for cmd in (["update-mime-database", str(MIME)], ["update-desktop-database", str(APPS)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False)
    print(f"installed {DESKTOP}, {ICON}, {MIME_XML}")


def remove():
    for f in (DESKTOP, ICON, MIME_XML):
        if f.exists():
            f.unlink()
            print(f"removed {f}")
    for cmd in (["update-mime-database", str(MIME)], ["update-desktop-database", str(APPS)]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, check=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    remove() if ap.parse_args().remove else install()
