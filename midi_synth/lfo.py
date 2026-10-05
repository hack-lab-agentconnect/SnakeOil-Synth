import numpy as np


def _shape(wave, phase, held):
    """Waveform value(s) in [-1, 1] at ``phase`` (scalar or array in [0, 1))."""
    if wave == "sine":
        return np.sin(2.0 * np.pi * phase)
    if wave == "triangle":
        return 1.0 - 4.0 * np.abs(np.mod(phase + 0.25, 1.0) - 0.5)
    if wave == "saw":
        return 2.0 * phase - 1.0
    if wave == "square":
        return np.where(phase < 0.5, 1.0, -1.0)
    raise ValueError("unknown LFO wave: %r" % (wave,))


class LFO:
    """Low-frequency oscillator advanced once per audio block."""

    def __init__(self, seed=1):
        self.phase = 0.0
        self._rng = np.random.default_rng(seed)
        self._held = float(self._rng.uniform(-1.0, 1.0))

    def next_block(self, n, sr, rate, wave, want_array=False):
        """Advance by one block of ``n`` samples.

        Returns ``(mid_value, samples)``: the value at the block centre and,
        when ``want_array`` is set, the per-sample values (otherwise None).
        """
        start = self.phase
        inc = rate * n / sr
        end = start + inc
        old = self._held
        if end >= 1.0:
            self._held = float(self._rng.uniform(-1.0, 1.0))
        new = self._held
        mid_phase = start + 0.5 * inc
        samples = None
        if wave == "random":
            mid = new if mid_phase >= 1.0 else old
            if want_array:
                ph = start + inc * np.arange(n) / n
                samples = np.where(ph >= 1.0, new, old)
        else:
            mid = float(_shape(wave, mid_phase % 1.0, 0.0))
            if want_array:
                ph = np.mod(start + inc * np.arange(n) / n, 1.0)
                samples = _shape(wave, ph, 0.0)
        self.phase = end % 1.0
        return mid, samples
