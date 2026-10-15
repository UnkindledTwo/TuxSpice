"""LTspice 'wavefile=' sources: a .wav file drives a node (full scale = ±1 V or ±1 A).

The samples are converted once to a time/value text file read by XSPICE 'filesource'."""
import hashlib
import struct
import wave
from pathlib import Path

from .. import config


def wav_to_text(path: Path, chan: int = 0) -> Path:
    path = Path(path)
    cache = config.DATA_DIR / "cache" / "wav"
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{path}|{chan}|{path.stat().st_mtime}".encode()).hexdigest()[:10]
    out = cache / f"{key}_{path.stem}_ch{chan}.txt"
    if out.exists():
        return out
    with wave.open(str(path), "rb") as w:
        nch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if chan >= nch:
        raise ValueError(f"{path.name} has {nch} channel(s); chan={chan} does not exist")
    full = float(2 ** (8 * width - 1))
    lines = []
    for i in range(n):
        off = (i * nch + chan) * width
        b = raw[off:off + width]
        if width == 1:
            v = (b[0] - 128) / 128.0                          # 8-bit WAV is unsigned
        elif width == 3:
            v = int.from_bytes(b, "little", signed=True) / full
        else:
            v = struct.unpack("<h" if width == 2 else "<i", b)[0] / full
        lines.append(f"{i / rate:.9g} {v:.6g}")
    out.write_text("\n".join(lines) + "\n")
    return out


def to_elements(name, n_p, n_m, wav_path: Path, chan: int, current=False):
    txt = wav_to_text(wav_path, chan)
    port = f"%id([{n_p} {n_m}])" if current else f"%vd([{n_p} {n_m}])"
    return [f"A{name} {port} {name}_wav",
            f'.model {name}_wav filesource (file="{txt}" amploffset=[0] amplscale=[1] '
            "timeoffset=0 timescale=1 timerelative=false amplstep=false)"]
