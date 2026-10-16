from pyltspice.model.asc import Flag, Schematic, SymbolInst, Text, Wire
from pyltspice.model.edit import cleanup_wires
from pyltspice.model.library import default_library
from pyltspice.model.netlist import connectivity, generate_netlist

from .conftest import needs_lib


def rc_lowpass():
    """V1 -> R1 -> out, C1 to ground (resistor pins at (16,16)/(16,96) from origin)."""
    items = [
        SymbolInst("voltage", 0, 0, "R0", {}, {"InstName": "V1", "Value": "AC 1"}),
        SymbolInst("res", 96, -16, "R90", {}, {"InstName": "R1", "Value": "1k"}),
        SymbolInst("cap", 112, 0, "R0", {}, {"InstName": "C1", "Value": "1u"}),
        Wire(0, 16, 0, 0), Wire(0, 0, 0, 0),
        Wire(0, 0, 16, 0),
        Wire(80, 0, 128, 0),
        Flag(0, 96, "0"), Flag(128, 64, "0"), Flag(128, 0, "out"),
        Text(0, 140, "Left", 2, "!.ac dec 20 1 1Meg"),
    ]
    return Schematic(items=items)


@needs_lib
def test_rc_netlist():
    sch = rc_lowpass()
    nl = generate_netlist(sch)
    lines = nl.text.splitlines()
    assert "V1 N001 0 AC 1" in lines
    assert "R1 out N001 1k" in lines           # R90: pin 1 is on the right
    assert "C1 out 0 1u" in lines
    assert ".ac dec 20 1 1Meg" in lines
    assert not nl.errors


@needs_lib
def test_unconnected_pin_named_nc():
    sch = Schematic(items=[SymbolInst("res", 0, 0, "R0", {}, {"InstName": "R1", "Value": "1"})])
    line = [l for l in generate_netlist(sch).text.splitlines() if l.startswith("R1")][0]
    assert line == "R1 NC_01 NC_02 1"


@needs_lib
def test_t_junction_connects_and_dots():
    sch = Schematic(items=[Wire(0, 0, 64, 0), Wire(32, 0, 32, 32), Flag(0, 0, "A"), Flag(32, 32, "B")])
    conn = connectivity(sch)
    assert conn.net_at(32, 32) == conn.net_at(0, 0) == "A"
    assert (32, 0) in conn.junctions


@needs_lib
def test_wire_through_resistor_is_cut():
    # a wire drawn straight across a vertical resistor must not short it
    sch = Schematic(items=[SymbolInst("res", 0, 0, "R0", {}, {"InstName": "R1", "Value": "1"}),
                           Wire(16, -32, 16, 128)])
    cleanup_wires(sch, default_library())
    segs = sorted((w.y1, w.y2) for w in sch.wires)
    assert segs == [(-32, 16), (96, 128)]


@needs_lib
def test_subckt_value2_rules():
    # SpiceModel names a file -> Value2 holds the subckt name
    sch = Schematic(items=[SymbolInst("OpAmps\\\\UniversalOpAmp2", 0, 0, "R0", {}, {"InstName": "U1"})])
    line = [l for l in generate_netlist(sch).text.splitlines() if l.startswith("XU1")][0]
    assert " level2 Avol=1Meg" in line


@needs_lib
def test_mirrored_rotated_part_connects():
    # SYMBOL res -192 160 M90 sits between two wire ends; a wrong M90 left it unconnected
    from pyltspice import config
    from pyltspice.model.asc import load_asc
    p = config.EXAMPLES_DIR / "Educational" / "IdealTransformer.asc"
    lines = generate_netlist(load_asc(p)).text.splitlines()
    rin = next(l for l in lines if l.startswith("Rin"))
    assert "NC_" not in rin and rin.split()[1:3] == ["N001", "IN"]


@needs_lib
def test_hierarchical_sheet(tmp_path):
    """parent.asc uses block 'half' implemented by half.asc (a 1:1 divider)."""
    from pyltspice.model.asc import load_asc
    from pyltspice.model.library import SymbolLibrary
    from pyltspice.model.symgen import write_symbol_for
    half = Schematic(items=[
        SymbolInst("res", 0, 0, "R0", {}, {"InstName": "R1", "Value": "1k"}),
        SymbolInst("res", 0, 96, "R0", {}, {"InstName": "R2", "Value": "1k"}),
        Flag(16, 16, "IN", "In"), Flag(16, 96, "OUT", "Out"), Flag(16, 192, "0"),
        Wire(16, 96, 16, 112)])
    half.save(tmp_path / "half.asc")
    write_symbol_for(tmp_path / "half.asc")
    parent = Schematic(items=[
        SymbolInst("voltage", 0, 0, "R0", {}, {"InstName": "V1", "Value": "2"}),
        SymbolInst("half", 200, 0, "R0", {}, {"InstName": "U1"}),
        Flag(0, 16, "a"), Flag(0, 96, "0"), Text(0, 200, "Left", 2, "!.op")])
    parent.path = tmp_path / "parent.asc"
    lib = SymbolLibrary()
    sym = lib.get("half", [tmp_path])
    # connect the block's ports by label: IN pin to 'a', OUT pin to 'b'
    from pyltspice.model.netlist import symbol_pins
    for pr in symbol_pins(parent.symbols[1], sym):
        parent.items.append(Flag(*pr.point, "a" if pr.pin.name == "IN" else "b"))
    nl = generate_netlist(parent, lib)
    text = nl.text.splitlines()
    assert "XU1 a b half" in text
    assert ".subckt half IN OUT" in text and ".ends half" in text
    assert not nl.errors, nl.errors


@needs_lib
def test_library_symbol_is_not_hierarchical():
    # examples/Educational/opamp.asc uses the library 'opamp' symbol; it must not become
    # a subcircuit of itself
    from pyltspice import config
    from pyltspice.model.asc import load_asc
    t = generate_netlist(load_asc(config.EXAMPLES_DIR / "Educational" / "opamp.asc")).text
    assert ".subckt" not in t.lower()


@needs_lib
def test_order_gaps_and_value_parameters():
    """ADG919's symbol skips SpiceOrder 6-7 of an 8-port subckt; LTC1068-200 keeps its
    parameters (Fclk=...) in Value while SpiceModel names the subckt."""
    from pyltspice.model.asc import Schematic, SymbolInst
    from pyltspice.model.netlist import generate_netlist
    sch = Schematic(items=[SymbolInst("ADG919", 0, 0, "R0", {}, {"InstName": "U1"}),
                           SymbolInst("LTC1068-200", 400, 0, "R0", {}, {"InstName": "U2"})])
    lines = generate_netlist(sch).text.splitlines()
    u1 = next(l for l in lines if l.startswith("XU1")).split()
    assert len(u1) == 1 + 8 + 1 and u1[6:8] == ["NC_U1_6", "NC_U1_7"]
    u2 = next(l for l in lines if l.startswith("XU2"))
    assert u2.split()[-1] == "Fclk=500K" and "LTC1068-200" in u2
