# CLAUDE.md

## Project

`pyltspice/` is a native Linux, LTspice-compatible schematic capture and waveform viewer
(PySide6 + pyqtgraph + numpy). It reads and writes LTspice `.asc`/`.asy` files and simulates
with **ngspice**, not LTspice.

- `LTspice64.msi`: the user's own LTspice installer. Its symbol/model libraries, examples and
  help are extracted locally and never redistributed or committed.
- `work/`: scratch output from batch sims (`*.ngspice.cir`, `*.log`, `*.raw`, screenshots). It is disposable.
- `.venv/`: the project virtualenv. Use `../.venv/bin/python` from inside `pyltspice/`.

## Layout (`pyltspice/pyltspice/`)

- `config.py`: data paths. Library at `~/.local/share/pyltspice/ltspice_lib` (`lib/sym`, `lib/sub`,
  `lib/cmp`, `examples`, `help`). Env overrides: `PYLTSPICE_DATA`, `PYLTSPICE_LIB`, `PYLTSPICE_NGSPICE`.
- `model/`: file formats and the data model: `asc.py` (schematic load/save, round-trips byte-for-byte
  modulo normalization), `asy.py` (symbols), `library.py`, `netlist.py` (schematic → SPICE netlist),
  `edit.py` (edit ops / undo), `geometry.py`, `textio.py` (encoding detection).
- `sim/`: `ltcompat.py` translates LTspice netlist dialect → ngspice (parasitics like Rser/Cpar,
  1-arg `.tran`, `.lib`, default models, dropped options/params, µ suffix). `runner.py` runs ngspice
  with `set ngbehavior=ltpsa` + binary raw output and implements `.step` itself. `rawfile.py` parses
  `.raw`. `vectors.py` and `spicenum.py` handle names and SPICE number parsing.
- `ui/`: Qt GUI. `main_window.py` is the entry point, plus `schematic_window`/`schematic_view`/`items`/`tools`
  (editing), `waveform.py` (pyqtgraph plots), dialogs, `theme.py` (LTspice default colors, saved in QSettings).
- Entry point: `pyltspice` console script → `pyltspice.app:main` (also `python -m pyltspice`).

## Setup

```sh
python3 scripts/extract_msi.py ../LTspice64.msi   # needs 7z (p7zip-full)
```
ngspice comes from the system (`/usr/bin/ngspice`) unless a bundled copy is found in the data dir.

## Commands (run from `pyltspice/`)

```sh
../.venv/bin/python -m pytest -q                      # full suite, ~3 s (round-trips every example .asc)
../.venv/bin/python -m pytest -q tests/test_sim.py    # run a single file while iterating
../.venv/bin/pip install -e .                         # after changing pyproject.toml / entry points
../.venv/bin/python scripts/sim_example.py ../work <asc...>    # headless netlist+sim, OK/FAIL per file
../.venv/bin/python scripts/render_png.py <asc> <png>           # render schematic to PNG
QT_QPA_PLATFORM=offscreen ../.venv/bin/python scripts/gui_smoke.py ...  # drive GUI headlessly + screenshot
../.venv/bin/python scripts/install_desktop.py [--remove]      # launcher, icon, .asc/.raw association (~/.local/share)
```

## Testing notes

- `tests/conftest.py` forces `QT_QPA_PLATFORM=offscreen`, points `XDG_CONFIG_HOME` at a temp dir (so
  tests never touch the user's `~/.config/pyltspice`), and has a session `qapp` fixture. Any new
  script that opens `MainWindow` must do the same (see `scripts/gui_smoke.py`).
- `needs_lib` / `needs_ngspice` markers skip tests when the extracted library or ngspice is missing.
- `test_asc.py` round-trips **every** example `.asc` in the extracted library, so `.asc` writer changes must preserve it.
- To check visual changes, render them to PNG (`render_png.py` / `gui_smoke.py`) and look at the image.
  Don't rely only on the tests.
- `tests/` is a package (`__init__.py`); test modules import helpers via `from .conftest import ...`.
- GUI tests hang on any modal: right-click in idle mode opens a context menu (`QMenu.exec`), and
  closing a modified schematic asks to save. Leave modes with right-click only while a tool is
  active, and call `doc.undo.setClean()` before `win.close()`.
- Netlist pin order follows `SpiceOrder` after rotation, e.g. an R90 resistor nets as `R1 <right> <left>`.
- Orientations: `Mn` means rotate by n, *then* mirror x (M90 maps (x, y) → (y, x)). Verified against
  wire ends in `IdealTransformer.asc`; `test_mirrored_rotated_part_connects` guards it.
- Connectivity follows LTspice: a wire running under a component is cut at its pins, and the piece
  between two pins of the same part is ignored (`netlist._effective_wires`).

## Constraints

- UI parity with LTspice is clean-room: match it from the bundled help (`help/*.htm`) and by observing
  LTspice under Wine. Never decompile or disassemble `LTspice.exe`, and don't copy its bitmaps
  (toolbar icons are drawn in `ui/icons.py`). The app is named `pyltspice`, not "LTspice".
- About 3k of the ~5k files in `lib/sub` are encrypted ADI models (`<Binary File>` header). Report them as
  unsupported (`ltcompat.scan_definitions`); never try to decrypt them.
- LTspice-only `A` devices are emulated in `sim/adevices.py` (OTA as B sources, gates/flip-flops via
  XSPICE, Schmitt/S&H/VCO/varistor behavioural). PHASEDET and COUNTER are still reported as unsupported.

## ngspice quirks handled in `sim/`

- numparam has no `pi`: `translate()` prepends `.param pi=...`.
- `lib/cmp/standard.*` and some libraries are UTF-16 with no BOM. `textio.decode` sniffs this.
- Included libraries are rewritten (`ltcompat.ngspice_readable`) into `<data>/cache/libs`: A-devices,
  `table()`, parasitics, LTspice switch extensions, `.param` syntax, inline `;` comments,
  undeclared subckt params. Bump `LIB_CACHE_VERSION` whenever the rewrite changes, or stale copies are used.
- `.lib file` (no section) becomes `.include "<abs path>"`, and paths are resolved case-insensitively.
- ngspice reads `.spiceinit` from its cwd, so the runner works in a temp dir that holds one.
- Device currents come back as `i(@q1[ic])` and `v1#branch`. `vectors.lt_name` maps them to
  LTspice names (`Ic(Q1)`, `I(V1)`).
- X-instance rule (`netlist.element_line`): when SpiceModel names a model, use it plus Value2. When
  SpiceModel is a *file*, Value2 is the subckt name plus params. Otherwise use Value, then Value2.
- LTspice functions ngspice lacks (`u`, `uramp`, `buf`, `inv`, `mc`, `flat`, `gauss`) are added as
  `.func` only when used. `laplace=` and `wavefile=` are reported as unsupported.
- Non-converging runs are retried with relaxed options, each retry capped at `RETRY_TIMEOUT` (120 s).

## Status

The roadmap, priorities and completed work are in `pyltspice/docs/PLAN.md`. Keep it up to date when
finishing or reprioritizing work.

- `pyltspice/docs/ui_spec.md` tracks every LTspice menu/shortcut/behaviour with its source (help page
  or recollection) and implementation status. Update it when adding UI.
- Re-measure simulation compatibility with `scripts/sim_example.py ../work <dir>/*.asc`
  (latest numbers are in PLAN.md).
