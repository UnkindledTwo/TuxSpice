"""Plain-language explanations of ngspice failures (a TuxSpice extra).

ngspice's messages name lower-case nodes and instances ("singular matrix: check node n003",
"trouble with node "xu1.n002"", "unknown subckt: x1 a 0 bar"). explain() turns them into
Issues that say what is wrong and point at the part or net, which the Problems panel then
highlights on the schematic. Names inside subcircuits are reported against the top-level
instance (xu1.q3 -> XU1)."""
import re

from ..model.check import Issue

_SINGULAR = re.compile(r"singular matrix:\s+check nodes?\s+(\S+)(?:\s+and\s+(\S+))?", re.I)
_TIMESTEP = re.compile(r"time ?step too small(?:; time = ([-+\d.e]+))?", re.I)
_TROUBLE_NODE = re.compile(r'trouble with node "?([^"\s]+)"?', re.I)
_TROUBLE_INST = re.compile(r"trouble with (?:(\S+)-instance\s+)?(\S+)", re.I)
_UNKNOWN_SUBCKT = re.compile(r"unknown subckt:\s+(\S+)(.*)", re.I)
_NO_MODEL = re.compile(r"can't find model '([^']+)'|could not find model \"([^\"]+)\"", re.I)
_NO_MODEL_DEF = re.compile(r"unable to find definition of model\s+(\S+)", re.I)
_ERROR_ON_LINE = re.compile(r"error on line\s+\d+.*:\s*$", re.I)
_NO_VALUE = re.compile(r"(\S+): resistance too low or not given", re.I)
_GAVE_UP = re.compile(r"gave up after (\d+) s", re.I)


def top_instance(name: str) -> str:
    """'xu1.q3' and 'q.xu1.q3' -> 'xu1'; 'r1' -> 'r1'."""
    parts = name.strip('"').split(".")
    if len(parts) > 1 and len(parts[0]) == 1:
        parts = parts[1:]
    return parts[0]


def _node_ref(node):
    """(parts, nets, description) for an ngspice node name."""
    node = node.strip('"').rstrip(",")
    if node.endswith("#branch"):
        src = node[:-len("#branch")]
        return [top_instance(src)], [], src.upper()
    if "." in node:
        inst = top_instance(node)
        return [inst], [], f"{node.split('.')[-1]} inside {inst.upper()}"
    return [], [node], node.upper() if re.fullmatch(r"n\d{3,}", node) else node


def explain(log: str, errors=(), netlist: str = "") -> list[Issue]:
    """Issues for a failed run. `netlist` (the run's input) lets missing models be traced
    back to the parts that use them."""
    text = log + "\n" + "\n".join(errors)
    lines = text.splitlines()
    elements = [l.split() for l in netlist.splitlines() if l[:1].isalpha()]
    issues, seen = [], set()

    def add(key, issue):
        if key not in seen:
            seen.add(key)
            issues.append(issue)

    for m in _SINGULAR.finditer(text):
        for node in filter(None, m.groups()):
            parts, nets, what = _node_ref(node)
            if node.lower().endswith("#branch"):
                add(("loop", node.lower()), Issue(
                    "error", f"Voltage source or inductor {what} is in a loop or shorted", parts,
                    hint="Ideal voltage sources and inductors can't form a loop or sit in parallel: "
                         "ngspice can't split the current between them. Add a series resistance "
                         "(Rser=...) to one of them, or remove the duplicate."))
            else:
                add(("float", node.lower()), Issue(
                    "error", f"Node {what} has no DC path to ground", parts, nets,
                    hint="It is connected only through capacitors, current sources or control "
                         "inputs, so its voltage is undefined (\"singular matrix\"). Add a large "
                         "resistor to ground (e.g. 100Meg) or check the wiring."))

    for i, line in enumerate(lines):
        m = _TIMESTEP.search(line)
        if m and "op failed" not in line.lower():      # "Transient op failed": no DC solution
            near = " ".join(lines[i:i + 3])
            parts, nets, where = [], [], ""
            mn = _TROUBLE_NODE.search(near)
            mi = _TROUBLE_INST.search(near) if not mn else None
            if mn:
                parts, nets, what = _node_ref(mn.group(1))
                where = f" near node {what}"
            elif mi:
                parts = [top_instance(mi.group(2))]
                where = f" at {parts[0].upper()}"
            at = f" at t = {float(m.group(1)):.4g} s" if m.group(1) else ""
            add(("timestep",), Issue(
                "error", f"The simulation stalled{at}{where}: the time step shrank to nothing",
                parts, nets,
                hint="Something changes too abruptly for ngspice to follow. Usual causes: a source "
                     "with 0 s rise or fall time, an ideal switch or diode with no on-resistance, a "
                     "behavioural expression that jumps (if/ternary), or an inductor with no Rser. "
                     "Give edges a finite time, add small series resistances, or try "
                     "Tools > Settings > SPICE > Gear integration."))
        m = _UNKNOWN_SUBCKT.search(line)
        if m:
            tok = (m.group(1) + m.group(2)).split()
            name = [t for t in tok if "=" not in t][-1]
            add(("subckt", name.lower()), Issue(
                "error", f"{top_instance(tok[0]).upper()} uses subcircuit {name.upper()}, which "
                         f"isn't defined", [top_instance(tok[0])],
                hint="Add the library that defines it with a .lib or .include directive, or drop the "
                     "model file onto the schematic (TuxSpice makes a symbol for it)."))
        for rx in (_NO_MODEL, _NO_MODEL_DEF):
            m = rx.search(line)
            if m:
                model = next(g for g in m.groups() if g)
                inst = ""
                for tok in [l.split() for l in lines[max(0, i - 3):i + 3]] + elements:
                    if tok and model.lower() in (t.lower() for t in tok[1:]) and tok[0][:1].isalpha():
                        inst = top_instance(tok[0])
                        break
                add(("model", model.lower()), Issue(
                    "error", (f"{inst.upper()} uses" if inst else "A part uses") +
                    f" model {model.upper()}, which isn't defined", [inst] if inst else [],
                    hint="Check the spelling of the part's value, or add the model with .model, "
                         ".lib or .include. Dropping the model file onto the schematic also works."))
        m = _NO_VALUE.search(line)
        if m:
            add(("value", m.group(1).lower()), Issue(
                "warning", f"{m.group(1).upper()} has no resistance value; ngspice used 1 mΩ",
                [m.group(1)], hint="Right-click the resistor and enter its value."))
        if _ERROR_ON_LINE.search(line) and i + 2 < len(lines):
            bad, why = lines[i + 1].strip(), lines[i + 2].strip()
            tok = bad.split()
            if tok and not any(k in why.lower() for k in ("modelname", "unknown subckt")):
                add(("line", bad.lower()), Issue(
                    "error", f"ngspice can't read {top_instance(tok[0]).upper()}: {why}",
                    [top_instance(tok[0])], hint=f"The netlist line was: {bad}"))
        m = _GAVE_UP.search(line)
        if m:
            add(("timeout",), Issue(
                "error", f"The simulation was stopped after {m.group(1)} s",
                hint="A retry with relaxed settings took too long. Shorten the .tran time, or "
                     "look for the cause of the slowdown (see above)."))
        if "ran out of memory" in line.lower():
            add(("memory",), Issue(
                "error", "ngspice ran out of memory", hint=(
                    "The run stored more data than fits. Shorten the .tran stop time, give .tran a "
                    "larger maximum step, or save fewer signals (.save).")))

    if not any(i.severity == "error" for i in issues) and re.search(
            r"gmin stepping failed|source stepping failed|no convergence|iteration limit|op failed|"
            r"operating point could not", text, re.I):
        add(("op",), Issue(
            "error", "ngspice couldn't find the DC operating point", hint=(
                "Check for floating nodes and missing ground, give sources a series resistance, "
                "help it with .nodeset, or skip the operating point with .tran ... uic.")))
    if not issues:
        for e in errors:
            add(("raw", e), Issue("error", e))
    return issues
