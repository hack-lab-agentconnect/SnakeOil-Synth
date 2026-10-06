"""The osc 1 square layer is additive and Juno-style (2026-10-05).

The saw is untouched. The pulse is the same ramp compared with a threshold, so it is high at
the top of the rising ramp (t >= 1 - duty), reinforces the saw, and is added at `square_level`.
"""
import math

import numpy as np
import pytest

from midi_synth.config import DEFAULT_SQUARE_LEVEL, MIN_DUTY
from midi_synth.engine import SynthEngine
from midi_synth.oscillators import Oscillator, _poly_blep, pulse_wave, saw_wave
from tests.reference_dsp import ref_poly_blep, ref_pulse_top, ref_pulse_wave, ref_saw_wave

SR = 44100
FREQS = [55.0, 220.0, 880.0]
# duty -> {level: expected dB over the plain saw}
EXPECTED_DB = {
    0.02: {0.5: 0.3, 1.0: 0.7},
    0.25: {0.5: 3.0, 1.0: 5.4},
    0.5: {0.5: 5.1, 1.0: 8.5},
}


def rms(x):
    return math.sqrt(float(np.mean(np.square(x))))


def db(a, b):
    return 20.0 * math.log10(a / b)


def render(freq, duty, layer, level=DEFAULT_SQUARE_LEVEL, n=SR):
    osc = Oscillator(SR, "saw")
    osc.layer_square = layer
    osc.square_level = level
    osc.duty = duty
    return osc.generate(freq, n)


def top_pulse(t, inc, duty):
    """The layer's pulse alone: layered output at level 1 minus the saw."""
    osc = Oscillator(SR, "saw")
    osc.layer_square = True
    osc.square_level = 1.0
    osc.duty = duty
    return osc._shape(t, inc) - saw_wave(t, inc)


def test_default_level_constant():
    assert DEFAULT_SQUARE_LEVEL == 0.5
    assert Oscillator(SR, "saw").square_level == DEFAULT_SQUARE_LEVEL


def test_layer_gain_is_gone():
    import midi_synth.oscillators as osc

    assert not hasattr(osc, "layer_gain")


# (a) top alignment ------------------------------------------------------------

@pytest.mark.parametrize("duty", [0.1, 0.25, 0.5])
def test_pulse_is_positively_correlated_with_saw(duty):
    inc = 20.0 / SR
    t = np.mod(np.arange(SR * 10) * inc, 1.0)
    saw = saw_wave(t, inc)
    p = top_pulse(t, inc, duty)
    cov = float(np.mean((saw - saw.mean()) * (p - p.mean())))
    assert cov > 0.0
    assert cov == pytest.approx(duty, rel=0.10)
    assert float(np.var(p)) == pytest.approx(duty / (1.0 - duty), rel=0.05)
    assert abs(float(np.mean(p))) < 0.01  # zero-mean, so it adds no DC


@pytest.mark.parametrize("duty", [0.05, 0.25, 0.5])
def test_pulse_is_high_exactly_for_top_of_ramp(duty):
    inc = 0.002
    t = np.mod(0.0003 + inc * np.arange(20000), 1.0)
    p = top_pulse(t, inc, duty)
    away = (np.abs(t - (1.0 - duty)) > 3 * inc) & (t > 3 * inc) & (t < 1.0 - 3 * inc)
    high = away & (t >= 1.0 - duty)
    low = away & (t < 1.0 - duty)
    assert high.any() and low.any()
    assert np.allclose(p[high], 1.0, atol=1e-9)
    assert np.allclose(p[low], -duty / (1.0 - duty), atol=1e-9)


@pytest.mark.parametrize("duty", [0.0, 0.02, 0.1, 0.25, 0.5, 0.7])
@pytest.mark.parametrize("inc", [0.0005, 0.01, 0.1, 0.45])
def test_layered_matches_independent_reference(duty, inc):
    t = np.mod(0.123 + inc * np.arange(2048), 1.0)
    d = min(max(duty, MIN_DUTY), 0.5)
    assert np.max(np.abs(top_pulse(t, inc, duty) - ref_pulse_top(t, inc, duty))) < 1e-12
    # the reference itself follows the stated formula
    s = (np.where(t >= 1 - d, 1.0, -1.0)
         + ref_poly_blep(np.mod(t + d, 1.0), inc) - ref_poly_blep(t, inc))
    assert np.allclose(ref_pulse_top(t, inc, duty), (s - (2 * d - 1)) / (2 - 2 * d), atol=1e-14)


# (b) loudness table -----------------------------------------------------------

@pytest.mark.parametrize("freq", FREQS)
@pytest.mark.parametrize("duty", sorted(EXPECTED_DB))
@pytest.mark.parametrize("level", [0.5, 1.0])
def test_loudness_over_saw(freq, duty, level):
    diff = db(rms(render(freq, duty, True, level)), rms(render(freq, duty, False)))
    assert diff == pytest.approx(EXPECTED_DB[duty][level], abs=0.6)


# (c) bit-identical when off ---------------------------------------------------

@pytest.mark.parametrize("duty", [0.0, 0.2, 0.5])
def test_level_zero_and_toggle_off_are_bit_identical_to_saw(duty):
    plain = render(440.0, duty, False, 1.0, n=4096)
    assert np.array_equal(render(440.0, duty, True, 0.0, n=4096), plain)
    osc = Oscillator(SR, "saw")
    t = osc.advance(440.0, 4096)
    assert np.array_equal(plain, saw_wave(t, 440.0 / SR))


# (d) peaks --------------------------------------------------------------------

@pytest.mark.parametrize("freq", FREQS)
@pytest.mark.parametrize("duty", [0.0, 0.02, 0.1, 0.25, 0.4, 0.5])
def test_peak_bounded(freq, duty):
    assert np.max(np.abs(render(freq, duty, True, 1.0))) <= 2.05
    assert np.max(np.abs(render(freq, duty, True, 0.5))) <= 1.6


# (e) monotonic ----------------------------------------------------------------

@pytest.mark.parametrize("freq", FREQS)
def test_loudness_increases_with_level(freq):
    levels = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    vals = [rms(render(freq, 0.5, True, lv)) for lv in levels]
    assert all(b > a for a, b in zip(vals, vals[1:]))


# (f) band-limiting ------------------------------------------------------------

@pytest.mark.parametrize("duty,level", [(0.25, 0.5), (0.5, 1.0), (0.1, 1.0)])
def test_band_limited_close_to_oversampled_naive(duty, level):
    # Reference: naive saw + top pulse, each output sample the mean of 16 sub-samples centred
    # on it (a box-filter downsample). Both signals carry a little residual aliasing, so a loose
    # 5 % of the signal RMS is robust, while a naive layer without oversampling lands further
    # from the reference than the BLEP one does.
    freq, n, os_ = 55.0, 4410, 16
    got = render(freq, duty, True, level, n=n)
    d = min(max(duty, MIN_DUTY), 0.5)

    def naive(t):
        p = (np.where(t >= 1.0 - d, 1.0, -1.0) - (2 * d - 1)) / (2 - 2 * d)
        return 2.0 * t - 1.0 + level * p

    k = np.arange(n)[:, None] + (np.arange(os_)[None, :] - (os_ - 1) / 2.0) / os_
    want = naive(np.mod(freq / SR * k, 1.0)).mean(axis=1)
    assert rms(got - want) < 0.05 * rms(want)
    plain = naive(np.mod(freq / SR * np.arange(n), 1.0))
    assert rms(got - want) < rms(plain - want)


# (g) osc 2's square is unchanged ----------------------------------------------

@pytest.mark.parametrize("duty", [0.0, 0.02, 0.1, 0.25, 0.5, 0.7])
@pytest.mark.parametrize("inc", [0.0005, 0.01, 0.1, 0.45])
def test_pulse_wave_is_bit_identical_to_reference(duty, inc):
    t = np.mod(0.123 + inc * np.arange(2048), 1.0)
    # The osc 2 square is exactly the pre-layer-change formula (restated here), and matches the
    # frozen reference to rounding (its BLEP is written differently, so not bit-for-bit).
    d = min(max(duty, MIN_DUTY), 0.5)
    frozen = np.where(t < d, 1.0, -1.0) + _poly_blep(t, inc) - _poly_blep(np.mod(t - d, 1.0), inc)
    frozen = (frozen - (2.0 * d - 1.0)) / (2.0 - 2.0 * d)
    assert np.array_equal(pulse_wave(t, inc, duty), frozen)
    assert np.max(np.abs(pulse_wave(t, inc, duty) - ref_pulse_wave(t, inc, duty))) < 1e-12
    assert np.array_equal(saw_wave(t, inc), 2.0 * t - 1.0 - _poly_blep(t, inc))
    assert np.max(np.abs(saw_wave(t, inc) - ref_saw_wave(t, inc))) < 1e-12
    sq = Oscillator(SR, "square")
    sq.layer_square = True
    sq.square_level = 1.0
    sq.duty = duty
    assert np.array_equal(sq._shape(t, inc), pulse_wave(t, inc, duty))


# (h) engine level -------------------------------------------------------------

def test_engine_layer_adds_about_five_db_at_full_pwm():
    def run(layer):
        e = SynthEngine(sr=SR, block_size=256, max_voices=2)
        e.set_osc_levels(1.0, 0.0)
        e.set_lpf_cutoff(20000.0)
        for fx in ("chorus", "delay", "reverb", "bitcrush"):
            e.set_effect(fx, False)
        e.set_osc1_square(layer)
        e.set_osc1_pwm(0.5)
        e.set_osc1_square_level(0.5)
        e.note_on(57, 100)
        out = np.concatenate([e.render(256) for _ in range(120)])
        return out[256 * 40:]  # past the attack, sustain region

    assert db(rms(run(True)), rms(run(False))) == pytest.approx(5.0, abs=1.0)
