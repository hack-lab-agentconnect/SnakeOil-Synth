import pytest

from midi_synth.bindings import CC, NOTE, Profile, Source, default_profile
from midi_synth.engine import SynthEngine
from midi_synth.midi_router import MidiRouter
from midi_synth.params import build_registry


@pytest.fixture
def rig():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    router = MidiRouter(registry, default_profile())
    return engine, registry, router


def test_bound_cc_sets_param(rig):
    engine, _, router = rig
    assert router.handle_cc(0, 1, 127) is True
    assert engine.params["fm_depth"] == 1.0


def test_unbound_cc_returns_false(rig):
    _, _, router = rig
    assert router.handle_cc(0, 99, 10) is False


def test_channel_specific_binding_ignores_other_channels(rig):
    engine, registry, _ = rig
    profile = Profile("t", [(Source(CC, 74, 2), "osc1_level")])
    router = MidiRouter(registry, profile)
    assert router.handle_cc(0, 74, 0) is False   # channel 1
    assert router.handle_cc(1, 74, 0) is True    # channel 2
    assert engine.params["osc1_level"] == 0.0


def test_learn_cc_binds_and_applies_afterwards(rig):
    engine, _, router = rig
    learned, changed = [], []
    router.on_learned = lambda pid, src: learned.append((pid, src))
    router.on_profile_changed = changed.append
    router.arm("osc1_level")
    assert router.armed == "osc1_level"
    assert router.handle_cc(2, 74, 64) is True
    assert router.armed is None
    assert learned == [("osc1_level", Source(CC, 74, 3))]
    assert changed == [router.profile]
    router.handle_cc(2, 74, 0)
    assert engine.params["osc1_level"] == 0.0


def test_learn_steals_param_from_old_source(rig):
    _, _, router = rig
    router.arm("osc1_level")           # default has CC 29 -> osc1_level
    router.handle_cc(0, 74, 10)
    assert router.profile.param_for(CC, 1, 29) is None
    assert router.profile.param_for(CC, 1, 74) == "osc1_level"


def test_learn_toggle_from_note(rig):
    _, registry, router = rig
    router.arm("fx_reverb")
    assert router.handle_note(0, 60, 100, True) is True
    assert router.profile.source_for("fx_reverb") == Source(NOTE, 60, 1)
    assert router.handle_note(0, 60, 0, False) is True       # release consumed
    assert registry.get("fx_reverb") is False                # binding press did not toggle
    router.handle_note(0, 60, 40, True)                      # soft press still toggles
    assert registry.get("fx_reverb") is True
    router.handle_note(0, 60, 0, False)


def test_notes_ignored_while_learning_continuous_param(rig):
    _, _, router = rig
    router.arm("osc1_level")
    assert router.handle_note(0, 60, 100, True) is False
    assert router.armed == "osc1_level"


def test_unbound_note_returns_false(rig):
    _, _, router = rig
    assert router.handle_note(0, 60, 100, True) is False
    assert router.handle_note(0, 60, 0, False) is False


def test_clear_binding_notifies_and_unbinds(rig):
    _, _, router = rig
    changed = []
    router.on_profile_changed = changed.append
    router.clear_binding("fm_depth")
    assert router.profile.source_for("fm_depth") is None
    assert len(changed) == 1
    router.clear_binding("fm_depth")        # already clear: no second notification
    assert len(changed) == 1


def test_message_callback_reports_cc(rig):
    _, _, router = rig
    seen = []
    router.on_message = seen.append
    router.handle_cc(0, 1, 127)
    assert seen == ["CC 1 ch1 = 127"]


def test_set_profile_disarms_and_swaps(rig):
    engine, _, router = rig
    router.arm("osc1_level")
    router.set_profile(Profile("empty"))
    assert router.armed is None
    assert router.handle_cc(0, 1, 127) is False


def test_arm_unknown_param_raises(rig):
    _, _, router = rig
    with pytest.raises(KeyError):
        router.arm("nope")


def test_save_failure_reported_not_raised(rig):
    _, _, router = rig
    seen = []
    router.on_message = seen.append

    def boom(profile):
        raise OSError("disk full")

    router.on_profile_changed = boom
    router.arm("osc1_level")
    router.handle_cc(0, 74, 1)
    assert any("disk full" in m for m in seen)
    assert router.profile.param_for(CC, 1, 74) == "osc1_level"
