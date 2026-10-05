import mido
import pytest

from midi_synth.bindings import NOTE, Source
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput


@pytest.fixture
def rig():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=4)
    return engine, MidiInput(engine)


def test_note_on_and_off_play_the_engine(rig):
    engine, midi = rig
    midi._on_message(mido.Message("note_on", note=60, velocity=100))
    assert engine.active_note_count() == 1
    assert any(v.gate for v in engine.voices)
    midi._on_message(mido.Message("note_off", note=60))
    assert not any(v.gate for v in engine.voices)


def test_note_on_velocity_zero_is_note_off(rig):
    engine, midi = rig
    midi._on_message(mido.Message("note_on", note=60, velocity=100))
    midi._on_message(mido.Message("note_on", note=60, velocity=0))
    assert not any(v.gate for v in engine.voices)


def test_default_profile_cc_controls_engine(rig):
    engine, midi = rig
    midi._on_message(mido.Message("control_change", control=29, value=0))
    assert engine.params["osc1_level"] == 0.0
    midi._on_message(mido.Message("control_change", control=21, value=127))
    assert engine.effects.delay.enabled is True


def test_note_bound_to_toggle_is_consumed_not_played(rig):
    engine, midi = rig
    midi.router.profile.bind(Source(NOTE, 36, None), "fx_delay")
    midi._on_message(mido.Message("note_on", note=36, velocity=100))
    assert engine.active_note_count() == 0
    assert engine.effects.delay.enabled is True


def test_learn_through_midi_input(rig):
    engine, midi = rig
    midi.router.arm("master_gain")
    midi._on_message(mido.Message("control_change", channel=4, control=50, value=0))
    midi._on_message(mido.Message("control_change", channel=4, control=50, value=127))
    assert engine.params["master_gain"] == pytest.approx(1.2)


def test_channel_filter_is_one_based():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    midi = MidiInput(engine, channel=2)
    midi._on_message(mido.Message("note_on", channel=0, note=60, velocity=100))
    assert engine.active_note_count() == 0
    midi._on_message(mido.Message("note_on", channel=1, note=60, velocity=100))
    assert engine.active_note_count() == 1


def test_pitchwheel_and_program_change(rig):
    engine, midi = rig
    midi._on_message(mido.Message("pitchwheel", pitch=8191))
    assert engine.params["pitch_bend"] > 1.9
    midi._on_message(mido.Message("program_change", program=64))
    assert engine.params["osc1_waveform"] == "triangle"
