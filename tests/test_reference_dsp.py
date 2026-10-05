import numpy as np
import pytest

from midi_synth.filters import lpf_coefficients
from midi_synth.voice import Voice
from tests.reference_dsp import (
    RefBitcrusher, RefChorus, RefDelay, RefEnvelope, RefLowPass, RefReverb,
    RefVoice,
)

SR = 48000


def _noise(n=256, seed=0):
    return np.random.default_rng(seed).uniform(-0.5, 0.5, n)


def _check(out, n):
    assert len(out) == n
    assert np.all(np.isfinite(out))


@pytest.mark.parametrize("cls", [RefChorus, RefDelay, RefReverb, RefBitcrusher])
def test_reference_effects_process_block(cls):
    fx = cls(SR, enabled=True)
    for seed in range(3):
        _check(fx.process(_noise(256, seed)), 256)


def test_reference_lowpass_and_envelope():
    lp = RefLowPass(SR)
    _check(lp.process(_noise(), lpf_coefficients(2000.0, 0.3, SR)), 256)
    env = RefEnvelope(SR)
    env.note_on()
    _check(env.process(256), 256)
    assert env.active


PARAM_SETS = [
    {},
    {"mod_mode": "fm", "fm_depth": 0.7, "mod_index": 5.6, "osc2_level": 1.0},
    {"mod_mode": "sync", "fm_depth": 0.6, "osc2_level": 0.8, "osc1_octave_down": True},
    {"mod_mode": "am", "fm_depth": 0.5, "osc2_level": 1.0, "detune2_cents": 0.3},
    {"mod_mode": "ring", "fm_depth": 0.9, "osc2_level": 1.0, "osc1_pwm": 0.4},
    {"lpf_coeffs": None, "osc2_level": 0.5},
]


def _params(**over):
    p = {
        "osc1_level": 1.0, "osc2_level": 0.0, "osc1_square": True,
        "osc1_pwm": 0.0, "osc2_pwm": 0.0, "mod_mode": "fm", "fm_depth": 0.0,
        "mod_index": 0.0, "detune2_semitones": 0.0, "detune2_cents": 0.0,
        "osc1_octave_down": False, "osc2_octave_up": True, "pitch_ratio": 1.0,
        "lpf_mode": "voice",
        "lpf_coeffs": lpf_coefficients(2000.0, 0.2, SR),
    }
    p.update(over)
    return p


@pytest.mark.parametrize("over", PARAM_SETS)
def test_ref_voice_matches_production_voice(over):
    params = _params(**over)
    ref, prod = RefVoice(SR), Voice(SR)
    ref.note_on(57, 0.8, 1)
    prod.note_on(57, 0.8, 1)
    for block in range(6):
        if block == 4:
            ref.note_off()
            prod.note_off()
        a = ref.render(256, params)
        b = prod.render(256, params)
        _check(a, 256)
        assert np.array_equal(a, b)
