"""Tools > Export Netlist: ASCII netlists for PCB layout tools.

LTspice offers about twenty formats (see help/pcbnetlistextraction.htm); TuxSpice writes the most
common ones. Pins are numbered by SpiceOrder, as LTspice does, so the PCB symbols need the same pin
order as the LTspice symbols. The footprint is the part's Footprint attribute if it has one,
otherwise the symbol name.
"""
from .asc import Schematic
from .library import SymbolLibrary, default_library, schematic_dirs
from .netlist import connectivity, symbol_pins

FORMATS = {"Tango": ".net", "PADS": ".asc", "Allegro (Telesis)": ".net", "Wire List": ".txt"}


def _parts_and_nets(sch: Schematic, lib: SymbolLibrary):
    local = schematic_dirs(sch.path)
    conn = connectivity(sch, lib)
    parts, nets = [], {}
    for inst in sch.symbols:
        sym = lib.get(inst.symbol, local)
        if sym is None or not sym.pins:
            continue
        ref = inst.name or "?"
        foot = inst.attrs.get("Footprint") or sym.attrs.get("Footprint") or \
            inst.symbol.replace("\\\\", "\\").split("\\")[-1]
        value = inst.attrs.get("Value") or sym.attrs.get("Value", "")
        parts.append((ref, foot, value))
        for pr in symbol_pins(inst, sym):
            net = conn.net_of_point.get(pr.point)
            if net is None:
                continue
            net = "GND" if net == "0" else net
            nets.setdefault(net, []).append((ref, str(pr.pin.order)))
    return parts, nets


def export(sch: Schematic, lib: SymbolLibrary | None = None, fmt="Tango") -> str:
    parts, nets = _parts_and_nets(sch, lib or default_library())
    out = []
    if fmt == "Tango":
        for ref, foot, value in parts:
            out += ["[", ref, foot, value, "", "", "]"]
        for net, pins in sorted(nets.items()):
            out += ["(", net] + [f"{r}-{p}" for r, p in pins] + [")"]
    elif fmt == "PADS":
        out.append("*PADS-PCB*")
        out.append("*PART*")
        out += [f"{ref} {foot}" for ref, foot, _ in parts]
        out.append("*NET*")
        for net, pins in sorted(nets.items()):
            out.append(f"*SIGNAL* {net}")
            out.append(" ".join(f"{r}.{p}" for r, p in pins))
        out.append("*END*")
    elif fmt == "Allegro (Telesis)":
        out.append("$PACKAGES")
        out += [f"'{foot}' ! '{value}' ; {ref}" for ref, foot, value in parts]
        out.append("$NETS")
        for net, pins in sorted(nets.items()):
            out.append(f"'{net}' ; " + " ".join(f"{r}.{p}" for r, p in pins))
        out.append("$END")
    else:                                   # Wire List
        out.append("Wire List")
        out.append("")
        out.append("<<< Component List >>>")
        out += [f"{value:<20}{ref:<12}{foot}" for ref, foot, value in parts]
        out.append("")
        out.append("<<< Wire List >>>")
        for net, pins in sorted(nets.items()):
            out.append(f"[{net}]")
            out += [f"        {r:<12}{p}" for r, p in pins]
    return "\n".join(out) + "\n"
