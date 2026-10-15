"""LTspice 'Laplace=' sources -> plain ngspice elements (integrator chain).

Only rational functions of s are supported: numbers, {param expressions}, bare parameter
names, s, + - * /, and integer powers (** or ^). Coefficients that involve parameters are
kept as brace expressions, which ngspice's numparam evaluates. XSPICE s_xfer is not used
because it takes its DC state from int_ic instead of solving the operating point."""
import re

from . import spicenum


class Unsupported(ValueError):
    pass


# ---------------------------------------------------------------- coefficient arithmetic
# A coefficient is a float or an expression string.

def _c(x):
    return x if isinstance(x, str) else repr(float(x))


def cadd(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return a + b
    if a == 0.0:
        return b
    if b == 0.0:
        return a
    return f"({_c(a)}+{_c(b)})"


def cneg(a):
    return -a if isinstance(a, float) else f"(-{a})"


def cmul(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return a * b
    if a == 0.0 or b == 0.0:
        return 0.0
    if a == 1.0:
        return b
    if b == 1.0:
        return a
    return f"({_c(a)}*{_c(b)})"


def cdiv(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return a / b
    if b == 1.0:
        return a
    return f"({_c(a)}/{_c(b)})"


# ---------------------------------------------------------------- polynomials (ascending)

def padd(p, q):
    n = max(len(p), len(q))
    p = p + [0.0] * (n - len(p))
    q = q + [0.0] * (n - len(q))
    return [cadd(a, b) for a, b in zip(p, q)]


def pmul(p, q):
    out = [0.0] * (len(p) + len(q) - 1)
    for i, a in enumerate(p):
        for j, b in enumerate(q):
            out[i + j] = cadd(out[i + j], cmul(a, b))
    return out


class RF:
    """Rational function num(s)/den(s), times an optional pure delay exp(-s*delay)."""

    def __init__(self, num, den=None, delay=0.0):
        self.num, self.den, self.delay = num, den or [1.0], delay

    def _same_delay(self, o):
        if self.delay != o.delay:
            raise Unsupported("sums of differently delayed terms are not supported")
        return self.delay

    def __add__(self, o):
        d = self._same_delay(o)
        return RF(padd(pmul(self.num, o.den), pmul(o.num, self.den)), pmul(self.den, o.den), d)

    def __sub__(self, o):
        return self + RF([cneg(c) for c in o.num], o.den, o.delay)

    def __mul__(self, o):
        return RF(pmul(self.num, o.num), pmul(self.den, o.den), cadd(self.delay, o.delay))

    def __truediv__(self, o):
        if o.delay != 0.0:
            raise Unsupported("dividing by a delay (negative delay) is not supported")
        return RF(pmul(self.num, o.den), pmul(self.den, o.num), self.delay)

    def __pow__(self, n):
        if n < 0:
            return RF([1.0]) / (self ** -n)
        r = RF([1.0])
        for _ in range(n):
            r = r * self
        return r


# ---------------------------------------------------------------- parser

_TOKEN = re.compile(r"\s*(\{[^}]*\}|\*\*|[-+*/^()]|[A-Za-z_]\w*|(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?[A-Za-zµ]*)")


def _tokens(expr):
    pos, out = 0, []
    expr = expr.strip()
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            raise Unsupported(f"cannot parse Laplace expression near '{expr[pos:pos + 10]}'")
        out.append(m.group(1))
        pos = m.end()
    return out


class _Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expr(self):
        v = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            r = self.term()
            v = v + r if op == "+" else v - r
        return v

    def term(self):
        v = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()
            r = self.unary()
            v = v * r if op == "*" else v / r
        return v

    def unary(self):
        if self.peek() == "-":
            self.take()
            return RF([-1.0]) * self.unary()
        if self.peek() == "+":
            self.take()
        return self.power()

    def power(self):
        base = self.atom()
        if self.peek() in ("**", "^"):
            self.take()
            tok = self.take()
            neg = False
            if tok == "-":
                neg, tok = True, self.take()
            n = spicenum.parse(tok or "")
            if n is None or n != int(n):
                raise Unsupported("only integer powers are supported in Laplace expressions")
            return base ** (-int(n) if neg else int(n))
        return base

    def atom(self):
        tok = self.take()
        if tok is None:
            raise Unsupported("unexpected end of Laplace expression")
        if tok == "(":
            v = self.expr()
            if self.take() != ")":
                raise Unsupported("unbalanced parentheses in Laplace expression")
            return v
        if tok.lower() == "s":
            return RF([0.0, 1.0])
        if tok.startswith("{"):
            return RF([f"({tok[1:-1]})"])
        x = spicenum.parse(tok)
        if x is not None:
            return RF([x])
        if re.match(r"[A-Za-z_]\w*$", tok):
            if self.peek() == "(" and tok.lower() == "exp":
                self.take()
                arg = self.expr()
                if self.take() != ")":
                    raise Unsupported("unbalanced parentheses in Laplace expression")
                # exp(-T*s): a pure delay of T
                num, den = _trim(arg.num), _trim(arg.den)
                if arg.delay != 0.0 or den != [1.0] or len(num) != 2 or num[0] != 0.0:
                    raise Unsupported("exp() in Laplace= must be a pure delay exp(-T*s)")
                return RF([1.0], delay=cneg(num[1]))
            if self.peek() == "(" and tok.lower() == "sqrt":
                self.take()
                arg = self.expr()
                if self.take() != ")":
                    raise Unsupported("unbalanced parentheses in Laplace expression")
                return sqrt_ladder(arg)
            if self.peek() == "(":
                raise Unsupported(f"function {tok}() is not supported in Laplace expressions")
            return RF([f"({tok})"])
        raise Unsupported(f"unexpected '{tok}' in Laplace expression")


SQRT_DECADES = 5          # band above the corner covered by the sqrt() approximation
SQRT_STEP = 10 ** 0.25   # zero/pole spacing: a quarter decade


def sqrt_ladder(arg: RF) -> RF:
    """sqrt(c0 + c1*s) as alternating real zeros and poles (quarter-decade spacing), the
    usual half-order approximation: +10 dB/decade above the corner, within ~0.1 dB over
    SQRT_DECADES decades. Only numeric first-order arguments are supported."""
    num, den = _trim(arg.num), _trim(arg.den)
    if arg.delay != 0.0 or den != [1.0] or len(num) != 2 \
            or not all(isinstance(c, float) for c in num) or num[0] <= 0 or num[1] <= 0:
        raise Unsupported("sqrt() in Laplace= is only supported as sqrt(a + b*s) with positive numbers")
    c0, c1 = num
    w = c0 / c1                                    # corner (rad/s)
    out = RF([c0 ** 0.5])
    k = 0
    while k < 4 * SQRT_DECADES:
        # starting half a step above the corner gives ~0.1 dB error over the band
        z, p_ = w * SQRT_STEP ** (k + 0.5), w * SQRT_STEP ** (k + 1.5)
        out = out * RF([1.0, 1.0 / z], [1.0, 1.0 / p_])
        k += 2
    return out


def parse(expr: str) -> RF:
    p = _Parser(_tokens(expr))
    v = p.expr()
    if p.peek() is not None:
        raise Unsupported(f"unexpected '{p.peek()}' in Laplace expression")
    return v


def _trim(poly):
    while len(poly) > 1 and poly[-1] == 0.0:
        poly = poly[:-1]
    return poly


def _b(c):
    """Coefficient as text for a B-source expression."""
    return f"{{{c}}}" if isinstance(c, str) else f"({c:.12g})"


def to_elements(name, out_p, out_n, in_p, in_n, expr, current=False):
    """Lines implementing out = H(s) * V(in_p, in_n) (voltage, or current for G).

    Built from plain elements in controllable canonical form so SPICE solves DC, AC and
    transient consistently: states z1..zn are capacitor voltages, time scaled by
    T = (a_n/a_0)^(1/n) so the states stay near the size of the input."""
    rf = parse(expr)
    num, den = _trim(rf.num), _trim(rf.den)
    if len(num) > len(den):
        raise Unsupported("Laplace numerator degree exceeds denominator degree")
    n = len(den) - 1
    el = "G" if current else "E"
    u = f"V({in_p},{in_n})"
    lines = []
    if rf.delay != 0.0:
        # ideal delay: a lossless line driven by a voltage source, terminated in Z0
        d = f"{rf.delay:.12g}" if isinstance(rf.delay, float) else f"{{{rf.delay}}}"
        lines += [f"E{name}_dly {name}_di 0 {in_p} {in_n} 1",
                  f"T{name}_dly {name}_di 0 {name}_do 0 Z0=1 TD={d}",
                  f"R{name}_dly {name}_do 0 1"]
        in_p, in_n = f"{name}_do", "0"
        u = f"V({in_p})"
    if n == 0:
        return lines + [f"{el}{name} {out_p} {out_n} {in_p} {in_n} {{{_c(cdiv(num[0], den[0]))}}}"]
    a0, an = den[0], den[n]
    if a0 == 0.0:
        T = 1.0
    elif isinstance(a0, float) and isinstance(an, float):
        T = abs(an / a0) ** (1.0 / n)
    else:
        T = f"(abs(({_c(an)})/({_c(a0)}))**(1.0/{n}))"
    # coefficients in scaled time p = s*T: a_i' = a_i / T^i
    def scaled(c, i):
        t = T ** i if isinstance(T, float) else (f"({T}**{i})" if i else 1.0)
        return cdiv(c, t)
    a = [scaled(c, i) for i, c in enumerate(den)]
    b = [scaled(c, i) for i, c in enumerate(num)] + [0.0] * (n + 1 - len(num))
    an_ = a[n]
    z = [f"{name}_z{k}" for k in range(1, n + 1)]
    cap = f"{{{T}}}" if isinstance(T, str) else f"{T:.12g}"
    for k in range(n):
        if k < n - 1:
            deriv = f"V({z[k + 1]})"
        else:
            terms = " - ".join([f"{_b(a[i])}*V({z[i]})" for i in range(n)])
            deriv = f"({u} - {terms})/{_b(an_)}"
        lines += [f"B{name}_d{k + 1} 0 {z[k]} I={deriv}",
                  f"C{name}_z{k + 1} {z[k]} 0 {cap}",
                  f"R{name}_z{k + 1} {z[k]} 0 1e15"]
    out_terms = [f"{_b(cadd(b[i], cneg(cdiv(cmul(b[n], a[i]), an_))))}*V({z[i]})" for i in range(n)]
    if b[n] != 0.0:
        out_terms.append(f"{_b(cdiv(b[n], an_))}*{u}")
    kind = "I" if current else "V"
    lines.append(f"B{name} {out_p} {out_n} {kind}={' + '.join(out_terms)}")
    return lines
