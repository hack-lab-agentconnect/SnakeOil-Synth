import numpy as np

from .config import DEFAULT_DUTY, DEFAULT_SQUARE_LEVEL, MIN_DUTY


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


def _top_pulse(t, inc, duty, blep_t):
    """Juno-style pulse: the saw's ramp compared with a threshold, high for t >= 1 - duty.

    The falling edge is the saw's wrap, so the saw's `blep_t` is reused for it.
    """
    d = min(max(duty, MIN_DUTY), 0.5)
    s = np.where(t >= 1.0 - d, 1.0, -1.0)
    s = s + _poly_blep(np.mod(t + d, 1.0), inc) - blep_t
    return (s - (2.0 * d - 1.0)) / (2.0 - 2.0 * d)


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
        self.square_level = DEFAULT_SQUARE_LEVEL

    def reset(self):
        self.phase = 0.0

    def _shape(self, t, inc):
        if self.waveform == "saw":
            b0 = _poly_blep(t, inc)
            saw = 2.0 * t - 1.0 - b0
            if self.layer_square and self.square_level > 0.0:
                return saw + self.square_level * _top_pulse(t, inc, self.duty, b0)
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
