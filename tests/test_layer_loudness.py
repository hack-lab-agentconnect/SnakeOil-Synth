"""The osc 1 square layer is RMS-matched to the plain saw (2026-10-05)."""
import math

import numpy as np
import pytest

from midi_synth.config import MIN_DUTY
from midi_synth.engine import SynthEngine
from midi_synth.oscillators import Oscillator, layer_gain, pulse_wave, saw_wave

SR = 44100
DUTIES = [0.0, 0.02, 0.1, 0.25, 0.4, 0.5]
FREQS = [55.0, 220.0, 880.0]


def rms(x):
    return math.sqrt(float(np.mean(np.square(x))))


def db(a, b):
    return 20.0 * math.log10(a / b)


def render(freq, duty, layer, n=SR):
    osc = Oscillator(SR, "saw")
    osc.layer_square = layer
    osc.duty = duty
    return osc.generate(freq, n)


def test_layer_gain_values():
    assert layer_gain(0.5) == 1.0
    assert layer_gain(0.7) == 1.0
    assert layer_gain(0.02) == pytest.approx(1.03, abs=0.01)
    assert layer_gain(0.25) == pytest.approx(math.sqrt(2.0), abs=0.01)
    assert 1.4 < layer_gain(0.3) < 1.45


def test_layer_gain_clamps_like_pulse_wave_and_is_finite():
    assert layer_gain(0.0) == layer_gain(MIN_DUTY) == layer_gain(-1.0)
    for d in np.linspace(0.0, 0.6, 61):
        g = layer_gain(float(d))
        assert math.isfinite(g) and g > 0.0
    assert layer_gain(0.6) == layer_gain(0.5) == 1.0


@pytest.mark.parametrize("duty", DUTIES)
def test_variance_formula_matches_measurement(duty):
    d = min(max(duty, MIN_DUTY), 0.5)
    inc = 20.0 / SR
    t = np.mod(np.arange(SR * 10) * inc, 1.0)
    saw, pulse = saw_wave(t, inc), pulse_wave(t, inc, d)
    analytic = 1.0 / 3.0 + d / (1.0 - d) - 2.0 * d
    measured = float(np.var(saw + pulse))
    assert measured == pytest.approx(analytic, rel=0.02)
    assert float(np.var(pulse)) == pytest.approx(d / (1.0 - d), rel=0.02)


@pytest.mark.parametrize("freq", FREQS)
@pytest.mark.parametrize("duty", DUTIES)
def test_layer_rms_matches_saw(freq, duty):
    diff = db(rms(render(freq, duty, True)), rms(render(freq, duty, False)))
    assert abs(diff) <= 0.3


@pytest.mark.parametrize("freq", FREQS)
@pytest.mark.parametrize("duty", DUTIES)
def test_layer_peak_bounded(freq, duty):
    assert np.max(np.abs(render(freq, duty, True))) <= 1.2


@pytest.mark.parametrize("pwm", [0.0, 0.5])
def test_engine_layer_toggle_keeps_loudness(pwm):
    def run(layer):
        e = SynthEngine(sr=SR, block_size=256, max_voices=2)
        e.set_osc_levels(1.0, 0.0)
        e.set_lpf_cutoff(20000.0)
        for fx in ("chorus", "delay", "reverb", "bitcrush"):
            e.set_effect(fx, False)
        e.set_osc1_square(layer)
        e.set_osc1_pwm(pwm)
        e.note_on(57, 100)
        out = np.concatenate([e.render(256) for _ in range(120)])
        return out[256 * 40:]  # past the attack, sustain region

    assert abs(db(rms(run(True)), rms(run(False)))) <= 0.5
