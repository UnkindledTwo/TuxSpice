"""First-run setup: find the user's own LTspice64.msi and extract its symbol/model libraries,
examples and help pages into the data directory. Nothing is redistributed."""
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from . import config

HELP_EXT = {".htm", ".html", ".png", ".gif", ".svg", ".jpg", ".css"}
DOWNLOAD_URL = "https://www.analog.com/en/resources/design-tools-and-calculators/ltspice-simulator.html"


def have_7z():
    return shutil.which("7z") is not None


def find_installers(dirs=None):
    """LTspice*.msi in the usual places (Downloads, Desktop, home, the working directory) and
    one folder below them, newest first."""
    home = Path.home()
    dirs = dirs if dirs is not None else [home / "Downloads", home / "Desktop", home, Path.cwd()]
    found = set()
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for pat in ("*.msi", "*/*.msi"):
            try:
                for p in d.glob(pat):
                    if p.name.lower().startswith("ltspice") and p.is_file():
                        found.add(p.resolve())
            except OSError:
                continue
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def extract(msi, dest=None, log=print):
    """Unpack lib.zip, examples.zip, reference.zip and the help pages from the installer.
    Needs 7z (p7zip-full) for the MSI and its cabinet."""
    dest = Path(dest or config.LIB_ROOT)
    if not have_7z():
        raise RuntimeError("7z is required: sudo apt install p7zip-full")
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        log("Unpacking the installer...")
        _7z(["x", "-y", str(msi), "disk1.cab", f"-o{tmp}"])
        if not (tmp / "disk1.cab").exists():
            raise RuntimeError(f"{Path(msi).name} doesn't look like an LTspice installer (no disk1.cab)")
        cab = tmp / "cab"
        log("Unpacking its cabinet...")
        _7z(["x", "-y", str(tmp / "disk1.cab"), f"-o{cab}"])
        for name in ("lib.zip", "examples.zip", "reference.zip"):
            if not (cab / name).exists():
                continue          # reference.zip (docs for AI assistants) is new in LTspice 26.1
            log(f"Extracting {name}...")
            with zipfile.ZipFile(cab / name) as z:
                z.extractall(dest)
        help_dir = dest / "help"
        help_dir.mkdir(exist_ok=True)
        n = 0
        for f in cab.iterdir():
            if f.suffix.lower() in HELP_EXT or f.name in ("ChangeLog.txt", "LTspiceChangeLog.txt"):
                shutil.copy2(f, help_dir / f.name)
                n += 1
        log(f"Copied {n} help files")
    if not (dest / "lib" / "sym").is_dir():
        raise RuntimeError("The installer had no symbol library (lib/sym)")
    log(f"Done: {dest}")
    return dest


def _7z(args):
    r = subprocess.run(["7z", *args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError("7z failed: " + (r.stderr.strip().splitlines() or ["?"])[-1])
