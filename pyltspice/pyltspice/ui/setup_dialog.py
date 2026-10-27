"""First-run setup: extract the LTspice library from the user's own installer.

Shown at startup when lib/sym is missing, and again when a command needs the library
(e.g. Component, P). Extraction runs on a worker thread; see pyltspice.setup_lib."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QVBoxLayout)

from .. import config, setup_lib
from ..model.library import default_library


class _Bridge(QObject):
    log = Signal(str)
    done = Signal(str)          # "" on success, else the error


class SetupDialog(QDialog):
    def __init__(self, parent=None, installers=None):
        super().__init__(parent)
        self.setWindowTitle("TuxSpice Setup")
        self.setMinimumWidth(560)
        self.running = False
        lay = QVBoxLayout(self)
        intro = QLabel("TuxSpice uses the symbols, models and examples of your own copy of LTspice. "
                       f"They aren't in <tt>{config.LIB_ROOT}</tt> yet.<br><br>"
                       "Pick your LTspice installer (<b>LTspice64.msi</b>) and TuxSpice will extract "
                       "them. Nothing is installed system-wide or sent anywhere.")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        lay.addWidget(intro)

        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.lineEdit().setPlaceholderText("Path to LTspice64.msi")
        found = setup_lib.find_installers() if installers is None else installers
        for p in found:
            self.combo.addItem(str(p))
        row.addWidget(self.combo, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        lay.addLayout(row)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setOpenExternalLinks(False)
        self.hint.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        lay.addWidget(self.hint)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)            # busy indicator: 7z gives no percentages
        self.progress.hide()
        lay.addWidget(self.progress)
        self.log = QLabel()
        lay.addWidget(self.log)

        self.buttons = QDialogButtonBox()
        self.extract_btn = self.buttons.addButton("Extract", QDialogButtonBox.AcceptRole)
        self.later_btn = self.buttons.addButton("Not Now", QDialogButtonBox.RejectRole)
        self.extract_btn.clicked.disconnect()
        self.extract_btn.clicked.connect(self.start)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self.bridge = _Bridge()
        self.bridge.log.connect(self.log.setText)
        self.bridge.done.connect(self._finished)
        self.combo.editTextChanged.connect(self._update)
        self._update()

    def msi(self):
        text = self.combo.currentText().strip()
        return Path(text).expanduser() if text else None

    def _browse(self):
        start = str(self.msi().parent if self.msi() else Path.home() / "Downloads")
        path, _ = QFileDialog.getOpenFileName(self, "LTspice installer", start, "Installer (*.msi);;All files (*)")
        if path:
            self.combo.setEditText(path)

    def _update(self, *_):
        msi = self.msi()
        if not setup_lib.have_7z():
            self.hint.setText("Extracting needs <b>7z</b>. Install it with "
                              "<tt>sudo apt install p7zip-full</tt>, then press Extract.")
        elif msi is None:
            self.hint.setText("No installer found in Downloads, Desktop or your home folder. "
                              f'Get it from <a href="{setup_lib.DOWNLOAD_URL}">Analog Devices</a>.')
        elif not msi.is_file():
            self.hint.setText("That file doesn't exist.")
        else:
            self.hint.setText("")
        self.extract_btn.setEnabled(not self.running and msi is not None and msi.is_file())

    def start(self):
        if not setup_lib.have_7z():
            self._update()
            return
        msi = self.msi()
        self.running = True
        self.progress.show()
        self.combo.setEnabled(False)
        self.later_btn.setEnabled(False)
        self._update()

        def work():
            try:
                setup_lib.extract(msi, config.LIB_ROOT, log=self.bridge.log.emit)
                self.bridge.done.emit("")
            except Exception as e:  # noqa: BLE001 - shown to the user, who can retry
                self.bridge.done.emit(str(e) or type(e).__name__)
        threading.Thread(target=work, daemon=True).start()

    def _finished(self, error):
        self.running = False
        self.progress.hide()
        self.combo.setEnabled(True)
        self.later_btn.setEnabled(True)
        self._update()
        if error:
            from .appearance import error_color
            self.log.setText(f"<span style='color:{error_color()}'>Extraction failed: {error}</span>")
            return
        default_library().rescan()
        self.accept()

    def reject(self):
        if not self.running:            # closing mid-extraction would leave a half-written library
            super().reject()


def library_missing():
    return not config.SYM_DIR.is_dir()


def ensure_library(parent):
    """Offer setup if the library is missing. True if it's there (now)."""
    if not library_missing():
        return True
    return SetupDialog(parent).exec() == QDialog.Accepted and not library_missing()
