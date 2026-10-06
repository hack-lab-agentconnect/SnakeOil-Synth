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
        # random-glide state: its own stream so the other waves are unaffected;
        # targets are drawn lazily on first use.
        self._grng = np.random.default_rng(seed)
        self._prev = None
        self._cur = 0.0

    def _glide(self, start, inc, n, idx):
        """Random-glide values at sample positions ``idx`` (array) of a block.

        Advances the target state past every cycle wrap in the block.
        """
        if self._prev is None:
            self._prev, self._cur = (float(v) for v in self._grng.uniform(-1.0, 1.0, 2))
        wraps = min(int(np.floor(start + inc)), 64)
        targets = np.empty(wraps + 2)
        targets[0], targets[1] = self._prev, self._cur
        if wraps:
            targets[2:] = self._grng.uniform(-1.0, 1.0, wraps)
        pos = start + inc * idx / n
        k = np.minimum(np.floor(pos).astype(np.intp), wraps)
        frac = np.clip(pos - k, 0.0, 1.0)
        a, b = targets[k], targets[k + 1]
        out = a + (b - a) * (1.0 - np.cos(np.pi * frac)) * 0.5
        self._prev, self._cur = float(targets[wraps]), float(targets[wraps + 1])
        return out

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
        elif wave == "random-glide":
            idx = np.append(np.arange(n), 0.5 * n) if want_array else np.array([0.5 * n])
            vals = self._glide(start, inc, n, idx)
            mid = float(vals[-1])
            if want_array:
                samples = vals[:-1]
        else:
            mid = float(_shape(wave, mid_phase % 1.0, 0.0))
            if want_array:
                ph = np.mod(start + inc * np.arange(n) / n, 1.0)
                samples = _shape(wave, ph, 0.0)
        self.phase = end % 1.0
        return mid, samples
