import math

import numpy as np
from scipy.signal import lfilter

LPF_MIN_HZ = 20.0
LPF_MAX_HZ = 20000.0
Q_MIN = 0.707
Q_MAX = 12.0


def resonance_to_q(resonance):
    r = min(max(float(resonance), 0.0), 1.0)
    return Q_MIN * (Q_MAX / Q_MIN) ** r


def lpf_coefficients(cutoff, resonance, sr):
    """RBJ low-pass biquad, normalised: (b0, b1, b2, a1, a2)."""
    cutoff = min(max(float(cutoff), LPF_MIN_HZ), 0.45 * sr)
    w0 = 2.0 * math.pi * cutoff / sr
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * resonance_to_q(resonance))
    a0 = 1.0 + alpha
    b0 = (1.0 - cos_w0) / 2.0 / a0
    return (b0, 2.0 * b0, b0, -2.0 * cos_w0 / a0, (1.0 - alpha) / a0)


class LowPass:
    """Biquad filter (direct form II transposed) that keeps state across blocks."""

    def __init__(self, sr):
        self.sr = sr
        self.z1 = 0.0
        self.z2 = 0.0

    def reset(self):
        self.z1 = 0.0
        self.z2 = 0.0

    def process(self, x, coeffs):
        b0, b1, b2, a1, a2 = coeffs
        y, zf = lfilter(
            [b0, b1, b2], [1.0, a1, a2], np.asarray(x, dtype=np.float64),
            zi=[self.z1, self.z2],
        )
        self.z1, self.z2 = float(zf[0]), float(zf[1])
        return y
