#!/usr/bin/env python3
"""Netlist + simulate schematics headlessly; print a one-line status for each."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pyltspice.model.asc import load_asc  # noqa: E402
from pyltspice.model.netlist import generate_netlist  # noqa: E402
from pyltspice.sim.runner import Simulator  # noqa: E402

out_dir = Path(sys.argv[1])
for f in sys.argv[2:]:
    p = Path(f)
    nl = generate_netlist(load_asc(p))
    r = Simulator(nl.text, out_dir / p.stem, [p.parent]).run()
    mp = r.main_plot()
    shape = None if mp is None else mp.data.shape
    print(f"{'OK  ' if r.ok else 'FAIL'} {p.name} {shape} {r.errors[:2]}")
