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
- **Looks and feels like LTspice 26** (checked side by side against LTspice running under Wine):
  its default colors and fonts, toolbar order and redrawn icons, menus that switch between
  schematic and waveform windows, window tabs, mode cursors, status-bar hints and dialog layouts.
- **Editing**: LTspice-style editing modes (place, wire, label, move, stretch, duplicate, rotate,
  mirror, delete, zoom area, search), undo/redo, LTspice's own placement and wiring behavior
  (parts carried by their middle, labels kept upright on rotation, click an open pin to start a
  wire), the component browser, R/C/L editors with "Select Resistor/Capacitor/Inductor" from
  LTspice's part databases, source, net-label, text and analysis dialogs, the attribute editor,
  and LTspice 26's default shortcuts (W/G/V/R/C/L/D/P/N/T, `.` directive, S stretch, Z zoom
  area, Alt+R run; XVII's F2–F9 still work).
- **Simulation**: netlists the schematic and translates the LTspice dialect for ngspice:
  - parasitics (`Rser`, `Cpar`, ...), one-argument `.tran`, `.lib`, default models, `table()`,
    LTspice functions (`u()`, `uramp()`, `rand()`, `random()`, `white()`, `mc()`, ...),
    frequency lists in `.ac`/`.noise`, hierarchical sheets
  - Laplace sources: rational functions, delays `exp(-sT)` and `sqrt()` terms (approximated to ~0.1 dB)
  - `wavefile=` sources, hysteretic-core (`Hc`/`Bs`/`Br`) and `Flux=` inductors
  - every LTspice `A` device: OTA, logic gates, flip-flops, Schmitt triggers (incl. differential),
    sample-and-hold, modulator/VCO, varistor, phase detector and counter
  - model-library quirks: per-subcircuit model scoping, LTspice ideal diodes and switch
    extensions, VDMOS defaults, perfect (k = 1) coupling, threshold `G` clamps (`vto=`/`dir=`),
    `load` current sources, behavioral `R=`/`Q=` elements, device currents such as `Id(M3)` in
    expressions, `temp` and `smallsig()` in expressions, nested `{}` braces, symbols that skip
    pin numbers
  - ngspice-only analyses LTspice lacks: `.pz` (pole-zero table) and `.disto` (2nd/3rd harmonic
    distortion plots)
  - IGBTs are approximated by a MOSFET-plus-transistor equivalent circuit (with a warning).

  `.step` (linear, octave, decade, list) and `.meas` are handled by TuxSpice itself. Measurements
  can use earlier results, and are reported per step in the SPICE Error Log (Ctrl+L).
- **Waveforms**: stacked plot panes, colored trace labels, dB and phase for AC, a second axis for
  currents, trace arithmetic, average/RMS, cursors, FFT, and `.plt` plot settings.
- **Probing**: click a wire to plot its voltage, a part to plot its current, Alt-click a part to plot its power.

### How many LTspice examples run

| Example set | Result |
|---|---|
| Educational (82) | EDU_RESULT |
| Applications (4,277) | 3,322 need an encrypted ADI model (see Limitations). Of the other 1,043, **929 (89%)** simulate; 102 fail and 12 time out at 60 s |

[`pyltspice/docs/PLAN.md`](pyltspice/docs/PLAN.md) lists what still fails and why.

## How TuxSpice compares

| | TuxSpice | LTspice | ngspice | KiCad |
|---|---|---|---|---|
| Runs natively on Linux | yes | no (Windows/macOS; Wine on Linux) | yes | yes |
| Schematic editor | yes, LTspice-style | yes | no (text netlists only) | yes, KiCad-style |
| Opens/saves LTspice `.asc`/`.asy` unchanged | yes, byte for byte | yes | no | imports `.asc` into its own format (KiCad 8+), doesn't save `.asc` |
| Uses LTspice's symbol/model libraries | yes (from your installer) | yes | by hand, many models need edits | by hand |
| LTspice dialect (A-devices, Rser/Cpar, `table()`, Laplace, `.step`, `.meas`...) | translated for ngspice | native | partly (`ngbehavior=lt`) | via ngspice, partly |
| Encrypted ADI models | no | yes | no | no |
| Simulation engine | ngspice | LTspice's own | itself | ngspice |
| Waveform viewer | LTspice-style, `.raw` files | yes | basic plots | yes |
| PCB layout | no | no | no | yes |

- **Compared with ngspice**: ngspice is only the simulator (a command-line program that reads
  netlists), and TuxSpice uses it underneath. On top of it, TuxSpice provides the schematic
  editor and waveform viewer, and a translation layer that makes LTspice schematics and vendor
  model libraries run unmodified. That layer handles LTspice-only devices and syntax, ADI
  macro-model quirks, `.step`/`.meas` (done by TuxSpice), and smoothing and retries where
  ngspice converges differently. You also get ngspice's own extras, such as `.pz` and `.disto`.
- **Compared with KiCad**: KiCad is a full schematic-to-PCB suite whose simulator also uses
  ngspice. It has its own schematic format, symbol libraries and SPICE model assignment, and it
  can import LTspice schematics, but it doesn't edit them as LTspice files and doesn't use
  LTspice's libraries and dialect directly. TuxSpice does one thing: it is a drop-in LTspice
  work-alike for Linux. Your `.asc` files stay LTspice files, and the libraries, shortcuts and
  workflow are LTspice's. It has no PCB layout.
- **Compared with LTspice**: same files, same libraries, same editing model, but a different
  simulator. Results usually match closely but not exactly, encrypted ADI models can't run,
  and some circuits are slower in ngspice.

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

- Encrypted Analog Devices models (about 3,000 of the files in `lib/sub`, needed by 3,322 of the
  bundled examples) only run inside LTspice. TuxSpice reports them as unsupported and doesn't
  decrypt them.
- `COUNTER` is undocumented in LTspice and no example uses it; TuxSpice models it as a clock
  divider (`cycles=` sets the ratio). The phase detector works on its own, but ngspice can stall
  inside some PLL loops (the PLL2 example).
- Some LTspice-only commands are not available: `.machine` state machines, `.timedomain`, the
  Transient Frequency Response analysis, efficiency reports, `.wave` export.
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
../.venv/bin/python scripts/sweep_examples.py ../work/out.tsv <dir|asc...>  # parallel compatibility sweep
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
