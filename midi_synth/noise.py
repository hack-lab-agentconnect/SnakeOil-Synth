"""Shared looping noise tables (white, pink, brown), built once per process.

Each table is Gaussian noise shaped in the frequency domain, so it loops
seamlessly, then normalised to ``NOISE_RMS``. Voices read consecutive
samples from their own start position.
"""
import numpy as np

from .config import NOISE_RMS, NOISE_TABLE_LEN

NOISE_COLORS = ("white", "pink", "brown")
_SEED = 20240607
_EXPONENT = {"white": 0.0, "pink": 0.5, "brown": 1.0}
_tables = {}


def _build(color):
    rng = np.random.default_rng(_SEED)
    spectrum = np.fft.rfft(rng.standard_normal(NOISE_TABLE_LEN))
    bins = np.arange(len(spectrum), dtype=np.float64)
    bins[0] = 1.0
    spectrum = spectrum / bins ** _EXPONENT[color]
    spectrum[0] = 0.0
    out = np.fft.irfft(spectrum, NOISE_TABLE_LEN)
    out -= out.mean()
    return out * (NOISE_RMS / float(np.sqrt(np.mean(out * out))))


def table(color):
    """The shared noise table for ``color`` (KeyError for an unknown color)."""
    t = _tables.get(color)
    if t is None:
        if color not in _EXPONENT:
            raise KeyError(color)
        t = _tables[color] = _build(color)
    return t
