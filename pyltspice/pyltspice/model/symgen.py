"""Automatic symbol generation for hierarchical sheets (Hierarchy > Open this Sheet's Symbol).

The sheet's I/O port labels become pins: inputs and bidirectional ports on the left,
outputs on the right, in name order."""
from pathlib import Path

from .asc import Schematic
from .textio import write_text


def sheet_ports(sch: Schematic):
    seen, ports = set(), []
    for f in sch.flags:
        if f.iopin and f.name.lower() not in seen:
            seen.add(f.name.lower())
            ports.append((f.name, f.iopin))
    return ports


def generate_symbol(sch: Schematic) -> str:
    ports = sheet_ports(sch)
    left = sorted([p for p in ports if p[1] != "Out"], key=lambda p: p[0].lower())
    right = sorted([p for p in ports if p[1] == "Out"], key=lambda p: p[0].lower())
    rows = max(len(left), len(right), 1)
    w, h = 128, 32 * rows + 32
    out = ["Version 4", "SymbolType BLOCK",
           f"RECTANGLE Normal {-w // 2} {-h // 2} {w // 2} {h // 2}",
           f"WINDOW 0 {-w // 2} {-h // 2 - 8} Left 2",
           f"WINDOW 3 {-w // 2} {h // 2 + 8} Left 2",
           "SYMATTR Prefix X"]
    order = 1
    for side, items in (("LEFT", left), ("RIGHT", right)):
        x = -w // 2 - 16 if side == "LEFT" else w // 2 + 16
        for i, (name, _) in enumerate(items):
            y = -h // 2 + 32 + 32 * i
            out += [f"PIN {x} {y} {side} 24", f"PINATTR PinName {name}", f"PINATTR SpiceOrder {order}"]
            out.append(f"LINE Normal {x} {y} {x + 16 if side == 'LEFT' else x - 16} {y}")
            order += 1
    return "\n".join(out) + "\n"


def write_symbol_for(path) -> Path:
    from .asc import load_asc
    path = Path(path)
    out = path.with_suffix(".asy")
    write_text(out, generate_symbol(load_asc(path)))
    return out
