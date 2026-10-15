"""FFT of transient waveforms (View > FFT)."""
import numpy as np

from .rawfile import Plot, Variable

WINDOWS = {
    "(none)": lambda n: np.ones(n),
    "Hann": np.hanning,
    "Hamming": np.hamming,
    "Blackman": np.blackman,
    "Bartlett": np.bartlett,
}


def spectrum(t, y, npts=65536, window="(none)", t0=None, t1=None):
    """Resample y(t) uniformly on [t0, t1] and return (freqs, complex amplitude spectrum).
    Amplitudes are scaled so a sine of amplitude A gives |X| = A at its frequency."""
    t = np.asarray(t, float)
    y = np.real(np.asarray(y))
    t0 = t[0] if t0 is None else t0
    t1 = t[-1] if t1 is None else t1
    tu = np.linspace(t0, t1, npts, endpoint=False)
    yu = np.interp(tu, t, y)
    w = WINDOWS[window](npts)
    X = np.fft.rfft(yu * w) / (w.sum() / 2)
    X[0] /= 2                                    # DC is not doubled
    f = np.fft.rfftfreq(npts, d=(t1 - t0) / npts)
    return f[1:], X[1:]                          # drop DC for the log axis


def fft_plot(t, traces: dict, **kw) -> Plot:
    """traces: {name: y}. Returns a complex Plot over frequency, one variable per trace."""
    cols, f = [], None
    for y in traces.values():
        f, X = spectrum(t, y, **kw)
        cols.append(X)
    data = np.vstack([f.astype(complex)] + cols)
    variables = [Variable(0, "frequency", "frequency")]
    variables += [Variable(i + 1, n, "voltage") for i, n in enumerate(traces)]
    p = Plot("FFT", "FFT", {"complex"}, variables)
    p.data = data
    return p
