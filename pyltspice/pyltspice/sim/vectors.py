"""LTspice-style names for ngspice vectors, and waveform arithmetic."""
import re

import numpy as np

_DEV_CURRENT = re.compile(r"^@([a-z0-9_.:]+)\[(\w+)\]$", re.I)
# ngspice device current names -> LTspice names (Ic, Ib, Ie, Id, Ig, Is...)
_CUR_PREFIX = {"i": "I", "ic": "Ic", "ib": "Ib", "ie": "Ie", "id": "Id", "ig": "Ig", "is": "Is"}


def lt_name(ng: str) -> str | None:
    """'v(n001)' -> 'V(n001)', 'v1#branch' -> 'I(V1)', '@q1[ic]' -> 'Ic(Q1)'.
    Returns None for vectors LTspice wouldn't show (internal device params)."""
    n = ng.strip()
    low = n.lower()
    if low in ("time", "frequency", "v-sweep", "i-sweep", "temp-sweep", "res-sweep"):
        return n
    m = re.match(r"^v\((.*)\)$", n, re.I)
    if m:
        return f"V({m.group(1).replace('.', ':')})"
    m = re.match(r"^i\((.*)\)$", n, re.I)
    if m:
        inner = m.group(1)
        if inner.startswith("@"):
            return lt_name(inner)
        return f"I({inner.upper().replace('.', ':')})"
    if low.endswith("#branch"):
        return f"I({n[:-7].upper().replace('.', ':')})"
    m = _DEV_CURRENT.match(n)
    if m:
        dev, q = m.group(1), m.group(2).lower()
        if q == "id" and dev.lower().rsplit(".", 1)[-1].startswith("d"):
            q = "i"           # diode current is I(D1) in LTspice
        if q in _CUR_PREFIX:
            return f"{_CUR_PREFIX[q]}({dev.upper().replace('.', ':')})"
        return None
    if "#" in n or "@" in n:
        return None
    if re.match(r"^[\w.:+-]+$", n):
        return f"V({n.replace('.', ':')})"
    return n


class VectorSet:
    """Name lookup over one plot, by LTspice-style name (case-insensitive)."""

    def __init__(self, plot):
        self.plot = plot
        self.by_name = {}
        for v in plot.variables[1:]:
            ln = lt_name(v.name)
            if ln:
                self.by_name.setdefault(ln.lower(), v.index)

    def names(self):
        out = []
        for v in self.plot.variables[1:]:
            ln = lt_name(v.name)
            if ln and self.by_name.get(ln.lower()) == v.index:
                out.append(ln)
        return out

    def get(self, name):
        i = self.by_name.get(name.lower())
        if i is None:
            # elements we replaced with equivalents: L1 -> BL1 (core) or VL1_s (Flux=)
            m = re.match(r"^I\(([^()]+)\)$", name.strip(), re.I)
            if m:
                for alias in (f"I(B{m.group(1)})", f"I(V{m.group(1)}_S)"):
                    j = self.by_name.get(alias.lower())
                    if j is not None:
                        return self.plot.data[j]
        if i is None:
            # V(a,b) differential
            m = re.match(r"^V\(([^,()]+),([^,()]+)\)$", name.strip(), re.I)
            if m:
                a, b = self.get(f"V({m.group(1)})"), self.get(f"V({m.group(2)})")
                if a is not None and b is not None:
                    return a - b
            return None
        return self.plot.data[i]

    @property
    def x(self):
        return self.plot.x

    # -- waveform arithmetic: "V(out)/V(in)", "V(a)*I(R1)", "db(V(out))"
    _FUNCS = {
        "abs": np.abs, "sqrt": np.sqrt, "exp": np.exp, "ln": np.log, "log": np.log,
        "log10": np.log10, "sin": np.sin, "cos": np.cos, "tan": np.tan, "atan": np.arctan,
        "re": np.real, "im": np.imag, "real": np.real, "imag": np.imag,
        "mag": np.abs, "ph": lambda z: np.degrees(np.angle(z)),
        "db": lambda z: 20 * np.log10(np.maximum(np.abs(z), 1e-300)),
        "min": np.minimum, "max": np.maximum, "pow": np.power,
        "pi": np.pi, "e": np.e,
    }

    def eval(self, expr: str):
        env = dict(self._FUNCS)
        env["time"] = env["frequency"] = self.x
        counter = [0]

        def sub(m):
            arr = self.get(m.group(0))
            if arr is None:
                raise KeyError(m.group(0))
            key = f"_v{counter[0]}"
            counter[0] += 1
            env[key] = arr
            return key

        py = re.sub(r"\b[IV][a-z]?\([^()]*\)", sub, expr, flags=re.I)
        py = py.replace("^", "**")
        if re.search(r"[^\w\s+\-*/().,]", py) or "__" in py:
            raise ValueError(f"Invalid expression: {expr}")
        return eval(py, {"__builtins__": {}}, env)  # noqa: S307 - restricted namespace


def unit_of(name: str) -> str:
    n = name.strip().upper()
    if n.startswith("V("):
        return "V"
    if n[:1] == "I" and "(" in n:
        return "A"
    if n in ("TIME",):
        return "s"
    if n == "FREQUENCY":
        return "Hz"
    return ""
