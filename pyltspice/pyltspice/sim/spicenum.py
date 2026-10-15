"""SPICE number parsing/formatting with LTspice suffix rules."""
import re

_SUFFIX = [("meg", 1e6), ("mil", 25.4e-6), ("f", 1e-15), ("p", 1e-12), ("n", 1e-9),
           ("u", 1e-6), ("µ", 1e-6), ("μ", 1e-6), ("m", 1e-3), ("k", 1e3),
           ("g", 1e9), ("t", 1e12)]
_NUM = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([a-zA-Zµμ]*)\s*$")


def parse(s: str) -> float | None:
    """'10K' -> 10000.0, '.01µ' -> 1e-8, '1Meg' -> 1e6; None if not a number."""
    m = _NUM.match(s)
    if not m:
        return None
    val = float(m.group(1))
    suf = m.group(2).lower()
    for name, mult in _SUFFIX:
        if suf.startswith(name):
            return val * mult
    return val


def fmt(v: float, unit: str = "", digits: int = 4) -> str:
    """Engineering notation the way LTspice displays it: 1.2345mV, 3.3K."""
    if v == 0:
        return f"0{unit}"
    prefixes = [(1e12, "T"), (1e9, "G"), (1e6, "Meg" if not unit else "M"), (1e3, "K" if not unit else "k"),
                (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p"), (1e-15, "f")]
    a = abs(v)
    for mult, p in prefixes:
        if a >= mult * 0.9995:
            s = f"{v / mult:.{digits}g}"
            return f"{s}{p}{unit}"
    return f"{v:.{digits}g}{unit}"
