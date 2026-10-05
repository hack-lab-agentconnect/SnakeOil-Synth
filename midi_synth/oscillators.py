import numpy as np

from .config import DEFAULT_DUTY, LAYER_GAIN, MIN_DUTY


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


def saw_wave(t, inc):
    return 2.0 * t - 1.0 - _poly_blep(t, inc)


def pulse_wave(t, inc, duty):
    duty = min(max(duty, MIN_DUTY), 0.5)
    s = np.where(t < duty, 1.0, -1.0)
    s = s + _poly_blep(t, inc) - _poly_blep(np.mod(t - duty, 1.0), inc)
    return (s - (2.0 * duty - 1.0)) / (2.0 - 2.0 * duty)


_WAVEFORMS = ("saw", "square")


class Oscillator:
    def __init__(self, sr, waveform="saw"):
        if waveform not in _WAVEFORMS:
            raise ValueError("unknown waveform: %r" % (waveform,))
        self.sr = sr
        self.waveform = waveform
        self.phase = 0.0
        self.duty = DEFAULT_DUTY
        self.layer_square = False

    def reset(self):
        self.phase = 0.0

    def _shape(self, t, inc):
        if self.waveform == "saw":
            saw = saw_wave(t, inc)
            if self.layer_square:
                return LAYER_GAIN * (saw + pulse_wave(t, inc, self.duty))
            return saw
        return pulse_wave(t, inc, self.duty)

    def advance(self, freq, n):
        inc = freq / self.sr
        t = np.mod(self.phase + inc * np.arange(n, dtype=np.float64), 1.0)
        self.phase = float(np.mod(self.phase + inc * n, 1.0))
        return t

    def shape(self, t, freq):
        return self._shape(t, freq / self.sr)

    def generate(self, freq, n, phase_mod=None):
        t = self.advance(freq, n)
        if phase_mod is not None:
            t = np.mod(t + phase_mod, 1.0)
        return self._shape(t, freq / self.sr)
