from pyltspice import config
from pyltspice.model.asc import load_asc, parse_asc
from pyltspice.model.textio import read_text

from .conftest import needs_lib

SAMPLE = """Version 4
SHEET 1 880 680
WIRE 128 96 32 96
FLAG 32 176 0
FLAG 128 96 out
IOPIN 128 96 Out
SYMBOL res 112 80 R0
WINDOW 0 36 40 Left 2
SYMATTR InstName R1
SYMATTR Value 1k
TEXT 32 216 Left 2 !.tran 1m
TEXT 32 240 Left 2 ;a comment\\nsecond line
"""


def _norm(t):
    return [" ".join(l.split()) for l in t.splitlines() if l.strip()]


def test_parse_and_write_back():
    sch = parse_asc(SAMPLE)
    assert len(sch.wires) == 1 and len(sch.symbols) == 1
    assert sch.flags[1].iopin == "Out"
    assert sch.symbols[0].attrs == {"InstName": "R1", "Value": "1k"}
    assert sch.texts[0].is_directive and sch.texts[1].body == "a comment\nsecond line"
    assert _norm(sch.to_text()) == _norm(SAMPLE)


@needs_lib
def test_roundtrip_all_examples():
    bad = []
    for p in sorted(config.EXAMPLES_DIR.rglob("*.asc")):
        if _norm(read_text(p)[0]) != _norm(load_asc(p).to_text()):
            bad.append(p.name)
    assert not bad, bad[:10]
