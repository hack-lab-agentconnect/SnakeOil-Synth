"""Auto limiter: stereo-linked, instant attack, exponential release, vectorised."""
import math

import numpy as np

from .config import LIMITER_CEILING, LIMITER_RELEASE_S

CHUNK = 4096
SNAP = 1e-9


def release_coeff(sr):
    """Per-sample decay factor of the gain reduction."""
    return math.exp(-1.0 / (LIMITER_RELEASE_S * sr))


def limiter_reduction(a, h_prev, d, powers=None):
    """Gain reduction h_i = max(a_i, d * h_{i-1}) with carry-in ``h_prev``.

    Computed as d**i * max(h_prev * d, running max of a_j * d**-j), in chunks
    of CHUNK samples so that d**-j cannot overflow.
    """
    n = len(a)
    out = np.empty(n)
    if powers is None:
        powers = d ** np.arange(CHUNK)
    carry = h_prev
    for start in range(0, n, CHUNK):
        seg = a[start:start + CHUNK]
        p = powers[:len(seg)]
        h = p * np.maximum(np.maximum.accumulate(seg / p), carry * d)
        out[start:start + len(seg)] = h
        carry = h[-1]
    return out


class Limiter:
    def __init__(self, sr):
        self.d = release_coeff(sr)
        self._powers = self.d ** np.arange(CHUNK)
        self.h = 0.0

    def reset(self):
        self.h = 0.0

    def process(self, driven):
        """Return (limited signal, minimum gain in the block); (2, n) input."""
        peak = np.abs(driven).max(axis=0)
        if self.h == 0.0 and not peak.max() > LIMITER_CEILING:
            return driven, 1.0
        a = 1.0 - LIMITER_CEILING / np.maximum(peak, LIMITER_CEILING)
        a = np.minimum(np.nan_to_num(a, nan=0.0), 1.0)
        h = limiter_reduction(a, self.h, self.d, self._powers)
        last = float(h[-1])
        self.h = last if last >= SNAP else 0.0
        gain = 1.0 - h
        return driven * gain, float(gain.min())
