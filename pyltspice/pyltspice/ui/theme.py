"""Default colors, matching LTspice's out-of-the-box schematic palette.

Values are adjustable through Tools > Color Preferences and saved in QSettings.
"""
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor

DEFAULTS = {
    "background": "#ffffff",
    "grid": "#808080",
    "wire": "#0000ff",
    "junction": "#0000ff",
    "component": "#000000",
    "component_fill": "#ffffff",
    "attribute": "#000000",
    "flag": "#000000",
    "directive": "#000000",
    "comment": "#0000ff",
    "graphic": "#0000ff",
    "selected": "#ff0000",
    "unconnected": "#ff0000",
    "sprite": "#ff0000",
    # waveform viewer
    "plot_background": "#ffffff",
    "plot_axis": "#000000",
    "plot_grid": "#c0c0c0",
    "plot_text": "#000000",
}

# trace colors used for successive traces in the waveform viewer
TRACE_COLORS = ["#00a000", "#0000ff", "#ff0000", "#00c0c0", "#c000c0", "#808000",
                "#808080", "#008080", "#800080", "#ff8000", "#4040ff", "#804000"]


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
