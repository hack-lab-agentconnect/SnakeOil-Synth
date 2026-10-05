import math

import numpy as np

HPF_MIN_HZ = 20.0
HPF_MAX_HZ = 8000.0
Q_MIN = 0.707
Q_MAX = 12.0


def resonance_to_q(resonance):
    r = min(max(float(resonance), 0.0), 1.0)
    return Q_MIN * (Q_MAX / Q_MIN) ** r


def hpf_coefficients(cutoff, resonance, sr):
    """RBJ high-pass biquad, normalised: (b0, b1, b2, a1, a2)."""
    cutoff = min(max(float(cutoff), HPF_MIN_HZ), 0.45 * sr)
    w0 = 2.0 * math.pi * cutoff / sr
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * resonance_to_q(resonance))
    a0 = 1.0 + alpha
    b0 = (1.0 + cos_w0) / 2.0 / a0
    return (b0, -2.0 * b0, b0, -2.0 * cos_w0 / a0, (1.0 - alpha) / a0)


class HighPass:
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
        z1, z2 = self.z1, self.z2
        samples = x.tolist()
        for i, v in enumerate(samples):
            y = b0 * v + z1
            z1 = b1 * v - a1 * y + z2
            z2 = b2 * v - a2 * y
            samples[i] = y
        self.z1, self.z2 = z1, z2
        return np.array(samples, dtype=np.float64)
