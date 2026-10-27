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
    measures: list = field(default_factory=list)    # .meas lines, evaluated in Python
    params: dict = field(default_factory=dict)      # numeric top-level .param values
    analysis: str = ""                               # tran / ac / dc / op / noise / tf
    dc_sweep: object = None                          # StepSpec for a .dc dec/oct/list sweep


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
    for d in list(search_dirs) + [config.SUB_DIR, config.CMP_DIR, config.SUB_DIR.parent, config.BUNDLED_MODELS]:
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


def model_card_files():
    """lib/cmp/standard.* then TuxSpice's own cards; the first definition of a name wins."""
    return [config.CMP_DIR / f for f in STANDARD_FILES] + \
        [config.BUNDLED_MODELS / f.replace("standard", "tuxspice") for f in STANDARD_FILES]


@lru_cache(maxsize=1)
def _standard_cards():
    cards = {}
    for p in model_card_files():
        if not p.exists():
            continue
        for line in join_continuations(decode(p.read_bytes())[0]):
            m = re.match(r"\s*\.model\s+(\S+)\s+(.*)", line, re.I)
            if m:
                cards.setdefault(m.group(1).lower(), line.strip())
    return cards


@lru_cache(maxsize=1)
def model_catalog():
    """Every part in the model-card libraries, for the Pick New Transistor/Diode/... dialog:
    [{name, kind (npn, pnp, d, vdmos, njf, pjf...), params {lower: value}, library}], first
    definition of a name only (LTspice's before TuxSpice's)."""
    out, seen = [], set()
    for p in model_card_files():
        if not p.exists():
            continue
        lib = "TuxSpice" if p.parent == config.BUNDLED_MODELS else "LTspice"
        for line in join_continuations(decode(p.read_bytes())[0]):
            m = re.match(r"\s*\.model\s+(\S+)\s+(?:ako:\s*\S+\s+)?([a-zA-Z]+)\s*\(?(.*?)\)?\s*$", line, re.I)
            if not m or m.group(1).lower() in seen:
                continue
            seen.add(m.group(1).lower())
            params = {k.lower(): v for k, v in re.findall(r"([A-Za-z_][\w.]*)\s*=\s*(\"[^\"]*\"|\S+)", m.group(3))}
            flags = {t.lower() for t in re.split(r"[\s,]+", re.sub(r"\S+\s*=\s*\S+", "", m.group(3))) if t}
            out.append({"name": m.group(1), "kind": m.group(2).lower(), "params": params,
                        "pchan": "pchan" in flags, "library": lib})
    return out


def standard_model(name: str) -> str | None:
    """The .model card for `name` from lib/cmp/standard.*, with continuations joined."""
    return _standard_cards().get(name.lower())


LIB_CACHE_VERSION = "58"     # bump when rewrite_device_line changes


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
            # same key as undot_subckt_names gives the renamed .subckt
            out.setdefault(pos[-1].lower().replace(".", "_"), set()).update(names)
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


def _nested_include(name, parent: Path, warnings, errors, passed, seen) -> str:
    """'.lib UniversalOpAmp2.lib' inside a library (AD8310.lib): resolve it like the netlist's
    own .lib lines and include an ngspice-readable copy."""
    p = resolve_file(name, [Path(parent).parent, config.SUB_DIR])   # parent is the including file
    if p is None:
        if errors is not None:
            errors.append(f"{parent.name}: could not open library file \"{name}\"")
        return f"* missing include {name}"
    if scan_definitions(str(p))[2]:
        if errors is not None:
            errors.append(f"{p.name} is an encrypted Analog Devices model; it only runs inside LTspice.")
        return f"* encrypted include {name}"
    if p.resolve() in seen:
        return f"* already included {name}"
    return f'.include "{ngspice_readable(p, warnings, errors, passed, seen | {p.resolve()})}"'


def ngspice_readable(p: Path, warnings=None, errors=None, passed=None, _seen=frozenset()) -> Path:
    """Path of a copy of library `p` that ngspice can read: 8-bit text with LTspice-only
    devices (A-devices, table() sources) rewritten. Unchanged files are used in place."""
    data = p.read_bytes()
    text = decode(data)[0]
    utf16 = len(data) > 1 and (data[1] == 0 or data[:2] == b"\xff\xfe")
    defined = {m.lower().replace(".", "_") for m in re.findall(r"(?im)^\s*\.subckt\s+(\S+)", text)}
    passed = {k: v for k, v in (passed or {}).items() if k in defined}
    needs = utf16 or "\u00b5" in text or re.search(r"(?im)^\s*\.(lib|inc)|^\s*a|table\s*\(|^\s*\.model\s+\S+\s+sw|rser|rpar|cpar|lser|noiseless|\w\s+\(|^\s*\.param|;|^\s*k|laplace|wavefile|igbt|vdmos|vfwd|ron", text)
    if not needs and not passed and text.isascii():
        return p
    cache = config.DATA_DIR / "cache" / "libs"
    cache.mkdir(parents=True, exist_ok=True)
    sig = sorted((k, sorted(v)) for k, v in passed.items())
    key = hashlib.md5(f"{p}|{LIB_CACHE_VERSION}|{sig}".encode()).hexdigest()[:10]
    out = cache / f"{key}_{p.name}"
    if out.exists() and out.stat().st_mtime >= p.stat().st_mtime:
        # errors found while rewriting are kept in the cached copy; report them every time
        if errors is not None:
            for line in out.read_text(encoding="latin-1").splitlines():
                if line.startswith(_ERROR_MARK):
                    errors.append(line[len(_ERROR_MARK):])
                elif not line.startswith("*"):
                    break
        return out
    errors = errors if errors is not None else []
    first_error = len(errors)
    lines = []
    for line in join_continuations(text.replace("\u00b5", "u").replace("\u03bc", "u")):
        inc = re.match(r"""(?i)\s*\.(?:lib|inc|include)\s+("[^"]+"|\S+)\s*$""", line)
        if inc:
            line = _nested_include(inc.group(1).strip('"'), p, warnings, errors, passed, _seen)
            lines.append(line)
            continue
        line = fix_expressions(line)
        new = rewrite_device_line(line, warnings if warnings is not None else [],
                                  errors if errors is not None else [])
        lines += new if new is not None else [line]
    lines = convert_machines(lines)
    lines = hoist_subckt_params(undot_subckt_names(rename_odd_element_names(lines)))
    lines = rename_reserved_params(lines)
    lines = adevices.disambiguate_models(lines)
    lines = rewrite_device_currents(lines)
    lines = adevices.rewrite_switches(lines)
    lines = adevices.rewrite_vdmos(lines)
    lines = adevices.rewrite_three_terminal_mos(lines)
    lines = adevices.rewrite_ideal_diodes(lines)
    lines = adevices.rewrite_igbts(lines, warnings if warnings is not None else [])
    lines = declare_passed_params(lines, passed)
    lines = [_ERROR_MARK + e for e in errors[first_error:]] + lines
    out.write_text("\n".join(lines) + "\n", encoding="latin-1", errors="replace")
    return out


_ERROR_MARK = "* TUXSPICE-ERROR: "


_FUNC_SPACE = re.compile(r"(?i)\b(sqrt|exp|ln|log|log10|abs|min|max|sin|cos|tan|atan|atan2|pow|pwr|"
                         r"if|limit|uplim|dnlim|table|tanh|sinh|cosh|sgn|int|floor|ceil|round)\s+\(")


def fix_expressions(line: str) -> str:
    """LTspice expression syntax ngspice lacks: 'sqrt (x)', table(x, x1,y1, ...) and
    '.param name expr' without '=' or braces."""
    if not line or line.lstrip()[:1] in "*;":
        return line
    line = strip_inline_comment(line)
    if not line.isascii():
        line = ascii_only(line)
    if re.match(r"(?i)\s*\.params\b", line):
        line = re.sub(r"(?i)^(\s*)\.params", r"\1.param", line)
    line = _FUNC_SPACE.sub(lambda m: m.group(1) + "(", line)
    if "table(" in line.lower():
        line = expand_table_calls(line)
    if line.lstrip().lower().startswith(".param"):
        line = _param_commas(line)
        line = normalize_param_line(line)
    if re.search(r"(?i)\btemp(er)?\b", line):
        line = _temp_in_params(line)
    if line.lstrip()[:1].lower() in "beg" and re.search(r"(?i)\b(cosh|sinh)\s*\(", line):
        line = re.sub(r"(?i)(?<![\w.])(cosh|sinh)\s*\(", lambda m: f"lt_{m.group(1).lower()}(", line)
    if "smallsig" in line.lower():
        # help (B. Arbitrary Behavioral Source): smallsig() is 1 during .ac/.noise, else 0;
        # translate() defines lt_smallsig for the analysis being run
        line = re.sub(r"(?i)\bsmallsig\s*\(\s*\)", "{lt_smallsig}", line)
    if "{" in line:
        line = flatten_braces(line)
    return line


def flatten_braces(line: str) -> str:
    """'{a*{b}}' -> '{a*(b)}': LTspice accepts braces nested inside an expression (often after
    table() expansion with {param} arguments), ngspice's numparam does not."""
    out, depth = [], 0
    for ch in line:
        if ch == "{":
            depth += 1
            out.append("{" if depth == 1 else "(")
        elif ch == "}" and depth:
            out.append("}" if depth == 1 else ")")
            depth -= 1
        else:
            out.append(ch)
    return "".join(out)


_TEMP = re.compile(r"(?i)\btemp(er)?\b(?!\s*=)")


def _temp_in_params(line: str) -> str:
    """LTspice lets `temp` appear in {...} parameter expressions and .param lines (ADI models use
    it for temperature drift); ngspice's numparam has no temperature variable there. Use the
    global `lt_temp`, which translate() defines from .temp (27 by default). Behavioral source
    equations outside braces keep `temp`/`temper`, which ngspice evaluates itself."""
    if line.lstrip().lower().startswith(".param"):
        return _TEMP.sub("lt_temp", line)
    out, depth, start = [], 0, 0
    for i, ch in enumerate(line):
        if ch == "{":
            if depth == 0:
                out.append(line[start:i])
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                out.append(_TEMP.sub("lt_temp", line[start:i + 1]))
                start = i + 1
    out.append(line[start:])
    return "".join(out)


_NON_ASCII = {"\u00a7": "S", "\u03a9": "", "\u2126": "", "\u00b0": "", "\u00b5": "u", "\u03bc": "u",
              "\u00a0": " "}


def ascii_only(line: str) -> str:
    """ADI libraries use characters like '§' in instance names (M§Q6, B§Ibp) and 'Ω' after
    values; ngspice rejects non-ASCII input. The mapping is fixed, so every reference to a
    renamed element is renamed the same way."""
    return "".join(c if c.isascii() else _NON_ASCII.get(c, "_") for c in line)


def _param_commas(line: str) -> str:
    """'.param M=20m, OS=6.3' (ADA4932.lib): LTspice allows commas between assignments.
    A comma at bracket depth 0 that is followed by 'name=' separates two assignments."""
    out, depth = [], 0
    for i, ch in enumerate(line):
        if ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        if ch == "," and depth == 0 and re.match(r"\s*\w+\s*=", line[i + 1:]):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


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
    # ngspice stops on cosh/sinh overflow; LTspice's models (AD8310) rely on it saturating
    "lt_cosh": ".func lt_cosh(x) {cosh(min(max(x,-300),300))}",
    "lt_sinh": ".func lt_sinh(x) {sinh(min(max(x,-300),300))}",
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
    if head == "_":
        # a non-ASCII first character (ascii_only maps it to '_'), e.g. AD8676.lib's
        # 'Ö§A3 ... Gm1= Ibias=': an undocumented LTspice-internal device. ('$' lines are
        # comments, which ngspice handles itself.)
        errors.append(f"'{tok[0]}' is an undocumented LTspice-only device type; "
                      "it cannot be simulated outside LTspice")
        return ["* " + stripped]
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
    if head == "d" and len(tok) >= 4 and re.search(r"(?i)(^|\s)n\s*=", " ".join(tok[4:])):
        return _series_diodes(tok)
    if head in "rc" and len(tok) >= 4:
        conv = _behavioral_rc(tok)
        if conv:
            return conv
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
        # 'NoJacob' (undocumented) only keeps the source out of LTspice's Jacobian: drop it
        dropped = [t for t in tok[3:] if t.lower() == "nojacob"]
        for t in tok[3:]:
            if t.lower() == "nojacob":
                continue
            k, eq, v = t.partition("=")
            if eq and k.lower() in ("rpar", "cpar"):
                el = "R" if k.lower() == "rpar" else "C"
                extra.append(f"{el}_{tok[0]}_par {tok[1]} {tok[2]} {v}")
            else:
                keep.append(t)
        if extra or dropped:
            return [" ".join(tok[:3] + keep)] + extra
        return None
    if head == "k" and len(tok) >= 4:
        # K1 L1 L2 L3 k -> one coupling statement per pair
        # inductor names as written on the schematic: T2b means element LT2b
        inds = [t if t[:1].lower() == "l" else "L" + t for t in tok[1:-1]]
        kval = tok[-1]
        kv = spicenum.parse(kval)
        if kv is not None and abs(kv) >= 1:
            # LTspice accepts perfect coupling; ngspice's inductance matrix becomes singular
            kval = "0.9999" if kv > 0 else "-0.9999"
        if len(inds) == 2:
            changed = inds != tok[1:-1] or kval != tok[-1]
            return [" ".join([tok[0]] + inds + [kval])] if changed else None
        if len(inds) > 2:
            out = []
            for i in range(len(inds)):
                for j in range(i + 1, len(inds)):
                    out.append(f"{tok[0]}_{i}{j} {inds[i]} {inds[j]} {kval}")
            return out
        return None
    if head == "r" and len(tok) >= 4:
        tok = _resistor_tc_list(tok)
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
    if head == "g":
        conv = _threshold_vccs(tok)
        if conv:
            return [conv]
    if head == "i" and any(t.lower() == "load" for t in tok[3:]):
        return _load_current_source(tok, warnings)
    return None


_DYNAMIC = re.compile(r"(?i)\b(v|i)\s*\(|\btime\b|(?<![\w.])x(?![\w(])")


def _behavioral_rc(tok):
    """LTspice's behavioral 'R n+ n- R=<expr>' and 'C n+ n- Q=<expr>' (the expression may use
    node voltages, currents and time; help pages R. Resistor / C. Capacitor). ngspice only
    takes constant values there, so they become B sources: I=V(n+,n-)/(expr) and
    I=ddt(expr). Plain parameter values (R={x}) are left alone."""
    key = "r" if tok[0][0].lower() == "r" else "q"
    rest = " ".join(tok[3:])
    m = re.match(rf"(?i)^{key}\s*=\s*(.+)$", rest)
    if not m:
        return None
    expr = m.group(1).strip()
    if expr.startswith("{") and expr.endswith("}"):
        expr = expr[1:-1]
    if not _DYNAMIC.search(expr):
        return None
    # parameters after the expression (e.g. 'noiseless') don't apply to a B source
    expr = re.sub(r"(?i)\s+(noiseless|tc\d?=\S+)$", "", expr)
    n1, n2 = tok[1], tok[2]
    # in LTspice's Q= (and R=) expressions, x is the voltage across the element
    expr = re.sub(r"(?i)(?<![\w.])x(?![\w(])", f"V({n1},{n2})", expr)
    if key == "r":
        return [f"B{tok[0]} {n1} {n2} I=V({n1},{n2})/({expr})"]
    return [f"B{tok[0]} {n1} {n2} I=ddt({expr})"]


_RESERVED = {"min", "max", "abs", "sqrt", "exp", "ln", "log", "log10", "sin", "cos", "tan", "asin",
             "acos", "atan", "sinh", "cosh", "tanh", "pow", "pwr", "sgn", "int", "floor", "ceil",
             "round", "if", "limit", "table", "uramp", "nint", "atan2", "hypot"}


def rename_reserved_params(lines: list[str]) -> list[str]:
    """A parameter may share its name with a function in LTspice ('.param Min=0.53', then
    'fCin**Min' in ADA4870.lib); ngspice's numparam reads it as the function. Rename such
    parameters to '<name>_' wherever they're used as a value (not followed by '(')."""
    names = set()
    for l in lines:
        low = l.lstrip().lower()
        if low.startswith((".param", ".subckt")) or low[:1] == "x":
            names |= {m.lower() for m in re.findall(r"(\w+)\s*=", l)}
    bad = names & _RESERVED
    if not bad:
        return lines
    pat = re.compile(r"(?i)(?<![\w.])(" + "|".join(sorted(bad)) + r")(?![\w.])(?!\s*\()")
    return [l if l.lstrip().startswith("*") else pat.sub(lambda m: m.group(1) + "_", l) for l in lines]


def _lt_bool(expr: str) -> str:
    """LTspice logic in behavioral expressions: '|' and '&' -> '||' and '&&'."""
    expr = re.sub(r"(?<![|])\|(?![|])", "||", expr)
    return re.sub(r"(?<![&])&(?![&])", "&&", expr)


def convert_machines(lines: list[str]) -> list[str]:
    """.machine/.state/.rule/.output/.endmachine (help: '.MACHINE - Arbitrary State Machine').

    ngspice has no discrete states, so each machine is built from XSPICE digital parts: the
    state *index* (states may share a value, e.g. S0a/S0b in the help's divide-by-2) is held in
    digital bits that feed back through 1 ns buffers. Each rule's condition becomes a digital
    signal (> .5, via a B source and an adc_bridge); gate logic picks the first rule that fires
    ('*' rules first, then in order) and sets the next index, which takes effect 1 ns later, so
    chained rules execute one at a time ("only one rule executes per timestep").
    .output lines are current sources into their node; the help reads them through ~1K
    resistors and the models (LTC6560/6563) feed them to DFLOP clocks, so the current is taken
    as expression x 1 mA, i.e. the expression's value in volts across 1K."""
    out, i, k = [], 0, 0
    while i < len(lines):
        if not re.match(r"(?i)\s*\.mach(ine)?\b", lines[i]):
            out.append(lines[i])
            i += 1
            continue
        j = i + 1
        states, rules, outputs = [], [], []
        while j < len(lines) and not re.match(r"(?i)\s*\.endmach(ine)?\b", lines[j]):
            l = lines[j].strip()
            m = re.match(r"(?i)\.state\s+(\w+)\s+(\S+)", l)
            if m:
                states.append((m.group(1).lower(), m.group(2)))
            m = re.match(r"(?i)\.rule\s+(\S+)\s+(\w+)\s+(.+)$", l)
            if m:
                rules.append((m.group(1).lower(), m.group(2).lower(), m.group(3)))
            m = re.match(r"(?i)\.output\s+\(\s*([^,)\s]+)\s*(?:,\s*([^)\s]+)\s*)?\)\s+(.+)$", l)
            if m:
                outputs.append(m.groups())
            j += 1
        i = j + 1
        k += 1
        out.append(f"* .machine {k} (emulated with XSPICE digital state bits)")
        out += _machine_parts(f"lt_mach{k}", states, rules, outputs)
    return out


def _machine_parts(tag, states, rules, outputs):
    index = {n: n_i for n_i, (n, _) in enumerate(states)}
    nb = max(1, (len(states) - 1).bit_length())
    lines = []
    gates = {}                                    # model name -> XSPICE model card

    def gate(kind, ins, out_node, name):
        model = f"{tag}_{kind}"
        if kind in ("and", "or") and len(ins) == 1:
            kind, model = "buf", f"{tag}_buf"
        if kind == "buf":
            gates[model] = f".model {model} d_buffer(rise_delay=1e-12 fall_delay=1e-12)"
            lines.append(f"A{tag}_{name} {ins[0]} {out_node} {model}")
        elif kind == "inv":
            gates[model] = f".model {model} d_inverter(rise_delay=1e-12 fall_delay=1e-12)"
            lines.append(f"A{tag}_{name} {ins[0]} {out_node} {model}")
        else:
            gates[model] = f".model {model} d_{kind}(rise_delay=1e-12 fall_delay=1e-12)"
            lines.append(f"A{tag}_{name} [{' '.join(ins)}] {out_node} {model}")

    # constant 0 / 1 and the current-state bits with their complements
    lines += [f"A{tag}_z0 [0] [{tag}_zero] {tag}_zm",
              f".model {tag}_zm adc_bridge(in_low=0.5 in_high=0.5)"]
    gate("inv", [f"{tag}_zero"], f"{tag}_one", "one")
    cur = [f"{tag}_q{b}" for b in range(nb)]
    ncur = [f"{tag}_nq{b}" for b in range(nb)]
    for b in range(nb):
        gate("inv", [cur[b]], ncur[b], f"nq{b}")

    def is_state(n_i):
        return [cur[b] if (n_i >> b) & 1 else ncur[b] for b in range(nb)]

    # analog view of the state, for expressions: index from the bits, value by index
    lines.append(f"A{tag}_dac [{' '.join(cur)}] [{' '.join(f'{tag}_qa{b}' for b in range(nb))}] {tag}_dacm")
    lines.append(f".model {tag}_dacm dac_bridge(out_low=0 out_high=1 t_rise=1e-9 t_fall=1e-9)")
    idx = "(" + "+".join(f"{1 << b}*V({tag}_qa{b})" for b in range(nb)) + ")"
    lines.append(f"B{tag}_idx {tag}_idx 0 V={idx}")
    ix = f"floor(V({tag}_idx)+0.5)"
    value = f"({states[-1][1]})" if states else "0"
    for n_i in range(len(states) - 2, -1, -1):
        value = f"({ix}=={n_i} ? ({states[n_i][1]}) : {value})"

    def subst(expr):
        expr = _lt_bool(expr)
        expr = re.sub(r"(?i)(?<![\w.])state(?![\w(])", value, expr)
        for name, v in states:
            expr = re.sub(rf"(?i)(?<![\w.]){re.escape(name)}(?![\w(])", f"({v})", expr)
        return expr

    if states:
        ordered = [r for r in rules if r[0] == "*" and r[1] in index] + \
                  [r for r in rules if r[0] != "*" and r[1] in index]
        sel = []                                  # (digital node, new index) per rule, priority order
        prev_any = None
        for r_i, (old, new, cond) in enumerate(ordered):
            ca, cd = f"{tag}_c{r_i}a", f"{tag}_c{r_i}"
            lines.append(f"B{tag}_c{r_i} {ca} 0 V=(({subst(cond)})>0.5 ? 1 : 0)")
            lines += [f"A{tag}_c{r_i}adc [{ca}] [{cd}] {tag}_cadc"]
            fire = f"{tag}_f{r_i}"
            gate("and", [cd] + (is_state(index[old]) if old != "*" and old in index else []), fire, f"f{r_i}")
            if prev_any is None:
                pick = fire
                any_now = fire
            else:
                nprev, pick, any_now = f"{tag}_np{r_i}", f"{tag}_s{r_i}", f"{tag}_any{r_i}"
                gate("inv", [prev_any], nprev, f"np{r_i}")
                gate("and", [fire, nprev], pick, f"s{r_i}")
                gate("or", [prev_any, fire], any_now, f"any{r_i}")
            sel.append((pick, index[new]))
            prev_any = any_now
        lines.append(f".model {tag}_cadc adc_bridge(in_low=0.5 in_high=0.5)")
        hold = f"{tag}_hold"
        if prev_any is None:
            gate("buf", [f"{tag}_one"], hold, "hold")
        else:
            gate("inv", [prev_any], hold, "hold")
        for b in range(nb):
            terms = [p for p, n_i in sel if (n_i >> b) & 1]
            keep = f"{tag}_k{b}"
            gate("and", [hold, cur[b]], keep, f"k{b}")
            gate("or", terms + [keep], f"{tag}_n{b}", f"n{b}")
            # memory: an always-enabled latch with a 1 ns data delay, starting at 0 (the first
            # declared state is the initial one); rules see the state of 1 ns ago
            lines.append(f"A{tag}_d{b} {tag}_n{b} {tag}_one {tag}_zero {tag}_zero {cur[b]} {tag}_nql{b} {tag}_dly")
        lines.append(f".model {tag}_dly d_dlatch(data_delay=1e-9 enable_delay=1e-9 set_delay=1e-9 "
                     "reset_delay=1e-9 ic=0 rise_delay=1e-12 fall_delay=1e-12)")
    for n, (pos, neg, expr) in enumerate(outputs):
        lines.append(f"B{tag}_o{n} {neg or 0} {pos} I=1m*({subst(expr)})")
    return lines + list(gates.values())


def hoist_subckt_params(lines: list[str]) -> list[str]:
    """LTspice evaluates a subckt's .param lines regardless of where they stand (ADA4870.lib
    defines ORn after the elements using it); ngspice's numparam evaluates in order. Move each
    subckt's .param lines right after its header, keeping their order (later ones may use
    earlier ones)."""
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if not l.lstrip().lower().startswith(".subckt"):
            out.append(l)
            i += 1
            continue
        depth, j, body = 0, i + 1, []
        while j < len(lines):
            low = lines[j].lstrip().lower()
            if low.startswith(".subckt"):
                depth += 1
            elif low.startswith(".ends"):
                if depth == 0:
                    break
                depth -= 1
            body.append(lines[j])
            j += 1
        # only top-level params of this subckt (not those of nested subckts)
        params, rest, d = [], [], 0
        for b in body:
            low = b.lstrip().lower()
            if low.startswith(".subckt"):
                d += 1
            elif low.startswith(".ends"):
                d -= 1
            (params if d == 0 and low.startswith(".param") else rest).append(b)
        out += [l] + params + rest
        i = j
    return out


def undot_subckt_names(lines: list[str]) -> list[str]:
    """ngspice uses '.' as its hierarchy separator, so a subckt named 'LT1965-x.x' is never
    found. Dots in subckt names become '_', in .subckt/.ends lines and in X instances alike
    (both the libraries and the netlist go through this)."""
    out = []
    for l in lines:
        low = l.lstrip().lower()
        tok = l.split()
        if low.startswith((".subckt", ".ends")) and len(tok) >= 2 and "." in tok[1]:
            tok[1] = tok[1].replace(".", "_")
            l = " ".join(tok)
        elif tok and tok[0][:1] in "xX" and len(tok) >= 3:
            k = next((i for i, t in enumerate(tok) if "=" in t or t.lower() == "params:"), len(tok))
            if k - 1 >= 1 and "." in tok[k - 1] and spicenum.parse(tok[k - 1]) is None:
                tok[k - 1] = tok[k - 1].replace(".", "_")
                l = " ".join(tok)
        out.append(l)
    return out


def rename_odd_element_names(lines: list[str]) -> list[str]:
    """Element names containing '+' or '-' (AD8475.lib: 'V_Current_Sense+', used by H sources
    and in I(...)) are legal in LTspice, not in ngspice. Rename them (+ -> P, - -> M) and every
    reference to them in the same text."""
    odd = {}
    for l in lines:
        t = l.split(None, 1)
        if t and t[0][:1].isalpha() and re.search(r"[+-]", t[0]) and not l.lstrip().startswith("."):
            odd[t[0].lower()] = t[0].replace("+", "P").replace("-", "M")
    if not odd:
        return lines
    pat = re.compile(r"(?i)(?<![\w$+-])(" + "|".join(re.escape(k) for k in sorted(odd, key=len, reverse=True))
                     + r")(?![\w$+-])")
    return [l if l.lstrip().startswith("*") else pat.sub(lambda m: odd[m.group(1).lower()], l) for l in lines]


# terminal (1-based) whose current each LTspice current function reads, per element letter
_TERMINALS = {"m": {"id": 1, "ig": 2, "is": 3, "ib": 4},
              "q": {"ic": 1, "ib": 2, "ie": 3, "is": 4},
              "j": {"id": 1, "ig": 2, "is": 3},
              "z": {"id": 1, "ig": 2, "is": 3}}
_CURRENT_REF = re.compile(r"(?i)\b(i[a-z]?)\(\s*([a-z][\w$§.:]*)\s*\)")


def rewrite_device_currents(lines: list[str]) -> list[str]:
    """LTspice expressions may read any element's current: Id(M3), Ic(Q1), I(R5), I(D2)...
    ngspice B/E/G expressions only know voltage-source currents. Each referenced terminal gets
    a 0 V sense source in series (current into the terminal, as LTspice reports it) and the
    reference becomes I(V__s_<dev>_<n>). Done per .subckt scope, since names are local."""
    out = list(lines)
    scopes, start = [], 0
    for i, l in enumerate(out):
        low = l.lstrip().lower()
        if low.startswith(".subckt"):
            scopes.append((start, i)); start = i + 1
        elif low.startswith(".ends"):
            scopes.append((start, i)); start = i + 1
    scopes.append((start, len(out)))
    for a, b in scopes:
        _sense_scope(out, a, b)
    return [x for l in out for x in l.split("\n")]


def _sense_scope(out, a, b):
    devices = {}
    for i in range(a, b):
        l = out[i]
        if l and l.strip() and l.lstrip()[0].isalpha():
            devices.setdefault(l.split()[0].lower(), i)
    needed = {}                       # (device, terminal) -> sense source name
    for i in range(a, b):
        l = out[i]
        if not l or l.lstrip()[:1].lower() not in "beg" or "(" not in l:
            continue
        def sub(m):
            fn, name = m.group(1).lower(), m.group(2)
            dev = name.lower()
            if dev not in devices or dev[0] in "vb" or (fn == "i" and dev[0] in "efgh"):
                return m.group(0)
            if fn == "i":
                term = 1
            else:
                term = _TERMINALS.get(dev[0], {}).get(fn)
                if term is None:
                    return m.group(0)
            key = (dev, term)
            if key not in needed:
                needed[key] = f"V__s_{name}_{term}".replace(".", "_").replace(":", "_")
            return f"I({needed[key]})"
        new = _CURRENT_REF.sub(sub, l)
        if new != l:
            out[i] = new
    extra = {}
    for (dev, term), vname in needed.items():
        i = devices[dev]
        tok = out[i].split()
        if term >= len(tok):
            continue
        node = tok[term]
        tok[term] = f"{node}__s_{vname[4:]}"
        out[i] = " ".join(tok)
        extra.setdefault(i, []).append(f"{vname} {node} {tok[term]} 0")
    for i in sorted(extra, reverse=True):
        out[i] = "\n".join([out[i]] + extra[i])


def _series_diodes(tok):
    """'D1 a k model n=4': help (D. Diode) says instance parameter N is the number of series
    devices. ngspice has no such parameter, so expand a chain; the first diode keeps the name,
    so I(D1) is still the chain current."""
    keep, n = [], None
    for t in tok[4:]:
        k, eq, v = t.partition("=")
        if eq and k.lower() == "n":
            n = spicenum.parse(v)
        else:
            keep.append(t)
    n = int(round(n)) if n else 1
    if n <= 1:
        return [" ".join(tok[:4] + keep)]
    name, a, k, model = tok[:4]
    nodes = [a] + [f"{name}_s{i}" for i in range(1, n)] + [k]
    out = [" ".join([name if i == 0 else f"{name}_{i + 1}", nodes[i], nodes[i + 1], model] + keep)
           for i in range(n)]
    # the nodes between the diodes float while they're off (LTspice ideal diodes become B
    # sources with ~no leakage here): give each a 1G DC path so the matrix stays regular
    out += [f"R{name}_s{i} {nodes[i]} 0 1G" for i in range(1, n)]
    return out


def _resistor_tc_list(tok):
    """'R1 a b 500K tc = 0 -.25u 0 30p' (LTC3.lib): LTspice takes a list of temperature
    coefficients after tc=; ngspice knows tc1 and tc2 only. Higher orders are dropped (they
    vanish at the nominal 27 C like the others)."""
    for k, t in enumerate(tok):
        if t.lower().startswith("tc="):
            vals = [t.split("=", 1)[1]] if t.split("=", 1)[1] else []
            j = k + 1
            while j < len(tok) and spicenum.parse(tok[j].rstrip(",")) is not None and "=" not in tok[j]:
                vals.append(tok[j].rstrip(","))
                j += 1
            vals = [v for x in vals for v in x.split(",") if v]
            new = [f"tc{n + 1}={v}" for n, v in enumerate(vals[:2])]
            return tok[:k] + new + tok[j:]
    return tok


def _value(v: str) -> str:
    v = v.strip()
    return f"({v[1:-1]})" if v.startswith("{") and v.endswith("}") else v


def _threshold_vccs(tok):
    """LTspice's undocumented 'G n+ n- nc+ nc- gm vto=<V> dir=1' (574 uses in LTC.lib and the
    ADI op-amp macro-models, always dir=1): a one-sided clamp that conducts gm*(V(nc+,nc-)-vto)
    once the control voltage passes vto, and nothing below. Read from how the models use it
    (output-stage and input clamps); dir=-1 is taken as the mirror image. Rendered as a
    B source with the same C1 quadratic knee (1 mV) as the ideal diodes, without a leakage tail."""
    if len(tok) < 7:
        return None
    pos, params = _split_params(tok[5:])
    keys = {k.split("=", 1)[0].lower(): k.split("=", 1)[1] for k in params}
    if "vto" not in keys and "dir" not in keys or len(pos) != 1:
        return None
    if any(w in " ".join(tok).lower() for w in ("poly", "table", "laplace", "value")):
        return None
    gm = _value(pos[0])
    vto = _value(keys.get("vto", "0"))
    d = spicenum.parse(keys.get("dir", "1")) or 1
    x = f"V({tok[3]},{tok[4]})-({vto})"
    if d >= 0:
        expr = f"({gm})*{adevices._quad_knee(x, '1m')}"
    else:
        expr = f"-({gm})*{adevices._quad_knee(f'-({x})', '1m')}"
    return f"B{tok[0]} {tok[1]} {tok[2]} I={expr}"


def _load_current_source(tok, warnings):
    """'I n+ n- <value> [AC=..] load' (help: I. Current Source): a dissipative load. Constant
    current above 0.5 V across it, falling to zero at 0 V with a resistance of 0.25 V / value
    near zero. I0*tanh(V/0.25V) has exactly that slope and is within 4% of I0 at 0.5 V.
    Only constant values are handled; for other forms 'load' is dropped with a warning."""
    rest = [t for t in tok[3:] if t.lower() != "load"]
    ac = [t for t in rest if t.lower().startswith("ac=") or t.lower() == "ac"]
    vals = [t for t in rest if t not in ac]
    i0 = spicenum.parse(vals[0]) if len(vals) == 1 and not vals[0].startswith("{") else None
    if len(vals) == 1 and vals[0].startswith("{"):
        i0 = vals[0]
    if i0 is None or (isinstance(i0, float) and i0 <= 0):
        if i0 is None:
            warnings.append(f"{tok[0]}: 'load' ignored for a non-constant current source")
        return [" ".join(tok[:3] + rest)]
    v = _value(vals[0]) if isinstance(i0, str) else f"{i0:.12g}"
    out = [f"B{tok[0]} {tok[1]} {tok[2]} I=({v})*tanh(V({tok[1]},{tok[2]})/0.25)"]
    if ac:
        out.append(" ".join([tok[0], tok[1], tok[2], "0"] + ac))
    return out


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
    lines = convert_machines(join_continuations(text.replace("µ", "u").replace("μ", "u")))
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
            elif head in (".pz", ".disto"):
                # ngspice-only analyses (LTspice has neither); passed through unchanged
                tr.analysis = tr.analysis or head[1:]
                out.append(line)
            elif head in (".ac", ".op", ".noise", ".tf", ".dc"):
                tr.analysis = tr.analysis or head[1:]
                if head == ".dc" and len(tok) > 1 and tok[1].lower() in ("dec", "oct") or \
                        head == ".dc" and len(tok) > 3 and tok[2].lower() == "list":
                    # LTspice: '.dc dec V1 10u 10 10' / '.dc V1 list 1 2 5'; ngspice's .dc is
                    # linear only. The runner sweeps the source over .op runs instead.
                    spec = _parse_step(tok[1:])
                    if spec is None or spec.is_param:
                        tr.errors.append(f"Unsupported .dc sweep: {line}")
                    else:
                        tr.dc_sweep = spec
                    out.append(".op")
                    continue
                if head == ".dc":
                    tok = [t for t in tok if t.lower() != "lin"]
                    line = " ".join(tok)
                if head in (".ac", ".noise"):
                    line = _frequency_list(tok, tr)
                out.append(line)
            elif head in (".meas", ".measure") and not in_subckt:
                tr.measures.append(line)
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
            elif head == ".param":
                if not in_subckt:
                    for k, v in re.findall(r"(\w+)=(\{[^}]*\}|\S+)", line[6:]):
                        x = spicenum.parse(v)
                        if x is not None:
                            tr.params[k] = x
                out.append(line)
            elif head == ".model":
                if len(tok) >= 3:
                    mtype = re.match(r"(?:ako:\S+\s*)?([a-zA-Z]+)", tok[2])
                    defined_models[tok[1].lower()] = mtype.group(1).lower() if mtype else ""
                out.append(line)
            elif head == ".fra":
                tr.errors.append("LTspice's Frequency Response Analysis (.fra with @ probes) "
                                 "is not supported by TuxSpice")
            elif head in (".wave", ".net", ".probe", ".loadbias", ".savebias"):
                tr.warnings.append(f"{head} is not supported by ngspice and was ignored")
            else:
                out.append(line)
            continue

        letter = head[0]
        if letter == "@":
            out.append("* " + line)           # FRA probe; .fra reports the error
            continue
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
            if letter == "d" and any(t.lower().startswith("n=") for t in tok[4:]):
                out += _series_diodes(tok)
            else:
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

    out = rename_reserved_params(undot_subckt_names(rename_odd_element_names(out)))
    out = adevices.disambiguate_models(out)
    out = rewrite_device_currents(out)
    out = adevices.rewrite_switches(out)
    out = adevices.rewrite_vdmos(out)
    out = adevices.rewrite_ideal_diodes(out)
    out = adevices.rewrite_igbts(out, tr.warnings)
    out = declare_passed_params(out, passed)
    used = funcs_used("\n".join(out))
    # scan the rewritten copies (and their nested includes): rewrites can introduce helpers
    pending = re.findall(r'^\.include "([^"]+)"', "\n".join(out), re.M)
    scanned = set()
    while pending:
        inc = pending.pop()
        if inc in scanned:
            continue
        scanned.add(inc)
        used |= _lib_funcs(inc)
        try:
            pending += re.findall(r'^\.include "([^"]+)"', Path(inc).read_text(encoding="latin-1"), re.M)
        except OSError:
            pass
    for f in list(used):
        used |= FUNC_DEPS.get(f, set())
    func_defs = [LT_FUNCS[f] for f in LT_FUNCS if f in used]     # dict order = dependency order
    temps = [spicenum.parse(t) for l in out if l.lower().startswith(".temp")
             for t in l.split()[1:2]]
    lt_temp = temps[0] if temps and temps[0] is not None else 27
    smallsig = 1 if tr.analysis in ("ac", "noise") else 0
    body = [title, ".param pi=3.141592653589793", f".param lt_temp={lt_temp:g}",
            f".param lt_smallsig={smallsig}"] + func_defs + out + model_cards + [".options savecurrents", ".end"]
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
