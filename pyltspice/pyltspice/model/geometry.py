"""LTspice coordinate transforms and text justification.

LTspice uses screen coordinates (y grows downward) on a 16-unit grid. A symbol
orientation is one of R0/R90/R180/R270 (rotation) or M0/M90/M180/M270 (rotate,
then mirror about the y axis). R90 maps (x, y) -> (-y, x), which is a clockwise
quarter turn on screen.
"""
from dataclasses import dataclass

GRID = 16

# orientation -> 2x2 matrix (a, b, c, d): x' = a*x + b*y, y' = c*x + d*y
_ROT = {0: (1, 0, 0, 1), 90: (0, -1, 1, 0), 180: (-1, 0, 0, -1), 270: (0, 1, -1, 0)}
ORIENTATIONS = ("R0", "R90", "R180", "R270", "M0", "M90", "M180", "M270")


def _mul(m, n):
    a, b, c, d = m
    e, f, g, h = n
    return (a * e + b * g, a * f + b * h, c * e + d * g, c * f + d * h)


def orient_matrix(orient: str):
    rot = _ROT[int(orient[1:])]
    if orient[0] == "M":
        # rotate first, then mirror: M90 maps (x, y) -> (y, x)
        return _mul((-1, 0, 0, 1), rot)
    return rot


def matrix_orient(m):
    for o in ORIENTATIONS:
        if orient_matrix(o) == m:
            return o
    raise ValueError(m)


def apply(m, x, y):
    a, b, c, d = m
    return a * x + b * y, c * x + d * y


def rotate_orient(orient: str, clockwise=True) -> str:
    """Orientation after one more R90 (clockwise) turn, as Ctrl+R does."""
    step = _ROT[90] if clockwise else _ROT[270]
    return matrix_orient(_mul(step, orient_matrix(orient)))


def mirror_orient(orient: str) -> str:
    """Orientation after mirroring left-right on screen, as Ctrl+E does."""
    return matrix_orient(_mul((-1, 0, 0, 1), orient_matrix(orient)))


# ---------------------------------------------------------------- text frames

# justification -> (vertical?, ax, ay); ax/ay locate the anchor within the text
# box in the text's own frame: ax 0=start .5=middle 1=end, ay 0=top 1=bottom.
_JUST = {
    "Left": (0.0, 0.5), "Right": (1.0, 0.5), "Center": (0.5, 0.5),
    "Top": (0.5, 0.0), "Bottom": (0.5, 1.0),
}


@dataclass(frozen=True)
class TextFrame:
    """Readable on-screen placement of a text block.

    vertical: text runs bottom-to-top (rotated 90 degrees counter-clockwise).
    ax, ay: anchor position inside the text box in the text's own frame.
    """
    vertical: bool
    ax: float
    ay: float

    @classmethod
    def from_just(cls, just: str) -> "TextFrame":
        vertical = just.startswith("V")
        ax, ay = _JUST.get(just[1:] if vertical else just, (0.0, 0.5))
        return cls(vertical, ax, ay)

    def to_just(self) -> str:
        best = min(_JUST, key=lambda k: abs(_JUST[k][0] - self.ax) + abs(_JUST[k][1] - self.ay))
        return ("V" if self.vertical else "") + best

    def transformed(self, m) -> "TextFrame":
        # direction and up vectors of the text in screen coordinates
        d, u = ((0, -1), (-1, 0)) if self.vertical else ((1, 0), (0, -1))
        d2 = apply(m, *d)
        u2 = apply(m, *u)
        # pick the readable direction along the same axis
        if d2 in ((1, 0), (0, -1)):
            e, ax = d2, self.ax
        else:
            e, ax = (-d2[0], -d2[1]), 1.0 - self.ax
        v = (0, -1) if e == (1, 0) else (-1, 0)
        ay = self.ay if u2 == v else 1.0 - self.ay
        return TextFrame(e == (0, -1), ax, ay)


# LTspice font size index -> relative scale (index 2 is the default)
FONT_SCALE = {0: 0.625, 1: 1.0, 2: 1.5, 3: 2.0, 4: 2.5, 5: 3.5, 6: 5.0, 7: 7.0}
