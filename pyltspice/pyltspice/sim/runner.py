"""Run ngspice on a translated netlist, including LTspice-style .step sweeps."""
import itertools
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from . import ltcompat, spicenum
from .rawfile import Plot, combine_steps, read_raw

SPICEINIT = "set ngbehavior=ltpsa\nset filetype=binary\n"


@dataclass
class SimResult:
    plots: list = field(default_factory=list)     # rawfile.Plot
    log: str = ""
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    measurements: list = field(default_factory=list)   # (name, text)
    raw_path: Path | None = None
    ok: bool = False

    def main_plot(self) -> Plot | None:
        """The analysis plot to show (skip the implicit operating point)."""
        for p in self.plots:
            if p.analysis != "op":
                return p
        return self.plots[0] if self.plots else None


class Cancelled(Exception):
    pass


# Fallbacks when ngspice fails to converge (LTspice also retries with other solver settings)
CONVERGENCE_RETRIES = [
    ".options reltol=0.003 method=gear",
    ".options reltol=0.01 method=gear itl1=500 itl4=200 gmin=1e-10",
]
RETRY_TIMEOUT = 30.0       # seconds a relaxed-settings retry may take
_NONCONVERGENCE = ("timestep too small", "gmin stepping failed", "source stepping failed",
                   "could not be simulated", "no convergence")


def _with_options(text: str, opt: str) -> str:
    lines = text.rstrip().splitlines()
    if lines and lines[-1].strip().lower() == ".end":
        lines.insert(len(lines) - 1, opt)
    else:
        lines.append(opt)
    return "\n".join(lines) + "\n"


def _apply_step(text: str, spec: ltcompat.StepSpec, value: float) -> str:
    val = f"{value:.12g}"
    lines = text.splitlines()
    if spec.is_param:
        name = spec.name.lower()
        out = []
        for line in lines:
            if line.lower().startswith(".param"):
                # drop this parameter's definition, keep the others on the line
                body = re.sub(r"\s*=\s*", "=", line[6:])
                parts = re.findall(r"(\S+?)=(\{[^}]*\}|\S+)", body)
                keep = [f"{k}={v}" for k, v in parts if k.lower() != name]
                if keep:
                    out.append(".param " + " ".join(keep))
                continue
            out.append(line)
        # insert the stepped value before the first non-title line
        out.insert(1, f".param {spec.name}={val}")
        return "\n".join(out) + "\n"
    # stepping an independent source / element value: replace its first value token
    out = []
    for line in lines:
        tok = line.split()
        if tok and tok[0].lower() == spec.name.lower() and len(tok) >= 3:
            rest = tok[3:]
            if rest and rest[0].lower() == "dc":
                rest = rest[1:]
            if rest and spicenum.parse(rest[0]) is not None:
                rest = rest[1:]
            line = " ".join(tok[:3] + [val] + rest)
        out.append(line)
    return "\n".join(out) + "\n"


def parse_measurements(log: str):
    out = []
    for line in log.splitlines():
        m = re.match(r"\s*([A-Za-z_][\w.]*)\s*=\s*(\S.*)$", line)
        if m and not line.lstrip().startswith(("Warning", "Note", "Error")) \
                and re.match(r"^[-+]?[\d.]", m.group(2)):
            out.append((m.group(1), m.group(2)))
    return out


def _error_lines(log: str):
    keys = ("error", "fatal", "unknown subckt", "unable to find", "could not find",
            "too few", "simulation interrupted", "no such", "singular matrix",
            "timestep too small", "aborted")
    return [l.strip() for l in log.splitlines() if any(k in l.lower() for k in keys)
            and "warning" not in l.lower()]


class Simulator:
    """Translate a netlist and run ngspice; call run() from a worker thread."""

    def __init__(self, netlist_text: str, out_base: Path, search_dirs=()):
        self.netlist_text = netlist_text
        self.out_base = Path(out_base)          # e.g. /dir/circuit -> circuit.raw, circuit.log
        self.search_dirs = list(search_dirs)
        self.proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def _run_once(self, cir_text: str, workdir: Path, tag: str, timeout=None):
        cir = workdir / f"run{tag}.cir"
        raw = workdir / f"run{tag}.raw"
        log = workdir / f"run{tag}.log"
        cir.write_text(cir_text, encoding="latin-1", errors="replace")
        exe = config.ngspice_path()
        if not exe:
            raise FileNotFoundError("ngspice not found. Install it with: sudo apt install ngspice")
        self.proc = subprocess.Popen([exe, "-b", "-r", str(raw), "-o", str(log), str(cir)],
                                     cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL)
        timed_out = False
        try:
            extra, _ = self.proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            extra, _ = self.proc.communicate()
            timed_out = True
        if self.cancelled:
            raise Cancelled()
        text = log.read_text(errors="replace") if log.exists() else ""
        text += extra.decode(errors="replace")
        if timed_out:
            return [], text + f"\nError: gave up after {timeout:.0f} s\n", raw
        plots = read_raw(raw) if raw.exists() and raw.stat().st_size else []
        return plots, text, raw

    def run(self) -> SimResult:
        res = SimResult()
        tr = ltcompat.translate(self.netlist_text, self.search_dirs)
        res.warnings += tr.warnings
        res.errors += tr.errors
        if tr.errors:
            res.log = "\n".join(tr.errors)
            return res
        self.out_base.parent.mkdir(parents=True, exist_ok=True)
        (self.out_base.parent / (self.out_base.name + ".ngspice.cir")).write_text(
            tr.text, encoding="latin-1", errors="replace")
        with tempfile.TemporaryDirectory(prefix="pyltspice-") as tmp:
            work = Path(tmp)
            (work / ".spiceinit").write_text(SPICEINIT)
            combos = list(itertools.product(*[s.values for s in tr.steps])) if tr.steps else [()]
            runs, logs, labels = [], [], []
            for n, combo in enumerate(combos):
                text = tr.text
                for spec, val in zip(tr.steps, combo):
                    text = _apply_step(text, spec, val)
                plots, log, raw = self._run_once(text, work, str(n))
                for opt in CONVERGENCE_RETRIES:
                    if not any(k in log.lower() for k in _NONCONVERGENCE):
                        break
                    plots2, log2, raw2 = self._run_once(_with_options(text, opt), work, f"{n}r",
                                                        timeout=RETRY_TIMEOUT)
                    log = log + f"\n--- retrying with relaxed settings: {opt}\n" + log2
                    plots, raw = plots2, raw2
                    if not any(k in log2.lower() for k in _NONCONVERGENCE):
                        res.warnings.append(f"Converged only with relaxed settings: {opt}")
                        log = log2 if plots else log
                        break
                label = " ".join(f"{s.name}={spicenum.fmt(v)}" for s, v in zip(tr.steps, combo))
                logs.append((f"Step {n + 1}/{len(combos)}: {label}\n" if label else "") + log)
                labels.append(label)
                errs = _error_lines(log)
                main = [pl for pl in plots if pl.analysis != "op"]
                if main and all(pl.data is None or pl.data.shape[1] == 0 for pl in main):
                    plots = []           # analysis aborted before producing any data
                runs.append(plots)
                if not plots:
                    res.errors += errs or ["ngspice produced no output"]
                    break
            res.log = "\n".join(logs)
            res.measurements = parse_measurements(res.log)
            if runs and all(runs) and len(runs) == len(combos):
                if len(runs) == 1:
                    res.plots = runs[0]
                else:
                    res.plots = [combine_steps([r[i] for r in runs], labels)
                                 for i in range(min(len(r) for r in runs))]
                res.ok = True
                raw_out = self.out_base.with_suffix(".raw")
                if len(runs) == 1:
                    raw_out.write_bytes(raw.read_bytes())
                res.raw_path = raw_out
        self.out_base.with_suffix(".log").write_text(res.log, errors="replace")
        return res
