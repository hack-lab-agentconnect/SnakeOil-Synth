import numpy as np
import pytest

from midi_synth.filters import HighPass, hpf_coefficients, resonance_to_q

SR = 44100


def gain(freq, cutoff, resonance, n=SR // 2):
    t = np.arange(n) / SR
    y = HighPass(SR).process(np.sin(2 * np.pi * freq * t),
                             hpf_coefficients(cutoff, resonance, SR))
    return np.sqrt(np.mean(y[n // 2:] ** 2)) / np.sqrt(0.5)


def test_attenuates_far_below_cutoff():
    assert gain(100, 1000, 0.0) < 0.02


def test_passes_far_above_cutoff():
    assert gain(8000, 1000, 0.0) > 0.95


def test_minus_3db_at_cutoff_without_resonance():
    assert gain(1000, 1000, 0.0) == pytest.approx(0.707, abs=0.03)


def test_resonance_boosts_at_cutoff():
    assert gain(1000, 1000, 1.0) > 5.0


def test_resonance_to_q_endpoints_and_clamp():
    assert resonance_to_q(0.0) == pytest.approx(0.707)
    assert resonance_to_q(1.0) == pytest.approx(12.0)
    assert resonance_to_q(-5) == pytest.approx(0.707)
    assert resonance_to_q(5) == pytest.approx(12.0)


def test_state_carries_across_blocks():
    x = np.random.default_rng(0).standard_normal(512)
    coeffs = hpf_coefficients(800, 0.6, SR)
    whole = HighPass(SR).process(x, coeffs)
    f = HighPass(SR)
    parts = np.concatenate([f.process(x[:100], coeffs), f.process(x[100:], coeffs)])
    assert np.allclose(whole, parts)


def test_reset_clears_state():
    f = HighPass(SR)
    f.process(np.ones(64), hpf_coefficients(500, 0.5, SR))
    f.reset()
    assert (f.z1, f.z2) == (0.0, 0.0)


@pytest.mark.parametrize("cutoff", [0.0, 20.0, 8000.0, 1e9])
@pytest.mark.parametrize("res", [0.0, 0.5, 1.0])
def test_coefficients_finite_and_stable(cutoff, res):
    b0, b1, b2, a1, a2 = hpf_coefficients(cutoff, res, SR)
    assert all(np.isfinite([b0, b1, b2, a1, a2]))
    assert abs(a2) < 1.0
