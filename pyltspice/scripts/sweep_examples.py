#!/usr/bin/env python3
"""Simulate many schematics in parallel and classify each one.

    sweep_examples.py OUT.tsv [--jobs N] [--timeout S] [--static] FILE_OR_DIR...

Each schematic runs in its own subprocess (killed after --timeout seconds, default 60).
Results go to OUT.tsv, one line per file: status, seconds, path, first message.
Status is OK, FAIL, TIMEOUT or ENCRYPTED (an encrypted ADI model, which only LTspice can run).
--static only netlists and translates (fast): it finds ENCRYPTED and netlist errors without
simulating. Files already listed in OUT.tsv are skipped, so an interrupted sweep resumes.
"""
import argparse
import os
import shutil
import signal
import subprocess
import tempfile
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = r"""
import sys, tempfile
sys.path.insert(0, {root!r})
from pathlib import Path
from pyltspice.model.asc import load_asc
from pyltspice.model.netlist import generate_netlist
from pyltspice.sim.ltcompat import translate
p = Path(sys.argv[1])
nl = generate_netlist(load_asc(p))
tr = translate(nl.text, [p.parent])
enc = [e for e in tr.errors if "encrypted" in e]
if enc:
    print("RESULT ENCRYPTED", enc[0]); sys.exit(0)
if {static}:
    msg = (nl.errors + tr.errors)[:1]
    print("RESULT", "FAIL" if msg else "OK", msg[0] if msg else ""); sys.exit(0)
from pyltspice.sim.runner import Simulator
out = Path(tempfile.mkdtemp()) / p.stem
r = Simulator(nl.text, out, [p.parent]).run()
msg = ""
if not r.ok:
    # the most specific line: what ngspice choked on, else our own first error
    import re
    lines = r.log.splitlines()
    for i, l in enumerate(lines):
        if "Error on line" in l:
            msg = " || ".join(x.strip() for x in lines[i + 1:i + 3]); break
        if re.search(r"(?i)^\s*(error|fatal)", l) and "interrupted" not in l:
            msg = " || ".join(x.strip() for x in lines[i:i + 2]); break
    msg = msg or " | ".join(e.replace("\n", " ") for e in r.errors)
print("RESULT", "OK" if r.ok else "FAIL", msg.replace("\t", " ")[:300])
"""


def run_one(path: Path, timeout: float, static: bool):
    t0 = time.time()
    code = WORKER.format(root=str(ROOT), static=static)
    # each run gets its own TMPDIR, removed afterwards: a run killed at the time limit can't
    # clean up the simulator's work files itself, and long runs write gigabytes of raw data
    tmp = tempfile.mkdtemp(prefix="sweep-")
    env = dict(os.environ, TMPDIR=tmp)
    proc = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True, env=env)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)      # the worker *and* its ngspice
        proc.communicate()
        return "TIMEOUT", time.time() - t0, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    line = next((l for l in stdout.splitlines() if l.startswith("RESULT ")), None)
    if line is None:
        err = (stderr.strip().splitlines() or ["no result"])[-1][:200]
        return "FAIL", time.time() - t0, err
    _, status, *msg = line.split(" ", 2)
    return status, time.time() - t0, (msg[0] if msg else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--static", action="store_true")
    a = ap.parse_args()
    files = []
    for p in map(Path, a.paths):
        files += sorted(p.rglob("*.asc")) if p.is_dir() else [p]
    out = Path(a.out)
    done = set()
    if out.exists():
        done = {l.split("\t")[2] for l in out.read_text().splitlines() if l.count("\t") >= 3}
    todo = [f for f in files if str(f) not in done]
    print(f"{len(files)} files, {len(todo)} to run, {a.jobs} jobs", flush=True)
    with out.open("a") as fh, ThreadPoolExecutor(a.jobs) as pool:
        futs = {pool.submit(run_one, f, a.timeout, a.static): f for f in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            status, secs, msg = fut.result()
            fh.write(f"{status}\t{secs:.1f}\t{futs[fut]}\t{msg}\n")
            fh.flush()
            if n % 50 == 0:
                print(f"{n}/{len(todo)}", flush=True)
    rows = [l.split("\t") for l in out.read_text().splitlines() if l.count("\t") >= 3]
    counts = {}
    for r in rows:
        counts[r[0]] = counts.get(r[0], 0) + 1
    print(" ".join(f"{k}={v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
