"""Menu layouts, item for item as in LTspice 26.1.1 (observed under Wine, see docs/ui_spec.md).

LTspice swaps the whole menu bar with the kind of the active window: no window open, a schematic,
or a waveform plot. The right-click menus of schematics and plots reuse the same commands.

Entries: an action key, None for a separator, (title, [entries]) for a submenu,
"@recent" for the recent files (listed inline, as LTspice does) and "@windows" for the
numbered window list.
"""

HELP = ("&Help", ["help_topics", "help_shortcuts", "file_examples", None,
                  "help_model_changelog", "help_changelog", None, "help_about"])

LINE_STYLE = ("Line Style", ["style_0", "style_1", "style_2", "style_3", "style_4"])
DRAW = ("Draw", ["draw_line", "draw_rectangle", "draw_circle", "draw_arc", LINE_STYLE])
BOM = ("Bill of &Materials", ["bom_show", "bom_paste"])
EFFICIENCY = ("Efficiency &Report", ["eff_show", "eff_paste"])
MARCHING = ("Marching &Waves", ["march_restart", "march_pause"])
EFF_CALC = ("Efficiency Calculation", ["eff_start", "eff_end"])
WINDOW = ("&Window", ["win_tile_h", "win_tile_v", "win_cascade", "win_close_all", "win_arrange",
                      None, "@windows"])

EMPTY_MENUS = [
    ("&File", ["file_new", "file_new_symbol", "file_open", "file_examples", None,
               ("New &Library", ["file_new_lib_inductor"]), None,
               "file_print_setup", "file_print_mono", None, "@recent", None, "file_exit"]),
    ("&View", ["view_toolbar", "view_statusbar", "view_tabs"]),
    ("&Tools", ["tools_settings", "tools_colors", "tools_ai"]),
    HELP,
]

SCHEMATIC_MENUS = [
    ("&File", ["file_new", "file_new_symbol", "file_open", "file_examples", "file_save", "file_save_as",
               "file_close", None, "file_print", "file_print_preview", "file_print_setup", "file_print_mono",
               None, "@recent", None, "file_exit"]),
    ("&Edit", ["edit_undo", "edit_redo", "edit_text", "edit_directive", "sim_edit_cmd", "edit_resistor",
               "edit_capacitor", "edit_inductor", "edit_diode", "edit_component", "edit_import_model",
               "edit_rotate", "edit_mirror",
               "edit_wire", "edit_label", "edit_ground", "edit_bustap", "edit_delete", "edit_duplicate",
               "edit_move", "edit_drag", "edit_paste", DRAW]),
    ("&Hierarchy", ["hier_symbol", "hier_new_symbol", "hier_new_sheet", "hier_subckt"]),
    ("&View", ["view_zoom_area", "view_zoom_back", "view_fit", "view_recenter", None,
               "view_grid", "view_unconnected", "view_anchors", None, BOM, EFFICIENCY,
               "view_netlist", "view_log", "view_problems", None, "sim_add_trace", "plot_autorange", MARCHING,
               "view_probe_ref", None, "view_toolbar", "view_statusbar", "view_tabs"]),
    ("&Simulate", ["sim_run", "sim_halt", "sim_clear", EFF_CALC, None, "tools_settings", None,
                   "sim_edit_cmd", None, "sim_check"]),
    ("&Tools", ["tools_copy_bitmap", "tools_write_image", "tools_settings", "tools_colors",
                "tools_export_netlist", "tools_ai"]),
    WINDOW,
    HELP,
]

NOTES = ("Notes && Annotations", ["notes_cursor_pos", "notes_pm", "notes_gm", "notes_steps", None,
                                  "notes_text", "notes_arrow", "notes_line", "notes_rect", "notes_ellipse",
                                  "notes_style", "notes_nyquist"])
EYE = ("Eye Diagram", ["eye_setup"])

WAVEFORM_MENUS = [
    ("&File", ["file_new", "file_open", "file_examples", "plot_save", "plot_save_as", "file_close", None,
               "file_print", "file_print_preview", "file_print_setup", "file_print_mono", None,
               "file_export_data", "file_export_plot", "file_exec_meas", "file_fast_access", None, "@recent", None,
               "file_exit"]),
    ("&View", ["view_zoom_area", "view_zoom_back", "view_fit", "view_recenter", None, "view_log",
               "view_problems", None, "view_fft", None, "view_toolbar", "view_statusbar", "view_tabs"]),
    ("&Plot Settings", ["sim_add_trace", "plot_add_trace", "plot_delete_traces", "plot_select_steps",
                        "plot_cursor", "plot_clear_cursors", "plot_redraw", None,
                        "plot_pane_above", "plot_pane_below", "plot_pane_up", "plot_pane_down",
                        "plot_pane_delete", "plot_sync_x", None, "plot_grid", "plot_reset_colors",
                        "plot_mark_points", EYE, None, "plot_undo", "plot_redo", None,
                        "plot_autorange", "plot_manual_limits", "plot_autoranging", None, NOTES, None,
                        "plot_save_as", "plot_open", "plot_reload", None, "plot_defs", None,
                        "plot_meas_panel", "plot_step_legend", "plot_histogram"]),
    ("Simulatio&n", ["sim_run", "sim_halt", MARCHING]),
    ("&Tools", ["tools_copy_graph", "tools_write_image", "tools_settings", "tools_colors", "tools_ai"]),
    WINDOW,
    HELP,
]

SCHEMATIC_CONTEXT = [
    "sim_edit_cmd", "sim_run", "sim_halt",
    ("View", ["view_zoom_area", "view_fit", "view_anchors", "view_grid", None, "sim_add_trace",
              "view_opflags", None, "view_netlist", "view_log", None, EFFICIENCY, BOM, None,
              "ctx_copy_image", "tools_write_image"]),
    ("Edit", ["edit_move", "edit_drag", "edit_delete", "edit_duplicate", "edit_undo", "edit_redo"]),
    ("Draft", ["edit_wire", "edit_component", "edit_label", "edit_directive", "ctx_comment",
               "edit_dataflag", "edit_bustap"]),
    DRAW,
    ("Waveforms", ["sim_add_trace", "plot_autorange", "view_probe_ref", "sim_clear", MARCHING, EFF_CALC]),
    ("Hierarchy", ["hier_symbol"]),
    None,
    ("File", ["file_save", "file_save_as", "file_print", "file_print_preview", "file_examples"]),
    "win_float",
]

WAVEFORM_CONTEXT = [
    "view_fit", "plot_autorange",
    ("View", ["plot_grid", "plot_mark_points", "sim_add_trace", "plot_select_steps", "plot_manual_limits",
              "plot_reset_colors", "view_fft", "view_log", "ctx_plot_defs", "tools_copy_graph",
              "tools_write_image", "view_recenter", None, "plot_meas_panel", "plot_step_legend"]),
    "ctx_add_traces", "plot_cursor", "plot_clear_cursors", "plot_redraw", "ctx_pane_above",
    "ctx_pane_below", "ctx_pane_up", "ctx_pane_down", "ctx_pane_delete", "plot_sync_x",
    NOTES,
    ("Edit", ["ctx_plot_move", "ctx_plot_stretch", "plot_delete_traces", "ctx_plot_duplicate",
              "plot_undo", "plot_redo"]),
    "ctx_copy_graph", None,
    ("Marching &Waveforms", ["march_restart", "march_pause"]), None,
    ("File", ["plot_save", "plot_save_as", "plot_reload", None, "file_print", "file_print_preview", None,
              "file_export_data", "file_export_plot", "file_exec_meas", "file_fast_access"]),
    "win_float", "ctx_waveform_settings",
]


def build(menu, entries, actions, special=None):
    """Fill a QMenu from a layout. special(name, menu) handles the '@...' entries."""
    for e in entries:
        if e is None:
            menu.addSeparator()
        elif isinstance(e, tuple):
            build(menu.addMenu(e[0]), e[1], actions, special)
        elif e.startswith("@"):
            if special is not None:
                special(e, menu)
        else:
            menu.addAction(actions[e])
