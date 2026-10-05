import math

import numpy as np

from .config import DEFAULT_DUTY, MIN_DUTY


def _poly_blep(t, dt):
    d = dt if dt > 1e-9 else 1e-9
    a = np.maximum(1.0 - t / d, 0.0)
    b = np.maximum(1.0 + (t - 1.0) / d, 0.0)
    return b * b - a * a


def saw_wave(t, inc):
    return 2.0 * t - 1.0 - _poly_blep(t, inc)


def _pulse_from_edges(t, duty, rising, inc):
    s = np.where(t < duty, 1.0, -1.0)
    s = s + rising - _poly_blep(np.mod(t - duty, 1.0), inc)
    return (s - (2.0 * duty - 1.0)) / (2.0 - 2.0 * duty)


def pulse_wave(t, inc, duty):
    duty = min(max(duty, MIN_DUTY), 0.5)
    return _pulse_from_edges(t, duty, _poly_blep(t, inc), inc)


def layer_gain(duty):
    """Gain that makes saw + pulse (duty clamped like pulse_wave) match the saw's RMS.

    For the saw (variance 1/3) and the pulse of effective duty d, var(pulse) = d / (1 - d)
    and cov(saw, pulse) = -d, so var(saw + pulse) = 1/3 + d / (1 - d) - 2d.
    """
    d = min(max(duty, MIN_DUTY), 0.5)
    if d >= 0.5:
        return 1.0
    return math.sqrt((1.0 / 3.0) / (1.0 / 3.0 + d / (1.0 - d) - 2.0 * d))


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
            b0 = _poly_blep(t, inc)
            saw = 2.0 * t - 1.0 - b0
            if self.layer_square:
                duty = min(max(self.duty, MIN_DUTY), 0.5)
                pulse = _pulse_from_edges(t, duty, b0, inc)
                return layer_gain(duty) * (saw + pulse)
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
