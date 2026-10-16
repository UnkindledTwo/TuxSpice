"""Locations of the LTspice library data and external tools."""
import os
import shutil
from pathlib import Path

DATA_DIR = Path(os.environ.get("PYLTSPICE_DATA", Path.home() / ".local/share/pyltspice"))
LIB_ROOT = Path(os.environ.get("PYLTSPICE_LIB", DATA_DIR / "ltspice_lib"))
SYM_DIR = LIB_ROOT / "lib" / "sym"
SUB_DIR = LIB_ROOT / "lib" / "sub"
CMP_DIR = LIB_ROOT / "lib" / "cmp"
EXAMPLES_DIR = LIB_ROOT / "examples"
HELP_DIR = LIB_ROOT / "help"


def ngspice_path():
    """ngspice binary: $PYLTSPICE_NGSPICE, a bundled copy in DATA_DIR, or PATH."""
    env = os.environ.get("PYLTSPICE_NGSPICE")
    if env:
        return env
    local = DATA_DIR / "ngspice" / "usr" / "bin" / "ngspice"
    if local.exists():
        return str(local)
    return shutil.which("ngspice")


def user_background() -> Path:
    """Settings > Operation > Background image > User supplied (LTspice: %USERPROFILE%\\LTspice.jpg)."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "pyltspice" / "TuxSpice.jpg"
