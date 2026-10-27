"""Entry point: pyltspice [file.asc|file.raw|file.net ...]"""
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from . import config


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("pyltspice")
    app.setOrganizationName("pyltspice")
    from .ui import appearance
    from .ui.settings_dialog import get
    appearance.apply(app, get("operation/app_theme"))    # follows the desktop's light/dark scheme
    from .ui.main_window import MainWindow
    win = MainWindow()
    try:
        app.styleHints().colorSchemeChanged.connect(win._color_scheme_changed)
    except AttributeError:      # Qt < 6.5
        pass
    win.show()
    win.ensure_library()        # first run: extract the library from the user's LTspice64.msi
    if not config.ngspice_path():
        QMessageBox.warning(win, "pyltspice", "ngspice was not found. Install it with:\n"
                            "sudo apt install ngspice")
    files = [a for a in argv[1:] if not a.startswith("-")]
    for f in files:
        win.open_file(f)
    if not files:
        win.new_schematic()
    from PySide6.QtCore import QTimer
    from .ui.autosave import offer_recovery
    QTimer.singleShot(300, lambda: offer_recovery(win))     # work left unsaved by a crash
    # MCP: AI assistants attach through pyltspice-mcp (Tools > Configure Third-Party AI Assistants)
    import os
    if not os.environ.get("PYLTSPICE_NO_MCP"):
        win.start_mcp_host()
        from PySide6.QtCore import QTimer
        from .ui.ai_dialog import offer_at_startup
        QTimer.singleShot(500, lambda: offer_at_startup(win))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
