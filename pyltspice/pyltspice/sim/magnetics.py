"""LTspice nonlinear inductors for ngspice.

1. Hysteretic core (Hc, Br, Bs + A, Lm, Lg, N): Chan et al., IEEE TCAD 10(4) 1991 major loop
       Bup(H) = Bs*(H-Hc)/(|H-Hc| + Hc*(Bs/Br-1)) + mu0*H
       Bdn(H) = Bs*(H+Hc)/(|H+Hc| + Hc*(Bs/Br-1)) + mu0*H
   Minor loops scale the active branch toward saturation: on a rising branch the core
   flux satisfies Bc = k*Bs + (1-k)*Bcu(H) with k constant, so the slope dB/dH can be
   computed from the present (B, H) alone. States B and H are capacitor voltages:
       dB/dt = V/(N*A),  dH/dt = (dB/dt)/g(B, H, sign V),  I = (H*Lm + B*Lg/mu0)/N
   The core starts demagnetised; DC current at the operating point is not modelled.
2. Behavioural flux inductor 'Flux=<expr of x>' where x is the inductor current:
   V = d(flux)/dt via ddt() on a sensed current."""
import re

from .adevices import num

MU0 = 4e-7 * 3.141592653589793


def _params(tokens):
    out = {}
    for t in tokens:
        k, eq, v = t.partition("=")
        if eq:
            out[k.lower()] = v
    return out


def is_core(tokens) -> bool:
    p = _params(tokens[3:])
    return "hc" in p and "bs" in p and "br" in p


def core_elements(tokens):
    name, a, b = tokens[:3]
    p = _params(tokens[3:])
    Hc, Bs, Br = num(p["hc"]), num(p["bs"]), num(p["br"])
    A, Lm = num(p.get("a", "1")), num(p.get("lm", "1"))
    Lg, N = num(p.get("lg", "0")), num(p.get("n", "1"))
    nb, nh = f"{name}_B", f"{name}_H"
    alpha = f"({Hc}*({Bs}/{Br}-1))"
    H, B = f"V({nh})", f"V({nb})"
    Bc = f"({B}-{MU0:.10g}*{H})"                         # core part of the flux density
    bcu = f"({Bs}*({H}-{Hc})/(abs({H}-{Hc})+{alpha}))"
    bcd = f"({Bs}*({H}+{Hc})/(abs({H}+{Hc})+{alpha}))"
    ku = f"max(min(({Bc}-{bcu})/({Bs}-{bcu}),0.999),-1)"
    kd = f"max(min(({Bc}-{bcd})/(-{Bs}-{bcd}),0.999),-1)"
    gu = f"((1-{ku})*{Bs}*{alpha}/(abs({H}-{Hc})+{alpha})**2+{MU0:.10g})"
    gd = f"((1-{kd})*{Bs}*{alpha}/(abs({H}+{Hc})+{alpha})**2+{MU0:.10g})"
    v = f"V({a},{b})"
    bdot = f"({v}/({N}*{A}))"
    return [
        f"B{name}_b 0 {nb} I={bdot}",
        f"C{name}_b {nb} 0 1",
        f"R{name}_b {nb} 0 1e12",
        f"B{name}_h 0 {nh} I={bdot}/({v}>=0 ? {gu} : {gd})",
        f"C{name}_h {nh} 0 1",
        f"R{name}_h {nh} 0 1e12",
        f"B{name} {a} {b} I=({H}*{Lm}+{B}*{Lg}/{MU0:.10g})/{N}",
    ]


def is_flux(line: str) -> bool:
    return re.search(r"(?i)\bflux\s*=", line) is not None


def flux_elements(line: str):
    """L1 a b Flux=<expr in x>  ->  sense source + B source V=ddt(flux(I))."""
    m = re.match(r"(?i)\s*(\S+)\s+(\S+)\s+(\S+)\s+flux\s*=\s*(.+)$", line)
    if not m:
        return None
    name, a, b, expr = m.groups()
    expr = expr.strip().strip("{}")
    mid = f"{name}_m"
    expr = re.sub(r"\bx\b", f"I(V{name}_s)", expr)
    return [f"V{name}_s {a} {mid} 0", f"B{name} {mid} {b} V=ddt({expr})"]
