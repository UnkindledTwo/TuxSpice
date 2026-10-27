"""Problems panel (a TuxSpice extra): the circuit check before a run and the explained
ngspice errors after a failed one. Clicking a problem highlights its parts and nets on the
schematic and brings them into view."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (QDockWidget, QLabel, QListWidget, QListWidgetItem, QSplitter, QVBoxLayout,
                               QWidget)
from shiboken6 import isValid


def objects_for(sw, issue):
    """Schematic objects an Issue points at: its parts (by InstName or netlist name) and the
    wires and labels of its nets (or, for a net with no wires, the parts touching it)."""
    from ..model.netlist import connectivity, spice_name, symbol_pins
    sch, lib, local = sw.doc.sch, sw.doc.lib, sw.doc.local_dirs
    want = {p.lower() for p in issue.parts if p}
    nets = {n.lower() for n in issue.nets if n}
    objs = []
    conn = connectivity(sch, lib) if nets else None
    for inst in sch.symbols:
        sym = lib.get(inst.symbol, local)
        names = {(inst.name or "").lower()} | ({spice_name(inst, sym).lower()} if sym else set())
        if names & want:
            objs.append(inst)
    if conn is not None:
        on_net = lambda x, y: (conn.net_at(x, y) or "").lower() in nets
        wires = [w for w in sch.wires if on_net(w.x1, w.y1) or on_net(w.x2, w.y2)]
        objs += wires + [f for f in sch.flags if on_net(f.x, f.y)]
        if not wires:
            for inst in sch.symbols:
                sym = lib.get(inst.symbol, local)
                if inst not in objs and any(on_net(*p.point) for p in symbol_pins(inst, sym)):
                    objs.append(inst)
    return objs


def severity_icon(severity, size=16):
    """A red disc for errors, an amber triangle for warnings (theme icons look alike in some
    GTK themes)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    if severity == "error":
        p.setBrush(QColor("#d32f2f"))
        p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
        fg = QColor("#ffffff")
    else:
        p.setBrush(QColor("#f2a900"))
        p.drawPolygon(QPolygonF([QPointF(size / 2, 1), QPointF(size - 1, size - 1), QPointF(1, size - 1)]))
        fg = QColor("#202020")
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * 0.7))
    p.setFont(f)
    p.setPen(fg)
    p.drawText(QRectF(0, size * 0.12 if severity != "error" else 0, size, size), Qt.AlignCenter, "!")
    p.end()
    return QIcon(pm)


class ProblemsDock(QDockWidget):
    def __init__(self, main):
        super().__init__("Problems", main)
        self.setObjectName("problems_dock")
        self.main = main
        self.source = None                # SchematicWindow the problems belong to
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 2, 4, 4)
        self.header = QLabel()
        lay.addWidget(self.header)
        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemClicked.connect(lambda it: self._selected(it))
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.hint.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hint.setMargin(6)
        split.addWidget(self.list)
        split.addWidget(self.hint)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        self.setWidget(body)
        self.issues = []

    def show_issues(self, source, issues, title):
        """List `issues` (model.check.Issue) for the schematic window `source` (may be None)."""
        self.source = source
        self.issues = list(issues)
        self.list.clear()
        self.hint.clear()
        icons = {"error": severity_icon("error"), "warning": severity_icon("warning")}
        for k, iss in enumerate(sorted(self.issues, key=lambda i: i.severity != "error")):
            it = QListWidgetItem(icons.get(iss.severity, icons["warning"]), iss.message)
            it.setData(Qt.UserRole, iss)
            it.setToolTip(iss.hint)
            self.list.addItem(it)
        errors = sum(i.severity == "error" for i in self.issues)
        warns = len(self.issues) - errors
        counts = ", ".join(s for s in (f"{errors} error(s)" if errors else "",
                                       f"{warns} warning(s)" if warns else "") if s) or "no problems found"
        self.header.setText(f"<b>{title}</b>: {counts}")
        if self.list.count():
            first = self.list.item(0).data(Qt.UserRole)
            self.hint.setText(first.hint or "")
        first_show = not self.isVisible() and not getattr(self, "_sized", False)
        self.show()
        self.raise_()
        if first_show:
            self._sized = True
            self.main.resizeDocks([self], [150], Qt.Vertical)

    def clear_for(self, source):
        if self.source is source:
            self.list.clear()
            self.hint.clear()
            self.issues = []
            self.header.setText("No problems")

    def _selected(self, item, *_):
        if item is None:
            return
        iss = item.data(Qt.UserRole)
        self.hint.setText(iss.hint or "")
        sw = self.source
        if sw is None or not isValid(sw):
            return
        objs = objects_for(sw, iss)
        sw.doc.scene.set_highlight(objs)
        rect = QRectF()
        for o in objs:
            gi = sw.doc.scene.item_of.get(id(o))
            if gi is not None:
                rect = rect.united(gi.sceneBoundingRect())
        if not rect.isNull():
            view = sw.view
            vis = view.mapToScene(view.viewport().rect()).boundingRect()
            if not vis.contains(rect):
                view.centerOn(rect.center())
        self.main.activate_window_of(sw)
