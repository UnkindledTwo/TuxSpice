"""Automatic waveform measurements for the plot's Measurements panel (a TuxSpice extra).

LTspice measures only what a .meas directive asks for. These are computed for the trace under
study over the x range on screen: level statistics, frequency and duty cycle, 10-90 % edges
and overshoot for transient data; peak gain, -3 dB band edges, unity-gain frequency and the
loop margins for AC data. Transient steps aren't evenly spaced, so time-weighted statistics
resample the trace onto a uniform grid first."""
import numpy as np

GRID = 20000          # uniform resample for percentiles and edges


def _crossing(f, v, i, level):
    """Frequency (interpolated in log f) and fraction where v crosses level between i and i+1."""
    t = (level - v[i]) / (v[i + 1] - v[i])
    return 10 ** (np.log10(f[i]) + t * (np.log10(f[i + 1]) - np.log10(f[i]))), t


def phase_margin(f, z):
    """(frequency, degrees) at the first downward 0 dB crossing of the loop gain z, or None.
    LTspice doesn't document its Annotate Phase Margin; this is the textbook definition,
    180 deg + phase there, wrapped to (-180, 180] so it doesn't matter which multiple of
    360 deg the unwrapped phase starts at."""
    mag = 20 * np.log10(np.maximum(np.abs(z), 1e-300))
    ph = np.degrees(np.unwrap(np.angle(z)))
    hits = np.flatnonzero((mag[:-1] > 0) & (mag[1:] <= 0))
    if not len(hits):
        return None
    i = hits[0]
    fc, t = _crossing(f, mag, i, 0.0)
    pm = (ph[i] + t * (ph[i + 1] - ph[i]) + 360) % 360 - 180
    return fc, (180.0 if pm == -180 else pm)


def gain_margin(f, z):
    """(frequency, dB) at the first phase crossing of -180 deg (mod 360), or None.
    Gain margin is minus the loop gain there (undocumented in LTspice, as phase_margin)."""
    mag = 20 * np.log10(np.maximum(np.abs(z), 1e-300))
    ph = np.degrees(np.unwrap(np.angle(z)))
    turn = np.floor((ph + 180) / 360)          # which odd multiple of 180 deg lies below
    hits = np.flatnonzero(turn[1:] != turn[:-1])
    if not len(hits):
        return None
    i = hits[0]
    level = 360 * max(turn[i], turn[i + 1]) - 180
    fc, t = _crossing(f, ph, i, level)
    return fc, -(mag[i] + t * (mag[i + 1] - mag[i]))


def _cross_times(x, y, level, rising):
    """Interpolated x where y crosses level, upward (rising) or downward."""
    above = y >= level
    idx = np.flatnonzero((~above[:-1] & above[1:]) if rising else (above[:-1] & ~above[1:]))
    t = (level - y[idx]) / (y[idx + 1] - y[idx])
    return x[idx] + t * (x[idx + 1] - x[idx])


def _edges(x, y, lo, hi):
    """Times of the rising and falling 50 % crossings, counting an edge only once the signal
    leaves a 10 % band around the threshold (noise or ringing near it isn't an extra edge)."""
    mid, band = (lo + hi) / 2, 0.1 * (hi - lo)
    up, down = _cross_times(x, y, mid, True), _cross_times(x, y, mid, False)
    state = np.where(y >= mid + band, 1, np.where(y <= mid - band, -1, 0))
    nz = np.flatnonzero(state)
    s = state[nz]
    rises, falls = [], []
    for c in np.flatnonzero(s[1:] != s[:-1]) + 1:
        xi = x[nz[c]]
        cand = (up if s[c] == 1 else down)
        cand = cand[cand <= xi]
        (rises if s[c] == 1 else falls).append(float(cand[-1]) if len(cand) else float(xi))
    return rises, falls


def _transition(x, y, a, b, rising):
    """x at which y passes level b after last being on the other side of level a."""
    hit_b = _cross_times(x, y, b, rising)
    hit_a = _cross_times(x, y, a, rising)
    for tb in hit_b:
        before = hit_a[hit_a <= tb]
        if len(before):
            return tb - before[-1]
    return None


def time_measures(x, y):
    """[(label, value, unit-kind)] for real data y(x); unit-kind is 'y', 'x', '%', 'Hz' or ''."""
    x, y = np.asarray(np.real(x), float), np.asarray(np.real(y), float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 2 or x[-1] <= x[0]:
        return []
    T = x[-1] - x[0]
    out = [("Minimum", float(y.min()), "y"), ("Maximum", float(y.max()), "y"),
           ("Peak-to-peak", float(y.max() - y.min()), "y"),
           ("Average", float(np.trapezoid(y, x) / T), "y"),
           ("RMS", float(np.sqrt(np.trapezoid(y * y, x) / T)), "y")]
    pp = y.max() - y.min()
    if pp <= 1e-12 * max(1.0, abs(y.max())):
        return out
    xu = np.linspace(x[0], x[-1], GRID)
    yu = np.interp(xu, x, y)
    mid = (yu.max() + yu.min()) / 2
    lo, hi = float(np.median(yu[yu < mid])), float(np.median(yu[yu >= mid]))
    rises, falls = _edges(xu, yu, lo, hi)
    square = np.mean((np.abs(yu - lo) < 0.1 * (hi - lo)) | (np.abs(yu - hi) < 0.1 * (hi - lo))) > 0.7
    if len(rises) >= 2:
        period = float(np.median(np.diff(rises)))
        out += [("Frequency", 1 / period, "Hz"), ("Period", period, "x")]
        if square and falls:
            highs = [next((f for f in falls if f > r), None) for r in rises[:-1]]
            highs = [f - r for r, f in zip(rises, highs) if f is not None]
            if highs:
                out.append(("Duty cycle", 100 * float(np.median(highs)) / period, "%"))
    if square or len(rises) + len(falls) <= 2:
        if len(rises) + len(falls) <= 2:          # a single step: settle on its final value
            first, final = float(yu[0]), float(np.mean(yu[-(GRID // 50):]))
            lo, hi = min(first, final), max(first, final)
            if hi - lo < 0.05 * pp:
                return out
        span = hi - lo
        r = _transition(xu, yu, lo + 0.1 * span, lo + 0.9 * span, True)
        f = _transition(xu, yu, hi - 0.1 * span, hi - 0.9 * span, False)
        if r is not None:
            out.append(("Rise time 10-90%", r, "x"))
        if f is not None:
            out.append(("Fall time 90-10%", f, "x"))
        if r is not None or f is not None:
            out.append(("Overshoot", 100 * max(0.0, float(yu.max()) - hi) / span, "%"))
            out.append(("Undershoot", 100 * max(0.0, lo - float(yu.min())) / span, "%"))
    return out


def ac_measures(f, z):
    """[(label, value, unit-kind)] for a complex response z(f); unit-kind 'dB', 'Hz' or '°'."""
    f, z = np.asarray(np.real(f), float), np.asarray(z, complex)
    ok = (f > 0) & np.isfinite(z)
    f, z = f[ok], z[ok]
    if len(f) < 2:
        return []
    mag = 20 * np.log10(np.maximum(np.abs(z), 1e-300))
    k = int(np.argmax(mag))
    out = [("Gain at start", float(mag[0]), "dB"), ("Peak gain", float(mag[k]), "dB"),
           ("Peak frequency", float(f[k]), "Hz")]
    level = mag[k] - 3.0
    below = np.flatnonzero(mag[:k] < level)
    if len(below):
        i = below[-1]
        out.append(("-3 dB low", _crossing(f, mag, i, level)[0], "Hz"))
    after = np.flatnonzero(mag[k:] < level)
    if len(after):
        i = k + after[0] - 1
        out.append(("-3 dB high", _crossing(f, mag, i, level)[0], "Hz"))
    unity = np.flatnonzero((mag[:-1] > 0) & (mag[1:] <= 0))
    if len(unity):
        out.append(("Unity gain", _crossing(f, mag, unity[0], 0.0)[0], "Hz"))
    pm = phase_margin(f, z)
    if pm:
        out.append(("Phase margin", pm[1], "°"))
    gm = gain_margin(f, z)
    if gm:
        out.append(("Gain margin", gm[1], "dB"))
    return out
