"""LTspice text files are either UTF-16LE (newer versions) or 8-bit Latin-1."""
from pathlib import Path


def decode(data: bytes):
    """Return (text, encoding, newline)."""
    if data[:2] == b"\xff\xfe":
        enc, text = "utf-16-le", data[2:].decode("utf-16-le", errors="replace")
    elif len(data) > 1 and data[1] == 0:
        enc, text = "utf-16-le", data.decode("utf-16-le", errors="replace")
    else:
        enc, text = "latin-1", data.decode("latin-1")
    newline = "\r\n" if "\r\n" in text[:4096] else "\n"
    return text, enc, newline


def read_text(path: Path):
    return decode(Path(path).read_bytes())


def write_text(path: Path, text: str, encoding="latin-1", newline="\n"):
    text = text.replace("\r\n", "\n").replace("\n", newline)
    data = text.encode(encoding, errors="replace")
    Path(path).write_bytes(data)
