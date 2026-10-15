"""Emulation of LTspice's proprietary 8-terminal A-devices in ngspice.

Terminal roles come from the pin names in lib/sym (Digital/*.asy, SpecialFunctions/*.asy);
behaviour and defaults from the bundled help page "A. Special Functions".

- OTA (also OTA2/MOTA*): behavioral B-source transconductor.
- AND/OR/XOR/BUF, DFLOP, SRFLOP: XSPICE digital models behind adc/dac bridges, so
  propagation delay (Td) and edge triggering behave like LTspice.
- SCHMITT, SAMPLEHOLD, MODULATOR, VARISTOR: behavioral approximations.

Unused terminals are tied to terminal 8 (com) by the netlister; a terminal equal to
com is treated as absent, as LTspice does.
"""
import re

from . import spicenum

GATES = {"and": "d_and", "or": "d_or", "xor": "d_xor", "buf": "d_buffer", "inv": "d_buffer"}
SUPPORTED = set(GATES) | {"ota", "dflop", "srflop", "schmitt", "schmtbuf", "schmtinv",
                          "samplehold", "modulator", "modulate", "modulate2", "varistor",
                          "phasedet", "phidet"}
UNSUPPORTED = {"counter", "diffschmitt", "diffschmtbuf", "diffschmtinv"}


def num(v: str) -> str:
    """Parameter value usable inside expressions: plain number or {expression}."""
    v = v.strip()
    x = spicenum.parse(v)
    if x is not None:
        return f"{x:.12g}"
    return "{" + v.strip("{}") + "}"


def _fnum(v, default):
    """Numeric value if known (for .model lines that need numbers), else default."""
    x = spicenum.parse(v) if isinstance(v, str) else v
    return default if x is None else x


def parse_params(tokens):
    params, flags = {}, set()
    for t in tokens:
        if "=" in t:
            k, _, v = t.partition("=")
            params[k.lower()] = v
        else:
            flags.add(t.lower())
    return params, flags


def is_ltspice_adevice(tok) -> bool:
    """An LTspice A-device line: name + 8 nodes + a known model keyword."""
    return len(tok) >= 10 and tok[9].lower() in (SUPPORTED | UNSUPPORTED)


def expand(tok, warnings: list) -> list[str] | None:
    """Rewrite one A-device line (already tokenized) into ngspice lines.
    Returns None if the device type cannot be emulated."""
    name = tok[0]
    nodes = tok[1:9]
    model = tok[9].lower()
    params, flags = parse_params(tok[10:])
    if model == "ota":
        return _ota(name, nodes, params, flags)
    if model in GATES:
        return _gate(name, nodes, model, params)
    if model == "dflop":
        return _dflop(name, nodes, params)
    if model == "srflop":
        return _srflop(name, nodes, params)
    if model in ("schmitt", "schmtbuf", "schmtinv"):
        return _schmitt(name, nodes, params)
    if model == "samplehold":
        return _samplehold(name, nodes, params)
    if model in ("modulator", "modulate", "modulate2"):
        return _modulator(name, nodes, params)
    if model == "varistor":
        return _varistor(name, nodes, params)
    if model in ("phasedet", "phidet"):
        return _phasedet(name, nodes, params)
    return None


# ---------------------------------------------------------------- analog helpers

def _sig(x):
    """Smooth step 0..1 (tanh form never overflows)."""
    return f"(0.5*(1+tanh({x})))"


def _latch(name, tag, vin, vt, vh, tau=1e-8):
    """Comparator with hysteresis: a state node s in 0..1 that heads for 1 when
    vin > vt+vh (or > vt-vh once already high). Transitions are smooth (tanh) so the
    simulator's time step doesn't collapse. Returns (lines, state node)."""
    s = f"{name}_{tag}"
    w = f"(max(abs({vh})/10,1m))"                         # width of the decision region
    thr = f"({vt}+({vh})*(1-2*{_sig(f'(V({s})-0.5)*20')}))"
    target = _sig(f"(({vin})-{thr})/{w}")
    return [f"B{name}_{tag} 0 {s} I=({target}-V({s}))*1e-3",
            f"C{name}_{tag} {s} 0 {tau * 1e-3:.6g}",
            f"R{name}_{tag} {s} 0 1e12"], s


def _out_stage(name, target_expr, out, com, params, suffix=""):
    """Drive `out` toward target (volts rel. com) through Rout, plus Cout/Tau."""
    rout = num(params.get("rout", "1"))
    lines = [f"B{name}_o{suffix} {com} {out} I=(({target_expr})-V({out},{com}))/{rout}"]
    if "tau" in params:
        lines.append(f"C{name}_t{suffix} {out} {com} {{({params['tau'].strip('{}')})/({rout.strip('{}')})}}")
    if "cout" in params:
        lines.append(f"C{name}_c{suffix} {out} {com} {num(params['cout'])}")
    return lines


def _levels(params):
    vhigh = num(params.get("vhigh", "1"))
    vlow = num(params.get("vlow", "0"))
    return vhigh, vlow


# ---------------------------------------------------------------- OTA

def _ota(name, n, params, flags):
    n1, n2, n3, n4, n5, n6, n7, n8 = n
    if n7 == n8:
        return []          # output tied to com: a noise-only instance, nothing to simulate
    g = num(params.get("g", "1"))
    ref = num(params.get("ref", "0"))
    vd = f"(V({n2},{n1})+{ref})"
    mult = f"*V({n3},{n4})" if (n3 != n8 or n4 != n8) else ""
    x = f"({g}*{vd}{mult})"
    has_iout = "iout" in params
    iout = num(params.get("iout", "10u"))
    isink = num(params["isink"]) if "isink" in params else f"(-{iout})"
    if "linear" in flags:
        expr = f"max(min({x},{iout}),{isink})" if has_iout or "isink" in params else x
    else:
        expr = f"({x}>0 ? {iout}*tanh({x}/{iout}) : abs({isink})*tanh({x}/abs({isink})))"
    lines = [f"B{name} {n8} {n7} I={expr}"]
    if "rout" in params:
        lines.append(f"R{name}_out {n7} {n8} {num(params['rout'])}")
    if "cout" in params:
        lines.append(f"C{name}_out {n7} {n8} {num(params['cout'])}")
    rclamp = num(params.get("rclamp", "1"))
    vhigh = params.get("vhigh", "2")
    vlow = params.get("vlow", "0")
    if _fnum(vhigh, 0) < 1e300 or _fnum(vlow, 0) > -1e300:
        vo = f"V({n7},{n8})"
        lines.append(f"B{name}_clamp {n7} {n8} I=({vo}>{num(vhigh)} ? ({vo}-{num(vhigh)})/{rclamp} : "
                     f"({vo}<{num(vlow)} ? ({vo}-{num(vlow)})/{rclamp} : 0))")
    if n5 != n8:       # supply rails limit the output
        lines.append(f"B{name}_rl {n7} {n5} I=(V({n7},{n5})<0 ? V({n7},{n5})/{rclamp} : 0)")
    if n6 != n8:
        lines.append(f"B{name}_rh {n7} {n6} I=(V({n7},{n6})>0 ? V({n7},{n6})/{rclamp} : 0)")
    return lines


# ---------------------------------------------------------------- digital (XSPICE)

def _delay(params):
    td = _fnum(params.get("td", "0"), 0.0)
    return max(td, 1e-12)


def _adc(name, analog_nodes, com, vth, tag="in"):
    """Analog inputs (rel. com) -> digital nodes. Returns (lines, digital node names)."""
    lines, dnodes = [], []
    srcs = []
    for k, a in enumerate(analog_nodes):
        if com != "0":
            ref = f"{name}_{tag}{k}a"
            lines.append(f"B{name}_{tag}{k} {ref} 0 V=V({a},{com})")
            a = ref
        srcs.append(a)
        dnodes.append(f"{name}_{tag}{k}d")
    lines.append(f"A{name}_{tag}adc [{' '.join(srcs)}] [{' '.join(dnodes)}] {name}_{tag}adcm")
    lines.append(f".model {name}_{tag}adcm adc_bridge(in_low={vth} in_high={vth})")
    return lines, dnodes


def _dac(name, outputs, com, params):
    """Digital nodes -> analog outputs. outputs: [(digital node, analog out node)]."""
    vhigh, vlow = _levels(params)
    tr = _fnum(params.get("trise", "1e-9"), 1e-9) or 1e-9
    tf = _fnum(params.get("tfall", params.get("trise", "1e-9")), 1e-9) or 1e-9
    lines = []
    dn = [d for d, _ in outputs]
    an = [f"{name}_o{k}a" for k in range(len(outputs))]
    lines.append(f"A{name}_dac [{' '.join(dn)}] [{' '.join(an)}] {name}_dacm")
    lines.append(f".model {name}_dacm dac_bridge(out_low={_fnum(vlow, 0)} out_high={_fnum(vhigh, 1)} "
                 f"t_rise={tr:.6g} t_fall={tf:.6g})")
    for k, (_, out) in enumerate(outputs):
        lines += _out_stage(name, f"V({an[k]})", out, com, params, suffix=str(k))
    return lines


def _vth(params):
    if "ref" in params:
        return _fnum(params["ref"], 0.5)
    return (_fnum(params.get("vhigh", "1"), 1) + _fnum(params.get("vlow", "0"), 0)) / 2


def _gate(name, n, model, params):
    com = n[7]
    ins = [x for x in n[:5] if x != com]
    if not ins:
        return []
    lines, d = _adc(name, ins, com, _vth(params))
    td = _delay(params)
    q = f"{name}_q"
    if len(ins) == 1 or model in ("buf", "inv"):
        lines.append(f"A{name}_g {d[0]} {q} {name}_gm")
        lines.append(f".model {name}_gm d_buffer(rise_delay={td:.6g} fall_delay={td:.6g})")
    else:
        lines.append(f"A{name}_g [{' '.join(d)}] {q} {name}_gm")
        lines.append(f".model {name}_gm {GATES[model]}(rise_delay={td:.6g} fall_delay={td:.6g})")
    return lines + _outputs(name, q, n[5], n[6], com, params)


def _outputs(name, q, nq_bar, nq, com, params):
    lines, outs = [], []
    if nq != com:
        outs.append((q, nq))
    if nq_bar != com:
        qb = f"{name}_qb"
        lines.append(f"A{name}_inv {q} {qb} {name}_invm")
        lines.append(f".model {name}_invm d_inverter(rise_delay=1e-12 fall_delay=1e-12)")
        outs.append((qb, nq_bar))
    return lines + (_dac(name, outs, com, params) if outs else [])


def _const_zero(name, com):
    """A digital node held at logic 0."""
    z = f"{name}_zero"
    return [f"A{name}_z0 [0] [{z}] {name}_z0m",
            f".model {name}_z0m adc_bridge(in_low=0.5 in_high=0.5)"], z


def _dflop(name, n, params):
    d_in, _, clk, pre, clr, nqb, nq, com = n
    td = _delay(params)
    used = [d_in, clk] + [x for x in (pre, clr) if x != com]
    lines, dig = _adc(name, used, com, _vth(params))
    dmap = dict(zip(used, dig))
    zl, zero = _const_zero(name, com)
    lines += zl
    q = f"{name}_q"
    lines.append(f"A{name}_ff {dmap[d_in]} {dmap[clk]} {dmap.get(pre, zero) if pre != com else zero} "
                 f"{dmap.get(clr, zero) if clr != com else zero} {q} {name}_nq {name}_ffm")
    lines.append(f".model {name}_ffm d_dff(clk_delay={td:.6g} set_delay={td:.6g} reset_delay={td:.6g} "
                 "rise_delay=1e-12 fall_delay=1e-12)")
    return lines + _outputs(name, q, nqb, nq, com, params)


def _srflop(name, n, params):
    s, r, *_rest = n
    nqb, nq, com = n[5], n[6], n[7]
    td = _delay(params)
    lines, dig = _adc(name, [s, r], com, _vth(params))
    zl, zero = _const_zero(name, com)
    lines += zl
    one = f"{name}_one"
    lines.append(f"A{name}_one {zero} {one} {name}_onem")
    lines.append(f".model {name}_onem d_inverter(rise_delay=1e-12 fall_delay=1e-12)")
    q = f"{name}_q"
    lines.append(f"A{name}_sr {dig[0]} {dig[1]} {one} {zero} {zero} {q} {name}_nq {name}_srm")
    lines.append(f".model {name}_srm d_srlatch(sr_delay={td:.6g} enable_delay={td:.6g} "
                 "set_delay=1e-12 reset_delay=1e-12 rise_delay=1e-12 fall_delay=1e-12)")
    return lines + _outputs(name, q, nqb, nq, com, params)


# ---------------------------------------------------------------- behavioral

def _schmitt(name, n, params):
    """Hysteresis via a fast state node that latches through positive feedback."""
    n1, n2, nqb, nq, com = n[0], n[1], n[5], n[6], n[7]
    vhigh, vlow = _levels(params)
    vt = num(params["vt"]) if "vt" in params else f"(({vhigh}+{vlow})/2)"
    vh = num(params.get("vh", "0"))
    vin = f"V({n1},{n2})"
    tau = _fnum(params.get("trise", "0"), 0.0) / 2.2 or 1e-8
    lines, s = _latch(name, "st", vin, vt, vh, tau)
    if nq != com:
        lines += _out_stage(name, f"{vlow}+({vhigh}-{vlow})*V({s})", nq, com, params, "q")
    if nqb != com:
        lines += _out_stage(name, f"{vhigh}-({vhigh}-{vlow})*V({s})", nqb, com, params, "qb")
    return lines


def _samplehold(name, n, params):
    """Tracks while S/H is high and samples on a rising CLK edge."""
    inp, inn, clk, sh, out, com = n[0], n[1], n[2], n[3], n[6], n[7]
    vth = f"{_vth(params):.6g}"
    h, cd = f"{name}_h", f"{name}_cd"
    track = []
    lines = []
    if clk != com:
        # a delayed copy of CLK turns a rising edge into a short sampling pulse
        lines += [f"B{name}_cd 0 {cd} I=((V({clk},{com})>{vth} ? 1 : 0)-V({cd}))*1e-3",
                  f"C{name}_cd {cd} 0 1e-11", f"R{name}_cd {cd} 0 1e12"]
        track.append(f"(V({clk},{com})>{vth} && V({cd})<0.5)")
    if sh != com:
        track.append(f"(V({sh},{com})>{vth})")
    cond = " || ".join(track) or "1"
    lines += [f"B{name}_h 0 {h} I=(({cond}) ? (V({inp},{inn})-V({h}))*10 : 0)",
              f"C{name}_h {h} 0 1e-12", f"R{name}_h {h} 0 1e15"]
    lines += _out_stage(name, f"V({h})", out, com, params)
    return lines


def _modulator(name, n, params):
    """VCO: f = space + (mark-space)*V(FM); amplitude V(AM) (1 if unused)."""
    fm, am, ncos, nsin, com = n[0], n[1], n[5], n[6], n[7]
    mark = num(params.get("mark", "1"))
    space = num(params.get("space", "0"))
    amp = f"V({am},{com})" if am != com else "1"
    ph = f"{name}_ph"
    lines = [f"B{name}_ph 0 {ph} I={space}+({mark}-{space})*V({fm},{com})",
             f"C{name}_ph {ph} 0 1", f"R{name}_ph {ph} 0 1e15"]
    if nsin != com:
        lines += _out_stage(name, f"{amp}*sin(2*pi*V({ph}))", nsin, com, params, "s")
    if ncos != com:
        lines += _out_stage(name, f"{amp}*cos(2*pi*V({ph}))", ncos, com, params, "c")
    return lines


def _phasedet(name, n, params):
    """Phase-frequency detector with charge-pump output (behaviour inferred from its
    parameters, the help is silent): rising edges of a set UP, of b set DN, both reset
    when both are set; output current Iout*(UP-DN) into Q, limited to Vlow..Vhigh."""
    a, b, out, com = n[0], n[1], n[6], n[7]
    ref = num(params.get("ref", "0"))
    # comparators with 1 mV hysteresis, so inputs resting on the threshold don't chatter
    lines = []
    latches = []
    for tag, inp in (("la", a), ("lb", b)):
        ll, node = _latch(name, tag, f"V({inp},{com})", ref, "1m")
        lines += ll
        latches.append(node)
    adc_lines, (da, db) = _adc(name, latches, "0", 0.5)
    lines += adc_lines
    zl, zero = _const_zero(name, com)
    lines += zl
    one, up, dn, rst = f"{name}_one", f"{name}_up", f"{name}_dn", f"{name}_rst"
    lines += [f"A{name}_one {zero} {one} {name}_onem",
              f".model {name}_onem d_inverter(rise_delay=1e-12 fall_delay=1e-12)",
              f"A{name}_ffu {one} {da} {zero} {rst} {up} {name}_nu {name}_ffm",
              f"A{name}_ffd {one} {db} {zero} {rst} {dn} {name}_nd {name}_ffm",
              f".model {name}_ffm d_dff(clk_delay=1e-12 set_delay=1e-12 reset_delay=1e-12 "
              "rise_delay=1e-12 fall_delay=1e-12)",
              f"A{name}_and [{up} {dn}] {rst} {name}_andm",
              f".model {name}_andm d_and(rise_delay=1e-9 fall_delay=1e-12)",
              f"A{name}_dac [{up} {dn}] [{name}_ua {name}_da] {name}_dacm",
              f".model {name}_dacm dac_bridge(out_low=0 out_high=1 t_rise=1e-9 t_fall=1e-9)"]
    iout = num(params.get("iout", "10u"))
    lines.append(f"B{name} {com} {out} I={iout}*(V({name}_ua)-V({name}_da))")
    lines += _smooth_clamp(name, out, com, params)
    lines.append(f"R{name}_sh {out} {com} 1e12")     # keeps the node defined at DC
    if "rout" in params:
        lines.append(f"R{name}_out {out} {com} {num(params['rout'])}")
    if "cout" in params:
        lines.append(f"C{name}_out {out} {com} {num(params['cout'])}")
    return lines


def _smooth_clamp(name, out, com, params, default_high="1e308", default_low="-1e308"):
    """Voltage compliance Vlow..Vhigh through Rclamp, with a softplus corner of width
    'epsilon' (default 10 mV) instead of a hard switch, which stalls the time step."""
    hi = _fnum(params.get("vhigh", default_high), None)
    lo = _fnum(params.get("vlow", default_low), None)
    if hi is not None and lo is not None and hi >= 1e300 and lo <= -1e300:
        return []
    rc = num(params.get("rclamp", "1"))
    eps = num(params.get("epsilon", "10m")) if _fnum(params.get("epsilon", "10m"), 0.01) else "10m"
    vo = f"V({out},{com})"
    sp = lambda x: f"(({x})>30 ? ({x}) : ln(1+exp({x})))"                      # noqa: E731
    vh, vl = f"({num(params.get('vhigh', default_high))})", f"({num(params.get('vlow', default_low))})"
    return [f"B{name}_clamp {out} {com} I=({eps})*({sp(f'({vo}-{vh})/({eps})')}"
            f"-{sp(f'({vl}-{vo})/({eps})')})/{rc}"]


def _varistor(name, n, params):
    n1, n2, out, com = n[0], n[1], n[6], n[7]
    rc = num(params.get("rclamp", "1"))
    v = f"V({out},{com})"
    vb = f"abs(V({n1},{n2}))"
    return [f"B{name} {out} {com} I=(abs({v})>{vb} ? sgn({v})*(abs({v})-{vb})/{rc} : 0)"]


# ---------------------------------------------------------------- G/E table()

_TABLE = re.compile(r"(?i)^([eg]\S*)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+table\s*\((.*)\)\s*$")


def convert_table(line: str) -> str | None:
    """LTspice 'G1 a b c d table(x1 y1 x2 y2)' -> ngspice TABLE syntax."""
    m = _TABLE.match(line.strip())
    if not m:
        return None
    name, a, b, c, d, body = m.groups()
    vals = body.replace(",", " ").split()
    if len(vals) % 2:
        return None
    pairs = " ".join(f"({vals[i]},{vals[i + 1]})" for i in range(0, len(vals), 2))
    return f"{name} {a} {b} TABLE {{V({c},{d})}} = {pairs}"


# ---------------------------------------------------------------- SW model extensions

_SW_EXT = ("vser", "ilimit", "level", "epsilon")


def _model_params(body: str):
    """'SW(Ron=10 Roff=1Meg Vt=0)' -> {'ron': '10', ...}"""
    inner = body[body.find("(") + 1:body.rfind(")")] if "(" in body else body
    inner = re.sub(r"\s*=\s*", "=", inner)
    out = {}
    for t in re.findall(r"(\w+)=(\{[^}]*\}|\S+)", inner):
        out[t[0].lower()] = t[1]
    return out


def rewrite_switches(lines: list[str]) -> list[str]:
    """Replace S elements whose .model uses LTspice-only SW features (negative Vh =
    smooth transition, Vser, Ilimit) with an equivalent behavioral current source."""
    models = {}
    for line in lines:
        m = re.match(r"(?i)\s*\.model\s+(\S+)\s+sw\b(.*)$", line)
        if m:
            p = _model_params(m.group(2))
            vh = _fnum(p.get("vh", "0"), 0.0)
            if any(k in p for k in _SW_EXT) or vh < 0 or (p.get("vh", "").startswith("{")):
                models[m.group(1).lower()] = p
    if not models:
        return lines
    out, renamed = [], {}
    for line in lines:
        tok = line.split()
        if tok and tok[0][0] in "sS" and len(tok) >= 6 and tok[5].lower() in models:
            out += _switch(tok, models[tok[5].lower()])
            renamed[tok[0].lower()] = f"V{tok[0]}_i"
        else:
            out.append(line)
    if renamed:
        # I(S1) in expressions now reads the switch's series sense source
        pat = re.compile(r"(?i)\bI\(\s*(" + "|".join(re.escape(k) for k in renamed) + r")\s*\)")
        out = [pat.sub(lambda m: f"I({renamed[m.group(1).lower()]})", l) for l in out]
    return out


def _switch(tok, p):
    name, a, b, cp, cn = tok[:5]
    ron = f"({num(p.get('ron', '1'))})"
    roff = f"({num(p.get('roff', '1e12'))})"
    vt = f"({num(p.get('vt', '0'))})"
    vh_raw = p.get("vh", "0")
    vser = f"({num(p.get('vser', '0'))})"
    vc = f"V({cp},{cn})"
    vh = _fnum(vh_raw, None)
    if vh is not None and vh >= 0:
        width = "1e-3"          # hysteresis approximated by a narrow transition
    else:
        width = f"abs({num(vh_raw)})"
    x = f"max(-1,min(1,({vc}-{vt})/{width}))"
    frac = f"(0.5+0.75*{x}-0.25*{x}*{x}*{x})"
    m = f"{name}_m"
    v = f"V({m},{b})"
    ion = f"(sgn({v})*max(abs({v})-{vser},0)/{ron})"
    if "ilimit" in p:
        il = f"({num(p['ilimit'])})"
        ion = f"({il}*tanh({ion}/{il}))"
    return [f"V{name}_i {a} {m} 0",
            f"B{name} {m} {b} I={v}/{roff}+{frac}*{ion}"]


# ---------------------------------------------------------------- IGBT (Z ... NIGBT/PIGBT)

def rewrite_igbts(lines: list[str], warnings: list) -> list[str]:
    """LTspice's IGBT (Hefner model) has no ngspice equivalent; substitute the classic
    MOSFET-driving-a-wide-base-BJT circuit using the model's threshold, KP, saturation
    current and capacitances (help page 'Z. MESFET and IGBT', defaults from there)."""
    models = {}
    for line in lines:
        m = re.match(r"(?i)\s*\.model\s+(\S+)\s+(nigbt|pigbt)\b(.*)$", line)
        if m:
            models[m.group(1).lower()] = (m.group(2).lower(), _model_params(m.group(3) or ""))
    if not models:
        return lines
    out = []
    for line in lines:
        tok = line.split()
        if re.match(r"(?i)\s*\.model\s+\S+\s+(nigbt|pigbt)\b", line):
            continue
        if tok and tok[0][0] in "zZ" and len(tok) >= 5 and tok[4].lower() in models:
            out += _igbt(tok, *models[tok[4].lower()])
            warnings.append(f"{tok[0]}: IGBT approximated by a MOSFET + bipolar equivalent circuit")
        else:
            out.append(line)
    return out


def _igbt(tok, kind, p):
    name, c, g, e = tok[:4]
    area = _fnum(tok[5], None) if len(tok) > 5 and "=" not in tok[5] else None
    area_m2 = _fnum(p.get("area", "1e-5"), 1e-5) * (area or 1.0)
    area_cm2 = area_m2 * 1e4
    vt = _fnum(p.get("vt", "4.7"), 4.7)
    kp = _fnum(p.get("kp", "0.38"), 0.38)
    js = _fnum(p.get("jsne", "6.5e-13"), 6.5e-13) * area_cm2
    cgs = _fnum(p.get("cgs", "1.24e-8"), 1.24e-8) * area_cm2
    cgd = _fnum(p.get("coxd", "3.5e-8"), 3.5e-8) * _fnum(p.get("agd", "5e-6"), 5e-6) * 1e4
    b = f"{name}_b"
    if kind == "nigbt":
        mos, bjt, vto = "NMOS", "PNP", vt
        lines = [f"M{name} {b} {g} {e} {e} {name}_m", f"Q{name} {e} {b} {c} {name}_q"]
    else:
        mos, bjt, vto = "PMOS", "NPN", -vt
        lines = [f"M{name} {b} {g} {e} {e} {name}_m", f"Q{name} {e} {b} {c} {name}_q"]
    lines += [f".model {name}_m {mos}(level=1 vto={vto:.6g} kp={kp:.6g})",
              f".model {name}_q {bjt}(is={js:.6g} bf=0.5 br=0.1)",
              f"C{name}_gs {g} {e} {cgs:.6g}",
              f"C{name}_gd {g} {c} {cgd:.6g}"]
    return lines
