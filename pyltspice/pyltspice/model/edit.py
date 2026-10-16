"""Geometric edits on schematic model objects (move/rotate/mirror/copy/naming)."""
import copy
import re

from . import asc
from .geometry import GRID, apply, mirror_orient, orient_matrix, rotate_orient
from .netlist import _on_segment, symbol_pins


def points_of(obj):
    """Anchor points of an object (for wires: both ends)."""
    if isinstance(obj, asc.Wire):
        return [(obj.x1, obj.y1), (obj.x2, obj.y2)]
    if isinstance(obj, asc.Graphic):
        c = obj.coords
        return [(c[i], c[i + 1]) for i in range(0, len(c), 2)]
    return [(obj.x, obj.y)]


def set_points(obj, pts):
    if isinstance(obj, asc.Wire):
        (obj.x1, obj.y1), (obj.x2, obj.y2) = pts
    elif isinstance(obj, asc.Graphic):
        obj.coords = [v for p in pts for v in p]
    else:
        obj.x, obj.y = pts[0]


def translate(obj, dx, dy):
    set_points(obj, [(x + dx, y + dy) for x, y in points_of(obj)])


def _xform_about(obj, m, cx, cy):
    def tp(x, y):
        rx, ry = apply(m, x - cx, y - cy)
        return cx + rx, cy + ry
    if isinstance(obj, asc.Graphic) and obj.kind in ("RECTANGLE", "CIRCLE", "ARC"):
        pts = [tp(*p) for p in points_of(obj)]
        set_points(obj, pts)
        return
    set_points(obj, [tp(*p) for p in points_of(obj)])


def rotate(objs, cx, cy):
    """Rotate a group 90 degrees clockwise on screen about (cx, cy)."""
    m = orient_matrix("R90")
    for o in objs:
        _xform_about(o, m, cx, cy)
        if isinstance(o, asc.SymbolInst):
            o.orient = rotate_orient(o.orient)
        elif isinstance(o, asc.Text):
            if o.just.startswith("V"):
                o.just = o.just[1:]
            else:
                o.just = "V" + o.just


def mirror(objs, cx, cy):
    m = orient_matrix("M0")
    for o in objs:
        _xform_about(o, m, cx, cy)
        if isinstance(o, asc.SymbolInst):
            o.orient = mirror_orient(o.orient)
        elif isinstance(o, asc.Text):
            o.just = {"Left": "Right", "Right": "Left", "VLeft": "VLeft"}.get(o.just, o.just)
        elif isinstance(o, asc.Graphic) and o.kind == "ARC":
            # mirroring reverses arc direction: swap start and end
            c = o.coords
            o.coords = c[:4] + c[6:8] + c[4:6]


def relayout_windows(inst: asc.SymbolInst, sym) -> None:
    """Keep InstName/Value readable after rotating or mirroring a part, as LTspice does.

    LTspice rewrites the WINDOW 0/3 lines of two-pin parts whose labels sit beside the body
    (res, cap, ind, diode, voltage, current...). The rule was read from the bundled examples
    (1600+ rotated resistors) and checked live: at R90/M90 the name sits at the body's left
    edge (VBottom) and the value at its right edge (VTop), both centred between the pins, so
    on screen the name is above the part and the value below it. R270/M270 swap the edges,
    R180/M180 swap the two labels' heights, and R0/M0 use the symbol's own windows.
    Other symbols are left alone."""
    if sym is None or len(sym.pins) != 2:
        return
    w0, w3 = sym.windows.get(0), sym.windows.get(3)
    p1, p2 = sym.pins
    if w0 is None or w3 is None or w0.just != "Left" or w3.just != "Left" or p1.x != p2.x:
        return
    from .asy import Window
    xs = [x for s in sym.shapes for x in s.coords[:4][0::2]]
    if not xs:
        return
    if any(s.kind == "ARC" for s in sym.shapes):
        x0 = min(min(s.coords[4], s.coords[6]) if s.kind == "ARC" else min(s.coords[:4][0::2])
                 for s in sym.shapes) + 1
    else:
        x0 = min(xs)
    x1 = max(xs)
    cy = (p1.y + p2.y) // 2
    rot = inst.orient.lstrip("RM")
    if rot == "90":
        new = {0: Window(x0, cy, "VBottom", w0.size), 3: Window(x1, cy, "VTop", w3.size)}
    elif rot == "270":
        new = {0: Window(x1, cy, "VTop", w0.size), 3: Window(x0, cy, "VBottom", w3.size)}
    elif rot == "180":
        new = {0: Window(w0.x, w3.y, w0.just, w0.size), 3: Window(w3.x, w0.y, w3.just, w3.size)}
    else:
        inst.windows.pop(0, None)
        inst.windows.pop(3, None)
        return
    inst.windows.update(new)


def group_center(objs):
    pts = [p for o in objs for p in points_of(o)]
    if not pts:
        return 0, 0
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    return round(cx / GRID) * GRID, round(cy / GRID) * GRID


def clone(objs):
    return [copy.deepcopy(o) for o in objs]


# ---------------------------------------------------------------- naming

def name_prefix(sym, inst=None) -> str:
    """Letter(s) used for new instance names: R, C, L, D, Q, M, V, U for subckts."""
    prefix = (inst.attrs.get("Prefix") if inst else None) or (sym.prefix if sym else "X")
    letter = prefix[0].upper()
    return "U" if letter == "X" else letter


def next_name(sch: asc.Schematic, prefix: str) -> str:
    used = set()
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$", re.I)
    for s in sch.symbols:
        m = pat.match(s.name)
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"{prefix}{n}"


def rename_copies(sch, objs, lib, local_dirs=()):
    """Give duplicated symbols fresh instance names."""
    for o in objs:
        if isinstance(o, asc.SymbolInst):
            sym = lib.get(o.symbol, local_dirs)
            p = name_prefix(sym, o)
            m = re.match(r"^([A-Za-z_]+)\d+$", o.name)
            if m:
                p = m.group(1)
            o.attrs["InstName"] = next_name(sch, p)
            sch.items.append(o)    # reserve the name while naming the rest
    for o in objs:
        if isinstance(o, asc.SymbolInst):
            sch.items.remove(o)


# ---------------------------------------------------------------- wire cleanup

def cleanup_wires(sch: asc.Schematic, lib, local_dirs=()):
    """Split wires at pins/endpoints lying on them, drop zero-length and duplicate
    wires, and remove segments that short two pins of the same component (LTspice
    cuts a wire drawn straight through a resistor)."""
    pin_owner = {}
    for inst in sch.symbols:
        for pr in symbol_pins(inst, lib.get(inst.symbol, local_dirs)):
            pin_owner.setdefault(pr.point, set()).add(id(inst))

    # split every wire at the pins lying on its interior, in one pass
    from .netlist import WireIndex
    index = WireIndex(sch.wires)
    cuts = {}
    for pt in pin_owner:
        for w in index.through(*pt):
            cuts.setdefault(id(w), []).append(pt)
    if cuts:
        out = []
        for item in sch.items:
            pts = cuts.get(id(item)) if isinstance(item, asc.Wire) else None
            if not pts:
                out.append(item)
                continue
            a = (item.x1, item.y1)
            pts = sorted(set(pts), key=lambda q: (q[0] - a[0]) ** 2 + (q[1] - a[1]) ** 2)
            chain = [a] + pts + [(item.x2, item.y2)]
            out += [asc.Wire(p[0], p[1], q[0], q[1]) for p, q in zip(chain, chain[1:])]
        sch.items[:] = out

    seen = set()
    keep = []
    for item in sch.items:
        if isinstance(item, asc.Wire):
            a, b = (item.x1, item.y1), (item.x2, item.y2)
            key = tuple(sorted((a, b)))
            if a == b or key in seen:
                continue
            owners = pin_owner.get(a, set()) & pin_owner.get(b, set())
            if owners:
                continue        # shorts the pins of a single component
            seen.add(key)
        keep.append(item)
    sch.items[:] = keep
