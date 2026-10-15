# TuxSpice

TuxSpice is a native Linux schematic capture and waveform viewer that works with LTspice files.
It opens and saves LTspice `.asc` schematics and `.asy` symbols, uses the symbol and model libraries
from your own LTspice installer, and runs simulations with [ngspice](https://ngspice.sourceforge.io/).
It does not need Wine.

It is written in Python with PySide6 (Qt), pyqtgraph and numpy.

![TuxSpice simulating the OP113 example: transient waveforms of V(IN) and V(OUT) above the schematic](example.png)

> The Python package and command are still called `pyltspice`, so the commands below use that name.

## Features

- **Schematics**: renders LTspice schematics with symbols, rotated and mirrored text, junction dots,
  net labels, ground and I/O ports. All 4,365 bundled example schematics round-trip byte for byte,
  so files saved here still open in LTspice.
- **Editing**: LTspice-style editing modes (place, wire, label, move, drag, duplicate, rotate,
  mirror, delete), undo/redo, component browser, R/C/L and source editors, attribute editor,
  Edit Simulation Command dialog, and the LTspice default shortcuts (F2–F9, R/C/L/D/G/T/S, Ctrl+R/E).
- **Simulation**: netlists the schematic and translates the LTspice dialect for ngspice:
  - parasitics (`Rser`, `Cpar`, ...), one-argument `.tran`, `.lib`, default models, `table()`,
    LTspice functions (`u()`, `uramp()`, `rand()`, `random()`, `white()`, `mc()`, ...),
    frequency lists in `.ac`/`.noise`, hierarchical sheets
  - Laplace sources: rational functions, delays `exp(-sT)` and `sqrt()` terms (approximated to ~0.1 dB)
  - `wavefile=` sources, hysteretic-core (`Hc`/`Bs`/`Br`) and `Flux=` inductors
  - LTspice `A` devices: OTA, logic gates, flip-flops, Schmitt, sample-and-hold, modulator,
    varistor and phase detector
  - model-library quirks: per-subcircuit model scoping, LTspice ideal diodes and switch
    extensions, VDMOS defaults, perfect (k = 1) coupling
  - IGBTs are approximated by a MOSFET-plus-transistor equivalent circuit (with a warning).

  `.step` (linear, octave, decade, list) and `.meas` are handled by TuxSpice itself. Measurements
  can use earlier results, and are reported per step in the SPICE Error Log (Ctrl+L).
- **Waveforms**: stacked plot panes, colored trace labels, dB and phase for AC, a second axis for
  currents, trace arithmetic, average/RMS, cursors, FFT, and `.plt` plot settings.
- **Probing**: click a wire to plot its voltage, a part to plot its current, Alt-click a part to plot its power.

About 87% of the LTspice educational examples (71/82) simulate successfully. See
[`pyltspice/docs/PLAN.md`](pyltspice/docs/PLAN.md) for what still fails and why.

## Requirements

- Linux, Python 3.10 or newer
- ngspice (`sudo apt install ngspice`)
- 7z, to extract the libraries (`sudo apt install p7zip-full`)
- Your own copy of the LTspice installer, `LTspice64.msi`, which you can download from Analog Devices

## Installation

```sh
python3 -m venv .venv
.venv/bin/pip install -e pyltspice

# Extract the symbol/model libraries, examples and help pages from your installer
.venv/bin/python pyltspice/scripts/extract_msi.py LTspice64.msi
```

The libraries are extracted to `~/.local/share/pyltspice/ltspice_lib`. They stay on your machine;
TuxSpice does not include or redistribute any LTspice files.

To add a desktop launcher, an icon, and `.asc`/`.raw` file associations (writes only under
`~/.local/share`):

```sh
.venv/bin/python pyltspice/scripts/install_desktop.py           # install
.venv/bin/python pyltspice/scripts/install_desktop.py --remove  # uninstall
```

## Usage

```sh
pyltspice                     # new schematic
pyltspice circuit.asc         # open a schematic
pyltspice results.raw         # open a waveform file
python -m pyltspice ...       # same as above
```

### Configuration

| Variable | Purpose |
|---|---|
| `PYLTSPICE_DATA` | Data directory (default `~/.local/share/pyltspice`) |
| `PYLTSPICE_LIB` | Extracted library directory (default `<data>/ltspice_lib`) |
| `PYLTSPICE_NGSPICE` | Path to the ngspice binary (default: a copy in the data directory, then `/usr/bin/ngspice`) |

Colors and other preferences are stored in `~/.config/pyltspice`.

## Limitations

- Encrypted Analog Devices models (about 3,000 of the files in `lib/sub`) cannot be used and are
  reported as unsupported.
- The `COUNTER` A-device is not supported. The phase detector works on its own, but ngspice can stall
  inside some PLL loops (the PLL2 example).
- ngspice converges differently from LTspice, so a few circuits fail or need relaxed options.
  TuxSpice retries non-converging runs automatically, for at most 30 seconds per retry.
- Some circuits are slow in ngspice: the Electrometer example takes about 5 minutes. Use Halt
  to stop a run.

## Development

Run these from the `pyltspice/` directory:

```sh
../.venv/bin/pip install -e '.[test]'
../.venv/bin/python -m pytest -q                                # full test suite, ~6 s
../.venv/bin/python scripts/sim_example.py ../work <asc...>      # headless netlist + sim, OK/FAIL per file
../.venv/bin/python scripts/render_png.py <asc> <png>            # render a schematic to PNG
QT_QPA_PLATFORM=offscreen ../.venv/bin/python scripts/gui_smoke.py ...  # drive the GUI headlessly
```

Layout (inside `pyltspice/`):

| Path | Contents |
|---|---|
| `pyltspice/model/` | `.asc`/`.asy` formats, symbol library, netlister, edit operations |
| `pyltspice/sim/` | LTspice → ngspice translation, runner, `.raw` reader, `.meas`, FFT, A-device, Laplace, magnetics and `.wav` emulation |
| `pyltspice/ui/` | Qt main window, schematic editor, dialogs, waveform viewer |
| `scripts/` | Library extraction, desktop install, headless sim and rendering tools |
| `docs/PLAN.md` | Roadmap and status |
| `docs/ui_spec.md` | Every LTspice menu, shortcut and behavior with its implementation status |

### Clean-room policy

UI parity with LTspice comes only from LTspice's documented behavior (its help pages) and from
watching it run. Contributions must not decompile or disassemble `LTspice.exe` or copy its bitmaps.
Toolbar icons are drawn in code.

## Disclaimer

TuxSpice is an independent project. It is not affiliated with, endorsed by, or supported by
Analog Devices. LTspice is a trademark of Analog Devices, Inc.
