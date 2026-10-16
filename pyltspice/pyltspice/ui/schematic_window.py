"""MDI child showing one schematic, with editing modes, editors and probing."""
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtWidgets import QDialog, QInputDialog, QMenu, QMessageBox, QVBoxLayout, QWidget

from ..model import asc
from ..model.asy import WINDOW_ATTR
from ..model.geometry import TextFrame, apply, orient_matrix
from ..model.netlist import symbol_pins
from . import dialogs, tools
from .document import SchematicDocument
from .render import text_bounds
from .schematic_view import SchematicView


class SchematicWindow(QWidget):
    status = Signal(str)
    probed = Signal(str)          # expression to plot
    title_changed = Signal()
    mode_changed = Signal()       # editing mode or carry state changed (Rotate/Mirror enabling)

    def __init__(self, doc: SchematicDocument, main):
        super().__init__()
        self.doc = doc
        self.main = main
        self.cursors = main.cursors
        self.view = SchematicView(doc.scene)
        from .settings_dialog import get
        self.view.show_grid = get("view/grid")
        self.view.reverse_wheel = get("drafting/reverse_wheel")
        self.view.mark_unconnected = get("drafting/mark_unconnected")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.tool = None
        self.sim_plot = None          # rawfile.Plot of the last run
        self.set_tool(None)
        doc.changed.connect(self.title_changed)
        doc.undo.cleanChanged.connect(lambda _: self.title_changed.emit())
        self.view.mouse_moved.connect(self._mouse_moved)
        self.setAttribute(Qt.WA_DeleteOnClose)

    # -- window identity
    @property
    def title(self):
        return self.doc.title + ("*" if self.doc.modified else "")

    # LTspice opens an empty sheet zoomed so a resistor is about 190 px tall
    NEW_SHEET_SCALE = 2.3

    def showEvent(self, ev):
        super().showEvent(ev)
        if not getattr(self, "_fitted", False):
            self._fitted = True
            if self.doc.sch.items:
                self.view.zoom_to_fit()
            else:
                self.view.resetTransform()
                self.view.scale(self.NEW_SHEET_SCALE, self.NEW_SHEET_SCALE)
                self.view.centerOn(0, 0)

    def _mouse_moved(self, x, y):
        if self.tool and self.tool.status:
            self.status.emit(self.tool.status)

    # -- modes
    def set_tool(self, tool):
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = tool or tools.IdleTool(self)
        self.view.tool = self.tool
        self.tool.activate()
        self.view.viewport().update()
        self.status.emit(self.tool.status or "")
        self.mode_changed.emit()

    def start_zoom_area(self):
        self.set_tool(tools.ZoomAreaTool(self))

    def find_text(self, text) -> int:
        """Highlight objects whose name, attributes, label or text contain `text` (case-insensitive)."""
        from ..model import asc
        needle = text.lower()
        hits = []
        for o in self.doc.sch.items:
            if isinstance(o, asc.SymbolInst):
                fields = [o.symbol, *o.attrs.values()]
            elif isinstance(o, asc.Flag):
                fields = [o.name]
            elif isinstance(o, asc.Text):
                fields = [o.text]
            else:
                continue
            if any(needle in str(f).lower() for f in fields):
                hits.append(o)
        self.doc.scene.set_highlight(hits)
        return len(hits)

    def start_wire(self):
        self.set_tool(tools.WireTool(self))

    def start_draw(self, kind):
        self.set_tool(tools.DrawTool(self, kind))

    def start_delete(self):
        self.set_tool(tools.DeleteTool(self))

    def start_move(self, mode="move"):
        self.set_tool(tools.MoveTool(self, mode))

    def place_symbol(self, symbol_name, attrs=None, label="Place Component"):
        sym = self.doc.lib.get(symbol_name, self.doc.local_dirs)
        if sym is None:
            QMessageBox.warning(self, "Component", f"Could not find symbol {symbol_name}")
            return

        def factory():
            # LTspice places with the symbol origin at the cursor, snapped to the grid
            inst = asc.SymbolInst(symbol_name, 0, 0, "R0", {}, dict(attrs or {}))
            return [inst]
        self.set_tool(tools.PlaceTool(self, factory, repeat=True, label=label))

    def place_ground(self):
        self.set_tool(tools.PlaceTool(self, lambda: [asc.Flag(0, 0, "0")], label="Place GND"))

    def place_data_flag(self):
        self.set_tool(tools.PlaceTool(self, lambda: [asc.DataFlag(0, 0, '""')], repeat=True,
                                      label="Place .op Data Label"))

    def place_label(self):
        dlg = dialogs.NetLabelDialog(self)
        dlg.set_names([f.name for f in self.doc.sch.flags if f.name != "0"])
        if dlg.exec() != QDialog.Accepted:
            return
        proto = asc.Flag(0, 0, "N")
        dlg.apply_to(proto)
        self.set_tool(tools.PlaceTool(self, lambda: [asc.Flag(0, 0, proto.name, proto.iopin)],
                                      repeat=False, label="Label Net"))

    def place_text(self, directive=False):
        dlg = dialogs.TextDialog(self, directive=directive)
        if dlg.exec() != QDialog.Accepted:
            return
        t = dlg.result_text()
        if len(t.text) <= 1:
            return
        self.set_tool(tools.PlaceTool(self, lambda: [asc.Text(0, 0, t.just, t.size, t.text)],
                                      repeat=False, label="Text"))

    def rotate_or_mirror(self, mirror=False):
        """Ctrl+R / Ctrl+E outside of a carry: forwarded to the active tool."""
        from PySide6.QtGui import QKeyEvent
        if hasattr(self.tool, "orient"):
            self.tool.orient(mirror)
            return
        key = Qt.Key_E if mirror else Qt.Key_R
        ev = QKeyEvent(QKeyEvent.KeyPress, key, Qt.ControlModifier)
        self.tool.key(self.view, ev)

    # -- editing objects (right-click)
    def edit_object(self, obj, ctrl=False, at=None):
        if isinstance(obj, asc.SymbolInst):
            self.edit_symbol(obj, ctrl, at)
        elif isinstance(obj, asc.Text):
            dlg = dialogs.TextDialog(self, obj)
            if dlg.exec() == QDialog.Accepted:
                self.doc.begin()
                new = dlg.result_text(obj.x, obj.y)
                obj.just, obj.size, obj.text = new.just, new.size, new.text
                self.doc.commit("Edit Text")
        elif isinstance(obj, asc.Flag):
            dlg = dialogs.NetLabelDialog(self, obj)
            dlg.set_names([f.name for f in self.doc.sch.flags if f.name != "0"])
            if dlg.exec() == QDialog.Accepted:
                self.doc.begin()
                dlg.apply_to(obj)
                self.doc.commit("Edit Label")
        elif isinstance(obj, asc.Wire):
            self.context_menu(self.cursor().pos())

    def _attr_window_at(self, inst, sym, at):
        """Which displayed attribute (Value, InstName...) lies under the mouse."""
        if at is None or sym is None:
            return None
        m = orient_matrix(inst.orient)
        windows = dict(sym.windows)
        windows.update(inst.windows)
        item = self.doc.scene.item_of.get(id(inst))
        for idx, w in windows.items():
            key = WINDOW_ATTR.get(idx)
            if key is None or w.just == "Invisible":
                continue
            text = item.attr_value(key) if item else ""
            if not text:
                continue
            x, y = apply(m, w.x, w.y)
            r = text_bounds(x + inst.x, y + inst.y, TextFrame.from_just(w.just).transformed(m), w.size, text)
            if r.adjusted(-2, -2, 2, 2).contains(at):
                return key
        return None

    def edit_symbol(self, inst, ctrl=False, at=None):
        sym = self.doc.lib.get(inst.symbol, self.doc.local_dirs)
        key = self._attr_window_at(inst, sym, at)
        prefix = (inst.attrs.get("Prefix") or (sym.prefix if sym else "X"))[:1].upper()
        base = inst.symbol.replace("\\\\", "/").replace("\\", "/").split("/")[-1].lower()
        self.doc.begin()
        accepted = False
        self.status.emit(f"Editing component: {inst.name}")
        if ctrl:
            dlg = dialogs.AttributeEditor(self, inst, sym)
            if dlg.exec() == QDialog.Accepted:
                dlg.apply()
                accepted = True
        elif key is not None:
            # Expert mode: right-click on the text itself edits that attribute
            cur = inst.attrs.get(key, sym.attrs.get(key, "") if sym else "")
            label = f"Enter new {key} for {inst.name}" if key != "InstName" else "Enter new instance name"
            text, ok = QInputDialog.getText(self, inst.name, label, text=cur)
            if ok:
                inst.attrs[key] = text
                accepted = True
        elif prefix in "RCL" and base in ("res", "res2", "cap", "polcap", "ind", "ind2"):
            dlg = dialogs.RLCDialog(self, inst, prefix, sym)
            if dlg.exec() == QDialog.Accepted:
                dlg.apply()
                accepted = True
        elif prefix in "VI" and base in ("voltage", "current"):
            # LTspice first shows a small DC editor; Advanced (or a non-DC value) opens the full one
            full = not dialogs.SimpleSourceDialog.handles(inst)
            if not full:
                dlg = dialogs.SimpleSourceDialog(self, inst, current=prefix == "I")
                if dlg.exec() == QDialog.Accepted:
                    dlg.apply()
                    accepted = True
                    full = dlg.advanced
            if full:
                dlg = dialogs.VoltageSourceDialog(self, inst, current=prefix == "I")
                dialogs.popup_at_cursor(dlg)
                if dlg.exec() == QDialog.Accepted:
                    dlg.apply()
                    accepted = True
        else:
            dlg = dialogs.AttributeEditor(self, inst, sym)
            if dlg.exec() == QDialog.Accepted:
                dlg.apply()
                accepted = True
        self.status.emit("")
        if accepted:
            self.doc.commit("Edit Component")
        else:
            self.doc.abort()

    def context_menu(self, global_pos):
        m = QMenu(self)
        a = self.main.actions
        for key in ("edit_component", "edit_wire", "edit_label", "edit_ground", "edit_text",
                    "edit_directive", None, "edit_delete", "edit_duplicate", "edit_move",
                    "edit_drag", None, "sim_edit_cmd", "sim_run", None, "view_fit"):
            if key is None:
                m.addSeparator()
            elif key in a:
                m.addAction(a[key])
        m.exec(global_pos)

    # -- hierarchy
    def descend(self, inst):
        """Open the schematic behind a hierarchical block (same name .asc)."""
        name = inst.symbol.replace("\\\\", "/").replace("\\", "/").split("/")[-1]
        for d in self.doc.local_dirs:
            p = Path(d) / f"{name}.asc"
            if p.exists():
                self.main.open_file(p)
                return

    # -- probing
    def probe_active(self):
        return self.sim_plot is not None

    def probe(self, pos, objs, alt=False):
        expr = self.probe_expr(pos, objs, alt)
        if expr:
            self.probed.emit(expr)

    def probe_hint(self, obj) -> str:
        """Status bar text while hovering with a probe, worded like LTspice's."""
        from ..sim.spicenum import fmt
        if isinstance(obj, asc.Wire):
            pos = QPointF(obj.x1, obj.y1)
        else:
            pos = QPointF(obj.x, obj.y)
        expr = self.probe_expr(pos, [obj])
        if not expr:
            return ""
        v = self._op_value(expr)
        if isinstance(obj, asc.SymbolInst):
            text = f"Left-click to plot {expr}.  Right click to edit."
            if v is not None:
                text += f"  DC operating point: {expr} = {fmt(v, 'A', 4)}"
            return text
        text = f"Click to plot {expr.upper()}."
        if v is not None:
            text += f"  DC operating point: {expr} = {fmt(v, 'V', 4)}"
        return text

    def _op_value(self, expr):
        """Operating-point value for the hover hint: from a .op run, else the first point of
        the last run (LTspice reports the transient's starting operating point)."""
        v = self.doc.scene.op_values.get(expr.lower())
        if v is not None:
            return v
        plot = self.sim_plot
        if plot is None or plot.is_complex or plot.data is None or not plot.data.shape[1]:
            return None
        if getattr(self, "_op_vectors_for", None) is not plot:
            from ..sim.vectors import VectorSet
            self._op_vectors, self._op_vectors_for = VectorSet(plot), plot
        y = self._op_vectors.get(expr)
        return None if y is None else float(y[0].real)

    def probe_expr(self, pos, objs, alt=False):
        expr = None
        sym_hit = next((o for o in objs if isinstance(o, asc.SymbolInst)), None)
        if sym_hit is not None:
            sym = self.doc.lib.get(sym_hit.symbol, self.doc.local_dirs)
            prefix = (sym_hit.attrs.get("Prefix") or (sym.prefix if sym else "X"))[:1].upper()
            name = sym_hit.name.upper()
            if name and name[0] != prefix:
                name = prefix + name
            if prefix == "Q":
                expr = f"Ic({name})"
            elif prefix in "MJ":
                expr = f"Id({name})"
            elif prefix in "RCLVIDBEFGH":
                expr = f"I({name})"
            if alt and expr and sym is not None and len(sym.pins) == 2:
                pins = symbol_pins(sym_hit, sym)
                n = [self.doc.scene.conn.net_at(*p.point) for p in sorted(pins, key=lambda p: p.pin.order)]
                expr = f"V({n[0]},{n[1]})*{expr}" if n[1] != "0" else f"V({n[0]})*{expr}"
        else:
            p = self.view.snap(pos)
            net = self.doc.scene.conn.net_at(int(p.x()), int(p.y()))
            if net is None:
                for o in objs:
                    if isinstance(o, asc.Wire):
                        net = self.doc.scene.conn.net_at(o.x1, o.y1)
                    elif isinstance(o, asc.Flag):
                        net = self.doc.scene.conn.net_at(o.x, o.y)
                    if net:
                        break
            if net and net != "0":
                expr = f"V({net})"
        return expr
