"""Parser for LTspice symbol (.asy) files."""
from dataclasses import dataclass, field
from pathlib import Path

from .textio import read_text

# WINDOW index -> attribute it displays
WINDOW_ATTR = {0: "InstName", 1: "Type", 2: "Description", 3: "Value", 38: "SpiceModel",
               39: "SpiceLine", 40: "SpiceLine2", 123: "Value2"}
ATTR_WINDOW = {v: k for k, v in WINDOW_ATTR.items()}


@dataclass
class Shape:
    kind: str            # LINE, RECTANGLE, CIRCLE, ARC
    coords: list         # 4 ints (8 for ARC: bbox, start point, end point)
    style: int = 0       # dash style: 0 solid, 1 dash, 2 dot, 3 dash-dot, 4 dash-dot-dot


@dataclass
class Text:
    x: int
    y: int
    just: str
    size: int
    text: str


@dataclass
class Window:
    x: int
    y: int
    just: str
    size: int


@dataclass
class Pin:
    x: int
    y: int
    just: str            # label placement: NONE, LEFT, RIGHT, TOP, BOTTOM, VLEFT...
    offset: int
    attrs: dict = field(default_factory=dict)

    @property
    def name(self):
        return self.attrs.get("PinName", "")

    @property
    def order(self):
        try:
            return int(self.attrs.get("SpiceOrder", 0))
        except ValueError:
            return 0


@dataclass
class Symbol:
    name: str = ""
    path: Path | None = None
    symbol_type: str = "CELL"
    shapes: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    windows: dict = field(default_factory=dict)   # index -> Window
    attrs: dict = field(default_factory=dict)     # SYMATTR, in file order
    pins: list = field(default_factory=list)

    @property
    def prefix(self):
        return self.attrs.get("Prefix", "X")

    def bbox(self):
        xs, ys = [], []
        for s in self.shapes:
            pts = s.coords[:4]
            xs += pts[0::2]
            ys += pts[1::2]
        for p in self.pins:
            xs.append(p.x)
            ys.append(p.y)
        if not xs:
            return (0, 0, 0, 0)
        return (min(xs), min(ys), max(xs), max(ys))


def _ints(tokens):
    return [int(float(t)) for t in tokens]


def parse_asy(text: str, name: str = "", path: Path | None = None) -> Symbol:
    sym = Symbol(name=name, path=path)
    pin = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        kw, _, rest = line.partition(" ")
        tok = rest.split()
        try:
            if kw == "SymbolType":
                sym.symbol_type = rest.strip()
            elif kw in ("LINE", "RECTANGLE", "CIRCLE", "ARC"):
                n = 8 if kw == "ARC" else 4
                coords = _ints(tok[1:1 + n])
                style = int(tok[1 + n]) if len(tok) > 1 + n else 0
                sym.shapes.append(Shape(kw, coords, style))
            elif kw == "TEXT":
                parts = rest.split(None, 4)
                sym.texts.append(Text(int(parts[0]), int(parts[1]), parts[2], int(parts[3]),
                                      parts[4] if len(parts) > 4 else ""))
            elif kw == "WINDOW":
                idx, x, y = _ints(tok[:3])
                just = tok[3] if len(tok) > 3 else "Left"
                size = int(tok[4]) if len(tok) > 4 else 2
                sym.windows[idx] = Window(x, y, just, size)
            elif kw == "SYMATTR":
                key, _, value = rest.partition(" ")
                sym.attrs[key] = value
            elif kw == "PIN":
                x, y = _ints(tok[:2])
                pin = Pin(x, y, tok[2] if len(tok) > 2 else "NONE",
                          int(tok[3]) if len(tok) > 3 else 0)
                sym.pins.append(pin)
            elif kw == "PINATTR" and pin is not None:
                key, _, value = rest.partition(" ")
                pin.attrs[key] = value
        except (ValueError, IndexError):
            continue  # tolerate malformed lines, as LTspice does
    return sym


def load_asy(path: Path, name: str = "") -> Symbol:
    return parse_asy(read_text(path)[0], name or path.stem, path)
