"""Use a vendor SPICE model file on a schematic (a TuxSpice extra).

Drop a .lib/.sub/.mod/.cir/.txt file onto a schematic, or use Edit > Place SPICE Model from
File: the file is scanned for .subckt and .model definitions, and the chosen one is placed.
A subcircuit gets a symbol written for it (LTspice makes you open the library and use
"Create Symbol" on each one): its pins are named from the .subckt line, or, when those are
just numbers, from the pin ladder vendors put in the comment above it:

    * CONNECTIONS:   NON-INVERTING INPUT
    *                | INVERTING INPUT
    *                | | POSITIVE POWER SUPPLY
    *                | | | NEGATIVE POWER SUPPLY
    *                | | | | OUTPUT
    .SUBCKT LM741    1 2 3 4 5

A five-pin subcircuit in LTspice's op-amp order (+in, -in, V+, V-, out) uses the standard
OpAmps\\opamp2 symbol instead. A .model card goes on the matching standard symbol (diode, npn,
nmos...). Either way the part carries ModelFile=<the file>, so the netlist includes it."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..model.textio import decode
from .ltcompat import join_continuations

MODEL_EXTS = (".lib", ".sub", ".mod", ".cir", ".txt", ".inc", ".ckt", ".sp", ".spi", ".model",
              ".bjt", ".dio", ".mos", ".jft")
MODEL_SYMBOLS = {"d": "diode", "npn": "npn", "pnp": "pnp", "nmos": "nmos", "pmos": "pmos",
                 "njf": "njf", "pjf": "pjf", "sw": "sw", "csw": "csw"}
OPAMP_ORDER = ["in+", "in-", "v+", "v-", "out"]


@dataclass
class Definition:
    kind: str                     # 'subckt' or 'model'
    name: str
    pins: list = field(default_factory=list)      # .subckt port tokens
    labels: list = field(default_factory=list)    # readable pin names (same length as pins)
    mtype: str = ""               # model type (d, npn, nmos, vdmos...)
    params: str = ""
    description: str = ""

    @property
    def symbol(self) -> str | None:
        """The standard LTspice symbol a .model card goes on, or None."""
        if self.kind != "model":
            return None
        if self.mtype == "vdmos":
            return "pmos" if re.search(r"\bpchan\b", self.params, re.I) else "nmos"
        return MODEL_SYMBOLS.get(self.mtype)

    def summary(self) -> str:
        if self.kind == "subckt":
            return f"subcircuit, {len(self.pins)} pins: " + " ".join(self.labels or self.pins)
        return f"{self.mtype.upper()} model"


def _pin_role(label: str) -> str:
    l = re.sub(r"[\s_]+", " ", label.lower()).strip()
    if re.search(r"non.?inv|^\+ ?in|^in ?\+|^inp\b|^in_?p$|^vin\+", l):
        return "in+"
    if re.search(r"inv|^- ?in|^in ?-|^inn\b|^in_?n$|^vin-", l):
        return "in-"
    if re.search(r"pos.*(supply|power|rail)|^v ?\+|^vcc|^vdd|^vs ?\+|^v ?pos", l):
        return "v+"
    if re.search(r"neg.*(supply|power|rail)|^v ?-|^vee|^vss|^vs ?-|^v ?neg", l):
        return "v-"
    if re.search(r"^out|output", l):
        return "out"
    return ""


def is_opamp(d: Definition) -> bool:
    names = d.labels or d.pins
    return d.kind == "subckt" and len(names) == 5 and [_pin_role(n) for n in names] == OPAMP_ORDER


def _pin_labels(comments, n):
    """Pin names from the comment block above a .subckt: a 'CONNECTIONS' ladder (one name per
    line, aligned with '|' marks) or a 'pins: a b c' / 'pin order: ...' line."""
    ladder = []
    for c in comments:
        body = c.lstrip("*").rstrip()
        if "|" in body or re.match(r"\s*(pin\s*)?connections?\s*:", body, re.I):
            label = re.sub(r"(?i)^\s*(pin\s*)?connections?\s*:?", "", body).replace("|", " ").strip()
            if label:
                ladder.append(label)
    if len(ladder) == n:
        return ladder
    for c in comments:
        m = re.search(r"(?i)\bpin(?:s| order| out)?\s*[:=]\s*(.+)$", c.lstrip("*"))
        if m:
            names = m.group(1).replace(",", " ").split()
            if len(names) == n:
                return names
    return []


def scan(path) -> tuple[list[Definition], bool]:
    """(top-level definitions, encrypted?) of a model file."""
    data = Path(path).read_bytes()
    if b"<Binary File>" in data[:200]:
        return [], True
    lines = join_continuations(decode(data)[0])
    defs, depth = [], 0
    for i, line in enumerate(lines):
        tok = line.split()
        if not tok:
            continue
        head = tok[0].lower()
        if head == ".subckt" and len(tok) >= 2:
            if depth == 0:
                pins, params = [], []
                for j, t in enumerate(tok[2:]):
                    if t.lower().rstrip(":") in ("params", "param") or "=" in t:
                        params = tok[2 + j:]
                        break
                    pins.append(t)
                comments = []
                for back in reversed(lines[max(0, i - 20):i]):
                    if back.strip().startswith("*") or not back.strip():
                        comments.insert(0, back)
                    else:
                        break
                labels = _pin_labels(comments, len(pins))
                if not labels and not all(re.fullmatch(r"\d+", p) for p in pins):
                    labels = list(pins)
                text = [c.lstrip("*").strip() for c in comments
                        if "|" not in c and re.search(r"[A-Za-z]{3}", c)]
                defs.append(Definition("subckt", tok[1], pins, labels, params=" ".join(params),
                                       description=" ".join(text[:2])[:160]))
            depth += 1
        elif head == ".ends":
            depth = max(0, depth - 1)
        elif head == ".model" and depth == 0 and len(tok) >= 3:
            rest = " ".join(tok[2:])
            rest = re.sub(r"(?i)^ako:\s*\S+\s*", "", rest)
            m = re.match(r"([a-zA-Z]+)", rest)
            if m:
                defs.append(Definition("model", tok[1], mtype=m.group(1).lower(), params=rest[len(m.group(1)):]))
    return defs, False


def model_file_attr(lib: Path, sch_path) -> str:
    """How the part names its model file: just the file name when it sits in the schematic's
    folder (found there, and the folder can be shared as is), else the absolute path."""
    lib = Path(lib).resolve()
    if sch_path is not None and lib.parent == Path(sch_path).resolve().parent:
        return lib.name
    return str(lib)


def symbol_dir(lib: Path, sch_path) -> Path:
    """Where a generated symbol goes: next to the schematic when the model file is there too,
    otherwise TuxSpice's AutoGenerated folder (as LTspice's lib/sym/AutoGenerated)."""
    if sch_path is not None and Path(lib).resolve().parent == Path(sch_path).resolve().parent:
        return Path(sch_path).resolve().parent
    return config.USER_SYM_DIR / "AutoGenerated"


def block_symbol(d: Definition, model_file: str) -> str:
    """An .asy box for a subcircuit: outputs on the right, everything else on the left (or an
    even split when no pin says 'out'), pins on the box edge with their names inside."""
    names = d.labels or d.pins
    order = list(range(1, len(names) + 1))
    right = [k for k, n in zip(order, names) if _pin_role(n) == "out" or re.search(r"(?i)out", n)]
    if not right or len(right) == len(names):
        half = (len(names) + 1) // 2
        right = order[half:]
    left = [k for k in order if k not in right]
    rows = max(len(left), len(right), 1)
    longest = max((len(n) for n in names), default=1)
    half_w = max(64, ((longest * 11 + 40 + 15) // 16) * 16)
    h = 32 * rows + 32
    top = -(h // 2 // 16) * 16
    out = ["Version 4", "SymbolType BLOCK",
           f"RECTANGLE Normal {-half_w} {top} {half_w} {top + h}",
           f"WINDOW 0 {-half_w} {top - 16} Left 2",
           f"WINDOW 3 {-half_w} {top + h + 16} Left 2",
           f"SYMATTR Value {d.name}",
           "SYMATTR Prefix X",
           f"SYMATTR SpiceModel {d.name}",
           f"SYMATTR ModelFile {model_file}"]
    if d.description:
        out.append(f"SYMATTR Description {d.description}")
    for side, ks, x in (("LEFT", left, -half_w), ("RIGHT", right, half_w)):
        for row, k in enumerate(ks):
            out += [f"PIN {x} {top + 32 + 32 * row} {side} 8", f"PINATTR PinName {names[k - 1]}",
                    f"PINATTR SpiceOrder {k}"]
    return "\n".join(out) + "\n"


def placement(d: Definition, lib: Path, sch_path):
    """(symbol name, instance attributes, .asy text to write or None, its path or None) for
    placing definition d from model file lib on a schematic saved at sch_path (or None)."""
    model_file = model_file_attr(lib, sch_path)
    if d.kind == "model":
        sym = d.symbol
        if sym is None:
            raise ValueError(f"TuxSpice has no standard symbol for {d.mtype.upper()} models")
        return sym, {"Value": d.name, "ModelFile": model_file}, None, None
    if is_opamp(d):
        return "OpAmps\\\\opamp2", {"Value": d.name, "ModelFile": model_file}, None, None
    folder = symbol_dir(lib, sch_path)
    safe = re.sub(r"[^\w.+-]", "_", d.name)
    asy = folder / f"{safe}.asy"
    name = safe if folder != config.USER_SYM_DIR / "AutoGenerated" else f"AutoGenerated\\\\{safe}"   # .asc spelling: doubled backslash
    return name, {}, block_symbol(d, model_file), asy
