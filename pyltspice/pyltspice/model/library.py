"""Symbol lookup over lib/sym plus per-schematic directories."""
from functools import lru_cache
from pathlib import Path

from .. import config
from .asy import Symbol, load_asy


def norm_name(name: str) -> str:
    """'Opamps\\\\opamp2' / 'Opamps/opamp2.asy' -> 'opamps/opamp2'."""
    n = name.replace("\\\\", "/").replace("\\", "/").strip("/").lower()
    return n[:-4] if n.endswith(".asy") else n


class SymbolLibrary:
    def __init__(self, roots=None):
        self.roots = [Path(r) for r in (roots or [config.SYM_DIR])]
        self.rescan()

    def rescan(self):
        """Index the symbol folders again (e.g. after first-run setup extracted them)."""
        self._by_rel = {}     # 'opamps/opamp2' -> path
        self._by_base = {}    # 'opamp2' -> path (first one found)
        for root in self.roots:
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                if p.suffix.lower() != ".asy":
                    continue
                rel = norm_name(str(p.relative_to(root)))
                self._by_rel.setdefault(rel, p)
                self._by_base.setdefault(rel.rsplit("/", 1)[-1], p)
        self._cache = {}

    def find(self, name: str, local_dirs=()) -> Path | None:
        n = norm_name(name)
        base = n.rsplit("/", 1)[-1]
        for d in local_dirs:
            d = Path(d)
            for cand in (d / (n + ".asy"), d / (base + ".asy")):
                hit = _ci_exists(cand)
                if hit:
                    return hit
        return self._by_rel.get(n) or self._by_base.get(base)

    def get(self, name: str, local_dirs=()) -> Symbol | None:
        key = (norm_name(name), tuple(str(d) for d in local_dirs))
        if key not in self._cache:
            p = self.find(name, local_dirs)
            self._cache[key] = load_asy(p, name) if p else None
        return self._cache[key]

    def categories(self):
        """Directory tree for the component browser: {'' : [...], 'opamps': [...]}"""
        tree = {}
        for rel in self._by_rel:
            folder, _, base = rel.rpartition("/")
            tree.setdefault(folder, []).append(base)
        return tree

    def path_for(self, rel: str) -> Path | None:
        return self._by_rel.get(norm_name(rel))


@lru_cache(maxsize=4096)
def _ci_exists_cached(parent: str, name_lower: str):
    try:
        for child in Path(parent).iterdir():
            if child.name.lower() == name_lower:
                return child
    except OSError:
        pass
    return None


def _ci_exists(path: Path) -> Path | None:
    """Case-insensitive file lookup (LTspice files come from Windows)."""
    if path.exists():
        return path
    parts = path.parts
    cur = Path(parts[0])
    for part in parts[1:]:
        nxt = _ci_exists_cached(str(cur), part.lower())
        if nxt is None:
            return None
        cur = nxt
    return cur


_default = None
# Settings > Search Paths > "Don't place symbols from schematic subdirectories" (off: search them)
SEARCH_SUBDIRS = True


def schematic_dirs(sch_path) -> list:
    """Folders searched for a schematic's own symbols and libraries: its folder and, as in
    LTspice, its subfolders (two levels deep, hidden ones skipped, at most 64)."""
    if not sch_path:
        return []
    folder = Path(sch_path).parent
    if not SEARCH_SUBDIRS:
        return [folder]
    try:
        stamp = folder.stat().st_mtime
    except OSError:
        return [folder]
    return [folder] + list(_subdirs(str(folder), stamp))


@lru_cache(maxsize=64)
def _subdirs(folder: str, _stamp) -> tuple:
    out, level = [], [Path(folder)]
    for _ in range(2):
        nxt = []
        for d in level:
            try:
                nxt += sorted(c for c in d.iterdir() if c.is_dir() and not c.name.startswith("."))
            except OSError:
                continue
        out += nxt
        level = nxt
        if len(out) >= 64:
            break
    return tuple(out[:64])


def default_library() -> SymbolLibrary:
    global _default
    if _default is None:
        _default = SymbolLibrary([config.SYM_DIR, config.BUNDLED_SYM])
    return _default


def set_extra_roots(roots):
    """Settings > Search Paths: symbol folders searched after lib/sym (new schematics use them)."""
    global _default
    roots = [Path(r) for r in roots if Path(r).is_dir()]
    if _default is not None and _default.roots[1:-1] == roots:
        return
    _default = SymbolLibrary([config.SYM_DIR] + roots + [config.BUNDLED_SYM])
