"""The Moog-style 4-pole low-pass: analytic checks and the cascaded LowPass."""
import math

import numpy as np
import pytest
from scipy.signal import bilinear, freqz, lfilter

from midi_synth.filters import (
    LADDER_K_MAX,
    LADDER_OSC_LEVEL,
    LADDER_OSC_START,
    LowPass,
    filter_coefficients,
    lpf24_coefficients,
    lpf_coefficients,
)
from tests.reference_dsp import RefLowPass

RATES = (44100, 48000, 96000)
RESONANCES = (0.0, 0.25, 0.5, 0.9, 1.0)


def cutoffs(sr):
    return (20.0, 200.0, 1000.0, 8000.0, 0.45 * sr)


def k_of(res):
    return LADDER_K_MAX * res


def analog(s, wc, k):
    return 1.0 / ((1.0 + s / wc) ** 4 + k)


def digital_response(sections, w):
    z = np.exp(1j * w)
    h = np.ones_like(z)
    for b0, b1, b2, a1, a2 in sections:
        h = h * (b0 + b1 / z + b2 / z ** 2) / (1.0 + a1 / z + a2 / z ** 2)
    return h


def reference_response(cutoff, res, sr, w):
    """The analog Moog ladder through the bilinear map s = 2*sr*(z-1)/(z+1)."""
    cutoff = min(max(cutoff, 20.0), 0.45 * sr)
    wc = 2.0 * sr * math.tan(math.pi * cutoff / sr)
    z = np.exp(1j * w)
    s = 2.0 * sr * (z - 1.0) / (z + 1.0)
    return analog(s, wc, k_of(res))


def test_constants():
    assert LADDER_K_MAX == 3.98
    assert LADDER_OSC_START == 0.9
    assert LADDER_OSC_LEVEL == 0.35


@pytest.mark.parametrize("sr", RATES)
def test_cascade_matches_analog_ladder_through_bilinear(sr):
    freqs = np.geomspace(5.0, 0.49 * sr, 200)
    w = 2.0 * np.pi * freqs / sr
    for fc in cutoffs(sr):
        for res in RESONANCES:
            sections = lpf24_coefficients(fc, res, sr)
            assert len(sections) == 2 and all(len(s) == 5 for s in sections)
            got = digital_response(sections, w)
            want = reference_response(fc, res, sr, w)
            # at 20 Hz the poles sit within ~1e-3 of z=1, so rounding the
            # float64 coefficients costs a few digits: 1e-9 elsewhere, 1e-7 there
            tol = 1e-7 if fc < 100.0 else 1e-9
            err = np.abs(got - want) / np.maximum(np.abs(want), 1e-3)
            assert err.max() < tol, (sr, fc, res, err.max())
            assert np.abs(np.abs(got) - np.abs(want)).max() < tol * max(1.0, np.abs(want).max())
            assert np.abs(np.angle(got / want)).max() < tol


@pytest.mark.parametrize("sr", RATES)
@pytest.mark.parametrize("fc", (200.0, 1000.0, 8000.0))
@pytest.mark.parametrize("res", RESONANCES)
def test_cascade_matches_scipy_bilinear_of_the_polynomial(sr, fc, res):
    k = k_of(res)
    wc = 2.0 * sr * math.tan(math.pi * fc / sr)
    den = (np.polynomial.Polynomial([1.0, 1.0 / wc]) ** 4 + k).coef[::-1]
    b, a = bilinear([1.0], den, fs=sr)
    w = 2.0 * np.pi * np.geomspace(100.0, 0.45 * sr, 200) / sr
    _, want = freqz(b, a, worN=w)
    got = digital_response(lpf24_coefficients(fc, res, sr), w)
    assert np.abs(got - want).max() < 1e-6 * max(1.0, np.abs(want).max())


@pytest.mark.parametrize("sr", RATES)
def test_dc_gain_is_one_over_one_plus_k(sr):
    for fc in cutoffs(sr):
        for res in RESONANCES:
            sec = lpf24_coefficients(fc, res, sr)
            dc = abs(digital_response(sec, np.array([1e-9]))[0])
            assert dc == pytest.approx(1.0 / (1.0 + k_of(res)), rel=1e-6)


def test_resonance_zero_is_four_coincident_poles():
    sr = 48000
    sections = lpf24_coefficients(1000.0, 0.0, sr)
    poles = np.concatenate([np.roots([1.0, a1, a2]) for _, _, _, a1, a2 in sections])
    assert np.allclose(poles, poles[0], atol=1e-6)
    assert np.allclose(poles.imag, 0.0, atol=1e-6)
    # each section Q = 0.5: critically damped, a2 == (a1/2)**2
    for _, _, _, a1, a2 in sections:
        assert a2 == pytest.approx((a1 / 2.0) ** 2, rel=1e-9)
    mag = abs(digital_response(sections, np.array([2 * np.pi * 1000.0 / sr]))[0])
    assert 20 * math.log10(mag) == pytest.approx(-12.04, abs=0.02)


def test_slope_is_24_db_per_octave():
    sr, fc = 44100, 300.0
    sec = lpf24_coefficients(fc, 0.3, sr)
    w = 2 * np.pi * np.array([4 * fc, 8 * fc]) / sr
    lo, hi = np.abs(digital_response(sec, w))
    # 4x -> 8x is exactly one octave
    assert abs(20 * math.log10(hi / lo) + 24.0) < 1.5


def test_gain_at_cutoff_rises_monotonically_with_resonance():
    sr, fc = 48000, 1000.0
    w = np.array([2 * np.pi * fc / sr])
    mags = [abs(digital_response(lpf24_coefficients(fc, r, sr), w)[0])
            for r in (0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0)]
    assert all(b > a for a, b in zip(mags, mags[1:]))
    for r, m in zip((0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0), mags):
        assert m == pytest.approx(1.0 / (4.0 - k_of(r)), rel=1e-6)


def test_resonance_peak_sits_near_the_cutoff():
    sr, fc = 48000, 1000.0
    freqs = np.linspace(100, 5000, 20000)
    w = 2 * np.pi * freqs / sr
    for r in (0.9, 0.95, 1.0):
        mag = np.abs(digital_response(lpf24_coefficients(fc, r, sr), w))
        assert 0.9 * fc < freqs[mag.argmax()] < 1.1 * fc


@pytest.mark.parametrize("sr", (44100, 96000))
def test_all_poles_inside_the_unit_circle(sr):
    for fc in (20.0, 0.45 * sr, 1000.0):
        for res in np.linspace(0.0, 1.0, 21):
            for _, _, _, a1, a2 in lpf24_coefficients(fc, res, sr):
                radius = np.abs(np.roots([1.0, a1, a2])).max()
                assert radius < 1.0, (sr, fc, res, radius)


def test_impulse_response_is_finite_and_rings_for_a_while():
    sr = 44100
    sections = lpf24_coefficients(1000.0, 1.0, sr)
    x = np.zeros(2 * sr)
    x[0] = 1.0
    y = x
    for b0, b1, b2, a1, a2 in sections:
        y = lfilter([b0, b1, b2], [1.0, a1, a2], y)
    assert np.all(np.isfinite(y))
    peak = np.abs(y).max()
    loud = np.nonzero(np.abs(y) > 1e-3 * peak)[0]
    ring = loud.max() / sr
    assert 0.05 < ring < 2.0
    assert np.abs(y[-sr // 10:]).max() < 1e-2 * peak


def test_dispatcher():
    sr = 44100
    assert filter_coefficients(1000.0, 0.3, sr, "12 dB") == lpf_coefficients(1000.0, 0.3, sr)
    assert filter_coefficients(1000.0, 0.3, sr, "24 dB") == lpf24_coefficients(1000.0, 0.3, sr)


# ---- LowPass with a pair of sections --------------------------------------

def naive_cascade(x, sections, state):
    y = np.empty(len(x))
    for i, v in enumerate(x):
        for idx, (b0, b1, b2, a1, a2) in enumerate(sections):
            x1, x2, y1, y2 = state[idx]
            out = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            state[idx] = (v, x1, out, y1)
            v = out
        y[i] = v
    return y


def test_pair_matches_naive_reference_over_many_blocks():
    rng = np.random.default_rng(1)
    sr = 44100
    lp = LowPass(sr)
    state = [(0.0,) * 4, (0.0,) * 4]
    for size in (1, 64, 256, 300, 256, 1, 64):
        x = rng.standard_normal(size)
        sec = lpf24_coefficients(1500.0, 0.8, sr)
        got = lp.process(x, sec)
        want = naive_cascade(x, sec, state)
        assert np.allclose(got, want, atol=1e-9, rtol=0)


def test_pair_state_carries_with_changing_coefficients():
    rng = np.random.default_rng(2)
    lp = LowPass(48000)
    out = []
    for fc in (500.0, 800.0, 1200.0):
        out.append(lp.process(rng.standard_normal(256), lpf24_coefficients(fc, 0.5, 48000)))
    assert np.all(np.isfinite(np.concatenate(out)))


def test_reset_clears_all_four_states():
    lp = LowPass(44100)
    lp.process(np.ones(100), lpf24_coefficients(1000.0, 0.9, 44100))
    assert any((lp.z1, lp.z2, lp.z3, lp.z4))
    lp.reset()
    assert (lp.z1, lp.z2, lp.z3, lp.z4) == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize("sr", RATES)
def test_five_tuple_path_is_unchanged(sr):
    rng = np.random.default_rng(3)
    lp, ref = LowPass(sr), RefLowPass(sr)
    zi = [0.0, 0.0]
    for size in (64, 256, 1, 300):
        x = rng.standard_normal(size)
        c = lpf_coefficients(900.0, 0.4, sr)
        got = lp.process(x, c)
        # exactly what the single-section code has always computed
        want, zf = lfilter([c[0], c[1], c[2]], [1.0, c[3], c[4]], x, zi=zi)
        zi = [float(zf[0]), float(zf[1])]
        assert np.array_equal(got, want)
        assert np.allclose(got, ref.process(x, c), atol=1e-10, rtol=0)
