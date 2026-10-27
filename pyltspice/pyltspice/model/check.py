"""Simulate > Check Circuit (a TuxSpice extra; LTspice has no such check).

Finds the mistakes that make a simulation fail or quietly compute the wrong thing, before
ngspice runs: no ground, nets with no DC path to ground, loops of voltage sources, parts
with no value, open or shorted two-terminal parts, duplicate names, and the classic SPICE
suffix traps (1M on a resistor is one milliohm; 10F on a capacitor is ten femtofarads).

Every check errs on the side of silence: a part whose DC behaviour isn't known (subcircuits,
A-devices) counts as connecting all its pins, so the check never invents a floating node."""
import re
from dataclasses import dataclass, field

from .asc import Schematic
from .library import SymbolLibrary, default_library, sch_dirs
from .netlist import _attr, connectivity, spice_name, symbol_pins


@dataclass
class Issue:
    severity: str                    # 'error' (the run will likely fail) or 'warning'
    message: str
    parts: list = field(default_factory=list)   # instance names (schematic or SPICE spelling)
    nets: list = field(default_factory=list)    # net names
    hint: str = ""                   # what to do about it


TWO_PIN = set("RCLVIDB")
_PLACEHOLDER = {"R": "R", "C": "C", "L": "L", "V": "V", "I": "I"}
_NUM = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)([a-zµ]*)", re.I)


def _conducting(letter, nets):
    """Which of a part's terminals are joined at DC (a list of groups)."""
    if letter in "CI":
        return []
    if letter == "M" and len(nets) >= 3:          # gate is insulated
        return [[n for i, n in enumerate(nets) if i != 1]]
    if letter in "EGFHSW" and len(nets) >= 2:     # control side draws no current
        return [nets[:2]]
    return [nets]


def _directive_elements(sch: Schematic):
    """(name, letter, nodes, tokens) for elements written as SPICE directives."""
    out, depth = [], 0
    for t in sch.texts:
        if not t.is_directive:
            continue
        for line in t.body.splitlines():
            tok = line.split()
            if not tok:
                continue
            head = tok[0].lower()
            if head.startswith(".subckt"):
                depth += 1
            elif head.startswith(".ends"):
                depth = max(0, depth - 1)
            if depth or not tok[0][:1].isalpha() or len(tok) < 3:
                continue
            letter = tok[0][0].upper()
            n = {"Q": 3, "J": 3, "M": 4, "E": 4, "G": 4, "S": 4, "T": 4}.get(letter, 2)
            if letter == "X":
                args = [a for a in tok[1:] if "=" not in a]
                nodes = args[:-1]
            elif letter == "K":
                continue
            else:
                nodes = tok[1:1 + n]
            out.append((tok[0], letter, nodes, tok))
    return out


def _value_issue(inst, sym, letter):
    name = inst.name or "?"
    value = _attr(inst, sym, "Value").strip()
    first = value.split()[0] if value else ""
    if letter in _PLACEHOLDER and first.upper() in ("", _PLACEHOLDER[letter]) \
            and not _attr(inst, sym, "Value2") and not _attr(inst, sym, "SpiceLine"):
        if letter in "RCL":
            return Issue("error", f"{name} has no value", [name],
                         hint=f"Right-click it and enter a value. ngspice would quietly use "
                              f"{'1 mΩ' if letter == 'R' else 'a default'} instead.")
        return None
    m = _NUM.match(first)
    if not m:
        return None
    suffix = m.group(2)
    if letter == "R" and suffix[:1] == "M" and not suffix.upper().startswith(("MEG", "MIL")):
        return Issue("warning", f"{name} = {first} is {m.group(1)} milliohm(s)", [name],
                     hint=f"In SPICE M means milli. For megohms write {m.group(1)}Meg.")
    if letter == "C" and suffix == "F":        # 700f is a deliberate 700 fF; 10F looks like farads
        return Issue("warning", f"{name} = {first} is {m.group(1)} femtofarad(s)", [name],
                     hint=f"In SPICE F means femto. For farads write {m.group(1)}, "
                          f"for microfarads {m.group(1)}µ.")
    return None


def check_schematic(sch: Schematic, lib: SymbolLibrary | None = None) -> list[Issue]:
    lib = lib or default_library()
    local = sch_dirs(sch)
    conn = connectivity(sch, lib)
    issues = []
    directives = "\n".join(t.body for t in sch.texts if t.is_directive).lower()
    parts = []                                    # (display name, spice name, letter, nets, inst, sym)
    for inst in sch.symbols:
        sym = lib.get(inst.symbol, local)
        if sym is None or not sym.pins:
            continue
        prefix = _attr(inst, sym, "Prefix")
        if prefix.startswith(";") or inst.attrs.get("SpiceLine", "").startswith(";"):
            continue
        pins = sorted(symbol_pins(inst, sym), key=lambda p: p.pin.order)
        nets = [conn.net_of_point[p.point] for p in pins]
        letter = (prefix or "X")[0].upper()
        parts.append((inst.name or "?", spice_name(inst, sym), letter, nets, inst, sym))
    extra = _directive_elements(sch)
    if not parts and not extra:
        return issues

    # duplicate names: ngspice keeps only one of them
    seen = {}
    for disp, sname, *_ in parts:
        seen.setdefault(sname.lower(), []).append(disp)
    for sname, names in seen.items():
        if len(names) > 1:
            issues.append(Issue("error", f"{len(names)} parts are named {names[0]}", names,
                                hint="Give each part its own name (right-click > InstName)."))

    # values
    for disp, sname, letter, nets, inst, sym in parts:
        iss = _value_issue(inst, sym, letter)
        if iss:
            issues.append(iss)

    # how many pins land on each net (directive elements count too)
    pin_count = {}
    for *_, nets, _i, _s in parts:
        for n in nets:
            pin_count[n.lower()] = pin_count.get(n.lower(), 0) + 1
    for _, _, nodes, _ in extra:
        for n in nodes:
            pin_count[n.lower()] = pin_count.get(n.lower(), 0) + 1

    for disp, sname, letter, nets, inst, sym in parts:
        if letter not in TWO_PIN or len(nets) != 2:
            continue
        a, b = nets
        if a.lower() == b.lower():
            if letter in "BI":             # LTspice idiom: B1 0 0 I=<expr> just computes a value
                continue
            sev = "error" if letter == "V" else "warning"
            issues.append(Issue(sev, f"{disp} is shorted: both ends are on net {a}", [disp], [a],
                                hint="Both pins connect to the same net, so the part does nothing"
                                     + (" and ngspice can't solve the circuit." if sev == "error" else ".")))
            continue
        for k, n in enumerate(nets):
            # a labelled net touching one pin is usually a deliberate probe point
            if n != "0" and pin_count.get(n.lower(), 0) <= 1 and _auto_name(n):
                issues.append(Issue("warning", f"{disp}: pin {k + 1} isn't connected to anything",
                                    [disp], [] if n.startswith("NC_") else [n],
                                    hint="Draw a wire from the pin (W) or delete the part."))

    has_ground = any(n == "0" for *_, nets, _i, _s in parts for n in nets) or \
        any(n == "0" for _, _, nodes, _ in extra for n in nodes)
    if not has_ground:
        issues.append(Issue("error", "The circuit has no ground", hint=(
            "Every SPICE circuit needs a node 0. Place a ground symbol (G) on the reference node.")))
        return issues

    # voltage-source loops (ideal sources in parallel, or a loop of them)
    adj = {}
    for disp, sname, letter, nets, inst, sym in parts:
        if letter != "V" or len(nets) != 2 or nets[0] == nets[1]:
            continue
        attrs = " ".join(_attr(inst, sym, k) for k in ("Value", "Value2", "SpiceLine", "SpiceLine2"))
        if "rser" in attrs.lower():
            continue
        a, b = nets[0].lower(), nets[1].lower()
        path = _path(adj, a, b)
        if path is not None:
            names = [disp] + path
            issues.append(Issue("error", f"Voltage sources {', '.join(names)} form a loop", names,
                                hint="Ideal voltage sources can't be in parallel or in a loop. "
                                     "Add a series resistance (Rser=...) to one of them."))
            continue
        adj.setdefault(a, []).append((b, disp))
        adj.setdefault(b, []).append((a, disp))

    # nets with no DC path to ground
    if not re.search(r"\.tran\b[^\n]*\buic\b", directives) and "rshunt" not in directives:
        parent = {}

        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        groups = []
        for *_, letter, nets, _i, _s in parts:
            groups += _conducting(letter, [n.lower() for n in nets])
        for _, letter, nodes, _ in extra:
            groups += _conducting(letter, [n.lower() for n in nodes])
        for g in groups:
            for n in g[1:]:
                parent[find(n)] = find(g[0])
        ground = find("0")
        floating = {}
        for disp, sname, letter, nets, inst, sym in parts:
            for n in nets:
                if not n.startswith("NC_") and find(n.lower()) != ground:
                    floating.setdefault(find(n.lower()), {}).setdefault(n, None)
        for nets in floating.values():
            names = list(nets)
            touching = [d for d, _s, _l, pn, _i, _y in parts if set(pn) & set(names)]
            what = f"net {names[0]}" if len(names) == 1 else "nets " + ", ".join(names)
            issues.append(Issue("warning", f"No DC path to ground from {what}", touching, names, hint=(
                "These nodes connect to the rest of the circuit only through capacitors, current "
                "sources or control inputs, so their DC voltage is undefined. ngspice usually gets "
                "past this with gmin stepping, but if it reports \"singular matrix\", add a large "
                "resistor to ground (e.g. 100Meg).")))
    return issues


def _auto_name(net):
    return bool(re.fullmatch(r"N\d{3,}|NC_\d+", net))


def _path(adj, a, b):
    """Names of the sources on a path from net a to net b, or None."""
    if a == b:
        return []
    prev, todo = {a: None}, [a]
    while todo:
        cur = todo.pop()
        for nxt, name in adj.get(cur, ()):
            if nxt not in prev:
                prev[nxt] = (cur, name)
                if nxt == b:
                    out = []
                    while prev[nxt] is not None:
                        nxt, name = prev[nxt]
                        out.append(name)
                    return out
                todo.append(nxt)
    return None
