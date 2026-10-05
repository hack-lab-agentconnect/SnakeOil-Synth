import numpy as np

from midi_synth.engine import SynthEngine
from midi_synth.params import build_registry


def make():
    return SynthEngine(sr=44100, block_size=256, max_voices=2)


def test_engine_param_defaults():
    p = make().params
    assert p["osc1_square"] is True
    assert p["osc1_pwm"] == 0.0
    assert p["osc2_pwm"] == 0.0
    assert p["osc2_octave_up"] is True
    assert p["osc1_octave_down"] is False
    assert p["lpf_cutoff"] == 2000.0
    assert p["lpf_mode"] == "voice"


def test_registry_defaults():
    reg = build_registry(make())
    assert reg.get("osc1_square") is True
    assert reg.get("osc1_pwm") == 0.0
    assert reg.get("osc2_pwm") == 0.0
    assert reg.get("osc2_octave") is True
    assert reg.get("lpf_cutoff") == 2000.0
    assert reg.get("lpf_master") is False


def test_fresh_engine_filter_is_active():
    e = make()
    assert e.params["lpf_coeffs"] is not None


def test_fresh_engine_held_note_is_finite_and_audible():
    e = make()
    e.note_on(60, 100)
    out = np.concatenate([e.render(256) for _ in range(20)])
    assert np.all(np.isfinite(out))
    assert float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) > 0.01
