"""TuxSpice's own model library (pyltspice/data/models): every part is simulated in ngspice and
checked against the datasheet typical values it was fitted to. Parts of one kind share a
netlist, so this is a handful of runs."""
import re

import numpy as np
import pytest

from pyltspice import config
from pyltspice.sim.runner import Simulator
from pyltspice.sim.vectors import VectorSet

from .conftest import needs_ngspice

pytestmark = needs_ngspice


def _cards(ext):
    text = (config.BUNDLED_MODELS / f"tuxspice.{ext}").read_text()
    return {m.group(1): m.group(2) for m in re.finditer(r"(?m)^\.model (\S+) (\S+?)\((.*)\)$", text)}


def _op(tmp_path, body, tag):
    res = Simulator("* models\n" + body + ".op\n.end\n", tmp_path / tag).run()
    assert res.ok, res.errors
    vs = VectorSet(res.plots[0])
    return lambda name: float(np.real(vs.get(name))[0])


GE = (0.08, 0.45)
# name: (test current, typical hFE[, VBE range]) from the datasheets
BJT = {"BC337": (0.1, 250), "BC327": (0.1, 250), "S8050": (0.1, 200), "S8550": (0.1, 200),
       "PN2222A": (0.15, 200), "2N5551": (0.01, 150), "MPSA42": (0.01, 100), "MPSA92": (0.01, 100),
       "BD139": (0.15, 100), "BD140": (0.15, 100), "TIP31C": (1, 60), "TIP32C": (1, 60),
       "TIP41C": (1, 60), "TIP42C": (1, 60), "MJE3055": (2, 50), "MJE2955": (2, 50),
       # germanium: (test current, hFE, VBE range) -- VBE is a few tenths of a volt
       "AC125": (2e-3, 125, GE), "AC126": (2e-3, 140, GE), "AC127": (0.1, 100, GE), "AC128": (0.3, 100, GE),
       "AC187": (0.3, 150, GE), "AC188": (0.3, 150, GE), "OC44": (1e-3, 100, GE), "OC45": (1e-3, 50, GE),
       "OC71": (1e-3, 47, GE), "OC72": (10e-3, 90, GE), "2N404": (10e-3, 60, GE), "2N1305": (10e-3, 80, GE),
       "2N1308": (10e-3, 80, GE), "AF117": (1e-3, 150, GE), "AF139": (1.5e-3, 50, GE)}
# BC107-109, BC177-179, BC237-239, BC307-309, BC546-560: hFE group at 2 mA, 5 V (plain number = B)
BC_GROUPS = {"": 290, "A": 180, "B": 290, "C": 520}


def _bjt_targets(cards):
    out = dict(BJT)
    for name in cards:
        m = re.fullmatch(r"BC(10[789]|17[789]|23[789]|30[789]|5[45]\d|560)([ABC]?)", name)
        if m:
            out[name] = (2e-3, BC_GROUPS[m.group(2)], (0.55, 0.75))
    return out


def test_bjt_hfe_and_vbe(tmp_path):
    cards = _cards("bjt")
    targets = _bjt_targets(cards)
    assert set(cards) == set(targets)
    assert {"BC238", "BC238B", "BC548C", "BC309", "AC128", "OC71"} <= set(cards)
    lines = ["Vp ref 0 5", "Vn refn 0 -5"]
    for k, (name, (ic, *_)) in enumerate(targets.items()):
        pnp = cards[name] == "PNP"
        # the collector current is forced; feedback on the base holds Vce at +-5 V
        lines += [f"I{k} {'c%d 0' % k if pnp else '0 c%d' % k} {ic}",
                  f"E{k} bb{k} 0 c{k} {'refn' if pnp else 'ref'} 1000",
                  f"Vb{k} bb{k} b{k} 0", f"Q{k} c{k} b{k} 0 {name}"]
    v = _op(tmp_path, "\n".join(lines) + "\n.lib tuxspice.bjt\n", "bjt")
    for k, (name, (ic, hfe, *vr)) in enumerate(targets.items()):
        ib = abs(v(f"I(Vb{k})"))
        vbe = abs(v(f"V(b{k})"))
        lo, hi = vr[0] if vr else (0.55, 1.1)
        assert 0.6 * hfe < ic / ib < 1.5 * hfe, (name, ic / ib)
        assert lo < vbe < hi, (name, vbe)


# name: (current, expected V across it; negative current = reverse, i.e. Vz)
DIODES = {"1N4001": (1, 0.93), "1N4002": (1, 0.93), "1N4004": (1, 0.93), "1N5408": (3, 0.93),
          "FR107": (1, 1.1), "UF4007": (1, 1.3), "MUR160": (1, 1.05), "1N5822": (3, 0.45),
          "BAT85": (1e-3, 0.32), "1N4728A": (-0.076, -3.3), "1N4732A": (-0.053, -4.7),
          "1N4733A": (-0.049, -5.1), "1N4734A": (-0.045, -5.6), "1N4739A": (-0.028, -9.1),
          "1N4740A": (-0.025, -10), "1N4742A": (-0.021, -12), "1N4744A": (-0.017, -15),
          "1N4746A": (-0.014, -18), "1N5231B": (-0.02, -5.1), "BZX84C5V1": (-0.005, -5.1),
          "BZX84C3V3": (-0.005, -3.3), "LED_RED": (0.02, 2.0), "LED_YELLOW": (0.02, 2.05),
          "LED_GREEN": (0.02, 2.2), "LED_BLUE": (0.02, 3.1), "LED_WHITE": (0.02, 3.1),
          # germanium signal diodes: Vf at 1 mA (a few tenths of a volt; silicon is ~0.6)
          "1N34A": (1e-3, 0.32), "1N60": (1e-3, 0.28), "1N270": (1e-3, 0.25), "OA90": (1e-3, 0.35),
          "OA91": (1e-3, 0.33), "OA95": (1e-3, 0.30), "AA119": (1e-3, 0.30)}


def test_diode_forward_and_zener_voltages(tmp_path):
    assert set(_cards("dio")) == set(DIODES)
    lines = []
    for k, (name, (i, _)) in enumerate(DIODES.items()):
        lines += [f"I{k} 0 a{k} {i}", f"D{k} a{k} 0 {name}"]
    v = _op(tmp_path, "\n".join(lines) + "\n.lib tuxspice.dio\n", "dio")
    for k, (name, (i, want)) in enumerate(DIODES.items()):
        got = v(f"V(a{k})")
        assert abs(got - want) < (0.03 * abs(want) if i < 0 else 0.06), (name, got, want)


# name: (Vgs for Rds(on), test Id, typical Rds(on), Vth)
MOS = {"2N7000": (10, 0.1, 1.2, 2.1), "BS250": (-10, -0.1, 9, -2.0), "AO3400": (10, 2, 0.019, 1.05),
       "IRF520": (10, 4, 0.20, 3), "IRF540": (10, 10, 0.060, 3), "IRF540N": (10, 10, 0.035, 3),
       "IRF640": (10, 9, 0.15, 3), "IRF740": (10, 5, 0.45, 3), "IRF3205": (10, 50, 0.0065, 3),
       "IRLZ44N": (5, 20, 0.020, 1.5), "IRF9540": (-10, -10, 0.15, -3), "IRF9Z34N": (-10, -10, 0.080, -3)}


def test_mosfet_rdson_and_threshold(tmp_path):
    assert set(_cards("mos")) == set(MOS)
    lines = []
    for k, (name, (vgs, idd, _, vth)) in enumerate(MOS.items()):
        s = -1 if vgs < 0 else 1
        lines += [f"Vg{k} g{k} 0 {vgs}", f"I{k} 0 d{k} {idd}", f"M{k} d{k} g{k} 0 {name}",
                  # gate tied to drain at 250 uA reads Vgs(th)
                  f"It{k} 0 t{k} {s * 250e-6}", f"Mt{k} t{k} t{k} 0 {name}"]
    v = _op(tmp_path, "\n".join(lines) + "\n.lib tuxspice.mos\n", "mos")
    for k, (name, (vgs, idd, ron, vth)) in enumerate(MOS.items()):
        assert 0.75 * ron < v(f"V(d{k})") / idd < 1.3 * ron, (name, v(f"V(d{k})") / idd)
        assert abs(v(f"V(t{k})") - vth) < 0.4, (name, v(f"V(t{k})"))


JFETS = {"2N5457": (3e-3, -1.8), "2N5458": (6e-3, -3.5), "BF245A": (4e-3, -1.5),
         "MPF102": (8e-3, -4.0), "2N5460": (-3e-3, 2.5)}


def test_jfet_idss_and_pinch_off(tmp_path):
    assert set(_cards("jft")) == set(JFETS)
    lines = []
    for k, (name, (idss, vp)) in enumerate(JFETS.items()):
        s = -1 if idss < 0 else 1
        lines += [f"Vd{k} d{k} 0 {15 * s}", f"J{k} d{k} 0 0 {name}",
                  f"Vo{k} o{k} 0 {15 * s}", f"Vgo{k} go{k} 0 {vp * 0.95}", f"Jo{k} o{k} go{k} 0 {name}"]
    v = _op(tmp_path, "\n".join(lines) + "\n.lib tuxspice.jft\n", "jft")
    for k, (name, (idss, vp)) in enumerate(JFETS.items()):
        got = -v(f"I(Vd{k})")
        assert abs(got - idss) < 0.1 * abs(idss), (name, got)
        assert abs(v(f"I(Vo{k})")) < 0.02 * abs(idss), name        # off near pinch-off


# name: (GBW, SR in V/us, Vos, high/low headroom, single supply?)
OPAMPS = {"LM741": (1e6, 0.5, 1e-3, 2, 2, False), "UA741": (1e6, 0.5, 1e-3, 2, 2, False),
          "LM358": (1e6, 0.3, 2e-3, 1.5, 0.02, True), "LM324": (1.2e6, 0.5, 2e-3, 1.5, 0.02, True),
          "LMV358": (1e6, 1, 1.7e-3, 0.01, 0.01, True), "TL071": (3e6, 13, 3e-3, 1.5, 1.5, False),
          "TL072": (3e6, 13, 3e-3, 1.5, 1.5, False), "TL074": (3e6, 13, 3e-3, 1.5, 1.5, False),
          "TL081": (3e6, 13, 3e-3, 1.5, 1.5, False), "TL082": (3e6, 13, 3e-3, 1.5, 1.5, False),
          "NE5532": (10e6, 9, 0.5e-3, 1.5, 1.5, False), "LM833": (15e6, 7, 0.3e-3, 1.5, 1.5, False),
          "MCP6002": (1e6, 0.6, 1e-3, 0.025, 0.025, True)}


def _opamp_rails(single):
    return ("vp5", "0", 2.5) if single else ("vp15", "vn15", 0.0)


def _supplies():
    return "Vp5 vp5 0 5\nVp15 vp15 0 15\nVn15 vn15 0 -15\nVm mid 0 2.5\n"


def test_opamp_offset_swing_and_bandwidth(tmp_path):
    names = [ln.split()[1] for ln in (config.BUNDLED_MODELS / "tuxspice_opamps.lib").read_text().splitlines()
             if ln.startswith(".subckt") and "TUX_OPAMP" not in ln]
    assert set(names) == set(OPAMPS)
    dc, ac = [_supplies()], [_supplies()]
    for k, (name, (gbw, sr, vos, hr, lr, single)) in enumerate(OPAMPS.items()):
        vp, vn, ref = _opamp_rails(single)
        r = "mid" if single else "0"
        dc += [f"Xf{k} {r} f{k} {vp} {vn} f{k} {name}",                       # follower: Vos
               f"Vh{k} h{k} 0 {ref + 0.5}", f"Xh{k} h{k} {r} {vp} {vn} oh{k} {name}",   # open loop: swing
               f"Vl{k} l{k} 0 {ref - 0.5}", f"Xl{k} l{k} {r} {vp} {vn} ol{k} {name}"]
        ac += [f"Va{k} a{k} {r} AC 1", f"Xa{k} a{k} n{k} {vp} {vn} o{k} {name}",   # gain of 10
               f"Rf{k} o{k} n{k} 9k", f"Rg{k} n{k} {r} 1k"]
    lib = "\n.lib tuxspice_opamps.lib\n"
    v = _op(tmp_path, "\n".join(dc) + lib, "opdc")
    rails = {False: (15, -15), True: (5, 0)}
    for k, (name, (gbw, sr, vos, hr, lr, single)) in enumerate(OPAMPS.items()):
        hi, lo = rails[single]
        ref = _opamp_rails(single)[2]
        assert abs(v(f"V(f{k})") - ref - vos) < 0.2 * vos + 2e-4, (name, v(f"V(f{k})") - ref)
        assert abs(v(f"V(oh{k})") - (hi - hr)) < 0.15, (name, v(f"V(oh{k})"))
        assert abs(v(f"V(ol{k})") - (lo + lr)) < 0.15, (name, v(f"V(ol{k})"))
    res = Simulator("* ac\n" + "\n".join(ac) + lib + ".ac dec 50 10 100Meg\n.end\n", tmp_path / "opac").run()
    assert res.ok, res.errors
    p = res.main_plot()
    vs = VectorSet(p)
    f = np.real(p.x)
    for k, (name, (gbw, *_)) in enumerate(OPAMPS.items()):
        mag = np.abs(vs.get(f"V(o{k})"))
        f3 = f[np.argmax(mag < mag[0] / np.sqrt(2))]
        assert 0.8 * gbw / 10 < f3 < 1.25 * gbw / 10, (name, f3)


def test_opamp_slew_rate(tmp_path):
    tran = [_supplies()]
    for k, (name, (gbw, sr, vos, hr, lr, single)) in enumerate(OPAMPS.items()):
        vp, vn, ref = _opamp_rails(single)
        step = 1.0 if single else 5.0
        tran += [f"Vs{k} s{k} 0 PULSE({ref - step} {ref + step} 1u 1n 1n 1 2)",
                 f"Xs{k} s{k} o{k} {vp} {vn} o{k} {name}"]
    res = Simulator("* sr\n" + "\n".join(tran) + "\n.lib tuxspice_opamps.lib\n.tran 1n 20u 0 5n\n.end\n",
                    tmp_path / "sr").run()
    assert res.ok, res.errors
    p = res.main_plot()
    vs = VectorSet(p)
    t = np.real(p.x)
    for k, (name, (gbw, sr, vos, hr, lr, single)) in enumerate(OPAMPS.items()):
        ref, step = _opamp_rails(single)[2], (1.0 if single else 5.0)
        after = t > 1e-6
        o = np.real(vs.get(f"V(o{k})"))[after]
        lo, hi = ref - 0.6 * step, ref + 0.6 * step        # 20 % .. 80 % of the step
        t0, t1 = np.interp([lo, hi], o, t[after])           # output rises monotonically
        slope = (hi - lo) / (t1 - t0) / 1e6
        assert 0.8 * sr < slope < 1.2 * sr, (name, slope)


def test_bundled_models_found_by_name_and_symbols_by_library(tmp_path):
    """Placing a part needs no .lib: model cards come in like standard.*, op-amp symbols carry
    their model file, and LTspice's own cards win when both define a name."""
    from pyltspice.model.library import default_library
    from pyltspice.sim import ltcompat
    assert ltcompat.standard_model("BC337").startswith(".model BC337 NPN")
    sym = default_library().get("OpAmps\\LM358")
    assert sym is not None and sym.attrs["ModelFile"] == "tuxspice_opamps.lib"
    nl = "* led\nV1 a 0 5\nR1 a b 150\nD1 b 0 LED_RED\nQ1 c b2 0 BC337\nV2 c 0 1\nV3 b2 0 0.6\n.op\n.end\n"
    res = Simulator(nl, tmp_path / "led").run()
    assert res.ok, res.errors
    v = VectorSet(res.plots[0])
    assert 1.9 < float(np.real(v.get("V(b)"))[0]) < 2.1
    if (config.CMP_DIR / "standard.bjt").exists():
        assert "mfg=NXP" in ltcompat.standard_model("2N3904")       # LTspice's card, not ours
    for f in ltcompat.model_card_files()[4:]:
        assert f.exists(), f


@pytest.mark.parametrize("name", sorted(OPAMPS))
def test_opamp_symbols_match_their_subckt(name):
    from pyltspice.model.asy import load_asy
    sym = load_asy(config.BUNDLED_SYM / "OpAmps" / f"{name}.asy")
    assert sym.attrs["SpiceModel"] == name and sym.attrs["Prefix"] == "X"
    assert [p.name for p in sorted(sym.pins, key=lambda p: int(p.attrs.get("SpiceOrder", 0)))] == \
        ["In+", "In-", "V+", "V-", "OUT"]


def test_schematic_with_bundled_opamp_simulates(tmp_path):
    """OpAmps\\LM358 from TuxSpice's symbols: the netlist pulls in its model file by itself."""
    from pyltspice.model import asc
    from pyltspice.model.library import default_library
    from pyltspice.model.netlist import generate_netlist
    sch = asc.parse_asc("Version 4\nSHEET 1 880 680\n"
                        "SYMBOL OpAmps\\\\LM358 0 0 R0\nSYMATTR InstName U1\n"
                        "FLAG -32 80 in\nFLAG -32 48 out\nFLAG 32 64 out\nFLAG 0 32 vcc\nFLAG 0 96 0\n"
                        "TEXT 0 200 Left 2 !V1 vcc 0 5\\nV2 in 0 2\n"
                        "TEXT 0 240 Left 2 !.op\n")
    nl = generate_netlist(sch, default_library()).text
    assert "XU1 in out vcc 0 out LM358" in nl and "tuxspice_opamps.lib" in nl
    res = Simulator(nl, tmp_path / "u1").run()
    assert res.ok, res.errors
    assert abs(float(np.real(VectorSet(res.plots[0]).get("V(out)"))[0]) - 2.002) < 1e-3
