"""Translate an LTspice netlist into something ngspice accepts.

ngspice already understands most LTspice syntax when run with
`set ngbehavior=ltpsa`; this module handles the rest: parasitic parameters on
C/L/V (Rser, Cpar...), single-argument .tran, `.lib file`, default device
models, 3-terminal MOSFETs, µ suffixes, and directives ngspice lacks.
"""
import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .. import config
from ..model.textio import decode
from . import adevices, laplace, magnetics, spicenum, wavefile

BUILTIN_MODELS = {
    "d": ".model D D", "npn": ".model NPN NPN", "pnp": ".model PNP PNP",
    "nmos": ".model NMOS NMOS", "pmos": ".model PMOS PMOS",
    "njf": ".model NJF NJF", "pjf": ".model PJF PJF",
}
STANDARD_FILES = ("standard.dio", "standard.bjt", "standard.mos", "standard.jft")
# instance parameters LTspice accepts but ngspice rejects (pure bookkeeping)
DROP_PARAMS = {"tol", "pwr", "mfg", "pn", "type", "irms", "ipk", "v", "vpk", "iave",
               "power", "rating", "tc", "m.", "dfn"}
DROP_OPTIONS = {"plotwinsize", "numdgt", "measdgt", "nomarch", "baudrate", "thev_inductors",
                "topologycheck", "fastaccess", "plotreltol", "plotvntol", "plotabstol",
                "trtol", "maxclocks", "minclocks", "startclocks", "cshunt", "gshunt",
                "sstol", "noopiter", "maxstep", "meascplxfmt", "nodiscard", "pivrel"}
LIB_EXTS = ("", ".lib", ".sub", ".mod", ".cir")


@dataclass
class StepSpec:
    name: str              # parameter name, or source/element name
    values: list
    is_param: bool = True


@dataclass
class Translation:
    text: str
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    steps: list = field(default_factory=list)       # StepSpec (outer loops first)
    analysis: str = ""                               # tran / ac / dc / op / noise / tf


def join_continuations(text: str):
    out = []
    for line in text.splitlines():
        if line.startswith("+") and out:
            out[-1] += " " + line[1:].strip()
        else:
            out.append(line.rstrip())
    return out


def resolve_file(name: str, search_dirs) -> Path | None:
    name = name.strip().strip('"').replace("\\", "/")
    p = Path(name)
    if p.is_absolute():
        return p if p.exists() else None
    for d in list(search_dirs) + [config.SUB_DIR, config.CMP_DIR, config.SUB_DIR.parent]:
        for ext in LIB_EXTS:
            cand = _ci_path(Path(d) / (name + ext))
            if cand is not None and cand.is_file():
                return cand
    return None


def _ci_path(path: Path) -> Path | None:
    if path.exists():
        return path
    parts = path.parts
    cur = Path(parts[0])
    for part in parts[1:]:
        try:
            match = next((c for c in cur.iterdir() if c.name.lower() == part.lower()), None)
        except OSError:
            return None
        if match is None:
            return None
        cur = match
    return cur


@lru_cache(maxsize=512)
def scan_definitions(path: str):
    """(models {name: type}, subckts set, encrypted?) defined in a library file."""
    models, subckts = {}, set()
    try:
        data = Path(path).read_bytes()
    except OSError:
        return models, subckts, False
    if b"<Binary File>" in data[:200]:
        return models, subckts, True
    text = decode(data)[0]
    for m in re.finditer(r"(?im)^\s*\.model\s+(\S+)\s+(?:ako:\s*\S+\s+)?([a-z]+)", text):
        models.setdefault(m.group(1).lower(), m.group(2).lower())
    for m in re.finditer(r"(?im)^\s*\.subckt\s+(\S+)", text):
        subckts.add(m.group(1).lower())
    return models, subckts, False


@lru_cache(maxsize=256)
def _lib_funcs(path: str) -> set:
    try:
        return funcs_used(decode(Path(path).read_bytes())[0])
    except OSError:
        return set()


@lru_cache(maxsize=1)
def _standard_cards():
    cards = {}
    for fname in STANDARD_FILES:
        p = config.CMP_DIR / fname
        if not p.exists():
            continue
        for line in join_continuations(decode(p.read_bytes())[0]):
            m = re.match(r"\s*\.model\s+(\S+)\s+(.*)", line, re.I)
            if m:
                cards.setdefault(m.group(1).lower(), line.strip())
    return cards


def standard_model(name: str) -> str | None:
    """The .model card for `name` from lib/cmp/standard.*, with continuations joined."""
    return _standard_cards().get(name.lower())


LIB_CACHE_VERSION = "15"     # bump when rewrite_device_line changes


def passed_params(lines) -> dict:
    """{subckt name (lower): {param names}} passed as name=value by X instances."""
    out = {}
    for line in lines:
        tok = line.split()
        if not tok or tok[0][0] not in "xX":
            continue
        pos = [t for t in tok[1:] if "=" not in t and t.lower() != "params:"]
        names = {t.split("=", 1)[0].lower() for t in tok[1:] if "=" in t}
        if pos and names:
            out.setdefault(pos[-1].lower(), set()).update(names)
    return out


def declare_passed_params(lines, passed: dict):
    """LTspice lets an instance pass parameters its .subckt never declares; ngspice
    needs them declared, so add them to the header (default 0)."""
    if not passed:
        return lines
    out = list(lines)
    i = 0
    while i < len(out):
        tok = out[i].split()
        if tok and tok[0].lower() == ".subckt" and len(tok) > 1 and tok[1].lower() in passed:
            declared = {t.split("=", 1)[0].lower() for t in tok if "=" in t}
            j = i + 1
            while j < len(out) and not out[j].strip().lower().startswith(".ends"):
                m = re.match(r"(?i)\s*\.param\s+(.*)", out[j])
                if m:
                    declared |= {k.lower() for k in re.findall(r"(\w+)\s*=", m.group(1))}
                j += 1
            missing = sorted(passed[tok[1].lower()] - declared)
            if missing:
                has_kw = any(t.lower() == "params:" for t in tok)
                out[i] = out[i].rstrip() + ("" if has_kw or declared & {t.split("=", 1)[0].lower()
                                                                          for t in tok if "=" in t}
                                            else " params:") + "".join(f" {m}=0" for m in missing)
            i = j
        i += 1
    return out


def ngspice_readable(p: Path, warnings=None, errors=None, passed=None) -> Path:
    """Path of a copy of library `p` that ngspice can read: 8-bit text with LTspice-only
    devices (A-devices, table() sources) rewritten. Unchanged files are used in place."""
    data = p.read_bytes()
    text = decode(data)[0]
    utf16 = len(data) > 1 and (data[1] == 0 or data[:2] == b"\xff\xfe")
    defined = {m.lower() for m in re.findall(r"(?im)^\s*\.subckt\s+(\S+)", text)}
    passed = {k: v for k, v in (passed or {}).items() if k in defined}
    needs = utf16 or "\u00b5" in text or re.search(r"(?im)^\s*a|table\s*\(|^\s*\.model\s+\S+\s+sw|rser|rpar|cpar|lser|noiseless|\w\s+\(|^\s*\.param|;|^\s*k|laplace|wavefile|igbt", text)
    if not needs and not passed:
        return p
    cache = config.DATA_DIR / "cache" / "libs"
    cache.mkdir(parents=True, exist_ok=True)
    sig = sorted((k, sorted(v)) for k, v in passed.items())
    key = hashlib.md5(f"{p}|{LIB_CACHE_VERSION}|{sig}".encode()).hexdigest()[:10]
    out = cache / f"{key}_{p.name}"
    if out.exists() and out.stat().st_mtime >= p.stat().st_mtime:
        return out
    lines = []
    for line in join_continuations(text.replace("\u00b5", "u").replace("\u03bc", "u")):
        line = fix_expressions(line)
        new = rewrite_device_line(line, warnings if warnings is not None else [],
                                  errors if errors is not None else [])
        lines += new if new is not None else [line]
    lines = adevices.rewrite_switches(lines)
    lines = adevices.rewrite_igbts(lines, warnings if warnings is not None else [])
    lines = declare_passed_params(lines, passed)
    out.write_text("\n".join(lines) + "\n", encoding="latin-1", errors="replace")
    return out


_FUNC_SPACE = re.compile(r"(?i)\b(sqrt|exp|ln|log|log10|abs|min|max|sin|cos|tan|atan|atan2|pow|pwr|"
                         r"if|limit|uplim|dnlim|table|tanh|sinh|cosh|sgn|int|floor|ceil|round)\s+\(")


def fix_expressions(line: str) -> str:
    """LTspice expression syntax ngspice lacks: 'sqrt (x)', table(x, x1,y1, ...) and
    '.param name expr' without '=' or braces."""
    if not line or line.lstrip()[:1] in "*;":
        return line
    line = strip_inline_comment(line)
    if re.match(r"(?i)\s*\.params\b", line):
        line = re.sub(r"(?i)^(\s*)\.params", r"\1.param", line)
    line = _FUNC_SPACE.sub(lambda m: m.group(1) + "(", line)
    if "table(" in line.lower():
        line = expand_table_calls(line)
    if line.lstrip().lower().startswith(".param"):
        line = normalize_param_line(line)
    return line


def strip_inline_comment(line: str) -> str:
    """LTspice treats ';' as the start of a comment anywhere on a line (outside quotes)."""
    if ";" not in line:
        return line
    quote = False
    for i, ch in enumerate(line):
        if ch == '"':
            quote = not quote
        elif ch == ";" and not quote:
            return line[:i].rstrip()
    return line


# LTspice built-in functions ngspice lacks, defined on demand
LT_FUNCS = {
    "u": ".func u(x) {x>0 ? 1 : 0}",
    "uramp": ".func uramp(x) {x>0 ? x : 0}",
    "buf": ".func buf(x) {x>0.5 ? 1 : 0}",
    "inv": ".func inv(x) {x>0.5 ? 0 : 1}",
    "mc": ".func mc(x,y) {unif(x,y)}",
    "flat": ".func flat(x) {aunif(0,x)}",
    "gauss": ".func gauss(x) {agauss(0,x,1)}",
    # rand(x): repeatable value in [0,1) per integer x (hash of floor(x))
    "rand": ".func rand(x) {abs(sin(floor(x)*12.9898)*43758.5453)"
            "-floor(abs(sin(floor(x)*12.9898)*43758.5453))}",
    "random": ".func random(x) {rand(x)+(x-floor(x))*(rand(x+1)-rand(x))}",
    "white": ".func white(x) {random(x)-0.5}",
}
# functions that need others defined first
FUNC_DEPS = {"random": {"rand"}, "white": {"random", "rand"}}
_FUNC_USE = re.compile(r"(?i)(?<![\w.@])(" + "|".join(LT_FUNCS) + r")\s*\(")


def funcs_used(text: str) -> set:
    return {m.group(1).lower() for m in _FUNC_USE.finditer(text)}


def normalize_param_line(line: str) -> str:
    """'.param X a*b' -> '.param X={a*b}'; 'Y=a*b' -> 'Y={a*b}'. Plain numbers stay."""
    body = line.lstrip()[6:].strip()
    m = re.match(r"^([A-Za-z_]\w*)\s+(?!=)(.+)$", body)
    if m and "=" not in m.group(2).split("(")[0]:
        assigns = [(m.group(1), m.group(2).strip())]
    else:
        # split 'a=1 b = c*2 d={x}' at top-level spaces followed by an assignment
        parts = re.split(r"\s+(?=[A-Za-z_]\w*\s*=)", re.sub(r"\s*=\s*", "=", body))
        assigns = []
        for part in parts:
            k, eq, v = part.partition("=")
            if not eq:
                return line
            assigns.append((k.strip(), v.strip()))
    out = []
    for k, v in assigns:
        if not (v.startswith("{") and v.endswith("}")) and spicenum.parse(v) is None:
            v = "{" + v + "}"
        out.append(f"{k}={v}")
    return ".param " + " ".join(out)


def _split_args(s):
    args, depth, cur = [], 0, ""
    for ch in s:
        if ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def expand_table_calls(line: str) -> str:
    """table(x, x1, y1, x2, y2, ...) -> piecewise-linear nested ternary expression.
    Element-level 'G a b c d table(...)' is left for adevices.convert_table."""
    out, i = "", 0
    low = line.lower()
    while True:
        j = low.find("table(", i)
        if j < 0:
            return out + line[i:]
        if j > 0 and (line[j - 1].isalnum() or line[j - 1] == "_"):
            out += line[i:j + 6]
            i = j + 6
            continue
        # find the matching parenthesis
        depth, k = 0, j + 5
        while k < len(line):
            if line[k] == "(":
                depth += 1
            elif line[k] == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        args = _split_args(line[j + 6:k])
        if len(args) < 3 or len(args) % 2 == 0:
            out += line[i:k + 1]
            i = k + 1
            continue
        x, pts = f"({args[0]})", [(args[n], args[n + 1]) for n in range(1, len(args), 2)]
        expr = f"({pts[-1][1]})"
        for (x0, y0), (x1, y1) in reversed(list(zip(pts, pts[1:]))):
            seg = f"({y0})+({x}-({x0}))*(({y1})-({y0}))/(({x1})-({x0}))"
            expr = f"({x}<=({x1}) ? {seg} : {expr})"
        expr = f"({x}<=({pts[0][0]}) ? ({pts[0][1]}) : {expr})"
        out += line[i:j] + expr
        i = k + 1


def rewrite_device_line(line: str, warnings: list, errors: list, search_dirs=()):
    """Rewrite LTspice-only device syntax; None means 'keep the line as is'."""
    stripped = line.strip()
    if not stripped or stripped[0] in "*;.+":
        return None
    head = stripped[0].lower()
    tok = _tokenize(stripped)
    if head in "eg" and re.search(r"(?i)\blaplace\s*=", stripped):
        m = re.match(r"(?i)\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+laplace\s*=\s*(.*)$", stripped)
        if m:
            expr = re.split(r"(?i)\s+(?:window|nfft|mtol|cache)\s*=", m.group(6))[0]
            try:
                return laplace.to_elements(m.group(1), m.group(2), m.group(3),
                                        m.group(4), m.group(5), expr, current=head == "g")
            except laplace.Unsupported as e:
                errors.append(f"{tok[0]}: {e}")
                return ["* " + stripped]
        errors.append(f"{tok[0]}: this form of Laplace= source is not supported")
        return ["* " + stripped]
    if head in "vi" and re.search(r"(?i)\bwavefile\s*=", stripped):
        m = re.search(r'(?i)\bwavefile\s*=\s*("[^"]+"|\S+)', stripped)
        cm = re.search(r"(?i)\bchan\s*=\s*(\d+)", stripped)
        p = resolve_file(m.group(1).strip('"'), search_dirs) if m else None
        if p is None:
            errors.append(f"{tok[0]}: cannot find wave file {m.group(1) if m else ''}")
            return ["* " + stripped]
        try:
            return wavefile.to_elements(tok[0], tok[1], tok[2], p, int(cm.group(1)) if cm else 0,
                                        current=head == "i")
        except (ValueError, OSError, EOFError) as e:
            errors.append(f"{tok[0]}: {e}")
            return ["* " + stripped]
    if head == "l" and len(tok) >= 4:
        if magnetics.is_flux(stripped):
            r = magnetics.flux_elements(stripped)
            if r:
                return r
        if magnetics.is_core(tok):
            return magnetics.core_elements(tok)
    if head in "clv" and len(tok) >= 4:
        pos, params = _split_params(tok[3:])
        if head == "v":
            pos = [re.sub(r"(?i)^sine\(", "sin(", p) for p in pos]
        pos = [p for p in pos if p.lower() != "noiseless"]
        tail, extra = _parasitics(tok[0], tok[1], tok[2], params)
        return [" ".join([tok[0], tok[1], tail] + pos + _keep_params(params, head))] + extra
    if head == "b" and len(tok) >= 4:
        # LTspice B sources accept Rpar=/Cpar= after the expression
        extra, keep = [], []
        for t in tok[3:]:
            k, eq, v = t.partition("=")
            if eq and k.lower() in ("rpar", "cpar"):
                el = "R" if k.lower() == "rpar" else "C"
                extra.append(f"{el}_{tok[0]}_par {tok[1]} {tok[2]} {v}")
            else:
                keep.append(t)
        if extra:
            return [" ".join(tok[:3] + keep)] + extra
        return None
    if head == "k" and len(tok) >= 5:
        # K1 L1 L2 L3 k -> one coupling statement per pair
        # inductor names as written on the schematic: T2b means element LT2b
        inds = [t if t[:1].lower() == "l" else "L" + t for t in tok[1:-1]]
        kval = tok[-1]
        if len(inds) == 2:
            return [" ".join([tok[0]] + inds + [kval])] if inds != tok[1:-1] else None
        if len(inds) > 2:
            out = []
            for i in range(len(inds)):
                for j in range(i + 1, len(inds)):
                    out.append(f"{tok[0]}_{i}{j} {inds[i]} {inds[j]} {kval}")
            return out
        return None
    if head == "r" and len(tok) >= 4:
        pos, params = _split_params(tok[3:])
        pos = ["noisy=0" if p.lower() == "noiseless" else p for p in pos]
        return [" ".join(tok[:3] + pos + _keep_params(params, "r"))]
    if head == "a":
        if adevices.is_ltspice_adevice(tok):
            lines = adevices.expand(tok, warnings)
            if lines is None:
                errors.append(f"{tok[0]}: LTspice special-function device {tok[9].upper()} "
                              "is not supported yet")
                return ["* " + stripped]
            return lines
        return None
    if head in "eg" and "table" in stripped.lower():
        conv = adevices.convert_table(stripped)
        return [conv] if conv else None
    return None


def _split_params(tokens):
    """Separate trailing key=value tokens from positional tokens."""
    pos, params = [], []
    for t in tokens:
        if "=" in t and not t.startswith("{"):
            params.append(t)
        else:
            pos.append(t)
    return pos, params


def _tokenize(line):
    """Split on whitespace but keep (...) and {...} groups and 'k = v' together."""
    line = re.sub(r"\s*=\s*", "=", line)
    toks, depth, cur = [], 0, ""
    for ch in line:
        if ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        if ch.isspace() and depth == 0:
            if cur:
                toks.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        toks.append(cur)
    return toks


def _parasitics(name, n1, n2, params):
    """Return (main element n2 node, extra lines) expanding Rser/Lser/Rpar/Cpar."""
    extra = []
    kv = {}
    for p in params:
        k, _, v = p.partition("=")
        kv[k.lower()] = v
    tail = n2
    rser, lser = kv.get("rser"), kv.get("lser")
    if lser and spicenum.parse(lser) not in (0.0,):
        mid = f"{name}_l"
        extra.append(f"L_{name}_ser {mid} {tail} {lser}")
        tail = mid
    if rser and spicenum.parse(rser) not in (0.0,):
        mid = f"{name}_r"
        extra.append(f"R_{name}_ser {mid} {tail} {rser}")
        tail = mid
    if kv.get("rpar"):
        extra.append(f"R_{name}_par {n1} {n2} {kv['rpar']}")
    if kv.get("cpar") and spicenum.parse(kv["cpar"]) not in (0.0,):
        extra.append(f"C_{name}_par {n1} {n2} {kv['cpar']}")
    return tail, extra


def _keep_params(params, element):
    out = []
    for p in params:
        k = p.partition("=")[0].lower()
        if k in ("rser", "lser", "rpar", "cpar") and element in "clv":
            continue
        if k in DROP_PARAMS:
            continue
        out.append(p)
    return out


def _parse_step(tokens) -> StepSpec | None:
    """.step [oct|dec|lin] [param] name start stop incr | .step [param] name list v1 v2..."""
    t = [x for x in tokens]
    mode = "lin"
    if t and t[0].lower() in ("oct", "dec", "lin"):
        mode = t.pop(0).lower()
    is_param = False
    if t and t[0].lower() == "param":
        is_param = True
        t.pop(0)
    if not t:
        return None
    name = t.pop(0)
    if not is_param and "(" in name:   # e.g. NPN 2N2222(VAF) model parameter: unsupported
        return None
    if t and t[0].lower() == "list":
        vals = [spicenum.parse(v) for v in t[1:]]
    else:
        if len(t) < 3:
            return None
        a, b, c = (spicenum.parse(v) for v in t[:3])
        if None in (a, b, c):
            return None
        vals = []
        if mode == "lin":
            if c == 0:
                return None
            n = int(round((b - a) / c)) + 1
            vals = [a + i * c for i in range(max(n, 1))]
        else:
            import math
            per = c
            ratio = 2.0 if mode == "oct" else 10.0
            n = int(math.floor(math.log(b / a, ratio) * per + 1e-9)) + 1
            vals = [a * ratio ** (i / per) for i in range(n)]
    if any(v is None for v in vals):
        return None
    return StepSpec(name, vals, is_param)


def translate(text: str, search_dirs=()) -> Translation:
    tr = Translation("")
    lines = join_continuations(text.replace("µ", "u").replace("μ", "u"))
    out = []
    defined_models, defined_subckts = {}, set()
    used_models = {}          # model name -> element letter
    includes = []
    mos_lines = []            # indices of M lines with 3 nodes
    title = lines[0] if lines else "* netlist"
    in_subckt = 0
    passed = passed_params(lines)

    for raw in lines[1:]:
        raw = fix_expressions(raw)
        line = raw.strip()
        if not line or line.startswith("*") or line.startswith(";"):
            out.append(raw)
            continue
        low = line.lower()
        tok = _tokenize(line)
        head = tok[0].lower()

        if head.startswith("."):
            if head == ".subckt":
                in_subckt += 1
                defined_subckts.add(tok[1].lower())
                out.append(line)
            elif head == ".ends":
                in_subckt = max(0, in_subckt - 1)
                out.append(line)
            elif head == ".backanno":
                continue
            elif head == ".end":
                continue
            elif head in (".lib", ".include", ".inc"):
                args = tok[1:]
                if head == ".lib" and len(args) >= 2:
                    out.append(line)      # ngspice-style section library
                    continue
                if not args:
                    continue
                p = resolve_file(args[0], search_dirs)
                if p is None:
                    tr.errors.append(f"Could not open library file \"{args[0]}\"")
                    continue
                models, subckts, encrypted = scan_definitions(str(p))
                if encrypted:
                    tr.errors.append(f"{p.name} is an encrypted Analog Devices model; "
                                     "it only runs inside LTspice.")
                    continue
                defined_models.update(models)
                defined_subckts |= subckts
                if str(p) not in includes:
                    includes.append(str(p))
                    out.append(f'.include "{ngspice_readable(p, tr.warnings, tr.errors, passed)}"')
            elif head == ".tran":
                tr.analysis = tr.analysis or "tran"
                out.append(_translate_tran(tok, tr))
            elif head in (".ac", ".op", ".noise", ".tf", ".dc"):
                tr.analysis = tr.analysis or head[1:]
                if head == ".dc":
                    tok = [t for t in tok if t.lower() != "lin"]
                    line = " ".join(tok)
                if head in (".ac", ".noise"):
                    line = _frequency_list(tok, tr)
                out.append(line)
            elif head == ".step":
                st = _parse_step(tok[1:])
                if st is None:
                    tr.warnings.append(f"Unsupported .step syntax ignored: {line}")
                else:
                    tr.steps.append(st)
            elif head in (".options", ".option", ".opt"):
                kept = [t for t in tok[1:] if t.partition("=")[0].lower() not in DROP_OPTIONS]
                if kept:
                    out.append(".options " + " ".join(kept))
            elif head == ".model":
                if len(tok) >= 3:
                    mtype = re.match(r"(?:ako:\S+\s*)?([a-zA-Z]+)", tok[2])
                    defined_models[tok[1].lower()] = mtype.group(1).lower() if mtype else ""
                out.append(line)
            elif head in (".wave", ".net", ".probe", ".loadbias", ".savebias", ".machine", ".endmachine"):
                tr.warnings.append(f"{head} is not supported by ngspice and was ignored")
            else:
                out.append(line)
            continue

        letter = head[0]
        if letter in "clvraegbki" and (rewritten := rewrite_device_line(
                line, tr.warnings, tr.errors, search_dirs)) is not None:
            out += rewritten
        elif letter in "dqjmz":
            # model name: first token after the nodes that names a model
            nn = {"d": 2, "q": 3, "j": 3, "m": 3, "z": 3}[letter]
            if len(tok) > nn + 1:
                model_idx = nn + 1
                # Q and M take an optional 4th node: tok[nn+1] is that node when it is
                # not a known model and is itself followed by a model-like identifier
                if letter in "qm" and len(tok) > nn + 2 \
                        and not _is_known_model(tok[nn + 1], defined_models) \
                        and not _looks_like_value(tok[nn + 2]):
                    model_idx = nn + 2
                used_models.setdefault(tok[model_idx].lower(), letter)
                if letter == "m" and model_idx == nn + 1 and not in_subckt:
                    mos_lines.append((len(out), tok, model_idx))
            pos, params = _split_params(tok)
            out.append(" ".join(pos + _keep_params(params, letter)))
        else:
            out.append(line)

    # default/standard models for devices referencing undefined models
    model_cards = []
    for name, letter in used_models.items():
        if name in defined_models:
            continue
        card = standard_model(name)
        if card is None and name in BUILTIN_MODELS:
            card = BUILTIN_MODELS[name]
        if card is None:
            tr.errors.append(f"Could not find model \"{name}\"")
            continue
        m = re.match(r"\s*\.model\s+(\S+)\s+([a-zA-Z]+)", card, re.I)
        defined_models[name] = m.group(2).lower() if m else ""
        model_cards.append(card)

    # LTspice ties the body of 3-terminal MOSFETs to the source; VDMOS has no body
    for idx, tok, model_idx in mos_lines:
        mtype = defined_models.get(tok[model_idx].lower(), "")
        if mtype != "vdmos":
            new = tok[:4] + [tok[3]] + tok[4:]
            out[idx] = " ".join(new)

    out = adevices.rewrite_switches(out)
    out = adevices.rewrite_igbts(out, tr.warnings)
    out = declare_passed_params(out, passed)
    used = funcs_used("\n".join(out))
    for inc in includes:
        used |= _lib_funcs(inc)
    for f in list(used):
        used |= FUNC_DEPS.get(f, set())
    func_defs = [LT_FUNCS[f] for f in LT_FUNCS if f in used]     # dict order = dependency order
    body = [title, ".param pi=3.141592653589793"] + func_defs + out + model_cards + [".options savecurrents", ".end"]
    tr.text = "\n".join(body) + "\n"
    return tr


def _frequency_list(tok, tr):
    """'.ac list f1 f2 ...' / '.noise out src list f1 ...': ngspice has no list sweep. One
    frequency becomes 'lin 1 f f'; several become a sweep spanning them."""
    low = [t.lower() for t in tok]
    if "list" not in low:
        return " ".join(tok)
    i = low.index("list")
    freqs = [spicenum.parse(t) for t in tok[i + 1:]]
    if not freqs or None in freqs:
        return " ".join(tok)
    head = tok[:i]
    if len(freqs) == 1:
        f = tok[i + 1]
        return " ".join(head + ["lin", "1", f, f])
    tr.warnings.append("frequency list replaced by a sweep from the lowest to the highest value")
    lo, hi = min(freqs), max(freqs)
    return " ".join(head + ["dec", "20", f"{lo:.6g}", f"{hi:.6g}"])


def _looks_like_value(t):
    return t.startswith("{") or "=" in t or spicenum.parse(t) is not None


def _is_known_model(t, defined):
    t = t.lower()
    return t in defined or t in BUILTIN_MODELS or standard_model(t) is not None


def _translate_tran(tok, tr: Translation) -> str:
    args, mods = [], []
    for t in tok[1:]:
        if t.lower() in ("uic", "startup", "steady", "nodiscard", "step"):
            mods.append(t.lower())
        else:
            args.append(t)
    for m in mods:
        if m != "uic":
            tr.warnings.append(f".tran modifier '{m}' is not supported by ngspice and was ignored")
    if len(args) == 1:
        tstop = args[0]
        v = spicenum.parse(tstop)
        tstep = f"{v / 1000:.6g}" if v is not None else "{(" + tstop.strip("{}") + ")/1000}"
        args = [tstep, tstop]
    elif len(args) >= 2:
        if spicenum.parse(args[0]) == 0:
            v = spicenum.parse(args[1])
            args[0] = f"{v / 1000:.6g}" if v is not None else "{(" + args[1].strip("{}") + ")/1000}"
    return " ".join([".tran"] + args + (["uic"] if "uic" in mods else []))
