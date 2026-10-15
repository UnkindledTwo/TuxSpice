#!/usr/bin/env python3
"""Drive the GUI headlessly: open, simulate, probe, screenshot (QT_QPA_PLATFORM=offscreen)."""
import os
import sys
import tempfile
from pathlib import Path

# don't write recent files / window geometry into the user's real settings
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="pyltspice-smoke-config-")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyltspice.ui.main_window import MainWindow  # noqa: E402


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main(asc, out_png, probes):
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.resize(1400, 950)
    win.show()
    win.open_file(asc)
    wait(200)
    sw = win.schematic()
    win.run_simulation()
    while win.sim_thread is not None:
        wait(100)
    wait(300)
    for expr in probes:
        sw.probed.emit(expr)
    wait(300)
    win.grab().save(out_png)
    pw = win.plot_window(sw)
    print("plot:", pw.viewer.trace_names() if pw else None)
    print("status:", win.status_label.text())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
