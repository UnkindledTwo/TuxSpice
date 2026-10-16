from pyltspice.sim import spicenum
from pyltspice.sim.ltcompat import translate


def lines(t):
    return translate("* t\n" + t).text.splitlines()


def test_numbers():
    assert spicenum.parse("10K") == 1e4
    assert abs(spicenum.parse(".01µ") - 1e-8) < 1e-20
    assert spicenum.parse("1Meg") == 1e6
    assert spicenum.parse("2.2mF") == 2.2e-3
    assert spicenum.parse("abc") is None
    assert spicenum.fmt(0.0012, "V") == "1.2mV"


def test_single_arg_tran():
    assert ".tran 2.5e-05 25m" in lines(".tran 25m startup")
    assert ".tran 1e-06 1m 0 1u" in lines(".tran 0 1m 0 1u")


def test_parasitics_expand():
    out = lines("C1 a b 10u Rser=0.1 V=50\n")
    assert "C1 a C1_r 10u" in out
    assert "R_C1_ser C1_r b 0.1" in out


def test_sine_and_micro():
    out = lines("V1 a 0 SINE(0 1 1k)\nC1 a 0 1µ\n")
    assert "V1 a 0 sin(0 1 1k)" in out
    assert "C1 a 0 1u" in out


def test_default_models_and_three_terminal_mos():
    out = lines("D1 a 0 D\nM1 d g 0 NMOS\n")
    assert ".model D D" in out
    assert "M1 d g 0 0 NMOS" in out


def test_step_parsing():
    tr = translate("* t\n.step param R 1k 3k 1k\n.step dec param C 1n 100n 1\n")
    assert [s.values for s in tr.steps][0] == [1000.0, 2000.0, 3000.0]
    assert len(tr.steps[1].values) == 3


def test_every_ltspice_adevice_is_emulated():
    """All A-device types in lib/sym translate (COUNTER was the last one)."""
    tr = translate("* t\nA1 clk 0 0 0 0 p2 p1 0 COUNTER cycles=4\n"
                   "A2 a b 0 0 0 qb q 0 SCHMITT vt=0.5 vh=0.1\n")
    assert not tr.errors
    assert "d_fdiv(div_factor=4 high_cycles=2" in tr.text


def test_adevices_expand():
    out = translate("* t\nA1 0 in 0 0 0 0 out 0 OTA g=1m linear Rout=1k\n"
                    "A2 a b 0 0 0 0 y 0 AND Td=1n\n").text
    assert "BA1 0 out I=(0.001*(V(in,0)+0))" in out
    assert "d_and(rise_delay=1e-09" in out and "adc_bridge" in out and "dac_bridge" in out


def test_param_normalization_and_table():
    out = lines(".param X table(p,0,0,10,1)\n.param a = 2*b c=3\n.param Rz=sqrt (4)\n")
    assert ".param X={((p)<=(0) ? (0) : ((p)<=(10) ? (0)+((p)-(0))*((1)-(0))/((10)-(0)) : (1)))}" in out
    assert ".param a={2*b} c=3" in out
    assert ".param Rz={sqrt(4)}" in out


def test_laplace_sqrt_approximation():
    import numpy as np
    from pyltspice.sim.laplace import parse
    rf = parse("1/sqrt(1+1u*s)")
    for w in (1e5, 1e6, 1e7, 1e8, 1e9):
        s = 1j * w
        h = np.polyval([complex(c) for c in reversed(rf.num)], s) / \
            np.polyval([complex(c) for c in reversed(rf.den)], s)
        assert abs(20 * np.log10(abs(h)) - 20 * np.log10(abs(1 / np.sqrt(1 + 1e-6 * s)))) < 0.2


def test_models_are_scoped_to_their_subckt():
    from pyltspice.sim.adevices import rewrite_ideal_diodes
    lines = [".subckt A 1 2", "D1 1 2 X", ".model X D(Ron=10 Vfwd=.5)", ".ends A",
             ".subckt B 1 2", "D1 1 2 X", ".model X D(Ron=99 Vfwd=-2)", ".ends B"]
    out = rewrite_ideal_diodes(lines)
    assert "(0.5)" in out[1] and "(10)" in out[1]
    assert "(-2)" in out[5] and "(99)" in out[5]


def test_perfect_coupling_clamped():
    out = lines("K1 L1 L2 L3 1\nK2 L4 L5 1\n")
    assert "K1_01 L1 L2 0.9999" in out and "K2 L4 L5 0.9999" in out


def test_model_params_with_commas():
    """LTC.lib's LT1012 has '.model DC D(Ron=1k, Roff=1T  Vfwd=1 ilimit=332u)': LTspice accepts
    commas between parameters; a value must not keep the comma."""
    from pyltspice.sim.adevices import _model_params
    p = _model_params("D(Ron=1k, Roff=1T  Vfwd=1 ilimit=332u noiseless)")
    assert p == {"ron": "1k", "roff": "1T", "vfwd": "1", "ilimit": "332u"}
