"""Default colors, matching LTspice's out-of-the-box palette.

Values read from Tools > Color Preferences of LTspice 26.1 under Wine (fresh settings).
Adjustable through Tools > Color Preferences and saved in QSettings.
"""
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor

DEFAULTS = {
    "background": "#c0c0c0",
    "grid": "#000000",
    "wire": "#0000ff",
    "junction": "#0000ff",
    "component": "#00007f",
    "component_fill": "#ffffc0",
    "attribute": "#000000",
    "flag_graphic": "#0000ff",
    "flag": "#000000",
    "directive": "#000000",
    "comment": "#0000c8",
    "graphic": "#0000c8",
    "selected": "#ffff00",
    "unconnected": "#0000ff",
    "sprite": "#ffff00",
    # waveform viewer
    "plot_background": "#000000",
    "plot_axis": "#afafaf",
    "plot_inactive_axis": "#969696",
    "plot_grid": "#646464",
    "plot_text": "#afafaf",
}

# trace colors used for successive traces in the waveform viewer (LTspice "Trace V(1)".."V(12)")
TRACE_COLORS = ["#00ff00", "#0000ff", "#ff0000", "#00afaf", "#ff00ff", "#808080",
                "#008000", "#0000af", "#af8000", "#800080", "#800000", "#afaf00"]


class Theme:
    def __init__(self):
        self.s = QSettings("pyltspice", "pyltspice")

    def color(self, key) -> QColor:
        return QColor(self.s.value(f"colors/{key}", DEFAULTS[key]))

    def set_color(self, key, value: QColor):
        self.s.setValue(f"colors/{key}", value.name())

    def reset(self):
        self.s.remove("colors")


_theme = None


def theme() -> Theme:
    global _theme
    if _theme is None:
        _theme = Theme()
    return _theme
