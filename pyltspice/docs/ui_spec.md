# LTspice UI specification (clean-room)

What the pyltspice interface must match. Sources, in order of authority:

- **H**: stated in the bundled help pages (`~/.local/share/pyltspice/ltspice_lib/help/*.htm`, file named).
- **R**: recollection of LTspice's behaviour. Treat as unverified until checked against LTspice
  running under Wine (install with `sudo apt install wine`, then `wine msiexec /i LTspice64.msi`).
  Mark entries **W** once verified there.

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

## Keyboard shortcuts (defaults)

User-programmable via Help > Keyboard Shortcut Cheat Sheet > Edit Keyboard Shortcuts, with load/save
to file (H keyboardshortcuts): ✅ (Help > Edit Keyboard Shortcuts; JSON files).

| Command | Default key | Source | Status |
|---|---|---|---|
| Component | F2 | R | ✅ (also P) |
| Draw Wire | F3 | R | ✅ (also W) |
| Label Net | F4 | R | ✅ (also N) |
| Delete | F5 / Del | R | ✅ |
| Duplicate | F6 / Ctrl+C | R | ✅ |
| Move | F7 | R | ✅ (also M) |
| Drag | F8 | R | ✅ |
| Undo / Redo | F9 / Shift+F9 | R | ✅ (also Ctrl+Z / Ctrl+Y) |
| Resistor, Capacitor, Inductor, Diode, GND, Text, SPICE directive | R, C, L, D, G, T, S | R | ✅ |
| Rotate / Mirror | Ctrl+R / Ctrl+E | R | ✅ |
| Zoom to Fit | Space | R | ✅ |
| Show Grid | Ctrl+G | R | ✅ |
| Mark unconnected pins | U | R | ✅ |
| Zoom back | Ctrl+B | R | ✅ |

## Colors and fonts

Defaults in `ui/theme.py`, all **R** until checked under Wine: white schematic background, blue wires and
junctions, black components and directives, blue comments; white waveform background with trace
order green, blue, red, cyan, magenta... Font: Arial, LTspice size index 0–7 → scale
0.625, 1, 1.5 (default), 2, 2.5, 3.5, 5, 7 (`model/geometry.py`). Tools > Color Preferences lets the
user click an object in a sample schematic and adjust RGB sliders (H schematiccolors). We use a list
of color buttons instead, which needs changing for parity.
