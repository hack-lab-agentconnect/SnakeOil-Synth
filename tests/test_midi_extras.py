import builtins

import mido
import pytest

import run
from midi_synth.bindings import CC, PRESSURE, Profile, Source, default_profile
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput
from midi_synth.midi_router import MidiRouter
from midi_synth.params import build_registry
from midi_synth.profiles import ProfileStore
from midi_synth.voice import IDLE, RELEASE


@pytest.fixture
def engine():
    return SynthEngine(sr=44100, block_size=64, max_voices=6)


@pytest.fixture
def rig(engine):
    return engine, MidiInput(engine)


def gated(engine):
    return sorted(v.note for v in engine.voices if v.gate)


def releasing(engine):
    return sorted(v.note for v in engine.voices if v.env.stage == RELEASE)


# ---- sustain pedal ------------------------------------------------------

def test_sustain_defers_single_note_off(engine):
    engine.set_sustain(True)
    engine.note_on(60)
    engine.note_off(60)
    assert gated(engine) == [60]
    assert releasing(engine) == []
    engine.set_sustain(False)
    assert gated(engine) == []
    assert releasing(engine) == [60]


def test_sustain_multiple_notes_any_release_order(engine):
    engine.set_sustain(True)
    for n in (60, 64, 67):
        engine.note_on(n)
    engine.note_off(67)
    engine.note_off(60)
    assert gated(engine) == [60, 64, 67]
    engine.set_sustain(False)
    # 64 never had a note_off, so it stays held
    assert releasing(engine) == [60, 67]
    assert gated(engine) == [64]


def test_pedal_up_releases_only_deferred_notes(engine):
    engine.note_on(60)
    engine.set_sustain(True)
    engine.note_on(64)
    engine.note_off(64)
    engine.set_sustain(False)
    assert gated(engine) == [60]
    assert releasing(engine) == [64]


def test_note_off_without_pedal_releases_immediately(engine):
    engine.note_on(60)
    engine.note_off(60)
    assert gated(engine) == []
    assert releasing(engine) == [60]


def test_retrigger_while_sustained_is_fresh_held_note(engine):
    engine.set_sustain(True)
    engine.note_on(60)
    engine.note_off(60)
    engine.note_on(60)
    assert 60 not in engine._sustained
    engine.set_sustain(False)
    assert gated(engine) == [60]          # the new press is still held
    engine.note_off(60)
    assert gated(engine) == []


def test_pedal_up_skips_deferred_note_whose_voice_was_stolen(engine):
    small = SynthEngine(sr=44100, block_size=64, max_voices=1)
    small.set_sustain(True)
    small.note_on(60)
    small.note_off(60)
    small.note_on(62)               # steals the only voice
    small.set_sustain(False)
    assert gated(small) == [62]


def test_set_sustain_true_only_sets_flag(engine):
    engine.note_on(60)
    engine.set_sustain(True)
    assert engine.sustain is True
    assert gated(engine) == [60]


def test_all_notes_off_clears_deferred_and_works_with_sustain(engine):
    engine.set_sustain(True)
    engine.note_on(60)
    engine.note_off(60)
    engine.note_on(64)
    engine.all_notes_off()
    assert gated(engine) == []
    assert engine._sustained == set()
    assert releasing(engine) == [60, 64]


def test_panic_silences_immediately(engine):
    engine.set_sustain(True)
    engine.note_on(60)
    engine.note_on(64)
    engine.note_off(64)
    engine.panic()
    assert engine.active_note_count() == 0
    assert all(v.env.stage == IDLE and v.env.level == 0.0 and not v.gate
               for v in engine.voices)
    assert engine.sustain is False
    assert engine._sustained == set()
    assert not engine.render(64).any()


def test_reset_controllers(engine):
    engine.set_pitch_bend(0.5)
    engine.set_sustain(True)
    engine.reset_controllers()
    assert engine.params["pitch_bend"] == 0.0
    assert engine.params["pitch_ratio"] == 1.0
    assert engine.sustain is False


def test_status_reports_sustain(engine):
    assert engine.status()["sustain"] is False
    engine.set_sustain(True)
    assert engine.status()["sustain"] is True


# ---- MidiInput ----------------------------------------------------------

def cc(control, value, channel=0):
    return mido.Message("control_change", channel=channel, control=control, value=value)


def test_cc64_pedal_through_midi_input(rig):
    engine, midi = rig
    midi._on_message(cc(64, 127))
    assert engine.sustain is True
    midi._on_message(mido.Message("note_on", note=60, velocity=100))
    midi._on_message(mido.Message("note_off", note=60))
    assert gated(engine) == [60]
    midi._on_message(cc(64, 63))
    assert engine.sustain is False
    assert gated(engine) == []


def test_cc64_threshold(rig):
    engine, midi = rig
    midi._on_message(cc(64, 64))
    assert engine.sustain is True
    midi._on_message(cc(64, 0))
    assert engine.sustain is False


def test_cc123_all_notes_off(rig):
    engine, midi = rig
    midi._on_message(mido.Message("note_on", note=60, velocity=100))
    midi._on_message(cc(123, 0))
    assert gated(engine) == []
    assert engine.active_note_count() == 1   # still ringing out


def test_cc120_all_sound_off(rig):
    engine, midi = rig
    midi._on_message(cc(64, 127))
    midi._on_message(mido.Message("note_on", note=60, velocity=100))
    midi._on_message(cc(120, 0))
    assert engine.active_note_count() == 0
    assert engine.sustain is False


def test_cc121_reset_controllers(rig):
    engine, midi = rig
    midi._on_message(mido.Message("pitchwheel", pitch=8191))
    midi._on_message(cc(64, 127))
    midi._on_message(cc(121, 0))
    assert engine.params["pitch_bend"] == 0.0
    assert engine.sustain is False


def test_user_binding_of_cc64_wins(engine):
    router = MidiRouter(build_registry(engine), default_profile())
    router.profile.bind(Source(CC, 64, None), "osc1_level")
    midi = MidiInput(engine, router=router)
    midi._on_message(cc(64, 0))
    assert engine.params["osc1_level"] == 0.0
    midi._on_message(cc(64, 127))
    assert engine.sustain is False


def test_learn_emits_for_builtin_cc_and_learn_consumes(engine):
    router = MidiRouter(build_registry(engine), default_profile())
    midi = MidiInput(engine, router=router)
    messages = []
    router.on_message = messages.append
    midi._on_message(cc(64, 127))
    assert messages == ["CC 64 ch1 = 127"]
    router.arm("osc1_level")
    midi._on_message(cc(64, 127, channel=1))
    assert router.profile.source_for("osc1_level") == Source(CC, 64, 2)
    assert engine.sustain is True    # armed message was consumed by learn; no change
    engine.set_sustain(False)


def test_aftertouch_routed_to_router(rig):
    engine, midi = rig
    midi.router.profile.bind(Source(PRESSURE, 0, None), "osc1_level")
    midi._on_message(mido.Message("aftertouch", channel=3, value=0))
    assert engine.params["osc1_level"] == 0.0


def test_polytouch_ignored_without_errors(rig, capsys):
    engine, midi = rig
    midi.router.profile.bind(Source(PRESSURE, 0, None), "osc1_level")
    before = dict(engine.params)
    midi._on_message(mido.Message("polytouch", note=60, value=0))
    assert engine.params == before
    assert capsys.readouterr().err == ""


# ---- bindings -----------------------------------------------------------

def test_pressure_source_round_trip_and_labels():
    src = Source(PRESSURE, 0, None)
    assert src.key() == "pressure:*:0"
    assert Source.from_key("pressure:*:0") == src
    assert Source.from_key("pressure:2:0") == Source(PRESSURE, 0, 2)
    assert src.label() == "Aftertouch"
    assert Source(PRESSURE, 0, 2).label() == "Aftertouch ch2"


def test_pressure_number_must_be_zero():
    with pytest.raises(ValueError):
        Source.from_key("pressure:*:5")


def test_pressure_overlaps():
    a = Source(PRESSURE, 0, None)
    assert a.overlaps(Source(PRESSURE, 0, 3))
    assert not Source(PRESSURE, 0, 1).overlaps(Source(PRESSURE, 0, 2))
    assert not a.overlaps(Source(CC, 0, None))


def test_profile_param_for_pressure():
    p = Profile("t", [(Source(PRESSURE, 0, None), "osc1_level")])
    assert p.param_for(PRESSURE, 4, 0) == "osc1_level"
    assert p.param_for(CC, 4, 0) is None


def test_profile_with_pressure_binding_round_trips_store(tmp_path):
    store = ProfileStore(tmp_path / "cfg")
    store.ensure_default()
    profile = default_profile("Expr")
    profile.bind(Source(PRESSURE, 0, 2), "lpf_cutoff")
    store.save(profile)
    loaded = store.load("Expr")
    assert loaded.source_for("lpf_cutoff") == Source(PRESSURE, 0, 2)
    assert loaded.param_for(PRESSURE, 2, 0) == "lpf_cutoff"


# ---- router -------------------------------------------------------------

@pytest.fixture
def router_rig():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    return engine, registry, MidiRouter(registry, default_profile())


def test_unbound_pressure_returns_false_and_reports(router_rig):
    _, _, router = router_rig
    messages = []
    router.on_message = messages.append
    assert router.handle_pressure(0, 64) is False
    assert messages == ["Aftertouch ch1 = 64"]


def test_learn_pressure_for_continuous_then_drives_param(router_rig):
    engine, _, router = router_rig
    learned, changed = [], []
    router.on_learned = lambda pid, src: learned.append((pid, src))
    router.on_profile_changed = changed.append
    router.arm("osc1_level")
    assert router.handle_pressure(1, 64) is True
    assert router.armed is None
    assert learned == [("osc1_level", Source(PRESSURE, 0, 2))]
    assert changed == [router.profile]
    assert learned[0][1].label() == "Aftertouch ch2"
    assert router.handle_pressure(1, 0) is True
    assert engine.params["osc1_level"] == 0.0
    assert router.handle_pressure(0, 0) is False   # other channel unbound


def test_learn_pressure_for_toggle(router_rig):
    _, registry, router = router_rig
    router.arm("fx_reverb")
    assert router.handle_pressure(0, 100) is True
    assert router.profile.source_for("fx_reverb") == Source(PRESSURE, 0, 1)
    router.handle_pressure(0, 127)
    assert registry.get("fx_reverb") is True


# ---- console ------------------------------------------------------------

def run_console(monkeypatch, capsys, lines, engine):
    feed = iter(lines + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    run.console_loop(engine)
    return capsys.readouterr().out


def test_console_sustain_and_panic(monkeypatch, capsys, engine):
    run_console(monkeypatch, capsys, ["sustain on"], engine)
    assert engine.sustain is True
    run_console(monkeypatch, capsys, ["sustain off"], engine)
    assert engine.sustain is False
    engine.note_on(60)
    run_console(monkeypatch, capsys, ["panic"], engine)
    assert engine.active_note_count() == 0


def test_console_sustain_usage_and_help(monkeypatch, capsys, engine):
    out = run_console(monkeypatch, capsys, ["sustain maybe", "sustain"], engine)
    assert out.count("usage: sustain <on|off>") == 2
    assert engine.sustain is False
    assert "sustain <on|off>" in run.HELP_TEXT
    assert "panic" in run.HELP_TEXT
