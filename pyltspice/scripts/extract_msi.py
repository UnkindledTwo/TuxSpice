#!/usr/bin/env python3
"""Extract the symbol/model libraries, examples and help pages from the user's
own LTspice64.msi into a local data directory. Nothing is redistributed."""
import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

DEFAULT_DEST = Path.home() / ".local/share/pyltspice/ltspice_lib"
HELP_EXT = {".htm", ".html", ".png", ".gif", ".svg", ".jpg", ".css"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("msi", type=Path)
    ap.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = ap.parse_args()
    if not shutil.which("7z"):
        sys.exit("7z is required (apt install p7zip-full)")
    args.dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        subprocess.run(["7z", "x", "-y", str(args.msi), "disk1.cab", f"-o{tmp}"],
                       check=True, stdout=subprocess.DEVNULL)
        cab = tmp / "cab"
        subprocess.run(["7z", "x", "-y", str(tmp / "disk1.cab"), f"-o{cab}"],
                       check=True, stdout=subprocess.DEVNULL)
        for name in ("lib.zip", "examples.zip", "reference.zip"):
            if not (cab / name).exists():
                continue          # reference.zip (docs for AI assistants) is new in LTspice 26.1
            with zipfile.ZipFile(cab / name) as z:
                z.extractall(args.dest)
            print(f"extracted {name}")
        help_dir = args.dest / "help"
        help_dir.mkdir(exist_ok=True)
        n = 0
        for f in cab.iterdir():
            if f.suffix.lower() in HELP_EXT:
                shutil.copy2(f, help_dir / f.name)
                n += 1
        for name in ("ChangeLog.txt", "LTspiceChangeLog.txt"):
            if (cab / name).exists():
                shutil.copy2(cab / name, help_dir / name)
                n += 1
        print(f"copied {n} help files")
    print(f"done -> {args.dest}")


if __name__ == "__main__":
    main()
