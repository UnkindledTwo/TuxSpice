"""Reader/writer for LTspice schematic (.asc) files.

Writing an unmodified schematic reproduces the original lines (modulo
whitespace), so files stay usable in LTspice itself.
"""
from dataclasses import dataclass, field
from pathlib import Path

from .asy import Window
from .textio import read_text, write_text


@dataclass
class Wire:
    x1: int
    y1: int
    x2: int
    y2: int

    def lines(self):
        return [f"WIRE {self.x1} {self.y1} {self.x2} {self.y2}"]


@dataclass
class Flag:
    """Net label. Name "0" is ground. iopin is None, "In", "Out" or "BiDir"."""
    x: int
    y: int
    name: str
    iopin: str | None = None

    def lines(self):
        out = [f"FLAG {self.x} {self.y} {self.name}"]
        if self.iopin:
            out.append(f"IOPIN {self.x} {self.y} {self.iopin}")
        return out


@dataclass
class SymbolInst:
    symbol: str                                    # e.g. "res", "Opamps\\opamp2"
    x: int
    y: int
    orient: str = "R0"
    windows: dict = field(default_factory=dict)    # index -> Window override
    attrs: dict = field(default_factory=dict)      # SYMATTR, in file order

    @property
    def name(self):
        return self.attrs.get("InstName", "")

    def lines(self):
        out = [f"SYMBOL {self.symbol} {self.x} {self.y} {self.orient}"]
        for idx, w in self.windows.items():
            out.append(f"WINDOW {idx} {w.x} {w.y} {w.just} {w.size}")
        for k, v in self.attrs.items():
            out.append(f"SYMATTR {k} {v}")
        return out


@dataclass
class Text:
    """Free text. Starts with '!' for a SPICE directive, ';' for a comment."""
    x: int
    y: int
    just: str
    size: int
    text: str

    @property
    def is_directive(self):
        return self.text.startswith("!")

    @property
    def body(self):
        """Displayed text with the !/; marker removed and \\n expanded."""
        t = self.text[1:] if self.text[:1] in "!;" else self.text
        return t.replace("\\n", "\n")

    def lines(self):
        return [f"TEXT {self.x} {self.y} {self.just} {self.size} {self.text}"]


@dataclass
class Graphic:
    kind: str           # LINE, RECTANGLE, CIRCLE, ARC
    coords: list
    style: int = 0
    pen: str = "Normal"

    def lines(self):
        c = " ".join(str(v) for v in self.coords)
        s = f" {self.style}" if self.style else ""
        return [f"{self.kind} {self.pen} {c}{s}"]


@dataclass
class DataFlag:
    x: int
    y: int
    expr: str

    def lines(self):
        return [f"DATAFLAG {self.x} {self.y} {self.expr}"]


@dataclass
class Raw:
    """Any line we don't interpret, kept verbatim."""
    line: str

    def lines(self):
        return [self.line]


@dataclass
class Schematic:
    version: str = "4"
    sheet: tuple = (1, 880, 680)
    items: list = field(default_factory=list)
    path: Path | None = None
    encoding: str = "latin-1"
    newline: str = "\n"

    def of(self, cls):
        return [i for i in self.items if isinstance(i, cls)]

    @property
    def wires(self):
        return self.of(Wire)

    @property
    def flags(self):
        return self.of(Flag)

    @property
    def symbols(self):
        return self.of(SymbolInst)

    @property
    def texts(self):
        return self.of(Text)

    def to_text(self):
        out = [f"Version {self.version}", "SHEET {} {} {}".format(*self.sheet)]
        for item in self.items:
            out += item.lines()
        return "\n".join(out) + "\n"

    def save(self, path: Path | None = None):
        path = Path(path or self.path)
        write_text(path, self.to_text(), self.encoding, self.newline)
        self.path = path


def _i(s):
    return int(float(s))


def parse_asc(text: str) -> Schematic:
    sch = Schematic(items=[])
    cur_sym = None
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        kw, _, rest = line.strip().partition(" ")
        tok = rest.split()
        try:
            if kw == "Version":
                sch.version = rest.strip()
            elif kw == "SHEET":
                sch.sheet = tuple(_i(t) for t in tok[:3])
            elif kw == "WIRE":
                sch.items.append(Wire(*(_i(t) for t in tok[:4])))
                cur_sym = None
            elif kw == "FLAG":
                sch.items.append(Flag(_i(tok[0]), _i(tok[1]), rest.split(None, 2)[2]))
                cur_sym = None
            elif kw == "IOPIN":
                x, y = _i(tok[0]), _i(tok[1])
                for f in reversed(sch.items):
                    if isinstance(f, Flag) and (f.x, f.y) == (x, y):
                        f.iopin = tok[2]
                        break
                else:
                    sch.items.append(Raw(line))
            elif kw == "SYMBOL":
                cur_sym = SymbolInst(tok[0], _i(tok[1]), _i(tok[2]), tok[3] if len(tok) > 3 else "R0")
                sch.items.append(cur_sym)
            elif kw == "WINDOW" and cur_sym is not None:
                cur_sym.windows[_i(tok[0])] = Window(_i(tok[1]), _i(tok[2]),
                                                     tok[3] if len(tok) > 3 else "Left",
                                                     _i(tok[4]) if len(tok) > 4 else 2)
            elif kw == "SYMATTR" and cur_sym is not None:
                key, _, value = rest.partition(" ")
                cur_sym.attrs[key] = value
            elif kw == "TEXT":
                parts = rest.split(None, 4)
                sch.items.append(Text(_i(parts[0]), _i(parts[1]), parts[2], _i(parts[3]),
                                      parts[4] if len(parts) > 4 else ""))
                cur_sym = None
            elif kw in ("LINE", "RECTANGLE", "CIRCLE", "ARC"):
                n = 8 if kw == "ARC" else 4
                coords = [_i(t) for t in tok[1:1 + n]]
                style = _i(tok[1 + n]) if len(tok) > 1 + n else 0
                sch.items.append(Graphic(kw, coords, style, tok[0]))
                cur_sym = None
            elif kw == "DATAFLAG":
                sch.items.append(DataFlag(_i(tok[0]), _i(tok[1]), rest.split(None, 2)[2]))
                cur_sym = None
            else:
                sch.items.append(Raw(line))
                cur_sym = None
        except (ValueError, IndexError):
            sch.items.append(Raw(line))
    return sch


def load_asc(path) -> Schematic:
    path = Path(path)
    text, enc, nl = read_text(path)
    sch = parse_asc(text)
    sch.path, sch.encoding, sch.newline = path, enc, nl
    return sch
