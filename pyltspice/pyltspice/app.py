"""Entry point: pyltspice [file.asc|file.raw|file.net ...]"""
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from . import config


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("pyltspice")
    app.setOrganizationName("pyltspice")
    from .ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    if not config.SYM_DIR.is_dir():
        QMessageBox.warning(win, "pyltspice",
                            f"The LTspice symbol library was not found in\n{config.LIB_ROOT}\n\n"
                            "Extract it from your installer with:\n"
                            "python scripts/extract_msi.py LTspice64.msi")
    if not config.ngspice_path():
        QMessageBox.warning(win, "pyltspice", "ngspice was not found. Install it with:\n"
                            "sudo apt install ngspice")
    files = [a for a in argv[1:] if not a.startswith("-")]
    for f in files:
        win.open_file(f)
    if not files:
        win.new_schematic()
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
