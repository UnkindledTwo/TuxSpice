# pyltspice plan

## Goal

A native Linux, Python clone of LTspice whose interface matches LTspice as closely as possible.
It opens and saves LTspice `.asc` schematics, uses the symbol and model libraries from the user's
own `LTspice64.msi`, and simulates with ngspice.

## Ground rules

- **Clean-room UI parity.** Match LTspice from its bundled help pages and by watching LTspice run
  under Wine. Never decompile or disassemble `LTspice.exe`: the license forbids it, and decompiled
  output wouldn't give usable source anyway. Don't copy its bitmaps; icons are drawn in code.
- **Libraries stay local.** `scripts/extract_msi.py` unpacks the user's installer into
  `~/.local/share/pyltspice/ltspice_lib`. Nothing from it is committed or redistributed.
- **Encrypted models stay encrypted.** About 3,000 of the ~5,000 files in `lib/sub` are encrypted
  Analog Devices models. Report them as unsupported and never try to decrypt them.
- **Keep files compatible with LTspice.** A schematic saved here must still open in LTspice. The
  test suite round-trips every bundled example to guard this.

## Architecture

| Layer | Modules | Job |
|---|---|---|
| File formats | `model/asc.py`, `asy.py`, `textio.py`, `library.py` | Read and write schematics and symbols, find symbols by name |
| Circuit model | `model/netlist.py`, `edit.py`, `geometry.py` | Connectivity, netlist generation, move/rotate/mirror, wire cleanup |
| Simulation | `sim/ltcompat.py`, `runner.py`, `rawfile.py`, `vectors.py` | Translate LTspice netlists for ngspice, run them (including `.step`), read results |
| GUI | `ui/*` | Main window, schematic editor, dialogs, waveform viewer |

## Done

Phase 1 (viewer):
- [x] Extract libraries, examples and help from the MSI
- [x] `.asc`/`.asy` parsers; all 4,365 example schematics round-trip exactly
- [x] Schematic rendering: symbols, rotated and mirrored text, junction dots, net labels, ground,
      I/O ports

Phase 2 (simulation):
- [x] Netlister: T-junctions, named nets, `NC_xx` pins, jumpers, Value/Value2/SpiceModel rules
- [x] LTspice-to-ngspice translation: parasitics (`Rser`/`Cpar`...), one-argument `.tran`, `.lib`,
      default and standard models, 3-terminal MOSFETs, `µ`, `pi`, UTF-16 libraries
- [x] Runner with our own `.step` support (linear, octave, decade, list); `.meas` results in the log
- [x] Waveform viewer: stacked panes, coloured trace labels, dB and phase for AC, a second axis for
      currents, Add Traces dialog, arithmetic on traces, average/RMS
- [x] Probing: click a wire for its voltage, a part for its current, Alt-click a part for its power

Phase 3 (editing):
- [x] Verb-noun editing modes: place, wire, label, ground, text/directive, delete, move, drag,
      duplicate, rotate, mirror; undo/redo
- [x] Dialogs: component browser, R/C/L editors, voltage/current source editor, attribute editor,
      Edit Simulation Command, net label, text
- [x] LTspice default shortcuts (F2–F9, R/C/L/D/G/T/S, Ctrl+R/E, Space)

Tests: 24 passing in about 3 s.

## Next steps, in priority order

### 1. LTspice compatibility (A devices and dialect), mostly done
Done:
- `sim/adevices.py`: OTA as B sources; gates and D/SR flip-flops as XSPICE models; Schmitt,
  sample-and-hold, modulator and varistor as behavioural approximations.
- `sim/laplace.py`: `Laplace=` sources that are ratios of polynomials in s, optionally times a
  pure delay `exp(-sT)`, become an integrator chain (DC, AC and transient all correct).
- Translation of LTspice-only syntax, both in the netlist and in included libraries (cached under
  `<data>/cache/libs`; bump `LIB_CACHE_VERSION` when the rewrite changes):
  - `table()`, `.param X expr` without `=`, `.params`, `sqrt (x)` with a space, inline `;` comments
  - C/L parasitics, B-source `Rpar`/`Cpar`, multi-inductor `K` statements, switch extensions
  - `u()`, `uramp()`, `mc()`, `flat()`, `gauss()` and similar, defined as `.func` when used
  - parameters an instance passes that its subcircuit never declares
- Netlister:
  - Mirrored orientations fixed (M90/M270 were swapped).
  - Wires running under a part are cut at its pins, as LTspice does.
  - `A` symbols are padded to 8 terminals, and hierarchical sheets are netlisted as `.subckt`.
- Runner: convergence retries capped at 120 s each, and a run with no data counts as a failure.
- Educational examples: 41/82 at the start of this work → 55 → 62 → **71/82 (87%)** after the
  orientation fix, Laplace, wavefile and hierarchy fixes (re-measure: `edu_sweep*.txt` in `work/`).

Open:
- Still failing (11): convergence in relax, Howland, Electrometer (time-step collapses at the first
  fast edge); HalfSlope (`sqrt()` in Laplace); IGBT (no IGBT model in ngspice); MeasureBW (chained
  `.meas`); NonLinearTransformer; PLL (`rand()`); PLL2 (PHASEDET); Royer (encrypted model);
  stepnoise (noise-analysis parameter).
- Not supported yet: `sqrt()` in Laplace (HalfSlope), PHASEDET/COUNTER A-devices (behaviour
  undocumented), `.meas` results reused in later `.meas` statements (MeasureBW), IGBT models.
- Done since: `wavefile=` sources (`sim/wavefile.py`, via XSPICE filesource), Laplace delays.

### 2. UI parity, in progress
- `docs/ui_spec.md` lists every menu item, shortcut and behaviour with its source (help page or
  recollection) and status.
- Done this round: waveform cursors with readout, `.op` data labels and hover values, Draw >
  Line/Rectangle/Circle/Arc, Zoom Back, Mark Unconnected Pins, the keyboard shortcut editor,
  Tools > Settings (drafting options), View > FFT, File > Export, `.plt` plot settings (auto-loaded
  after a run), Help change logs, and Hierarchy > Open this Sheet's Symbol.
- Blocked on you: installing Wine (`sudo apt install wine`) so the spec's "recollection"
  entries, colours and fonts can be checked against real LTspice.

### 3. Remaining features
- Symbol editor for `.asy` files (File > New Symbol, Edit > Add Pin/Port).
- Settings: symbol/library search paths, waveform font; colour dialog that works by clicking a
  sample schematic like LTspice's.
- Plot settings: axis ranges and colours from `.plt`; trace-selection undo.
- LTspice-only analysis forms: `.step` over model parameters and temperature, `.wave`, `.net`.
- Efficiency report, PCB netlist export, `.wav` export.

### 4. Packaging
- `.desktop` file, icon and MIME types for `.asc`/`.raw`.
- First-run wizard that finds `LTspice64.msi` and extracts it.

## How we check it works

- `../.venv/bin/python -m pytest -q`: format round-trips, geometry, netlists, translation, simulations
  checked against hand-computed RC results, `.step`, GUI editing driven by synthetic mouse events.
- `scripts/sim_example.py ../work <files>`: compatibility pass rate across the bundled examples.
- `scripts/render_png.py` and `scripts/gui_smoke.py`: screenshots for visual review, and later
  side-by-side comparison with LTspice under Wine.
