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
- **Encrypted models stay encrypted.** 2,990 of the 5,023 files in `lib/sub` are encrypted
  Analog Devices models. Never try to decrypt them. They are being replaced by behavioural clones
  fitted as black boxes to the user's own LTspice (section 1c). Clones are generated locally
  and never committed or redistributed. They back
  3,300 of 6,566 model-file symbols (nearly all ADC, DAC, switch and power parts; about 20% of
  op-amps; none in Contrib) and 3,322 of 4,365 examples (3,312 of them in Applications).
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
- [x] Dense traces (fast sources over long `.tran`, 10^5..10^7 points) draw per-pixel min/max of
      the visible range (`waveform.TraceCurve`): a 1 MHz pulse over 10 ms went from ~25 s per
      repaint (the window looked hung) to 0.3 s
- [x] Probing: click a wire for its voltage, a part for its current, Alt-click a part for its power

Phase 3 (editing):
- [x] Verb-noun editing modes: place, wire, label, ground, text/directive, delete, move, drag,
      duplicate, rotate, mirror; undo/redo
- [x] Dialogs: component browser, R/C/L editors, voltage/current source editor, attribute editor,
      Edit Simulation Command, net label, text
- [x] LTspice default shortcuts (F2–F9, R/C/L/D/G/T/S, Ctrl+R/E, Space)

Tests: 139 passing in about 15 s.

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
  orientation fix, Laplace, wavefile and hierarchy fixes → **79/82 (96%)** after the
  failing-examples pass (Electrometer only times out at 60 s; re-measure: `edu_sweep*.txt` in `work/`).

Open:
- Fixed in the "failing examples" pass:
  - stepnoise (`.noise ... list`), NonLinearTransformer (Chan hysteretic core, `sim/magnetics.py`,
    also `Flux=` inductors), PLL (`rand()`/`random()`/`white()`), IGBT (MOSFET+BJT equivalent,
    with a warning), HalfSlope (`sqrt()` in Laplace via a pole-zero ladder, ~0.1 dB),
    MeasureBW (`.meas` now evaluated in Python, `sim/measure.py`, chained results work).
  - relax and Howland: model cards are now scoped per `.subckt` (LTC.lib reuses names
    like `X` with different parameters), LTspice ideal diodes become smooth B sources, and VDMOS
    capacitances default to 0 as in LTspice.
  - Perfect coupling (k = 1) is clamped to 0.9999 for ngspice.
- Still open:
  - PLL2: the PHASEDET emulation (XSPICE flip-flops with hysteresis latches) is correct on its
    own, but ngspice's time step collapses inside this PLL's feedback loop.
  - Electrometer: works but takes about 5 minutes (1 MHz chopper simulated for 15 ms).
  - Royer: encrypted ADI model; can't run outside LTspice.

### 1a. Educational examples, re-measured after the Applications pass
- 79/82 top level, unchanged (Royer encrypted, Electrometer ~5 min, PLL2 stalls). Subfolders: 10
  FRA examples need encrypted models; PowerAmp fixed (diode `n=` = series devices); fra_eg1 uses
  LTspice's Frequency Response Analysis (`.fra` + `@` probe), now reported as unsupported.

### 1b. Applications examples (4,277), in progress
- `scripts/sweep_examples.py --static` classifies all examples: 3,322 need an encrypted ADI model
  (can't run outside LTspice), 1,043 don't.
- Of those 1,043: 608 ran at the start → **929** after this pass. Fixed: `vto=/dir=` threshold G
  clamps, `load` current sources, SpiceOrder gaps, `temp` in `{}`/`.param`, nested braces after
  `table()`, non-ASCII names (`M§Q6`), behavioral `R=`/`Q=`, comma-separated model params (LT1012),
  `NoJacob`, `smallsig()`, device currents in expressions (`Id(M3)`), parameter-style Value on
  model subckts (LTC1068), COUNTER.
- Still failing (114, by cause, from `work/s6.tsv`):
  - 28 "ngspice produced no output" and 12 timeouts at 60 s: convergence or slow runs; needs
    case-by-case work.
  - 12 numparam errors (`Undefined parameter [x]`, `[orn]`): expressions using names ngspice
    doesn't define.
  - 11 "not enough nodes" on MOS lines inside ADI macro-models.
  - 15 aborted runs and "impossible error" (ngspice internal) and 7 time-step failures.
  - 4 resistors with extra LTspice fields (`R n1 n2 5k -.1u 0 0p`), 4 `unknown subckt ltN-x.x`
    (a symbol naming a subckt the library doesn't define under that name), 3 `.machine`,
    2 `.timedomain` (LTspice-only commands), 2 `.tf` with a sweep argument, 2 diodes with `n=`.
  - 3 LT1964 variants whose model file isn't in the library at all.

### 1c. Behavioural clones of encrypted models (`pyltspice/clonegen/`), started 2026-10-27
Method: run each part's own example circuit in LTspice under Wine (as is, plus modified benches),
measure what the part does, fit a per-family TuxSpice template, then compare the clone in ngspice
against LTspice's waveforms. `ltcompat.clone_for` picks up `<data>/clones/<file>` automatically.

Inventory (`clonegen/inventory.py`, by symbol description; rough, refine per family):

| Family | Files | Examples |
|---|---|---|
| buck (590 monolithic SW-pin, 136 external-FET controllers, 86 µModules, 67 other) | 879 | 1,041 |
| other (supervisors, gate drivers, charge pumps, isolators, PoE...) | 515 | 580 |
| switch (analog switches/muxes, plus some misfiled switchers) | 351 | 381 |
| LDO | 247 | 335 |
| hot-swap / protection / ideal diode | 244 | 251 |
| boost | 204 | 208 |
| buck-boost / inverting / SEPIC | 169 | 176 |
| op-amp | 118 | 149 |
| charger, ADC, reference, LED, comparator, DAC | 64, 60, 61, 42, 18, 18 | 70, 66, 66, 44, 21, 17 |

Done:
- [x] LTspice batch runner under Wine, headless and parallel (`clonegen/ltspice.py`)
- [x] Pin-role mapper (`roles.py`), example-as-bench tooling, overlay plots (`bench.py`, `report.py`)
- [x] Step-down template (`buck.py`): peak current mode, XSPICE clock with RT law, soft-start/track
      pin or internal ramp, EN/UVLO hysteresis, start-up delay, sync/diode low side with a
      zero-current latch, burst/pulse skipping, PG window, INTVCC, boost diode, multi-channel
- [x] Fitter (`fit.py`): base, RT×1.5, overload (10 mΩ), 50× light load and EN-ramp benches
- [x] `.tran ... startup` now ramps top-level DC sources over 20 µs (was ignored; general fix)
- [x] Pilot LT8640: Vout 4.953 V vs LTspice 4.952 V, FB 0.968 V, f 994 kHz both, SS slope and
      start-up shape close, 11 s vs LTspice 7 s for 1 ms

Next, in order:
1. **Steady-state jitter** (LT8640): the clone's inductor peaks vary ±0.3 A cycle to cycle (LTspice:
   none) and Vout ripple is 34 mV p-p vs ~3 mV. Two causes feed each other: the peak-current
   reset is found with 30–180 ns steps, and the internal ITH node passes FB ripple through.
   A lower Cp pole alone didn't help. Try: a top-level PULSE breakpoint source at ~12× the fitted
   fsw (the XSPICE tick version cost 2.5×), a sampled/held ITH, then fit the loop to a
   load-step bench (gm, Rc, Cc against LTspice's Vout dip and recovery).
2. Start-up: `tdelay` should be measured from the UVLO crossing and the extrapolated SS start,
   not from a 2% crossing minus 20 µs. LTspice also shows a small FB bump right after the start.
3. Batch driver: `scripts/clone_models.py` to run inventory → fit → compare for a family in
   parallel (4 LTspice jobs, `--mem` cap on ngspice), resumable, writing a pass/fail table
   (Vout error, fsw error, run time) and overlay PNGs for failures.
4. Roll out to the 590 monolithic bucks, then controllers (TG/BG gate drive + external FETs),
   µModules (internal L: VOUT pin), boost, buck-boost, LDO, then the rest by example count.
5. Measure: re-run `sweep_examples.py` over the 3,322 encrypted-model examples and report
   how many run with clones, in PLAN and README.

Tools in `work/` used during the pilot (scratch, not part of the package): `cmp.py`, `fit_one.py`,
`regen.py`, `variant*.py`, `ngdump.py`, `ngcycles.py`.

### 2. UI parity, in progress
- `docs/ui_spec.md` lists every menu item, shortcut and behaviour with its source (help page or
  recollection) and status. Currently 45 done, 10 partial, 12 missing (one of them, Update
  components, not applicable).
- Done this round: waveform cursors with readout, `.op` data labels and hover values, Draw >
  Line/Rectangle/Circle/Arc, Zoom Back, Mark Unconnected Pins, the keyboard shortcut editor,
  Tools > Settings (drafting options), View > FFT, File > Export, `.plt` plot settings (auto-loaded
  after a run), Help change logs, and Hierarchy > Open this Sheet's Symbol.
- Wine round (LTspice 26.1.1 under Wine, see the **W** entries in `ui_spec.md`): default color palette
  for schematic and waveforms, Tahoma-28-bold schematic text, junction size, black waveform viewer
  with no grid, LTspice 26 toolbar order with redrawn icons, LTspice 26 default shortcuts (`.`
  directive, `S` stretch, `Z` zoom area, Alt+R run...), window tab strip, menu bar that swaps for
  waveform windows, Edit > Search, Mark Unconnected Pins on by default.
- Second Wine round, editing feel (TuxSpice driven side by side with LTspice on one nested display):
  part placement (carried by the middle, live name and pin squares, label relayout on rotate),
  wire drawing (leg order, first-leg commit, double right-click), pin-click wiring, cursors, probe
  hints with operating point, LTspice-layout dialogs (Component, Net Name, R/C/L with the part
  databases, source, text, analysis), post-run tiling and focus, shared-prefix plot ticks,
  toolbar pitch and grey disabled icons. Fixed: clicks inside a part's body didn't hit it.
- Third Wine round, menus and settings (2026-10-16): every menu captured from LTspice 26.1.1 (three
  menu bars, all submenus, both right-click menus) and rebuilt item for item in `ui/menus.py`, with
  icons; keys that LTspice reuses (C capacitor vs. cursor, P component vs. pane, Del, Ctrl+Z...)
  follow the active window. Tools > Settings now has LTspice's ten tabs with its defaults and [*]
  persistence; options with an ngspice/TuxSpice meaning work, the rest are greyed with a reason.
  New commands: Print Preview/Setup/Monochrome, Recenter, Mark Anchors, BOM on schematic/clipboard,
  Set Probe Reference, Clear Waveforms, Generate Subckt Netlist, Export Netlist (PCB), Write image
  (SVG/PNG), Arrange Icons, Float Window, Show .op Data Flags; in plots: pane above/below/up/down/
  delete, Sync Horiz. Axes, Select Steps, Place/Clear Cursors, Redraw, Reset Colors, Mark Data
  Points, Manual Limits, Autoranging, trace undo/redo, Delete Traces mode, Notes & Annotations
  (text, arrow, line, rectangle, ellipse, cursor position), Open/Reload Plot Settings, Plot Defs
  file, Execute .MEAS Script, degree-based trig in expressions (LTspice's default).
- MCP (2026-10-16): LTspice 26.1's MCP server mirrored after querying its bridge under Wine:
  `pyltspice-mcp` (stdio, no dependencies) with the same 17 tools and reply format, GUI-attached
  through a localhost host in the window (edits are undo steps) or headless, LTspice's AI
  reference docs from `reference.zip`, and Tools > Configure Third-Party AI Assistants for
  Claude Code/Desktop, Cursor and VS Code. Then made reply-compatible with LTspice's bridge by
  diffing ~100 calls against it (`scripts/mcp_diff.py`): JSON format, error texts, step/complex
  shapes, SQLite DDL, attach/status. That diff also exposed zero R/C/L currents in `.ac` runs
  (ngspice), now fixed with sense sources (16/16 Educational and 60/60 Applications `.ac`
  examples still pass). Possible next steps: an MCP tool to place/move parts
  through the editor instead of raw `.asc` text, and stepped runs written to `.raw` (results of
  `.step` runs live only in memory, so a fresh headless session can't read them from disk).
- Edit > Paste (Ctrl+V), per the help: Duplicate puts what it picks on the clipboard as `.asc`
  text (`application/x-tuxspice-asc`), so it pastes into another schematic or TuxSpice window;
  parts are renamed on a clash. Fixed on the way: a Python-made QMimeData left on the clipboard
  segfaulted the process at exit (Qt frees it after Python finalizes); it's released in `atexit`.
- Notes & Annotations > Annotate Phase Margin / Gain Margin / Steps (`waveform.phase_margin`,
  `gain_margin`): every AC trace (and shown `.step` run) of the active pane gets a marker and
  label; crowded labels move to the nearest free row.
- Plot annotations are `waveform.Note` data (redrawn from view coordinates): plot Edit > Move,
  Stretch (nearest end/corner), Duplicate and Delete work on them, and Plot Settings > Undo/Redo
  covers them along with the traces.
- Next from Wine: still greyed: symbol editor, buses (BUS tap), marching waveforms,
  efficiency report/calculation, eye diagram, Nyquist unit circle. Also Windows-style blue MDI title bars, the
  bottom of the Plot Settings menu (scrolled off the 900 px Wine screen: use a taller Xephyr),
  and checking the editing dialogs (component, analysis) against LTspice.

### 3. Remaining features
- Done: memory cap on every ngspice run (`runner.memory_limit`: 60 % of free RAM, or
  `PYLTSPICE_NGSPICE_MEM`), and `sweep_examples.py --mem` (1.5 GB per job, jobs sized to free RAM).
  A runaway run (LT6106.asc grew to 13.5 GB) on this swapless 15 GB machine made the OOM killer
  take the terminal down; now ngspice fails with "ran out of memory" instead. LT6106 itself still
  needs a look (likely a collapsing time step piling up points with `savecurrents`).
- Done: quality-of-life extras on top of LTspice (README "What TuxSpice adds", ui_spec "TuxSpice
  extras"): circuit check before runs (no example schematic is blocked: 0 errors over all 4,365),
  explained ngspice errors in a Problems panel, automatic waveform measurements, step legend and
  .meas histograms, PNG/SVG/CSV plot export with a report style, vendor model files placed with a
  generated symbol, autosave/crash recovery, desktop notifications. Possible next ones: overlay
  of the previous run's traces, .param sliders that re-run, reload when the .asc changes on disk,
  a visual diff of two schematic revisions.
- Symbol editor for `.asy` files (File > New Symbol, Edit > Add Pin/Port).
- Colour dialog that works by clicking a sample schematic like LTspice's.
- Plot settings: axis ranges and colours from `.plt`.
- LTspice-only analysis forms: `.step` over model parameters and temperature, `.wave`, `.net`.
- Efficiency report, `.wav` export, more PCB netlist formats (LTspice has ~20; we write 4).

- Done: TuxSpice's own model library (`pyltspice/data/models`, symbols in `data/sym/OpAmps`): 16
  BJTs, 26 diodes/zeners/LEDs, 12 MOSFETs, 5 JFETs and 13 op-amps that LTspice's libraries lack,
  plus the BC107/177/237/307/546 families (70, with A/B/C gain groups) and germanium parts
  (15 transistors, 7 diodes; `type=germanium`, searchable in the picker),
  fitted to datasheet typicals and simulated against them in `tests/test_models.py`. Found by
  name like `standard.*` (LTspice's cards win a clash). "Pick New Transistor/Diode/MOSFET/JFET"
  lists both libraries. Next: darlingtons (TIP120/122 need a subckt symbol), comparators
  (LM393/LM339), 555 timer, LM317/78xx regulators.

- Done: the greyed Settings now work (see the Settings rows in `ui_spec.md`): run options
  travel as `runner.RunOptions` (built by `settings_dialog.run_options()`, used by the GUI and
  the MCP headless runner); pin shorts, subfolder search, ortho stretch and cut angled wires are
  editing behaviour. Note: Save Defaults now hides subcircuit internals by default, as LTspice
  does; re-run `scripts/mcp_diff.py` against LTspice before relying on MCP vector lists.

- Done: dark and GTK themes (`ui/appearance.py`): icons are drawn for a light toolbar and restyled
  on dark palettes like dark icon themes do: greys inverted (white strokes, dark fills), colours
  kept saturated and only lightened to 4.5:1, blues moved to an azure accent (plain lightening
  looked washed out). Redrawn when the palette flips, hidden windows on show; toolbar tints from the palette; dark palette when the desktop prefers dark but Qt
  didn't apply it; Settings > Operation > Application theme. Checked with the real Mint-L-Dark
  GTK theme (`QT_QPA_PLATFORMTHEME=gtk3`). Margin labels restack on resize/zoom.

### 4. Packaging
- Done: `.desktop` file, icon and MIME types for `.asc`/`.raw` (`scripts/install_desktop.py`).
- Done: first-run setup (`ui/setup_dialog.py`, `setup_lib.py`): finds `LTspice*.msi` in Downloads,
  Desktop, home and the working directory (one level down), extracts it on a worker thread
  (~2 s), and also appears when Component (P) needs a missing library.

## How we check it works

- `../.venv/bin/python -m pytest -q`: format round-trips, geometry, netlists, translation, simulations
  checked against hand-computed RC results, `.step`, GUI editing driven by synthetic mouse events.
- `scripts/sim_example.py ../work <files>`: compatibility pass rate across the bundled examples.
- `scripts/render_png.py` and `scripts/gui_smoke.py`: screenshots for visual review, and later
  side-by-side comparison with LTspice under Wine.
