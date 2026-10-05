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
    assert [reg.from_midi("osc1_waveform", v) for v in (0, 31, 32, 64, 96, 127)] == [
        "sine", "sine", "square", "saw", "triangle", "triangle",
    ]
    assert reg.from_midi("mod_mode", 0) == "off"
    assert reg.from_midi("mod_mode", 127) == "sync"
    assert reg.from_midi("osc1_waveform", 254) == "triangle"  # program-change style overflow


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
        reg.set("osc1_waveform", "wobble")


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
        "osc1_waveform", "osc1_level", "osc2_waveform", "osc2_level",
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
