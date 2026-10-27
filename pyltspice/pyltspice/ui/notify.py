"""Desktop notification when a long simulation finishes (a TuxSpice extra).

Sent through notify-send (libnotify, the freedesktop notification service GNOME, KDE and most
desktops run), only when the run took at least Settings > TuxSpice > "...if it took at least"
seconds and TuxSpice isn't the active window. The taskbar entry is flagged as well."""
import shutil

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication


def duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s} s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min"


def should_notify(elapsed: float) -> bool:
    from .settings_dialog import get
    return bool(get("tux/notify")) and elapsed >= get("tux/notify_after") \
        and QApplication.activeWindow() is None


def notify(window, title: str, body: str, ok=True) -> bool:
    """Show a desktop notification and flag the window in the taskbar. True if sent."""
    QApplication.alert(window)
    exe = shutil.which("notify-send")
    if not exe:
        return False
    args = ["--app-name=TuxSpice", "--icon=pyltspice", f"--urgency={'normal' if ok else 'critical'}",
            title, body]
    return QProcess.startDetached(exe, args)[0]
