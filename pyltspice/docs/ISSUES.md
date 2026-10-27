# Open issues

Local issue list (not on GitHub), most important first. Order: things that can silently give
wrong results or break a stated guarantee, then gaps users hit in everyday work, then LTspice
parity and polish. Each entry says why it matters, what we know, and a way in.
Roadmap context is in `PLAN.md`; UI parity status in `ui_spec.md`.

## High

### 1. MCP replies not re-verified against LTspice after the Settings changes
- **Why:** CLAUDE.md promises byte-compatible replies with LTspice's MCP bridge. Two recent changes
  alter what a run returns: Save Defaults now hides subcircuit voltages/currents by default
  (`runner.keep_vector`), and every top-level inductor without Rser adds a warning that
  `sim_log` puts at the top of the log.
- **Known:** `tests/test_mcp.py` passes, but it doesn't compare with the real bridge.
- **Way in:** run `scripts/mcp_diff.py` under Wine (`run lt`, `run tux`, `compare`) and check
  vector lists and `get_spice_log` text. If LTspice doesn't log the Rser warning, keep it out of
  the MCP log.

### 2. 114 Applications examples still fail (of 1,043 without encrypted models)
- **Why:** this is the largest compatibility gap; every one is a real LTspice circuit that doesn't run.
- **Known (by cause, `work/s6.tsv`):** 28 "no output" + 12 timeouts (convergence/slow), 15 aborts
  and ngspice "impossible error", 12 numparam `Undefined parameter`, 11 "not enough nodes" on MOS
  lines inside ADI macro-models, 7 time-step failures, 4 resistors with extra LTspice fields
  (`R n1 n2 5k -.1u 0 0p`), 4 `unknown subckt ltN-x.x`, 3 `.machine`, 2 `.timedomain`, 2 `.tf`
  with a sweep, 2 diodes with `n=`, 3 LT1964 variants with no model file.
- **Way in:** the cheap, mechanical ones first (extra R fields, `.tf` sweep, `n=` diodes, MOS node
  count, numparam names). Each fixes a whole group. Then convergence case by case. Re-measure
  with `sweep_examples.py`.

### 3. Light/dark theme switching only checked offscreen
- **Why:** you reported the contrast problem on your own desktop (Mint-L-Dark, prefer-dark), and
  all checks since were offscreen renders with `QT_QPA_PLATFORMTHEME=gtk3`.
- **Known:** icons redraw on `PaletteChange` when darkness flips, and hidden windows redraw on
  show. The desktop's `colorSchemeChanged` re-applies the Application theme setting. None of this
  has run on a real xcb/Wayland session with the portal.
- **Way in:** run on the desktop (or in Xephyr with the portal), toggle the GNOME dark preference
  while TuxSpice is open, and check the menus, MDI tabs, dialogs and tooltips too, not just the
  toolbar.

### 4. No cross-probing inside hierarchical sheets
- **Why:** LTspice lets you open a block from its parent and probe nodes and currents inside it.
  TuxSpice's `descend` opens the sheet as a standalone file with no simulation attached
  (`sim_plot` is None), so probing there does nothing. Subcircuit vectors are also now hidden by
  default (Save Defaults), which this feature needs.
- **Way in:** open the child with the parent's instance path (`x1.`). Map clicks to `V(x1.net)` /
  `I(@r.x1.r1[i])` in the parent's plot. Always save the vectors of hierarchical-sheet instances
  (LTspice does) whatever Save Defaults says.

### 5. `$G_` global nets aren't global across the hierarchy
- **Why:** this is wrong-netlist territory. A `$G_VDD` label inside a sheet should join the
  top-level `$G_VDD`. Today it's only drawn as global (`ui_spec.md`: ◐).
- **Way in:** in `generate_netlist`, emit `$G_` nets as `.global`, or keep their names unprefixed
  when flattening subckts. Add a two-level test.

## Medium

### 6. Marching waveforms: no plot until ngspice finishes
- **Why:** long runs show nothing. The Electrometer example takes ~5 min with a blank screen.
  LTspice draws traces while simulating. The Settings option and the menu entry are greyed.
- **Way in:** run ngspice as a shared library (`libngspice`, callbacks per time point) or poll a
  growing ASCII raw file. Pause/Resume maps onto `bg_halt`/`bg_resume`.

### 7. No symbol editor
- **Why:** you can't draw a symbol for your own subcircuit or hierarchical block. File > New Symbol,
  Hierarchy > Create a New Blank Symbol and Edit > Add Pin/Port are greyed (`ui_spec.md` ❌).
- **Way in:** reuse the schematic editing tools on a `.asy` document (lines, rects, arcs, text,
  pins with PinName/SpiceOrder, attribute windows). `asy.py` already round-trips the format.

### 8. Plot annotations are lost when a plot is reopened
- **Why:** notes, arrows, boxes and margin labels live only in memory. `pltfile.write_plt` only
  stores trace sections.
- **Way in:** serialize `waveform.Note` (kind, pane index, view-coordinate points, colour, text)
  into the `.plt`. Check LTspice's own `.plt` syntax for annotations under Wine first, so the files
  stay compatible.

### 9. Common parts still missing from TuxSpice's library
- **Why:** the most-asked-for parts after the ones already added.
- **Known:** no darlingtons (TIP120/122, BD679, MPSA13: a single-BJT card gets Vce(sat) wrong, so
  each needs a subckt plus a symbol), comparators (LM393, LM339, LM311), the 555 timer, regulators
  (LM317, 78xx/79xx), optocouplers (PC817, 4N35). Op-amp macro-models don't model input
  common-mode range, phase reversal, noise or a second pole.
- **Way in:** extend `tuxspice_opamps.lib` (`TUX_OPAMP`) with a common-mode clamp. Add
  comparator and darlington subckts with symbols in `data/sym/`. Add rows to
  `tests/test_models.py` for each.

### 10. The user's own models are not in the parts picker
- **Why:** `user.dio`/`user.bjt`/`user.mos`/`user.jft` now feed simulations (Default Libraries), but
  `ltcompat.model_catalog()` only lists `standard.*` and TuxSpice's cards, so Pick New
  Transistor/... can't show them. `_is_known_model` also ignores them when deciding whether a
  token on a device line is a model name.
- **Way in:** pass the user directory into `model_catalog` (cache key: file mtimes) and
  `_is_known_model`. Label the rows "User" in the Library column.

### 11. Two Educational examples still don't finish
- **Known:** PLL2 stalls inside its PHASEDET loop in ngspice (the emulation is correct on its own).
  Electrometer runs but takes ~5 min (1 MHz chopper over 15 ms).
- **Way in:** PLL2: a smoother phase-detector edge or a breakpoint hint. Electrometer: profile the
  step control, try `.options method=gear` / a larger `reltol` as an automatic retry.

## Low

### 12. LTspice features still greyed out
- BUS tap (B), eye diagram, efficiency report / efficiency calculation, Draw Nyquist Unit Circle,
  the Transient Frequency Response analysis (`.fra`), `.machine` / `.timedomain` (also counted in
  #2), `.wave` export, Fast Access files, New Blank Symbol (see #7).

### 13. Paste between folders loses local symbols
- **Why:** Duplicate/Paste carries `.asc` text only. A part whose `.asy` sits next to the source
  schematic (or in a subfolder of it) shows up unresolved in a schematic in another folder.
- **Way in:** put the source schematic's folder in the clipboard data as well, and offer to copy
  the missing `.asy` files on paste (or add the folder to that document's search dirs).

### 14. Germanium model limits
- Icbo is constant with collector voltage (real germanium leakage rises with it). How the diodes'
  tunnelling term (JTUN/XTITUN) leakage scales with temperature isn't checked. There's no thermal
  runaway coupling (self-heating), which matters for AC128-class output stages.
- **Way in:** add a temperature row for the diodes to `test_germanium_leakage`. Consider a small
  subckt wrapper for voltage-dependent Icbo.

### 15. Setup and packaging
- First-run extraction needs the external `7z` (p7zip-full). There's no AppImage/Flatpak/PyPI
  package, and ngspice must come from the system.
- **Way in:** a pure-Python MSI/CAB reader (`olefile` + a cabinet decoder) would remove the 7z
  dependency. An AppImage could bundle ngspice.

### 16. Smaller UI parity gaps
- Configure Analysis has no Transient Frequency Response tab and no save/load-state options.
- Ctrl+click on a trace label should show average/RMS directly; today it's in the label's menu.
- The keyboard shortcut cheat sheet opens in a tab instead of an always-on-top window.
- I/O port labels are drawn as a plain box.
- MDI sub-windows don't have Windows-style blue title bars (cosmetic).
