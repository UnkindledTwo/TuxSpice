"""Application look on Linux desktops: light, dark and GTK-derived palettes.

The schematic and plot canvases keep LTspice's own colours (Tools > Color Preferences); this is
about the window chrome around them. TuxSpice follows the desktop's palette and, where the
desktop prefers a dark scheme that Qt didn't apply (GNOME without a Qt platform theme), switches
to a dark palette itself. Settings > Operation > Application theme overrides it (a TuxSpice
extra; LTspice has no such setting). Icons are drawn for a light toolbar, so `adapt_icon`
lightens any part of them that lacks contrast against a dark one.
"""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPalette, QPixmap

THEMES = ["System", "Light", "Dark"]

_DARK = {
    QPalette.Window: "#2b2b2b", QPalette.WindowText: "#e6e6e6", QPalette.Base: "#1f1f1f",
    QPalette.AlternateBase: "#2f2f2f", QPalette.Text: "#e6e6e6", QPalette.Button: "#353535",
    QPalette.ButtonText: "#e6e6e6", QPalette.BrightText: "#ffffff", QPalette.Highlight: "#3d7fd9",
    QPalette.HighlightedText: "#ffffff", QPalette.ToolTipBase: "#3a3a3a", QPalette.ToolTipText: "#f0f0f0",
    QPalette.Link: "#7fb2ff", QPalette.LinkVisited: "#c49cff", QPalette.PlaceholderText: "#8c8c8c",
    QPalette.Light: "#4a4a4a", QPalette.Midlight: "#3e3e3e", QPalette.Mid: "#262626",
    QPalette.Dark: "#1a1a1a", QPalette.Shadow: "#0d0d0d",
}
_DISABLED = {QPalette.WindowText: "#7c7c7c", QPalette.Text: "#7c7c7c", QPalette.ButtonText: "#7c7c7c",
             QPalette.HighlightedText: "#a0a0a0"}

_system = None          # the palette and style Qt started with


def dark_palette() -> QPalette:
    p = QPalette()
    for role, c in _DARK.items():
        p.setColor(role, QColor(c))
    for role, c in _DISABLED.items():
        p.setColor(QPalette.Disabled, role, QColor(c))
    return p


def luminance(c: QColor) -> float:
    """WCAG relative luminance."""
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a: QColor, b: QColor) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def is_dark(palette: QPalette | None = None) -> bool:
    palette = palette or QGuiApplication.palette()
    return luminance(palette.color(QPalette.Window)) < 0.2


def system_prefers_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:          # Qt < 6.5
        return False


def apply(app, choice="System"):
    """Set the application palette for Settings > Operation > Application theme."""
    global _system
    if _system is None:
        _system = (app.style().name(), QPalette(app.palette()))
    style, palette = _system
    if choice == "Dark" or (choice == "System" and system_prefers_dark() and not is_dark(palette)):
        if app.style().name().lower() != "fusion":
            app.setStyle("Fusion")          # native styles may ignore a dark palette
        app.setPalette(dark_palette())
    elif choice == "Light" and is_dark(palette):
        app.setStyle("Fusion")
        app.setPalette(app.style().standardPalette())
    else:
        if app.style().name() != style:
            app.setStyle(style)
        app.setPalette(palette)


def error_color() -> str:
    """Red for error text that reads on the current background."""
    return "#ff7b72" if is_dark() else "#c00000"


def toolbar_css(palette: QPalette | None = None) -> str:
    """Flat toolbar buttons with a hover/pressed tint taken from the palette's highlight."""
    palette = palette or QGuiApplication.palette()
    hi = palette.color(QPalette.Highlight)
    dark = is_dark(palette)
    hover = QColor(hi)
    hover.setAlpha(70 if dark else 40)
    pressed = QColor(hi)
    pressed.setAlpha(120 if dark else 80)
    border = palette.color(QPalette.Mid if dark else QPalette.Dark).name()

    def rgba(c):
        return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"
    return ("QToolBar { spacing: 1px; padding: 2px 2px; }"
            "QToolButton { padding: 0px; margin: 0px; border: 1px solid transparent; }"
            f"QToolButton:hover {{ border: 1px solid {border}; background: {rgba(hover)}; }}"
            f"QToolButton:pressed, QToolButton:checked {{ background: {rgba(pressed)}; }}")


def adapt_icon(pm: QPixmap, background: QColor, target=4.8) -> QPixmap:
    """Blend each too-dark pixel of an icon toward white until it has `target` contrast with the
    background (hue is kept, so blue stays blue, just lighter). Only for dark backgrounds."""
    if luminance(background) >= 0.2:
        return pm
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4].reshape(h, w, 4).copy()
    rgb = a[..., 2::-1].astype(float) / 255             # BGRA -> RGB
    y_bg = luminance(background)
    out = rgb.copy()
    todo = a[..., 3] > 0
    for t in np.linspace(0, 0.95, 20):
        c = rgb + (1 - rgb) * t
        cl = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
        y = cl @ np.array([0.2126, 0.7152, 0.0722])
        ok = todo & ((y + 0.05) / (y_bg + 0.05) >= target)
        out[ok] = c[ok]
        todo &= ~ok
        if not todo.any():
            break
    out[todo] = 1.0 - (1.0 - rgb[todo]) * 0.05          # couldn't reach it: nearly white
    a[..., 2::-1] = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
    res = QImage(a.data, w, h, w * 4, QImage.Format_ARGB32).copy()
    res.setDevicePixelRatio(pm.devicePixelRatio())
    return QPixmap.fromImage(res)
