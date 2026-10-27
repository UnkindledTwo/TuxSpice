#!/usr/bin/env python3
"""Extract the symbol/model libraries, examples and help pages from the user's
own LTspice64.msi into a local data directory. Nothing is redistributed.
TuxSpice offers the same on first start (pyltspice.setup_lib, ui/setup_dialog.py)."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pyltspice import config, setup_lib  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("msi", type=Path)
    ap.add_argument("--dest", type=Path, default=config.LIB_ROOT)
    args = ap.parse_args()
    try:
        setup_lib.extract(args.msi, args.dest)
    except RuntimeError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
