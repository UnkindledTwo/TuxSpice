"""LTspice plot settings (.plt): which traces go in which pane, per analysis.

Only the pane/trace layout is used; axis ranges and colour codes are ignored for now."""
import re
from pathlib import Path

from ..model.textio import read_text, write_text


def read_plt(path) -> dict:
    """{'transient analysis': [[expr, ...] per pane, top pane first], ...}"""
    text = read_text(path)[0]
    out = {}
    for m in re.finditer(r"\[([^\]]+)\]\s*\{", text):
        name = m.group(1).strip().lower()
        start = m.end()
        depth, i = 1, start
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        body = text[start:i - 1]
        panes = []
        for tl in re.finditer(r"(?m)^\s*traces:\s*\d+\s*(.*)$", body):
            panes.append(re.findall(r'\{\s*\d+\s*,\s*\d+\s*,\s*"((?:[^"\\]|\\.)*)"\s*\}', tl.group(1)))
        out[name] = panes
    return out


def write_plt(path, sections: dict, encoding="latin-1"):
    """sections: {'Transient Analysis': [[expr, ...], ...]}"""
    lines = []
    for name, panes in sections.items():
        lines += [f"[{name}]", "{", f"   Npanes: {len(panes)}"]
        for k, traces in enumerate(panes):
            items = " ".join(f'{{{524290 + j},0,"{t}"}}' for j, t in enumerate(traces))
            lines += ["   {", f"      traces: {len(traces)} {items}", "   }" + ("," if k < len(panes) - 1 else "")]
        lines.append("}")
    write_text(Path(path), "\n".join(lines) + "\n", encoding)


def plt_for(schematic_path) -> Path | None:
    """The .plt that belongs to a schematic (same name), if it exists."""
    if schematic_path is None:
        return None
    p = Path(schematic_path)
    for cand in p.parent.iterdir() if p.parent.is_dir() else []:
        if cand.suffix.lower() == ".plt" and cand.stem.lower() == p.stem.lower():
            return cand
    return None
