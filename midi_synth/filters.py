import math

import numpy as np
from scipy.signal import lfilter

LPF_MIN_HZ = 20.0
LPF_MAX_HZ = 20000.0
Q_MIN = 0.707
Q_MAX = 12.0

LADDER_K_MAX = 3.98          # feedback gain at full resonance (4.0 would self-oscillate)
LADDER_OSC_START = 0.9       # resonance above which the 24 dB mode whistles
LADDER_OSC_LEVEL = 0.35      # whistle amplitude at full resonance
_SQRT_HALF = math.sqrt(0.5)


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


def _rbj_section(w0, q, gain):
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    b0 = gain * (1.0 - cos_w0) / 2.0 / a0
    return (b0, 2.0 * b0, b0, -2.0 * cos_w0 / a0, (1.0 - alpha) / a0)


def lpf24_coefficients(cutoff, resonance, sr):
    """Moog-style 4-pole low-pass as two cascaded biquads.

    The analog ladder is H(s) = 1 / ((1 + s/wc)^4 + k) with k = LADDER_K_MAX *
    resonance; its poles form two conjugate pairs, each realised as an RBJ
    low-pass section (bilinear transform with a prewarped cutoff). The overall
    DC gain 1/(1+k) is folded into the first section. Returns
    ((b0, b1, b2, a1, a2), (b0, b1, b2, a1, a2)).
    """
    cutoff = min(max(float(cutoff), LPF_MIN_HZ), 0.45 * sr)
    r = min(max(float(resonance), 0.0), 1.0)
    k = LADDER_K_MAX * r
    kappa = k ** 0.25
    wc = 2.0 * sr * math.tan(math.pi * cutoff / sr)
    c = _SQRT_HALF * kappa
    wn_a = wc * math.sqrt(1.0 - 2.0 * c + kappa * kappa)
    q_a = wn_a / (2.0 * wc * (1.0 - c))
    wn_b = wc * math.sqrt(1.0 + 2.0 * c + kappa * kappa)
    q_b = wn_b / (2.0 * wc * (1.0 + c))
    first = _rbj_section(2.0 * math.atan(wn_a / (2.0 * sr)), q_a, 1.0 / (1.0 + k))
    second = _rbj_section(2.0 * math.atan(wn_b / (2.0 * sr)), q_b, 1.0)
    return (first, second)


def filter_coefficients(cutoff, resonance, sr, slope="12 dB"):
    """Coefficients for the chosen slope: a 5-tuple (12 dB) or a pair of them (24 dB)."""
    if slope == "24 dB":
        return lpf24_coefficients(cutoff, resonance, sr)
    return lpf_coefficients(cutoff, resonance, sr)


class LowPass:
    """Biquad filter (direct form II transposed) that keeps state across blocks."""

    def __init__(self, sr):
        self.sr = sr
        self.z1 = 0.0
        self.z2 = 0.0
        self.z3 = 0.0
        self.z4 = 0.0

    def reset(self):
        self.z1 = 0.0
        self.z2 = 0.0
        self.z3 = 0.0
        self.z4 = 0.0

    def process(self, x, coeffs):
        """Filter a block with one biquad (5-tuple) or two cascaded ones (pair)."""
        if len(coeffs) == 2:
            return self._process_pair(x, coeffs)
        b0, b1, b2, a1, a2 = coeffs
        y, zf = lfilter(
            [b0, b1, b2], [1.0, a1, a2], np.asarray(x, dtype=np.float64),
            zi=[self.z1, self.z2],
        )
        self.z1, self.z2 = float(zf[0]), float(zf[1])
        return y

    def _process_pair(self, x, coeffs):
        (b0, b1, b2, a1, a2), (c0, c1, c2, d1, d2) = coeffs
        y, zf = lfilter(
            [b0, b1, b2], [1.0, a1, a2], np.asarray(x, dtype=np.float64),
            zi=[self.z1, self.z2],
        )
        self.z1, self.z2 = float(zf[0]), float(zf[1])
        y, zf = lfilter([c0, c1, c2], [1.0, d1, d2], y, zi=[self.z3, self.z4])
        self.z3, self.z4 = float(zf[0]), float(zf[1])
        return y
