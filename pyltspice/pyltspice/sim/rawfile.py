"""Reader for SPICE .raw files written by ngspice or LTspice (binary or ASCII)."""
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class Variable:
    index: int
    name: str
    kind: str            # time, frequency, voltage, current, ...


@dataclass
class Plot:
    title: str = ""
    plotname: str = ""
    flags: set = field(default_factory=set)
    variables: list = field(default_factory=list)
    data: np.ndarray | None = None     # shape (nvars, npoints), real or complex
    step_bounds: list = field(default_factory=list)   # [(start, stop)] per .step run
    step_labels: list = field(default_factory=list)

    @property
    def is_complex(self):
        return "complex" in self.flags

    @property
    def xname(self):
        return self.variables[0].name if self.variables else ""

    def names(self):
        return [v.name for v in self.variables]

    def index_of(self, name):
        n = name.lower()
        for v in self.variables:
            if v.name.lower() == n:
                return v.index
        return None

    def get(self, name):
        i = self.index_of(name)
        return None if i is None else self.data[i]

    @property
    def x(self):
        x = self.data[0]
        return np.abs(x) if not self.is_complex else x.real

    @property
    def analysis(self):
        p = self.plotname.lower()
        if "pole-zero" in p:
            return "pz"
        if "distortion" in p:
            return "disto"
        # whole words: "DC transfer characteristic" contains "ac" as a substring
        for key in ("transient", "ac", "dc", "operating point", "noise", "transfer"):
            if re.search(rf"\b{key}\b", p):
                return {"transient": "tran", "operating point": "op", "transfer": "tf"}.get(key, key)
        return p


def _header_lines(raw: bytes, pos: int, utf16: bool):
    """Yield (line, next_pos) for header lines starting at pos."""
    if utf16:
        end = raw.find("\n".encode("utf-16-le"), pos)
        while end != -1 and (end - pos) % 2:
            end = raw.find("\n".encode("utf-16-le"), end + 1)
        if end == -1:
            return None, len(raw)
        return raw[pos:end].decode("utf-16-le").rstrip("\r"), end + 2
    end = raw.find(b"\n", pos)
    if end == -1:
        return None, len(raw)
    return raw[pos:end].decode("latin-1").rstrip("\r"), end + 1


def merge_sense_currents(plot: Plot):
    """AC runs carry 0 V sense sources (runner.add_ac_current_probes): copy their branch currents
    into the device current vectors ngspice left at zero, i(@r1[i]) <- i(v__isense_r1)."""
    if plot.data is None:
        return
    idx = {v.name.lower(): v.index for v in plot.variables}
    for v in plot.variables:
        m = re.match(r"^i\(v__isense_(.+)\)$|^v__isense_(.+)#branch$", v.name, re.I)
        if not m:
            continue
        dev = (m.group(1) or m.group(2)).lower()
        for target in (f"i(@{dev}[i])", f"@{dev}[i]"):
            if target in idx:
                plot.data[idx[target]] = plot.data[v.index]
                break


def read_raw(path) -> list[Plot]:
    plots = _read_raw(path)
    for p in plots:
        merge_sense_currents(p)
    return plots


def _read_raw(path) -> list[Plot]:
    raw = Path(path).read_bytes()
    utf16 = len(raw) > 1 and raw[1] == 0
    pos = 0
    plots = []
    while pos < len(raw):
        plot = Plot()
        nvars = npts = 0
        mode = None
        while True:
            line, pos = _header_lines(raw, pos, utf16)
            if line is None:
                break
            key, _, val = line.partition(":")
            k = key.strip().lower()
            if k == "title":
                plot.title = val.strip()
            elif k == "plotname":
                plot.plotname = val.strip()
            elif k == "flags":
                plot.flags = set(val.lower().split())
            elif k == "no. variables":
                nvars = int(val)
            elif k == "no. points":
                npts = int(val)
            elif k == "variables":
                for _ in range(nvars):
                    vline, pos = _header_lines(raw, pos, utf16)
                    if vline is None:          # truncated file (simulator crashed)
                        return plots
                    parts = vline.split()
                    plot.variables.append(Variable(int(parts[0]), parts[1],
                                                   parts[2] if len(parts) > 2 else ""))
            elif k in ("binary", "values"):
                mode = k
                break
        if mode is None:
            break
        if mode == "binary":
            pos = _read_binary(raw, pos, plot, nvars, npts, utf16)
        else:
            pos = _read_ascii(raw, pos, plot, nvars, npts, utf16)
        plots.append(plot)
    return plots


def _read_binary(raw, pos, plot, nvars, npts, utf16):
    ltspice = utf16 or "double" not in plot.flags and "complex" not in plot.flags \
        and _looks_ltspice(plot)
    if plot.is_complex:
        npts = min(npts, (len(raw) - pos) // (16 * nvars)) if nvars else 0
        size = 16 * nvars * npts
        arr = np.frombuffer(raw, dtype="<c16", count=nvars * npts, offset=pos)
        plot.data = arr.reshape(npts, nvars).T.copy()
        return pos + size
    if ltspice and "double" not in plot.flags:
        # LTspice: x axis as float64, everything else float32
        rec = np.dtype([("x", "<f8")] + [(f"v{i}", "<f4") for i in range(1, nvars)])
        arr = np.frombuffer(raw, dtype=rec, count=npts, offset=pos)
        data = np.empty((nvars, npts))
        data[0] = arr["x"]
        for i in range(1, nvars):
            data[i] = arr[f"v{i}"]
        plot.data = data
        return pos + rec.itemsize * npts
    npts = min(npts, (len(raw) - pos) // (8 * nvars)) if nvars else 0
    arr = np.frombuffer(raw, dtype="<f8", count=nvars * npts, offset=pos)
    plot.data = arr.reshape(npts, nvars).T.copy()
    return pos + 8 * nvars * npts


def _looks_ltspice(plot):
    return "forward" in plot.flags or "stepped" in plot.flags or "fastaccess" in plot.flags \
        or "LTspice" in plot.title


def _read_ascii(raw, pos, plot, nvars, npts, utf16):
    text = raw[pos:].decode("utf-16-le" if utf16 else "latin-1")
    toks = text.split()
    vals = []
    i = 0
    for _ in range(npts):
        i += 1                      # point index
        row = []
        for _v in range(nvars):
            t = toks[i]
            i += 1
            if plot.is_complex:
                re_, _, im = t.partition(",")
                row.append(complex(float(re_), float(im or 0)))
            else:
                row.append(float(t))
        vals.append(row)
    plot.data = np.array(vals, dtype=complex if plot.is_complex else float).T
    consumed = len(" ".join(toks[:i]).encode("utf-16-le" if utf16 else "latin-1"))
    return pos + max(consumed, len(raw) - pos)


def combine_steps(plots: list[Plot], labels: list[str]) -> Plot:
    """Concatenate one plot per .step run into a single stepped plot."""
    base = plots[0]
    names = base.names()
    out = Plot(base.title, base.plotname, set(base.flags) | {"stepped"}, list(base.variables))
    chunks, bounds, start = [], [], 0
    for p in plots:
        idx = [p.index_of(n) for n in names]
        chunk = np.vstack([p.data[i] if i is not None else np.full(p.data.shape[1], np.nan)
                           for i in idx])
        chunks.append(chunk)
        bounds.append((start, start + chunk.shape[1]))
        start += chunk.shape[1]
    out.data = np.hstack(chunks)
    out.step_bounds = bounds
    out.step_labels = labels
    return out
