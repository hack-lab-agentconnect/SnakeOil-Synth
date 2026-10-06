"""Auto limiter: stereo-linked, instant attack, holds its gain reduction."""
import numpy as np

from .config import LIMITER_CEILING


class Limiter:
    """Clamps at the deepest gain reduction needed so far and stays there.

    The held reduction h only ever grows until ``reset``; the gain is 1 - h on
    both channels. Per sample the reduction needed is
    ``1 - min(1, ceiling / peak)``, so no output sample exceeds the ceiling.
    """

    def __init__(self, sr):
        self.h = 0.0

    def reset(self):
        self.h = 0.0

    def process(self, driven):
        """Return (limited signal, input peak) for a (2, n) block."""
        peak = np.abs(driven).max(axis=0)
        block_peak = float(peak.max())
        if self.h == 0.0 and not block_peak > LIMITER_CEILING:
            return driven, block_peak
        a = 1.0 - LIMITER_CEILING / np.maximum(peak, LIMITER_CEILING)
        a = np.minimum(np.nan_to_num(a, nan=0.0), 1.0)
        h = np.maximum.accumulate(a)
        np.maximum(h, self.h, out=h)
        self.h = float(h[-1])
        return driven * (1.0 - h), block_peak
