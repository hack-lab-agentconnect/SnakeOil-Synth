import pytest

from midi_synth.engine import SynthEngine
from midi_synth.params import build_registry


@pytest.fixture
def rig():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    return engine, build_registry(engine)


def test_continuous_set_clamps_and_writes_engine(rig):
    engine, reg = rig
    reg.set("osc2_level", 5.0)
    assert engine.params["osc2_level"] == 1.0
    assert reg.get("osc2_level") == 1.0


def test_from_midi_continuous_endpoints(rig):
    _, reg = rig
    assert reg.from_midi("detune2_semitones", 0) == -12.0
    assert reg.from_midi("detune2_semitones", 127) == 12.0
    assert reg.from_midi("master_gain", 127) == pytest.approx(1.2)
    assert reg.from_midi("osc1_level", 0) == 0.0


def test_from_midi_choice_buckets(rig):
    _, reg = rig
    assert [reg.from_midi("mod_mode", v) for v in (0, 25, 26, 64, 102, 127)] == [
        "off", "off", "fm", "am", "ring", "sync",
    ]


def test_toggle_fires_once_per_press(rig):
    engine, reg = rig
    assert reg.get("fx_chorus") is False
    reg.apply_midi("fx_chorus", 127)
    assert reg.get("fx_chorus") is True
    reg.apply_midi("fx_chorus", 127)  # held, no retrigger
    assert reg.get("fx_chorus") is True
    reg.apply_midi("fx_chorus", 0)
    reg.apply_midi("fx_chorus", 127)
    assert reg.get("fx_chorus") is False
    assert engine.effects.chorus.enabled is False


def test_set_choice_rejects_unknown_value(rig):
    _, reg = rig
    with pytest.raises(ValueError):
        reg.set("mod_mode", "wobble")


def test_mod_mode_change_also_notifies_fm_depth(rig):
    _, reg = rig
    seen = []
    reg.add_listener(seen.append)
    reg.set("mod_mode", "am")
    assert seen == ["mod_mode", "fm_depth"]
    assert reg.get("fm_depth") == pytest.approx(0.7)


def test_cents_setter_preserves_semitones(rig):
    engine, reg = rig
    reg.set("detune2_semitones", 3.0)
    reg.set("detune2_cents", 0.25)
    assert engine.params["detune2_semitones"] == 3.0
    assert engine.params["detune2_cents"] == 0.25


def test_ids_cover_every_group(rig):
    _, reg = rig
    assert set(reg.ids()) >= {
        "osc1_level", "osc1_square", "osc1_pwm", "osc2_level", "osc2_pwm",
        "detune2_semitones", "detune2_cents", "mod_mode", "fm_depth",
        "master_gain", "fx_chorus", "fx_delay", "fx_reverb", "fx_bitcrush",
    }


def test_lpf_cutoff_is_log_mapped_from_midi(rig):
    _, reg = rig
    assert reg.from_midi("lpf_cutoff", 0) == pytest.approx(20.0)
    assert reg.from_midi("lpf_cutoff", 127) == pytest.approx(20000.0)
    assert 600.0 < reg.from_midi("lpf_cutoff", 64) < 700.0


def test_lpf_params_write_engine(rig):
    engine, reg = rig
    reg.set("lpf_cutoff", 1000.0)
    reg.set("lpf_resonance", 0.5)
    assert engine.params["lpf_cutoff"] == 1000.0
    assert engine.params["lpf_resonance"] == 0.5
    assert reg.get("lpf_master") is False
    reg.set("lpf_master", True)
    assert engine.params["lpf_mode"] == "master"
    reg.set("lpf_master", False)
    assert engine.params["lpf_mode"] == "voice"


def test_waveform_params_are_gone(rig):
    _, reg = rig
    assert "osc1_waveform" not in reg
    assert "osc2_waveform" not in reg


def test_pwm_and_square_params_defaults_and_ranges(rig):
    engine, reg = rig
    for pid in ("osc1_pwm", "osc2_pwm"):
        assert reg[pid].minimum == 0.0 and reg[pid].maximum == 0.5
        assert reg.get(pid) == 0.0
    assert reg["osc1_pwm"].group == "Oscillator 1"
    assert reg["osc2_pwm"].group == "Oscillator 2"
    assert reg["osc1_square"].kind == "toggle"
    assert reg["osc1_square"].group == "Oscillator 1"
    assert reg.get("osc1_square") is True


def test_pwm_and_square_params_reach_engine(rig):
    engine, reg = rig
    reg.set("osc1_square", True)
    reg.set("osc1_pwm", 0.25)
    reg.set("osc2_pwm", 9.0)
    assert engine.params["osc1_square"] is True
    assert engine.params["osc1_pwm"] == 0.25
    assert engine.params["osc2_pwm"] == 0.5
    assert reg.from_midi("osc1_pwm", 127) == 0.5
    assert reg.from_midi("osc2_pwm", 0) == 0.0


DIALS = {
    "fx_chorus_depth": ("fx_chorus", "Depth", 0.0, 1.0, 0.3),
    "fx_delay_time": ("fx_delay", "Time", 200.0, 4000.0, 300.0),
    "fx_reverb_amount": ("fx_reverb", "Amount", 0.0, 1.0, 0.3),
    "fx_bitcrush_amount": ("fx_bitcrush", "Crush", 0.0, 1.0, 0.5),
}


def test_effect_dials_ranges_and_defaults(rig):
    _, reg = rig
    for pid, (under, label, lo, hi, default) in DIALS.items():
        p = reg[pid]
        assert p.kind == "continuous" and p.group == "Effects"
        assert p.label == label and p.under == under
        assert (p.minimum, p.maximum) == (lo, hi)
        assert reg.get(pid) == pytest.approx(default)
        assert p.tooltip
        assert reg[under].kind == "toggle" and reg[under].under == ""
    assert reg["fx_delay_time"].scale == "log"
    ids = reg.ids()
    for pid, (under, *_rest) in DIALS.items():
        assert ids.index(pid) == ids.index(under) + 1


def test_delay_time_is_log_mapped_from_midi(rig):
    _, reg = rig
    assert reg.from_midi("fx_delay_time", 0) == pytest.approx(200.0)
    assert reg.from_midi("fx_delay_time", 127) == pytest.approx(4000.0)


def test_effect_dials_reach_effects(rig):
    engine, reg = rig
    reg.set("fx_chorus_depth", 0.6)
    assert engine.effects.chorus.amount == 0.6
    reg.set("fx_delay_time", 1000.0)
    assert engine.effects.delay.time_ms == 1000.0
    reg.set("fx_delay_time", 5.0)
    assert engine.effects.delay.time_ms == 200.0
    reg.set("fx_reverb_amount", 0.8)
    assert engine.effects.reverb.mix == 0.8
    reg.set("fx_bitcrush_amount", 1.0)
    assert engine.effects.bitcrush.amount == 1.0
    assert reg.get("fx_bitcrush_amount") == 1.0


def test_engine_status_includes_dials(rig):
    engine, reg = rig
    reg.set("fx_chorus_depth", 0.7)
    reg.set("fx_delay_time", 800.0)
    reg.set("fx_reverb_amount", 0.6)
    reg.set("fx_bitcrush_amount", 0.25)
    s = engine.status()
    assert s["chorus_depth"] == 0.7
    assert "chorus_rate" not in s
    assert s["delay_time"] == 800.0
    assert s["reverb_amount"] == 0.6
    assert s["crush_amount"] == 0.25
    assert s["delay_pingpong"] is False


def test_chorus_rate_param_removed(rig):
    _, reg = rig
    assert "fx_chorus_rate" not in [p.id for p in reg]
