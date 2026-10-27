import pytest
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


@needs_ngspice
def test_counter_divides_clock(tmp_path):
    """COUNTER cycles=4: Phi1 (pin 7) high for 2 of every 4 clock periods, Phi2 its complement."""
    net = ("* counter\nV1 clk 0 PULSE(0 1 0 1n 1n 0.5m 1m)\n"
           "A1 clk 0 0 0 0 p2 p1 0 COUNTER cycles=4\nR1 p1 0 1k\nR2 p2 0 1k\n"
           ".tran 0 9m 0 10u\n.end\n")
    r = Simulator(net, tmp_path / "c").run()
    assert r.ok, r.errors
    p = r.main_plot()
    v = VectorSet(p)
    t = np.real(p.x)
    p1, p2 = np.real(v.get("V(p1)")), np.real(v.get("V(p2)"))
    at = lambda arr, ms: arr[np.searchsorted(t, ms * 1e-3)]
    assert [round(at(p1, ms)) for ms in (0.25, 1.25, 2.25, 3.25, 4.25, 6.25)] == [1, 1, 0, 0, 1, 0]
    assert all(round(at(p1, ms) + at(p2, ms)) == 1 for ms in (0.25, 2.25, 4.25, 6.25))


@needs_ngspice
def test_pole_zero_rc(tmp_path):
    """.pz (ngspice extension): an RC low-pass has one real pole at -1/RC."""
    net = "* rc\nV1 in 0 AC 1\nR1 in out 1k\nC1 out 0 1u\n.pz in 0 out 0 vol pz\n.end\n"
    r = Simulator(net, tmp_path / "pz").run()
    assert r.ok, r.errors
    p = r.main_plot()
    assert p.analysis == "pz"
    poles = [complex(p.data[v.index][0]) for v in p.variables if v.name.startswith("v(pole")]
    assert len(poles) == 1 and abs(poles[0].real + 1000) < 1e-6 and abs(poles[0].imag) < 1e-9


@needs_ngspice
def test_distortion_two_harmonics(tmp_path):
    """.disto (ngspice extension) returns 2nd and 3rd harmonic result sets against frequency."""
    net = ("* amp\nV1 in 0 DC 0.7 AC 1 DISTOF1 1\nR1 in b 1k\nQ1 c b 0 qn\nRC vcc c 1k\n"
           "VCC vcc 0 5\n.model qn npn\n.disto dec 5 1k 1Meg\n.end\n")
    r = Simulator(net, tmp_path / "d").run()
    assert r.ok, r.errors
    sets = [p for p in r.plots if p.analysis == "disto"]
    assert [s.plotname.split("-")[-1].strip() for s in sets] == ["2nd harmonic", "3rd harmonic"]
    assert sets[0].variables[0].name == "frequency" and sets[0].is_complex


@needs_ngspice
def test_ac_device_currents_match_ltspice(tmp_path):
    """ngspice leaves @r1[i] at zero in .ac; TuxSpice adds sense sources so I(R1) is right.
    LTspice 26.1.1 gives -84.0535 dB / -93.595 deg for this circuit at 10 Hz."""
    import numpy as np
    from pyltspice.sim.rawfile import read_raw
    from pyltspice.sim.runner import Simulator
    from pyltspice.sim.vectors import VectorSet
    res = Simulator("* rc\nV1 N001 0 AC 1\nR1 out N001 1k\nC1 out 0 1u\n.ac dec 5 10 100k\n.end\n",
                    tmp_path / "ac").run()
    for plot in (res.main_plot(), read_raw(tmp_path / "ac.raw")[0]):
        vs = VectorSet(plot)
        assert "V(out__ir1)" not in vs.names() and not any("isense" in n.lower() for n in vs.names())
        i = vs.get("I(R1)")[0]
        assert 20 * np.log10(abs(i)) == pytest.approx(-84.0535, abs=1e-3)
        assert np.degrees(np.angle(i)) == pytest.approx(-93.595, abs=1e-2)
        assert np.allclose(vs.get("I(C1)"), -vs.get("I(R1)"))


@needs_ngspice
def test_op_keeps_its_first_vector(tmp_path):
    """An operating point has no sweep: its first variable (here V(a0)) is a signal, not an
    x axis, and must not be hidden."""
    res = Simulator("* op\nI0 0 a0 1m\nD0 a0 0 D\n.op\n.end\n", tmp_path / "op").run()
    assert res.ok, res.errors
    vs = VectorSet(res.plots[0])
    assert "V(a0)" in vs.names() and 0.5 < float(np.real(vs.get("V(a0)"))[0]) < 0.9


SUB = ("* opts\n.subckt blk a b\nR1 a m 1k\nQ1 b m 0 2N3904\n.ends\n"
       "V1 in 0 1\nX1 in out blk\nR2 out vcc 1k\nV2 vcc 0 5\nL1 vcc l 1u\nR3 l 0 1k\n.op\n.end\n")


@needs_ngspice
def test_save_defaults_listing_and_rser_warning(tmp_path):
    """Settings > Save Defaults filter what's saved (LTspice's defaults hide subcircuit
    internals); Generate Expanded Listing puts the flat netlist in the log; inductors
    without Rser are reported."""
    from pyltspice.sim.runner import RunOptions
    names = lambda res: VectorSet(res.plots[0]).names()
    res = Simulator(SUB, tmp_path / "a").run()
    assert res.ok, res.errors
    assert "V(out)" in names(res) and "I(R2)" in names(res)
    assert not any("x1" in n.lower() for n in names(res))                 # subcircuit internals hidden
    assert "L1: no series resistance (Rser) specified" in res.warnings
    res = Simulator(SUB, tmp_path / "b", options=RunOptions(
        save_subckt_voltages=True, save_subckt_currents=True, expanded_listing=True, warn_no_rser=False,
        ascii_raw=True)).run()
    assert res.ok, res.errors
    assert any("x1" in n.lower() and n.startswith("V(") for n in names(res))
    assert any("x1" in n.lower() and n.startswith("I") for n in names(res))
    assert "--- Expanded listing ---" in res.log and "x1.m" in res.log.lower()
    assert not res.warnings and (tmp_path / "b.raw").read_bytes().find(b"Values:") > 0   # ASCII .raw
    res = Simulator(SUB, tmp_path / "c", options=RunOptions(save_currents=False)).run()
    assert res.ok and "I(R2)" not in names(res) and "I(V2)" in names(res)


@needs_ngspice
def test_default_devices_libraries_and_user_models(tmp_path):
    from pyltspice.sim import ltcompat
    from pyltspice.sim.runner import RunOptions
    nl = "* q\nV1 c 0 5\nV2 b 0 0.7\nQ1 c b 0 MYQ\nD1 c 0 D\n.op\n.end\n"
    res = Simulator(nl, tmp_path / "a").run()
    assert not res.ok and any("MYQ" in e.upper() for e in res.errors)
    (tmp_path / "user.bjt").write_text(".model MYQ NPN(BF=123 IS=1e-15)\n.model BC337 NPN(BF=7)\n")
    res = Simulator(nl, tmp_path / "b", options=RunOptions(user_dir=tmp_path)).run()
    assert res.ok, res.errors
    assert ltcompat.user_model("bc337", tmp_path) == ".model BC337 NPN(BF=7)"      # user.* wins
    res = Simulator(nl, tmp_path / "c", options=RunOptions(user_dir=tmp_path, default_devices=False)).run()
    assert res.ok and "D: using SPICE's default model parameters" in res.warnings
    res = Simulator(nl, tmp_path / "d", options=RunOptions(user_dir=tmp_path, default_libraries=False)).run()
    assert not res.ok
    res = Simulator(nl.replace("MYQ", "BC337"), tmp_path / "e", options=RunOptions(solver="Alternate")).run()
    assert res.ok and ".options sparse" in (tmp_path / "e.ngspice.cir").read_text()


def test_random_seed_repeats_unless_reseeding():
    """LTspice gives the same random numbers every run unless Hacks > Use the clock to reseed;
    every .step run still gets its own seed."""
    from pyltspice.sim.runner import RunOptions, spiceinit
    assert spiceinit(RunOptions()) == spiceinit(RunOptions())
    assert spiceinit(RunOptions(), 0) != spiceinit(RunOptions(), 1)
    assert "num_threads=4" in spiceinit(RunOptions(threads=4))
    assert "rndseed=1\n" not in spiceinit(RunOptions(mc_reseed=True))
