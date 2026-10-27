"""Schematic connectivity and SPICE netlist generation (LTspice conventions)."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .asc import Schematic, Wire
from .geometry import apply, orient_matrix
from .library import SymbolLibrary, default_library, sch_dirs

MODEL_FILE_RE = re.compile(r"\.(lib|sub|mod|cir|txt|bjt|dio|mos|jft|inc|ckt|sp|spi|model)$", re.I)


class _UF:
    def __init__(self):
        self.parent = {}

    def find(self, a):
        p = self.parent.setdefault(a, a)
        while p != self.parent[p]:
            self.parent[p] = self.parent[self.parent[p]]
            p = self.parent[p]
        self.parent[a] = p
        return p

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _on_segment(px, py, w):
    """True if (px, py) lies strictly inside wire w (not on an endpoint)."""
    if (px, py) in ((w.x1, w.y1), (w.x2, w.y2)):
        return False
    if min(w.x1, w.x2) <= px <= max(w.x1, w.x2) and min(w.y1, w.y2) <= py <= max(w.y1, w.y2):
        return (w.x2 - w.x1) * (py - w.y1) == (w.y2 - w.y1) * (px - w.x1)
    return False


class WireIndex:
    """Find wires whose interior contains a point; axis-aligned wires are indexed."""

    def __init__(self, wires):
        self.h, self.v, self.other = {}, {}, []
        for w in wires:
            if w.y1 == w.y2:
                self.h.setdefault(w.y1, []).append(w)
            elif w.x1 == w.x2:
                self.v.setdefault(w.x1, []).append(w)
            else:
                self.other.append(w)

    def through(self, x, y):
        for w in self.h.get(y, ()):
            if min(w.x1, w.x2) < x < max(w.x1, w.x2):
                yield w
        for w in self.v.get(x, ()):
            if min(w.y1, w.y2) < y < max(w.y1, w.y2):
                yield w
        for w in self.other:
            if _on_segment(x, y, w):
                yield w


@dataclass
class PinRef:
    inst: object          # SymbolInst
    pin: object           # asy.Pin
    point: tuple


@dataclass
class Connectivity:
    """Electrical nets of one schematic sheet."""
    net_of_point: dict = field(default_factory=dict)   # (x, y) -> net name
    pins: list = field(default_factory=list)           # PinRef
    junctions: list = field(default_factory=list)      # points needing a dot
    unconnected: list = field(default_factory=list)    # pin points with nothing attached

    def net_at(self, x, y):
        return self.net_of_point.get((x, y))


def symbol_pins(inst, sym):
    if sym is None:
        return []
    m = orient_matrix(inst.orient)
    out = []
    for pin in sym.pins:
        x, y = apply(m, pin.x, pin.y)
        out.append(PinRef(inst, pin, (x + inst.x, y + inst.y)))
    return out


def _effective_wires(sch: Schematic, lib, local):
    """Wires as LTspice netlists them: a wire running under a component is cut at its pins
    and the piece between two pins of the same component is ignored (it is not a short)."""
    from .edit import cleanup_wires
    tmp = Schematic(items=[Wire(w.x1, w.y1, w.x2, w.y2) for w in sch.wires] + sch.symbols,
                    path=sch.path)
    cleanup_wires(tmp, lib, local)
    return tmp.wires


def connectivity(sch: Schematic, lib: SymbolLibrary | None = None) -> Connectivity:
    lib = lib or default_library()
    local = sch_dirs(sch)
    uf = _UF()
    wires = _effective_wires(sch, lib, local)
    conn = Connectivity()

    for inst in sch.symbols:
        conn.pins += symbol_pins(inst, lib.get(inst.symbol, local))

    points = set()
    degree = {}

    def bump(pt, n=1):
        degree[pt] = degree.get(pt, 0) + n

    for w in wires:
        a, b = (w.x1, w.y1), (w.x2, w.y2)
        uf.union(a, b)
        points.update((a, b))
        bump(a)
        bump(b)
    for pr in conn.pins:
        uf.find(pr.point)
        points.add(pr.point)
        bump(pr.point)
    for f in sch.flags:
        uf.find((f.x, f.y))
        points.add((f.x, f.y))

    # T-connections: a point touching the middle of a wire joins it
    index = WireIndex(wires)
    for pt in points:
        for w in index.through(*pt):
            uf.union(pt, (w.x1, w.y1))
            bump(pt, 2)

    # named flags merge nets everywhere on the sheet
    by_name = {}
    for f in sch.flags:
        key = f.name.lower() if f.name != "0" else "0"
        if key in by_name:
            uf.union(by_name[key], (f.x, f.y))
        else:
            by_name[key] = (f.x, f.y)

    # name the nets: ground wins, then labels, then N001...
    root_name = {}
    for f in sch.flags:
        r = uf.find((f.x, f.y))
        if f.name == "0":
            root_name[r] = "0"
        elif root_name.get(r) != "0":
            root_name.setdefault(r, f.name)

    members = {}
    for pt in points:
        members.setdefault(uf.find(pt), []).append(pt)

    counter = 0
    nc = 0
    # deterministic auto-numbering in order of first pin appearance
    for pr in conn.pins:
        r = uf.find(pr.point)
        if r in root_name:
            continue
        if len(members[r]) == 1 and degree.get(pr.point) == 1:
            nc += 1
            root_name[r] = f"NC_{nc:02d}"
            conn.unconnected.append(pr.point)
            continue
        counter += 1
        root_name[r] = f"N{counter:03d}"
    for r in members:
        if r not in root_name:
            counter += 1
            root_name[r] = f"N{counter:03d}"

    for pt in points:
        conn.net_of_point[pt] = root_name[uf.find(pt)]
    conn.junctions = sorted(p for p, d in degree.items() if d >= 3)
    return conn


# ---------------------------------------------------------------- netlisting

@dataclass
class Netlist:
    text: str
    includes: list
    errors: list


def _attr(inst, sym, key):
    v = inst.attrs.get(key)
    if v is None and sym is not None:
        v = sym.attrs.get(key)
    if v == '""':
        return ""
    return v or ""


def spice_name(inst, sym) -> str:
    """The instance's name in the netlist: its InstName, with the Prefix letter put in front
    when it doesn't start with it (U1 with Prefix X nets as XU1)."""
    letter = (_attr(inst, sym, "Prefix") or "X")[0].upper()
    name = inst.name or "?"
    return name if name[0].upper() == letter else letter + name


def element_line(inst, sym, nodes) -> tuple[str, list]:
    """SPICE line for one symbol instance, plus files it needs included."""
    letter = (_attr(inst, sym, "Prefix") or "X")[0].upper()
    name = spice_name(inst, sym)
    includes = []
    if letter == "J" and len(nodes) == 2 and not _attr(inst, sym, "Value"):
        # Misc\\jumper: a short that lets one net carry two names
        return f"V_{name} {nodes[0]} {nodes[1]} 0", includes
    value = _attr(inst, sym, "Value")
    value2 = _attr(inst, sym, "Value2")
    model = _attr(inst, sym, "SpiceModel")
    model_file = _attr(inst, sym, "ModelFile")
    if model_file:
        includes.append(model_file)
    model_is_file = bool(model and MODEL_FILE_RE.search(model))
    if model_is_file:
        includes.append(model)
        model = ""
    parts = [name] + nodes
    if letter == "X":
        # subckt name: SpiceModel when it names one; with a model *file*, Value2 holds
        # the subckt name (+params); otherwise Value2 adds parameters after Value
        if model:
            # e.g. LTC1068-200: SpiceModel LTC1068-200, Value Fclk=2Meg -> parameters
            parts += [model] + ([value] if "=" in value else []) + [value2]
        elif model_is_file and value2:
            parts.append(value2)
        else:
            parts += [value, value2]
    else:
        if model and model != value:
            parts.append(model)
        if value:
            parts.append(value)
        if value2:
            parts.append(value2)
    for k in ("SpiceLine", "SpiceLine2"):
        v = _attr(inst, sym, k)
        if v:
            parts.append(v)
    return " ".join(p for p in parts if p), includes


def _fill_order_gaps(inst, pins, nodes):
    """Some ADI symbols skip SpiceOrder numbers for pins they don't draw (ADG919: 1-5 and 8,
    against an 8-port subckt). The subckt still needs a node in every position, so missing
    orders get their own unconnected node, as LTspice must do for these examples to run."""
    orders = [p.pin.order for p in pins]
    if not orders or orders == list(range(1, len(orders) + 1)):
        return nodes
    by_order = dict(zip(orders, nodes))
    tag = re.sub(r"\W", "_", inst.name or "X")
    return [by_order.get(k, f"NC_{tag}_{k}") for k in range(1, max(orders) + 1)]


def _adevice_nodes(pins, nodes):
    """LTspice A-devices always have 8 terminals: missing or unconnected ones are tied to
    terminal 8 (com), and an unconnected com goes to node 0."""
    by_order = {p.pin.order: n for p, n in zip(pins, nodes)}
    com = by_order.get(8, "0")
    if com.startswith("NC_"):
        com = "0"
    out = []
    for i in range(1, 9):
        n = by_order.get(i, com)
        out.append(com if n.startswith("NC_") or i == 8 else n)
    return out


ANALYSES = (".tran", ".ac", ".dc", ".op", ".noise", ".tf", ".step", ".four", ".meas", ".measure",
            ".net", ".save", ".backanno", ".end")


def child_sheet(inst, sym, local_dirs) -> Path | None:
    """The .asc implementing a hierarchical block: same name as the symbol, next to the
    parent schematic, for symbols that don't name a SPICE model themselves."""
    if sym is None or sym.attrs.get("SpiceModel") or sym.attrs.get("ModelFile") \
            or inst.attrs.get("SpiceModel") or sym.prefix[:1].upper() != "X" or sym.path is None:
        return None
    base = inst.symbol.replace("\\\\", "/").replace("\\", "/").split("/")[-1]
    for d in local_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for c in d.iterdir():
            # only a symbol drawn next to its sheet is a hierarchical block (library
            # symbols such as lib/sym/opamp.asy never are, even if an opamp.asc exists)
            if c.suffix.lower() == ".asc" and c.stem.lower() == base.lower() \
                    and sym.path.parent.resolve() == c.parent.resolve():
                return c
    return None


def _body_lines(sch: Schematic, lib, local, conn, includes, errors, subckts, stack):
    lines = []
    for inst in sch.symbols:
        sym = lib.get(inst.symbol, local)
        if sym is None:
            errors.append(f"Could not find symbol {inst.symbol}")
            continue
        if not sym.pins:
            continue
        if inst.attrs.get("SpiceLine", "").startswith(";") or _attr(inst, sym, "Prefix").startswith(";"):
            continue
        pins = sorted(symbol_pins(inst, sym), key=lambda p: p.pin.order)
        nodes = [conn.net_of_point[p.point] for p in pins]
        if _attr(inst, sym, "Prefix")[:1].upper() == "A":
            nodes = _adevice_nodes(pins, nodes)
        elif _attr(inst, sym, "Prefix")[:1].upper() == "X":
            nodes = _fill_order_gaps(inst, pins, nodes)
        child = child_sheet(inst, sym, local)
        if child is not None:
            name = child.stem
            _subckt(child, sym, lib, includes, errors, subckts, stack)
            iname = inst.name or "?"
            iname = iname if iname[:1].upper() == "X" else "X" + iname
            lines.append(" ".join([iname] + nodes + [name]))
            continue
        line, inc = element_line(inst, sym, nodes)
        lines.append(line)
        for i in inc:
            if i not in includes:
                includes.append(i)
    return lines


def _subckt(path: Path, sym, lib, includes, errors, subckts, stack):
    """Netlist a hierarchical sheet once as .subckt; ports in the symbol's pin order."""
    key = path.stem.lower()
    if key in subckts:
        return
    if key in stack:
        errors.append(f"Recursive hierarchy through {path.name}")
        return
    from .asc import load_asc
    child = load_asc(path)
    local = [path.parent]
    conn = connectivity(child, lib)
    names = {f.name.lower(): (f.x, f.y) for f in child.flags if f.name != "0"}
    ports = []
    for pin in sorted(sym.pins, key=lambda p: p.order):
        pt = names.get(pin.name.lower())
        if pt is None:
            errors.append(f"{path.name}: no net label for port {pin.name}")
            ports.append(f"{pin.name}_unconnected")
        else:
            ports.append(conn.net_of_point[pt])
    subckts[key] = None                      # reserve (and detect recursion)
    body = _body_lines(child, lib, local, conn, includes, errors, subckts, stack | {key})
    for t in child.texts:
        if t.is_directive:
            body += [l for l in t.text[1:].split("\\n")
                     if not l.strip().lower().startswith(ANALYSES)]
    subckts[key] = [f".subckt {path.stem} {' '.join(ports)}"] + body + [f".ends {path.stem}"]


def generate_netlist(sch: Schematic, lib: SymbolLibrary | None = None) -> Netlist:
    lib = lib or default_library()
    local = sch_dirs(sch)
    conn = connectivity(sch, lib)
    lines = [f"* {sch.path}" if sch.path else "* untitled"]
    includes, errors, subckts = [], [], {}
    lines += _body_lines(sch, lib, local, conn, includes, errors, subckts, frozenset())
    for t in sch.texts:
        if t.is_directive:
            lines += t.text[1:].split("\\n")
    for sub in subckts.values():
        if sub:
            lines += sub
    for inc in includes:
        lines.append(f'.lib "{inc}"' if " " in inc else f".lib {inc}")
    if not any(l.strip().lower().startswith(".backanno") for l in lines):
        lines.append(".backanno")
    lines.append(".end")
    return Netlist("\n".join(lines) + "\n", includes, errors)


def write_netlist(sch: Schematic, out: Path | None = None, lib=None) -> Path:
    nl = generate_netlist(sch, lib)
    out = Path(out or Path(sch.path).with_suffix(".net"))
    out.write_text(nl.text, encoding="latin-1", errors="replace")
    return out


def subckt_netlist(sch: Schematic, lib: SymbolLibrary | None = None, name="sheet") -> tuple[str, list]:
    """Hierarchy > Generate Subckt Netlist: this sheet as '.subckt name <I/O ports>'.
    Analysis commands are left out; other directives stay inside the subcircuit."""
    lib = lib or default_library()
    local = sch_dirs(sch)
    conn = connectivity(sch, lib)
    ports, seen = [], set()
    for f in sch.flags:
        if f.iopin and f.name.lower() not in seen:
            seen.add(f.name.lower())
            ports.append(conn.net_of_point.get((f.x, f.y), f.name))
    includes, errors, subckts = [], [], {}
    body = _body_lines(sch, lib, local, conn, includes, errors, subckts, frozenset())
    for t in sch.texts:
        if t.is_directive:
            body += [l for l in t.text[1:].split("\\n")
                     if not l.strip().lower().startswith(ANALYSES + (".backanno", ".end"))]
    lines = [f"* {sch.path}" if sch.path else "* untitled", f".subckt {name} {' '.join(ports)}".rstrip()]
    lines += body
    for sub in subckts.values():
        if sub:
            lines += sub
    for inc in includes:
        lines.append(f".lib {inc}")
    lines.append(f".ends {name}")
    return "\n".join(lines) + "\n", errors
