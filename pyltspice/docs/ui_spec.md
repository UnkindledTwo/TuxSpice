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

## Menus (schematic window)

| Menu item | Source | Status |
|---|---|---|
| File > New Schematic / Open / Close / Save / Save As | R | ✅ |
| File > New Symbol | H creatingnewsymbols | ❌ |
| File > New Library > Inductor | H inductormodels | ❌ |
| File > Open Examples | H examplecircuits | ✅ |
| File > Export (waveform data as text) | H exportingwaveformdata | ✅ tab-separated, first .step run |
| File > Execute (.meas script on a waveform) | H measureevaluateuserdefinedele | ❌ |
| File > Print / Print Preview | R | ◐ print only |
| Edit > Undo / Redo | H basicschematicediting | ✅ |
| Edit > Text / SPICE Directive / SPICE Analysis | H basicschematicediting | ✅ |
| Edit > Resistor / Capacitor / Inductor / Diode / Component | H basicschematicediting | ✅ |
| Edit > Rotate / Mirror | H basicschematicediting | ✅ |
| Edit > Draw Wire / Label Net / Place GND | H basicschematicediting | ✅ |
| Edit > Delete / Duplicate / Move / Drag | H basicschematicediting | ✅ |
| Edit > Draw > Line / Rectangle / Circle / Arc / Text | H basicschematicediting | ✅ |
| Edit > Attributes > Edit Attributes / Attribute Window | H addingattributes, attributevisibility | ◐ via attribute editor |
| Edit > Add Pin/Port (symbol editor) | H addingthepins | ❌ |
| Hierarchy > Open this Sheet's Symbol | H automaticsymbolgeneration | ✅ generates from I/O ports; hierarchical sheets netlist as .subckt |
| View > Zoom to Fit / Zoom In / Zoom Out | R | ✅ |
| View > Show Grid | H draftingoptions | ✅ |
| View > Mark Object Anchors | H drawingthebody | ❌ |
| View > SPICE Netlist | H spicenetlist | ✅ |
| View > SPICE Error Log | H measureevaluateuserdefinedele | ✅ |
| View > Efficiency Report | H efficiencyreport | ❌ |
| View > Bill of Materials | R | ✅ |
| Simulate > Run / Halt / Edit Simulation Cmd | R | ✅ |
| Simulate > Efficiency Calculation > Mark Start / Mark End | H steady | ❌ |
| Tools > Settings (incl. Hacks!, Waveform > Font) | H settings, inductormodels | ◐ drafting options only |
| Tools > Color Preferences | H schematiccolors, colorcontrol | ✅ |
| Tools > Export Netlist (PCB formats) | H pcbnetlistextraction | ❌ |
| Tools > Write to a .wav file | H exportingwaveformdata | ❌ |
| Tools > Update components | H softwareinstallation | ❌ (not applicable: no ADI server) |
| Window > Tile / Cascade / Close All | R | ✅ |
| Help > Help Topics | R | ✅ opens bundled HTML |
| Help > Keyboard Shortcut Cheat Sheet (always on top) | H keyboardshortcuts | ◐ opens in a tab, not always-on-top |
| Help > Show LTspice Change Log / Show Model Change Log | H programupdates | ✅ |

## Menus (waveform window)

| Menu item | Source | Status |
|---|---|---|
| Plot Settings > Visible Traces (choose from all data) | H datatraceselection | ◐ Add Traces dialog |
| Plot Settings > Add Trace (expressions allowed) | H datatraceselection, waveformarithmetic | ✅ |
| Plot Settings > Save / Open Plot Settings (.plt) | H saveplotconfigurations | ◐ pane/trace layout; `<name>.plt` auto-loads after a run |
| Plot Settings > Edit Plot Defs File (user functions) | H userdefinedfunctions | ❌ |
| View > FFT | H waveformarithmetic | ✅ points, window, zoomed range |
| Undo/redo of trace selection changes | H datatraceselection | ❌ |
| Cursors attached by clicking a trace label, readout window with difference | R | ✅ |
| Ctrl+click a trace label: average and RMS | R | ◐ in the label menu |

## Window layout and toolbar

| Behaviour | Source | Status |
|---|---|---|
| Toolbar order: Settings, New, Open, Save, Print, Configure Analysis, Run, Stop, Tile Vert., Tile Horiz., Cascade, Zoom Area, Zoom Back, Zoom to Fit, Autorange, Visible Traces, Wire, GND, Voltage Source, Resistor, Capacitor, Inductor, Diode, Component, Label Net, Text, SPICE Directive, Delete, Duplicate, Move, Stretch, Rotate, Mirror, Undo, Redo, Search | W | ✅ icons redrawn in `ui/icons.py` (bold black, blue accents, hollow blue pin circles) |
| Toolbar tooltip "Name (key)", long description in the status bar | W | ✅ |
| Window tab strip above the MDI area (View > Window Tabs, on by default); windows stay tiled | W | ✅ |
| Menu bar swaps for waveform windows: File, View, Plot Settings, Simulation, Tools, Window, Help | W | ◐ subset of items |
| A run tiles the plot above the schematic | W | ✅ |
| Status bar text is bold; shows `x = 12.56ms  y = 3.085V` over plots | W | ✅ |
| Edit > Search (Ctrl+F) | W | ✅ highlights matches |
| View > Zoom Area (Z): drag a box | W | ✅ schematic; plots zoom with a box drag anyway |
| Place BUS tap (B), Mark Anchors (Ctrl+A), Recenter, Marching Waves, Efficiency Report | W | ❌ |

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
| Show Grid / Mark Unconn. Pins / Mark Anchors | Ctrl+G / Ctrl+U / Ctrl+A | W | ✅ / ✅ / ❌ |
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
