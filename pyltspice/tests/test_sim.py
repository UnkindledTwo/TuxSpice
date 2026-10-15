import math

import numpy as np

from pyltspice.model.netlist import generate_netlist
from pyltspice.sim.runner import Simulator
from pyltspice.sim.vectors import VectorSet, lt_name

from .conftest import needs_lib, needs_ngspice
from .test_netlist import rc_lowpass


def test_vector_names():
    assert lt_name("v(n001)") == "V(n001)"
    assert lt_name("i(v1)") == "I(V1)"
    assert lt_name("i(@q1[ic])") == "Ic(Q1)"
    assert lt_name("@d1[id]") == "I(D1)"
    assert lt_name("v(xu1.n002)") == "V(xu1:n002)"


@needs_ngspice
def test_rc_ac_corner(tmp_path):
    nl = "* rc\nV1 in 0 AC 1\nR1 in out 1k\nC1 out 0 1u\n.ac dec 200 1 100k\n"
    res = Simulator(nl, tmp_path / "rc").run()
    assert res.ok, res.errors
    p = res.main_plot()
    vs = VectorSet(p)
    mag = np.abs(vs.get("V(out)"))
    f3 = np.interp(1 / math.sqrt(2), mag[::-1], p.x[::-1])
    assert abs(f3 - 1 / (2 * math.pi * 1e3 * 1e-6)) / 159.15 < 0.02


@needs_ngspice
def test_rc_tran_tau(tmp_path):
    nl = "* rc\nV1 in 0 PULSE(0 1 0 1n 1n 1 2)\nR1 in out 1k\nC1 out 0 1u\n.tran 5m\n"
    res = Simulator(nl, tmp_path / "rc").run()
    assert res.ok, res.errors
    p = res.main_plot()
    v = VectorSet(p).get("V(out)")
    assert abs(np.interp(1e-3, p.x, v) - (1 - math.exp(-1))) < 0.01


@needs_ngspice
def test_step_param(tmp_path):
    nl = "* s\n.param R=1k\nV1 in 0 1\nR1 in out {R}\nR2 out 0 1k\n.op\n.step param R list 1k 3k\n"
    res = Simulator(nl, tmp_path / "s").run()
    assert res.ok, res.errors
    p = res.main_plot()
    assert len(p.step_bounds) == 2
    v = VectorSet(p).get("V(out)")
    assert np.allclose([v[a] for a, _ in p.step_bounds], [0.5, 0.25], atol=1e-6)


@needs_lib
@needs_ngspice
def test_schematic_to_waveform(tmp_path):
    nl = generate_netlist(rc_lowpass())
    res = Simulator(nl.text, tmp_path / "rc").run()
    assert res.ok, res.errors
    assert VectorSet(res.main_plot()).get("V(out)") is not None


def test_plt_roundtrip(tmp_path):
    from pyltspice.sim.pltfile import read_plt, write_plt
    write_plt(tmp_path / "a.plt", {"Transient Analysis": [["V(out)", "I(R1)"], ["V(in)"]]})
    assert read_plt(tmp_path / "a.plt") == {"transient analysis": [["V(out)", "I(R1)"], ["V(in)"]]}


def test_fft_sine_amplitude():
    from pyltspice.sim.fft import spectrum
    t = np.linspace(0, 1e-3, 20001)
    y = 0.5 + 2.0 * np.sin(2 * math.pi * 10e3 * t)
    f, X = spectrum(t, y, npts=8192)
    k = np.argmax(np.abs(X))
    assert abs(f[k] - 10e3) < 1e3 and abs(abs(X[k]) - 2.0) < 0.05


@needs_lib
@needs_ngspice
def test_hierarchical_sheet_simulates(tmp_path):
    from pyltspice.model.library import SymbolLibrary
    from .test_netlist import test_hierarchical_sheet  # builds the design in tmp_path
    test_hierarchical_sheet(tmp_path)
    from pyltspice.model.asc import Flag, Schematic, SymbolInst, Text
    from pyltspice.model.netlist import symbol_pins
    lib = SymbolLibrary()
    parent = Schematic(items=[
        SymbolInst("voltage", 0, 0, "R0", {}, {"InstName": "V1", "Value": "2"}),
        SymbolInst("half", 200, 0, "R0", {}, {"InstName": "U1"}),
        Flag(0, 16, "a"), Flag(0, 96, "0"), Text(0, 200, "Left", 2, "!.op")])
    parent.path = tmp_path / "parent.asc"
    for pr in symbol_pins(parent.symbols[1], lib.get("half", [tmp_path])):
        parent.items.append(Flag(*pr.point, "a" if pr.pin.name == "IN" else "b"))
    res = Simulator(generate_netlist(parent, lib).text, tmp_path / "p", [tmp_path]).run()
    assert res.ok, res.errors
    assert abs(VectorSet(res.plots[0]).get("V(b)")[0] - 1.0) < 1e-6


@needs_ngspice
def test_laplace_bandpass(tmp_path):
    nl = ("* bp\n.param w0={2*pi*1k} Q=2\nV1 in 0 AC 1\n"
          "E1 out 0 in 0 Laplace={w0/Q}*s/(s*s+{w0/Q}*s+{w0*w0})\nR1 out 0 1k\n.ac dec 50 10 100k\n")
    res = Simulator(nl, tmp_path / "bp").run()
    assert res.ok, res.errors
    p = res.main_plot()
    mag = np.abs(VectorSet(p).get("V(out)"))
    k = np.argmax(mag)
    assert abs(mag[k] - 1) < 0.01 and abs(p.x[k] - 1e3) / 1e3 < 0.05


@needs_ngspice
def test_laplace_lowpass_transient(tmp_path):
    nl = ("* lp\nV1 in 0 PULSE(0 1 0 1n 1n 1 2)\nE1 out 0 in 0 Laplace=1/(1+1m*s)\n"
          "R1 out 0 1k\n.tran 0 5m 0 10u\n")
    res = Simulator(nl, tmp_path / "lp").run()
    assert res.ok, res.errors
    p = res.main_plot()
    v = VectorSet(p).get("V(out)")
    assert abs(np.interp(1e-3, p.x, v) - (1 - math.exp(-1))) < 0.02


@needs_ngspice
def test_laplace_delay(tmp_path):
    nl = ("* d\nV1 in 0 PULSE(0 1 1m 1n 1n 1 2)\nE1 out 0 in 0 Laplace=exp(-.5m*s)/(1+1u*s)\n"
          "R1 out 0 1k\n.tran 0 3m 0 5u\n")
    res = Simulator(nl, tmp_path / "d").run()
    assert res.ok, res.errors
    p = res.main_plot()
    v = VectorSet(p).get("V(out)")
    assert np.interp(1.4e-3, p.x, v) < 0.05 and np.interp(1.6e-3, p.x, v) > 0.95


@needs_ngspice
def test_wavefile_source(tmp_path):
    import wave
    import struct
    with wave.open(str(tmp_path / "w.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", int(16384 * math.sin(2 * math.pi * 100 * i / 8000)))
                               for i in range(800)))
    nl = "* w\nV1 x 0 wavefile=.\\w.wav chan=0\nR1 x 0 1k\n.tran 0 0.1 0 50u\n"
    res = Simulator(nl, tmp_path / "w", [tmp_path]).run()
    assert res.ok, res.errors
    p = res.main_plot()
    v = VectorSet(p).get("V(x)")
    assert abs(np.max(v) - 0.5) < 0.02          # half-scale sine


@needs_ngspice
def test_hysteretic_core_inductance(tmp_path):
    # example from the LTspice help: gapped ferrite core, unity dI/dt -> V = L
    nl = ("* core\nL1 N001 0 Hc=16. Bs=.44 Br=.10 A=0.0000251 Lm=0.0198 Lg=0.0006858 N=1000\n"
          "I1 0 N001 PWL(0 0 1 1)\n.tran .5\n.options maxstep=10u\n")
    res = Simulator(nl, tmp_path / "c").run()
    assert res.ok, res.errors
    p = res.main_plot()
    vs = VectorSet(p)
    v = vs.get("V(n001)")
    mu0 = 4e-7 * math.pi
    L_gap = mu0 * 1000 ** 2 * 0.0000251 / 0.0006858
    assert abs(np.interp(0.05, p.x, v) - L_gap) / L_gap < 0.03      # before saturation
    assert np.interp(0.4, p.x, v) < 0.1 * L_gap                       # saturated
    assert vs.get("I(L1)") is not None


@needs_ngspice
def test_flux_inductor(tmp_path):
    nl = "* f\nL1 N001 0 Flux=1m*x\nI1 0 N001 PWL(0 0 1 1)\n.tran 0 .5 0 1m\n"
    res = Simulator(nl, tmp_path / "f").run()
    assert res.ok, res.errors
    p = res.main_plot()
    assert abs(np.interp(0.25, p.x, VectorSet(p).get("V(n001)")) - 1e-3) < 1e-5


def test_noise_frequency_list():
    from pyltspice.sim.ltcompat import translate
    assert ".noise V(o) V1 lin 1 10K 10K" in translate("* n\n.noise V(o) V1 list 10K\n").text


@needs_ngspice
def test_phasedet_sign(tmp_path):
    """a faster than b -> UP dominates -> positive output (a PFD is phase-ambiguous at
    equal frequencies, so test with a frequency difference)."""
    nl = ("* pd\nA5 a b 0 0 0 0 q 0 PHASEDET Iout=15u Ref=0\nV1 a 0 SIN(0 1 1.3k)\n"
          "V2 b 0 SIN(0 1 1k)\nC1 q 0 10n\nR1 q 0 100k\n.tran 0 5m 0 2u\n")
    res = Simulator(nl, tmp_path / "pd").run()
    assert res.ok, res.errors
    p = res.main_plot()
    assert VectorSet(p).get("V(q)")[p.x > 3e-3].mean() > 0.1


@needs_ngspice
def test_measure_chained_and_trig_targ(tmp_path):
    nl = ("* rc\nV1 in 0 AC 1 PULSE(0 1 0 1n 1n 1 2)\nR1 in out 1k\nC1 out 0 1u\n.ac dec 100 1 100k\n"
          ".meas AC tmp MAX mag(V(out))\n"
          ".meas AC BW WHEN mag(V(out))=tmp/sqrt(2)\n"
          ".meas AC ratio PARAM BW*2\n")
    res = Simulator(nl, tmp_path / "m").run()
    assert res.ok, res.errors
    vals = dict(res.measurements)
    f3 = 1 / (2 * math.pi * 1e-3)
    assert abs(float(vals["BW"].split()[0]) - f3) / f3 < 0.01
    assert abs(float(vals["ratio"].split()[0]) / (2 * float(vals["BW"].split()[0])) - 1) < 1e-5
    nl2 = ("* rc\nV1 in 0 PULSE(0 1 1m 1n 1n 1 2)\nR1 in out 1k\nC1 out 0 1u\n.tran 0 6m 0 5u\n"
           ".meas TRAN rise TRIG V(out)=0.1 RISE=1 TARG V(out)=0.9 RISE=1\n"
           ".meas TRAN vavg AVG V(out) FROM=2m TO=6m\n")
    res = Simulator(nl2, tmp_path / "m2").run()
    vals = dict(res.measurements)
    assert abs(float(vals["rise"].split()[0]) - 1e-3 * math.log(9)) < 2e-5   # 10-90% = tau*ln 9
    assert 0 < float(vals["vavg"].split()[0]) < 1


@needs_lib
@needs_ngspice
def test_relaxation_oscillator_swings_rail_to_rail(tmp_path):
    """examples/Educational/relax.asc (LT1001 macro-model): needs subckt-scoped models,
    smooth ideal diodes and zero default VDMOS capacitances to oscillate correctly."""
    from pyltspice import config
    from pyltspice.model.asc import load_asc
    p = config.EXAMPLES_DIR / "Educational" / "relax.asc"
    res = Simulator(generate_netlist(load_asc(p)).text, tmp_path / "relax", [p.parent]).run()
    assert res.ok, res.errors
    v = VectorSet(res.main_plot()).get("V(out)")
    assert v.max() > 13 and v.min() < -13
