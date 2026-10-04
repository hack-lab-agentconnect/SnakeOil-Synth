import numpy as np

from .config import WAVEFORMS


def _poly_blep(t, dt):
    out = np.zeros_like(t)
    d = dt if dt > 1e-9 else 1e-9
    m = t < d
    if np.any(m):
        x = t[m] / d
        out[m] = 2.0 * x - x * x - 1.0
    m2 = t > 1.0 - d
    if np.any(m2):
        x = (t[m2] - 1.0) / d
        out[m2] = x * x + 2.0 * x + 1.0
    return out


class Oscillator:
    def __init__(self, sr, waveform="sine"):
        if waveform not in WAVEFORMS:
            raise ValueError("unknown waveform: %r" % (waveform,))
        self.sr = sr
        self.waveform = waveform
        self.phase = 0.0

    def reset(self):
        self.phase = 0.0

    def set_waveform(self, waveform):
        if waveform not in WAVEFORMS:
            raise ValueError("unknown waveform: %r" % (waveform,))
        self.waveform = waveform

    def _shape(self, t, inc):
        wf = self.waveform
        if wf == "sine":
            return np.sin(2.0 * np.pi * t)
        if wf == "saw":
            return 2.0 * t - 1.0 - _poly_blep(t, inc)
        if wf == "square":
            s = np.where(t < 0.5, 1.0, -1.0)
            s = s + _poly_blep(t, inc) - _poly_blep(np.mod(t + 0.5, 1.0), inc)
            return s
        if wf == "triangle":
            return 4.0 * np.abs(t - 0.5) - 1.0
        return np.sin(2.0 * np.pi * t)

    def generate(self, freq, n, phase_mod=None):
        inc = freq / self.sr
        t = np.mod(self.phase + inc * np.arange(n, dtype=np.float64), 1.0)
        if phase_mod is not None:
            t = np.mod(t + phase_mod, 1.0)
        out = self._shape(t, inc)
        self.phase = float(np.mod(self.phase + inc * n, 1.0))
        return out
