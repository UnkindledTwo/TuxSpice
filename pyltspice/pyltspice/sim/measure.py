""".meas/.measure evaluated in Python on the simulation results (LTspice semantics).

Supported:
  .meas [TRAN|AC|DC|NOISE] name FIND expr AT=x
  .meas ... name FIND expr WHEN lhs=rhs [TD=t] [RISE|FALL|CROSS=n|LAST]
  .meas ... name WHEN lhs=rhs [...]                      (result: the x value)
  .meas ... name DERIV expr AT=x | WHEN ...
  .meas ... name AVG|MAX|MIN|PP|RMS|INTEG expr [FROM=x] [TO=x] [TRIG ... TARG ...]
  .meas ... name TRIG lhs=rhs [TD] [RISE..] TARG lhs=rhs [TD] [RISE..]   (result: x difference)
  .meas ... name PARAM expr
Earlier results can be used by name in later expressions, as in LTspice."""
import math
import re

import numpy as np

from . import spicenum
from .vectors import VectorSet

ANALYSES = {"tran": "tran", "ac": "ac", "dc": "dc", "noise": "noise", "op": "op", "tf": "tf"}
_SCALAR_FUNCS = {"sqrt": math.sqrt, "abs": abs, "exp": math.exp, "ln": math.log, "log": math.log,
                 "log10": math.log10, "sin": math.sin, "cos": math.cos, "tan": math.tan,
                 "atan": math.atan, "min": min, "max": max, "pow": pow, "pi": math.pi}


class MeasError(ValueError):
    pass


def _tokens(body):
    """Split on whitespace, but keep 'a = b', '(..)' and '{..}' together."""
    body = re.sub(r"\s*=\s*", "=", body)
    out, depth, cur = [], 0, ""
    for ch in body:
        depth += (ch in "({") - (ch in ")}")
        if ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def parse(line: str):
    tok = _tokens(line.strip())
    if not tok or tok[0].lower() not in (".meas", ".measure"):
        return None
    tok = tok[1:]
    analysis = None
    if tok and tok[0].lower() in ANALYSES:
        analysis = ANALYSES[tok.pop(0).lower()]
    if not tok:
        return None
    return {"analysis": analysis, "name": tok[0], "rest": tok[1:], "text": line.strip()}


class Context:
    def __init__(self, plot, results, params):
        self.vs = VectorSet(plot)
        self.x = np.real(plot.x) if not plot.is_complex else plot.x.real
        self.is_ac = plot.is_complex
        self.results = results           # name -> value (earlier .meas)
        self.params = params             # .param values that are plain numbers

    def scalar(self, expr: str) -> float:
        expr = expr.strip().strip("{}").strip("'\"")
        v = spicenum.parse(expr)
        if v is not None:
            return v
        env = dict(_SCALAR_FUNCS)
        env.update({k.lower(): v for k, v in self.params.items()})
        env.update({k.lower(): v for k, v in self.results.items()})
        py = expr.replace("^", "**")
        py = re.sub(r"(?<![\w.])(\d+\.?\d*|\.\d+)(meg|[fpnumkgt])\b",
                    lambda m: repr(spicenum.parse(m.group(0))), py, flags=re.I)
        if re.search(r"[^\w\s+\-*/().,]", py) or "__" in py:
            raise MeasError(f"cannot evaluate '{expr}'")
        try:
            return float(eval(py.lower(), {"__builtins__": {}}, env))  # noqa: S307
        except Exception as e:  # noqa: BLE001
            raise MeasError(f"cannot evaluate '{expr}': {e}") from None

    def wave(self, expr: str):
        """Waveform of an expression, real-valued (AC: as written, e.g. mag(), else |.|)."""
        expr = expr.strip().strip("{}")
        if expr.lower() in ("time", "frequency"):
            return self.x
        for k, v in self.results.items():   # earlier results usable as constants
            expr = re.sub(rf"(?<![\w(]){re.escape(k)}(?![\w(])", repr(float(v)), expr, flags=re.I)
        try:
            y = self.vs.eval(re.sub(r"(?i)\bmag\(", "abs(", expr))
        except Exception:
            return np.full_like(self.x, self.scalar(expr), dtype=float)
        y = np.broadcast_to(np.asarray(y), self.x.shape)
        if np.iscomplexobj(y):
            y = np.abs(y)
        return np.asarray(y, dtype=float)


def _opts(tokens):
    """key=value options (lower-case keys) and remaining positional tokens."""
    kv, pos = {}, []
    for t in tokens:
        k, eq, v = t.partition("=")
        if eq and k.lower() in ("at", "td", "rise", "fall", "cross", "from", "to", "val"):
            kv[k.lower()] = v
        else:
            pos.append(t)
    return kv, pos


def _crossings(x, y, level, kind):
    """x positions where y crosses level; kind rise/fall/cross."""
    d = y - level
    out = []
    for i in range(len(d) - 1):
        a, b = d[i], d[i + 1]
        if a == b:
            continue
        up = a < 0 <= b
        down = a > 0 >= b
        if (kind == "rise" and up) or (kind == "fall" and down) or (kind == "cross" and (up or down)):
            out.append(x[i] + (x[i + 1] - x[i]) * (-a) / (b - a))
    return out


def _when(ctx, cond_tokens):
    """'lhs=rhs [TD=t] [RISE=n|FALL=n|CROSS=n|LAST]' -> x where it happens."""
    kv, pos = _opts(cond_tokens)
    if not pos:
        raise MeasError("missing condition")
    cond = pos[0]
    if "val" in kv:
        lhs, rhs = cond, kv["val"]
    else:
        if "=" not in cond:
            raise MeasError(f"bad condition '{cond}'")
        lhs, _, rhs = cond.partition("=")
    y = ctx.wave(lhs) - ctx.wave(rhs)
    x = ctx.x
    td = ctx.scalar(kv["td"]) if "td" in kv else None
    if td is not None:
        m = x >= td
        x, y = x[m], y[m]
    kind, n = "cross", "1"
    for k in ("rise", "fall", "cross"):
        if k in kv:
            kind, n = k, kv[k]
    pts = _crossings(x, y, 0.0, kind)
    if not pts:
        raise MeasError("condition never met")
    if n.lower() == "last":
        return pts[-1]
    i = int(ctx.scalar(n))
    if i < 1 or i > len(pts):
        raise MeasError(f"only {len(pts)} {kind} event(s)")
    return pts[i - 1]


def _split_trig_targ(rest):
    low = [t.lower() for t in rest]
    ti = low.index("trig") if "trig" in low else None
    gi = low.index("targ") if "targ" in low else None
    return ti, gi


def evaluate(m, ctx: Context):
    rest = m["rest"]
    if not rest:
        raise MeasError("empty .meas")
    kw = rest[0].lower()
    if kw == "param":
        return ctx.scalar(" ".join(rest[1:])), None
    if kw in ("find", "deriv"):
        expr = rest[1]
        low = [t.lower() for t in rest]
        y = ctx.wave(expr)
        if kw == "deriv":
            y = np.gradient(y, ctx.x)
        if "when" in low:
            x0 = _when(ctx, rest[low.index("when") + 1:])
        else:
            kv, _ = _opts(rest[2:])
            if "at" not in kv:
                raise MeasError("FIND needs AT= or WHEN")
            x0 = ctx.scalar(kv["at"])
        return float(np.interp(x0, ctx.x, y)), x0
    if kw == "when":
        x0 = _when(ctx, rest[1:])
        return x0, x0
    ti, gi = _split_trig_targ(rest)
    if kw in ("avg", "max", "min", "pp", "rms", "integ"):
        expr = rest[1]
        y, x = ctx.wave(expr), ctx.x
        kv, _ = _opts(rest[2:ti] if ti else rest[2:])
        lo = ctx.scalar(kv["from"]) if "from" in kv else x[0]
        hi = ctx.scalar(kv["to"]) if "to" in kv else x[-1]
        if ti is not None and gi is not None:
            lo, hi = _when(ctx, rest[ti + 1:gi]), _when(ctx, rest[gi + 1:])
        m_ = (x >= lo) & (x <= hi)
        xs, ys = x[m_], y[m_]
        if len(xs) < 1:
            raise MeasError("empty interval")
        if kw == "max":
            return float(ys.max()), float(xs[np.argmax(ys)])
        if kw == "min":
            return float(ys.min()), float(xs[np.argmin(ys)])
        if kw == "pp":
            return float(ys.max() - ys.min()), None
        span = xs[-1] - xs[0] if len(xs) > 1 else 0.0
        integ = float(np.trapezoid(ys, xs)) if len(xs) > 1 else 0.0
        if kw == "integ":
            return integ, None
        if kw == "avg":
            return (integ / span if span else float(ys[0])), None
        return (math.sqrt(float(np.trapezoid(ys * ys, xs)) / span) if span else abs(float(ys[0]))), None
    if kw == "trig" or (ti is not None and gi is not None):
        t0 = _when(ctx, rest[(ti or 0) + 1:gi])
        t1 = _when(ctx, rest[gi + 1:])
        return t1 - t0, None
    raise MeasError(f"unsupported .meas form '{rest[0]}'")


def run_measures(measures, plots, params=None, table=None):
    """measures: parsed dicts. plots: list of rawfile.Plot (one per analysis).
    Returns list of (name, text) in LTspice log style; stepped plots give one row per step.
    `table`, if given, receives {name: [(step label, value or None)]} (for histograms)."""
    params = params or {}
    out = []
    results = {}
    by_analysis = {p.analysis: p for p in plots}
    for m in measures:
        plot = by_analysis.get(m["analysis"]) if m["analysis"] else next(
            (p for p in plots if p.analysis != "op"), plots[0] if plots else None)
        if plot is None:
            out.append((m["name"], "skipped (no matching analysis)"))
            continue
        steps = plot.step_bounds or [(0, plot.data.shape[1])]
        labels = plot.step_labels or [""] * len(steps)
        rows = []
        for (a, b), label in zip(steps, labels):
            sub = _slice(plot, a, b)
            ctx = Context(sub, results, params)
            try:
                val, at = evaluate(m, ctx)
                txt = f"{val:.6g}" + (f" at {at:.6g}" if at is not None and m["rest"][0].lower() != "when" else "")
            except MeasError as e:
                val, txt = None, f"FAIL ({e})"
            rows.append((label, val, txt))
        if table is not None:
            table[m["name"]] = [(label, val) for label, val, _ in rows]
        if rows and rows[0][1] is not None:
            results[m["name"].lower()] = rows[-1][1] if len(rows) == 1 else rows[0][1]
        for label, _, txt in rows:
            out.append((m["name"], f"{txt}" + (f"   [{label}]" if label else "")))
    return out


def _slice(plot, a, b):
    from .rawfile import Plot
    p = Plot(plot.title, plot.plotname, set(plot.flags), list(plot.variables))
    p.data = plot.data[:, a:b]
    return p
