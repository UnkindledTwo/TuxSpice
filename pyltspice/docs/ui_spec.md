# LTspice UI specification (clean-room)

What the pyltspice interface must match. Sources, in order of authority:

- **H**: stated in the bundled help pages (`~/.local/share/pyltspice/ltspice_lib/help/*.htm`, file named).
- **R**: recollection of LTspice's behaviour. Treat as unverified until checked against LTspice
  running under Wine (install with `sudo apt install wine`, then `wine msiexec /i LTspice64.msi`).
  Mark entries **W** once verified there.
- **W**: observed in LTspice 26.1.1 under Wine with fresh settings (`%APPDATA%\LTspice.ini` removed) and
  the "new" LTspice 26 default shortcuts. Run it on a nested display (`Xephyr :5`) so screenshots and
  synthetic input don't touch the desktop, and use a copy of the Wine prefix with `LTspice.ini`
  removed so the user's own settings are never touched. TuxSpice can run on the same nested display
  and be driven with the same XTest input for a like-for-like comparison; XFixes gives the cursor
  image. Note: LTspice crashes on exit under Wine, so it never writes its colors to the ini; read
  them from Tools > Color Preferences instead.

Status: ✅ implemented, ◐ partial, ❌ missing.

## Editing model

| Behaviour | Source | Status |
|---|---|---|
| Verb-noun editing: pick the command (move, delete...), then the objects; mode stays active until right-click or Esc | H basicschematicediting | ✅ |
| Drag a box to select several objects for the active command | H basicschematicediting | ✅ |
| A wire drawn through a component is cut so the component sits in series | H basicschematicediting | ✅ |
| Right-click on attribute text edits that attribute (Expert mode) | H editingcomponents | ✅ |
| Right-click on component body opens the type-specific editor (Assisted mode) | H editingcomponents | ✅ R/C/L/V/I; ◐ others use the attribute editor |
| Ctrl+right-click on body opens the Component Attribute Editor (Super Expert) | H editingcomponents | ✅ |
| Net names starting with `$G_` are global, drawn with a box | H labelanodename | ◐ drawn; netlisting not global across hierarchy |
| I/O port labels drawn differently, no netlist effect | H labelanodename | ◐ simple box outline |
| Ctrl held while drawing wires toggles orthogonal snapping | H draftingoptions | ✅ |
| Mouse wheel toward you zooms in (option to reverse) | H draftingoptions | ✅ |

## Menus

All **W** (LTspice 26.1.1 under Wine, captured 2026-10-16). The menu bar has three layouts,
chosen by the active window. Layouts are data in `ui/menus.py`; ✅ works, ◐ partial, ❌ present
but greyed out (not implemented), – deliberately left out.

**No window open**: File (New Schematic Ctrl+N, New Symbol, Open... Ctrl+O, Open Examples..., New
Library > Inductor, Print Setup..., Print Monochrome, recent files, Exit), View (Toolbar, Status
Bar, Window Tabs), Tools (Settings, Color Preferences, Configure Third-Party AI Assistants...,
Update components), Help.

**Schematic**: File, Edit, Hierarchy, View, Simulate, Tools, Window, Help.

| Menu | Items (LTspice order, default keys) | Status |
|---|---|---|
| File | New Schematic, New Symbol, Open, Open Examples, Save Ctrl+S, Save As Ctrl+Shift+S, Close Ctrl+W, Print Ctrl+P, Print Preview, Print Setup, Print Monochrome, recent files (inline), Exit | ✅; New Symbol ❌ (no symbol editor) |
| Edit | Undo Ctrl+Z, Redo Ctrl+Shift+Z, Text T, SPICE Directive `.`, Configure SPICE Analysis A, Resistor R, Capacitor C, Inductor L, Diode D, Component P, Rotate Ctrl+R, Mirror Ctrl+E, Draw Wire W, Label Net N, Place GND G, Place BUS tap B, Delete "Backspace or Del", Duplicate Ctrl+C, Move M, Stretch S, Paste Ctrl+V, Draw > (Line, Rectangle, Ellipse, Arc, Line Style >) | ✅ (Duplicate puts its picks on the clipboard; Paste carries them into any TuxSpice schematic); BUS tap ❌. No Search entry (toolbar/Ctrl+F only). Current source I is a key only (26.0.2) |
| Hierarchy | Open or Generate this Sheet's Symbol, Create a New Blank Symbol, Create a New Blank Sheet, Generate Subckt Netlist | ✅; New Blank Symbol ❌ |
| View | Zoom Area Z, Zoom Back Shift+Z, Zoom to Fit Space, Recenter, Show Grid Ctrl+G, Mark Unconn. Pins Ctrl+U, Mark Anchors Ctrl+A, Bill of Materials > (Show on Schematic, Paste to clipboard), Efficiency Report > (same), Update and View SPICE Netlist, SPICE Output Log Ctrl+L, Visible Traces, Autorange Y-axis, Marching Waves > ((Re-)Start, Pause), Set Probe Reference, Toolbar, Status Bar, Window Tabs | ✅; Efficiency Report ❌, Marching Waves ❌ |
| Simulate | Run/Pause Alt+R, Stop Alt+S, Clear Waveforms `0`, Efficiency Calculation > (Mark Start, Mark End), Settings, Configure Analysis A | ✅; Efficiency Calculation ❌ |
| Tools | Copy bitmap to Clipboard, Write image to .emf file, Settings, Color Preferences, Export Netlist, Configure Third-Party AI Assistants..., Update components | ✅; image written as SVG/PNG; Export Netlist offers Tango, PADS, Allegro (Telesis), Wire List (LTspice has ~20 formats); Update components – |
| Window | Tile Horizontally, Tile Vertically, Cascade, Close Everything, Arrange Icons, numbered window list (active one checked) | ✅ |
| Help | LTspice Help F1, Keyboard Shortcut Cheat Sheet, Open Examples..., Get Support on EngineerZone, Go to Analog.com, Go to myAnalog, Show Model Change Log, Show LTspice Change Log, Check for LTspice updates..., About LTspice | ✅ as TuxSpice Help/About; ADI web links and updates – |

**Waveform**: File, View, Plot Settings, Simulation, Tools, Window, Help.

| Menu | Items | Status |
|---|---|---|
| File | New Schematic, Open, Open Examples, Save Plot Settings Ctrl+S, Save Plot Settings As Ctrl+Shift+S, Close, Print, Print Preview, Print Setup, Print Monochrome, Export data as text, Execute .MEAS Script, Convert to Fast Access, recent files, Exit | ✅; Fast Access ❌ |
| View | Zoom Area, Zoom Back, Zoom to Fit, Recenter, SPICE Output Log, FFT, Toolbar, Status Bar, Window Tabs | ✅ |
| Plot Settings | Visible Traces, Add trace A, Delete Traces "Backspace or Del" (then click labels), Select Steps Shift+S, Place Cursor on Active Trace C, Clear All Cursors "Shift+C or Esc", Redraw F5, Add Plot Pane Above Active Pane P, Below B, Move Active Pane Up U / Down D, Delete Active Pane, Sync. Horiz. Axes, Grid Ctrl+G, Reset Colors, Mark Data Points, Eye Diagram >, Undo Ctrl+Z, Redo Ctrl+Shift+Z, Autorange Y-axis Ctrl+Y, Manual Limits, Autoranging, Notes & Annotations >, Save Plot Settings As, Open Plot Settings File O, Reload Plot Settings Ctrl+Space, (scrolled off-screen under Wine; per help:) Edit Plot Defs File | ✅; Eye Diagram ❌ |
| Notes & Annotations | Cursor Position L, Annotate Phase Margin, Annotate Gain Margin, Annotate Steps, Text T, Arrow, Line I, Rectangle R, Ellipse, Line Style/Color, Draw Nyquist Unit Circle | ✅ text/arrow/line/rectangle/ellipse/cursor position/color; phase/gain margin and steps (undocumented: textbook 0 dB / -180° crossovers, step names at each curve's right end); Nyquist ❌ |
| Simulation | Run/Pause, Stop, Marching Waves > | ✅; Marching ❌ |
| Tools | Copy Graph Image to Clipboard, Write image to .emf file, Settings, Color Preferences, (AI assistants, Update components) | ✅ (SVG/PNG) |

**Right-click, schematic** (empty paper): Configure Analysis, Run/Pause, Stop, View > (Zoom Area, Zoom
to Fit, Mark Anchors, Show Grid, Visible Traces, Show .op Data Flags, Update and View SPICE Netlist,
SPICE Output Log, Efficiency Report >, Bill of Materials >, Copy Image to Clipboard, Write image to
.emf file), Edit > (Move, Stretch, Delete, Duplicate, Undo, Redo), Draft > (Draw Wire, Component,
Label Net, SPICE Directive, Comment Text, .op Data Label, Place BUS tap), Draw >, Waveforms > (Visible
Traces, Autorange Y-axis, Set Probe Reference, Clear Waveforms, Marching Waves >, Efficiency
Calculation >), Hierarchy > (Open or Generate this Sheet's Symbol), File > (Save, Save As, Print,
Print Preview, Open Examples), Float Window. ✅

**Right-click, plot**: Zoom to Fit, Autorange Y-axis, View > (Grid, Mark Data Points, Visible Traces,
Select Steps, Manual Limits, Reset Colors, FFT, SPICE Output Log, Plot Defs File, Copy Image to
Clipboard, Write image, Recenter), Add Traces, Place Cursor on Active Trace, Clear All Cursors,
Redraw, Add Plot Pane Above/Below, Move Plot Pane Up/Down, Delete this Pane, Sync. Horiz. Axes,
Notes & Annotations >, Edit > (Move, Stretch, Delete, Duplicate, Undo, Redo), Copy Image to
Clipboard, Marching Waveforms >, File > (Save Plot Settings, Save As, Reload, Print, Print Preview,
Export data as text, Execute .MEAS Script, Convert to Fast Access), Float Window, Waveform Settings
(Settings on the Waveforms tab). ✅ (annotation Move/Stretch/Duplicate ❌)

Keys that LTspice reuses across window kinds (A, C, D, P, B, R, T, I, L, U, Del, F5, Ctrl+Z, Ctrl+G,
Ctrl+S) act on the active window kind only.

Other menu-related items:

| Item | Source | Status |
|---|---|---|
| Undo/redo of trace selection changes | H datatraceselection | ✅ Plot Settings > Undo/Redo |
| Cursors attached by clicking a trace label, readout window with difference | R | ✅ |
| Ctrl+click a trace label: average and RMS | R | ◐ in the label menu |
| Plot Settings > Edit Plot Defs File: `.func`/`.param` for expressions | H userdefinedfunctions | ✅ `<user files or data dir>/plot.defs` |
| Set Probe Reference: later voltage probes are relative to the picked node | W | ✅ |
| Keyboard Shortcut Cheat Sheet (always on top) | H keyboardshortcuts | ◐ opens in a tab; editing moved to Settings > Schematic/Waveforms > Keyboard Shortcuts, as in LTspice |

## Settings dialog

All **W**. Tabs: Operation, Schematic, Waveforms, SPICE, Save Defaults, Netlist Options, Compression,
Search Paths, Internet, Hacks (LTspice draws them in two rows), each with "[*] Setting remembered
between program invocations.", Reset to Default Values, and OK / Cancel / Help. Only [*] settings
persist; the others reset every start. Defaults in `settings_dialog.SPEC`.

| Tab | Items (default) | Status |
|---|---|---|
| Operation | Marching Waveforms (on), Generate Expanded Listing[*], Save all open files on start of simulation[*], Automatically delete .raw files[*], Warn if no Rser is specified for inductors[*] (on), Background image[*] (Oscilloscope), Toolbar Style[*] (Default), Toolbar icon size[*] (Default), Waveform Plotting Thread Priority[*] (medium), RAM for Fast Access Conversion[*] (40%) | ✅ save-on-run, delete .raw, background (Oscilloscope/None/user `~/.config/pyltspice/TuxSpice.jpg`), icon size; others greyed |
| Schematic | Allow direct component pin shorts[*], Automatically scroll the view[*] (on), Mark text justification anchor points, Mark unconnected pins (on), Show schematic grid points[*], Orthogonal snap wires (on), Ortho stretch mode[*], Cut angled wires during stretch (on), Un-do history size (500), Pen thickness[*] (1), Show Title Blocks[*] (on), Reverse Mouse Wheel Scroll[*], Cursor type[*] (Auto); Font Properties[*]: Tahoma, Size 28, Bold; Color Scheme[*], Keyboard Shortcuts[*] buttons | ✅ except pin shorts, ortho stretch, cut angled wires, title blocks (greyed) |
| Waveforms | Data trace width[*] (1), Cursor width[*] (1), Use radian measure in waveform expressions[*] (off: sin(90) = 1), Mouse cursor type[*], Font[*] Arial, Font point size[*] 10, Bold Font[*]; Color Scheme, Open Plot Defs, Keyboard Shortcuts; Directory for .raw and .log data files[*] | ✅ |
| SPICE | Default Integration Method[*] (trapezoidal / modified trap / Gear), Noopiter, Skip Gmin Stepping, Engine: Solver[*] Normal, Max threads, Matrix Compiler, Thread Priority[*]; Gmin 1e-12, Abstol 1e-12, Reltol 0.001, Chgtol 1e-14, Trtol[*] 2, Volttol 1e-06, Sstol 0.001, MinDeltaGmin 0.0001, No Bypass[*] | ✅ method and tolerances become `.options` (only values changed from these defaults); engine, Sstol, MinDeltaGmin, No Bypass greyed |
| Save Defaults | Save Device Currents[*] (on), Save Subcircuit Node Voltages[*], Save Subcircuit Device Currents[*], Don't save Ib(), Ie(), Is(), Ig(), or Ix()[*], Save Internal Device Voltages | greyed (ngspice saves everything) |
| Netlist Options | Convert 'µ' to 'u'[*], Reverse comp. order; Default Devices[*], Default Libraries[*] (on) | ✅ first two (netlist view and `.net`); models greyed |
| Compression | ASCII data files[*], Only compress transient analyses[*] (on), Enable 1st/2nd Order Compression[*], Window Size 1024, Relative Tolerance 0.0025, Absolute Voltage 1e-05, Current 1e-09 | greyed |
| Search Paths | Don't place symbols from schematic subdirectories[*], User files, Symbol Search Paths[*], Simulation Library Search Paths[*] (right-click > Browse) | ✅ (subdirectories are never searched anyway) |
| Internet | Don't cache files, Don't verify checksums, Send my anonymous usage data[*], LTspice URL, Connection Type, proxy | greyed (no network use) |
| Hacks | Latest Convergence Hacks, Show Energy Conservation Check Sum[*], Trade accuracy for convergence for TSTS, Gate Current, Minimum shunt to main capacitance ratio, Don't temperature scale JFET Isr[*], Add GMIN across current sources, Supply a min. inductor damping if no Rpar is given[*], Use the clock to reseed the MC generator[*] | greyed |

## MCP / Third-Party AI Assistants

Sources: H Third_Party_AI_Tools.htm (and its dialog picture), and **W**: LTspice 26.1.1's
`ltspice-mcp-bridge.exe` driven over stdio under Wine. `scripts/mcp_diff.py` runs the same ~100-call
session (every tool, error cases included) against both servers and diffs the replies field by field;
both TuxSpice modes (headless and attached to a window) were checked that way on 2026-10-16.

| Behaviour (LTspice) | Status |
|---|---|
| 18 tools (15 design + status/attach/start_headless) with the same input schemas and annotations (title, read-only/destructive/idempotent/open-world hints) | ✅ |
| initialize always answers protocol 2025-03-26; serverInfo carries name, version, mode, autoStarted, backendActive, headlessLaunchAvailable; capabilities `resources: {}`, `tools.listChanged`; no prompts | ✅ (also answers `ping`, which MCP requires and LTspice lacks) |
| Tool replies: one text block of compact JSON with sorted keys, non-ASCII kept (`1µ`), scalars as strings; no `isError` key on success; errors are plain text with `isError: true` | ✅ |
| status/attach/start_headless replies are pretty-printed JSON; attach → `{attachedPid, ok, port}` plus `notifications/tools/list_changed`; failures `{error, ok: false}` | ✅ |
| Paths must be absolute (relative → "file not found"); every error message's wording | ✅ copied word for word |
| open_design `{already_open, path, status, type}`; start_simulation `{message, path, result}`; is_simulation_running adds `path` when given (unknown document → "document not found") | ✅ |
| get_spice_log `{text}` (`""` before any run, `{}` for a missing .log file) | ✅ (TuxSpice's log is ngspice's, plus .meas results) |
| set_design_content `{status, unchanged}` (+ `message` for a changed schematic); same text → `unchanged: "true"` | ✅; invalid schematic text crashes LTspice 26.1.1, TuxSpice refuses it with an error |
| bring_to_front always `{status: "ok"}` | ✅ |
| Raw tools report the `.raw` path; without a path only the active waveform window counts; steps `{index: "0", params: {"r": 1000.0}, n_points}`; complex data `{real, imag}` or `{mag_db20, phase_deg}`; x-axis may be requested as a signal; names case-insensitive, echoed as given; `x_min`/`x_max` echoed as `"%f"`; read cap counts complex signals twice | ✅ (headless TuxSpice has no windows: without a path it uses the last run) |
| export_raw_waveforms: tables created in the order run, steps, step_params, signals, samples with identical DDL (INTEGER flags, step/signal primary keys, REAL step values, var_index = .raw column) | ✅ identical schema |
| Resources `ltspice-ref:///` (sorted, summaries from the reference README index; README readable but unlisted) and `ltspice-design:///<path>`; read errors returned as tool-style errors ("Resource not found", "Unknown URI scheme", "document not found") | ✅ plus TUXSPICE-NOTES.md |
| Status bar shows "MCP Connected: &lt;client name&gt;" | ✅ |
| Expected differences | `precision` "double" (ngspice) vs "single"; point counts (different time steps); product names |
| Tools > Configure Third-Party AI Assistants dialog, startup offer | ✅ Linux config paths (`mcp/clients.py`) |

First start of LTspice 26 with old settings asks "New Keyboard Shortcuts" (keep customized or take
the new defaults) and may ask about anonymous usage data; TuxSpice asks neither.

## Window layout and toolbar

| Behaviour | Source | Status |
|---|---|---|
| Toolbar order: Settings, New, Open, Save, Print, Configure Analysis, Run, Stop, Tile Vert., Tile Horiz., Cascade, Zoom Area, Zoom Back, Zoom to Fit, Autorange, Visible Traces, Wire, GND, Voltage Source, Resistor, Capacitor, Inductor, Diode, Component, Label Net, Text, SPICE Directive, Delete, Duplicate, Move, Stretch, Rotate, Mirror, Undo, Redo, Search | W | ✅ icons redrawn in `ui/icons.py` (bold black, blue accents, hollow blue pin circles) |
| Toolbar tooltip "Name (key)", long description in the status bar | W | ✅ |
| Window tab strip above the MDI area (View > Window Tabs, on by default); windows stay tiled | W | ✅ |
| Menu bar swaps between three layouts (no window, schematic, waveform) | W | ✅ see Menus |
| A run tiles the plot above the schematic | W | ✅ |
| Status bar text is bold; shows `x = 12.56ms  y = 3.085V` over plots | W | ✅ |
| Edit > Search (Ctrl+F) | W | ✅ highlights matches |
| View > Zoom Area (Z): drag a box | W | ✅ schematic; plots zoom with a box drag anyway |
| Place BUS tap (B), Marching Waves, Efficiency Report | W | ❌ |
| Mark Anchors (Ctrl+A), Recenter | W | ✅ |

## Editing feel (all W, LTspice 26.1.1)

| Behaviour | Status |
|---|---|
| New sheet opens zoomed in (a resistor is ~190 px tall), not fitted | ✅ |
| Placing a part: the sprite is carried by its middle (origin snapped so the centre is nearest the cursor), shows its future name (R1, R2...) and hollow pin squares; status "Type Ctrl+R to rotate or Ctrl+E to mirror."; the system cursor is hidden | ✅ |
| Ctrl+R / Ctrl+E while placing or carrying; the next sprite keeps the orientation | ✅ |
| Rotating a two-pin part rewrites WINDOW 0/3 so the name sits above and the value below (R90: `0 0 56 VBottom` / `3 32 56 VTop` for res; R270 and R180 analogous; rule confirmed on 1600+ example parts) | ✅ |
| Rotate/Mirror toolbar buttons are enabled only while placing or carrying | ✅ |
| Wire mode: hidden cursor, full-view dotted black crosshair, bold rubber band; the first move picks which leg comes first (vertical on a diagonal); a click on empty paper commits only the first leg and keeps the second live; a click on a pin/wire ends the wire; first right-click drops the live wire, the second leaves the mode | ✅ |
| Left-clicking an unconnected pin in idle mode starts a wire (26.0 change log) | ✅ |
| Move/Stretch/Delete: no hover highlight; selection box is a thin black dotted rectangle; carried parts keep their colours and their pin squares move with them | ✅ |
| Cursors: scissors (delete), crosshair+two squares (move), crosshair+wired squares (stretch), crosshair+plus (duplicate), magnifier (zoom), red pen probe (voltage, hotspot at the tip), clamp with cyan arrow (current), gapped crosshair over schematics with results and over plots | ✅ drawn in `ui/icons.py` |
| Probe hover text: "Click to plot V(N002).  DC operating point: V(n002) = …" / "Left-click to plot I(R3).  Right click to edit.  DC operating point: …" | ✅ (op point from a .op run, else the first point of the run) |
| Right-click a part: its editor opens at the cursor; status "Editing component: R3" | ✅ |
| R/C/L editors: Manufacturer/Part Number, "Select Resistor/Capacitor/Inductor" (table from `lib/cmp/standard_*.db`, opens at the current value, Show All / Part No. filter), properties group, OK/Cancel top right; selections stored as `mfg=` `pn=` `type=` in SpiceLine | ✅ |
| Voltage/current source: small DC editor (DC value, Series Resistance, Advanced); non-DC values open the full editor directly | ✅ |
| Net Name dialog: GND / COM / name with small pictures, Port Type list (None, Input, Output, BiDirect), opens at the cursor | ✅ |
| Text / SPICE directive dialog: groups in one row with OK/Cancel at the right, short edit box, "Press Shift+Enter to start a new line." (Enter accepts) | ✅ |
| Configure Analysis: right-aligned labels, short fields, "label: [x]" options, "Syntax: …" caption, plain OK/Cancel | ◐ no Transient Frequency Response tab, no save/load-state options |
| Component dialog: name + description + preview (with pin squares) on the left; Show, Search, folder path, multi-column list on the right; typing jumps to the first match and opens its folder (no filtering); clicking copies the name into Search; Open Example Circuit when an example of that name exists; Refresh / Cancel / Place | ✅ (no Get Product Info, no analog.com selector) |
| Run: all windows tiled horizontally, new plot on top, schematics re-fitted, schematic stays active; plot window named `<sheet>.raw`; empty plot already spans the simulated time with no Y labels | ✅ |
| Plot ticks share one prefix and precision (0ms 3ms 6ms…, 0.5V…5.0V) | ✅ (tick spacing is pyqtgraph's, not LTspice's 1/2/3/5/9 steps) |
| Undo/Redo with nothing to undo shows "Nothing to Undo" | ✅ |
| Empty MDI area shows an oscilloscope-like backdrop (LTspice's default background image) | ✅ drawn, not copied |
| Toolbar: 28 px icons on a 34 px pitch with a gripper; disabled buttons are flat grey silhouettes | ✅ |

## Keyboard shortcuts (defaults)

User-programmable via Help > Keyboard Shortcut Cheat Sheet > Edit Keyboard Shortcuts, with load/save
to file (H keyboardshortcuts): ✅ (Help > Edit Keyboard Shortcuts; JSON files).

LTspice 26 replaced the XVII defaults (F2..F9, S = directive) with letter keys. On first start it offers
to switch; TuxSpice uses the new set and keeps the XVII F-keys as secondary keys.

| Command | Default key (LTspice 26) | Source | Status |
|---|---|---|---|
| Configure Analysis | A | W | ✅ |
| Run/Pause / Stop | Alt+R / Alt+S | W | ✅ |
| Zoom Area / Zoom Back / Zoom to Fit | Z / Shift+Z / Space | W | ✅ (Ctrl+B kept) |
| Autorange Y-axis | Ctrl+Y | W | ✅ |
| Wire, GND, Voltage, Resistor, Capacitor, Inductor, Diode, Component, Label Net, Text | W, G, V, R, C, L, D, P, N, T | W | ✅ |
| SPICE Directive | . (period) | W | ✅ |
| Delete | Backspace or Del | W | ✅ (F5 kept) |
| Duplicate / Move / Stretch | Ctrl+C / M / S | W | ✅ (F6/F7/F8 kept) |
| Rotate / Mirror | Ctrl+R / Ctrl+E | W | ✅ |
| Undo / Redo | Ctrl+Z / Ctrl+Shift+Z | W | ✅ (F9, Shift+F9, Ctrl+Y kept) |
| Search | Ctrl+F | W | ✅ |
| Save As / Close | Ctrl+Shift+S / Ctrl+W | W | ✅ |
| Show Grid / Mark Unconn. Pins / Mark Anchors | Ctrl+G / Ctrl+U / Ctrl+A | W | ✅ |
| SPICE Output Log | Ctrl+L | W | ✅ |

## Colors and fonts

All **W** (Tools > Color Preferences, fresh settings), in `ui/theme.py`:

- Schematic: background 192,192,192; wires and junctions 0,0,255; component body 0,0,127; graphic
  flag (GND, port outlines) 0,0,255; component fill-in 255,255,192; component text, flag text and
  SPICE directives black; comments and graphic annotation 0,0,200; unconnected pin 0,0,255;
  highlight 255,255,0; grid black.
- Waveform: background black; axis 175,175,175; inactive axis 150,150,150; grid 100,100,100 (off by
  default); traces V(1)..V(12): 0,255,0 · 0,0,255 · 255,0,0 · 0,175,175 · 255,0,255 · 128,128,128 ·
  0,128,0 · 0,0,175 · 175,128,0 · 128,0,128 · 128,0,0 · 175,175,0.
- Netlist view: text black, comments 0,128,0, dot commands 0,0,255 (from the ini).
- Schematic font: Tahoma 28, bold. The default text size has a 22.4-unit em, junction squares are
  about 8.5 units. TuxSpice falls back to DejaVu Sans Bold condensed to 90% when Tahoma is missing.
- Waveform font: Arial 10 pt, bold. Settings > Schematic: Mark unconnected pins on, grid off.
- The color dialog lists the same 14 schematic items under LTspice's names, but uses color buttons
  instead of LTspice's clickable sample schematic with RGB sliders.
