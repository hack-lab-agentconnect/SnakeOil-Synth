import numpy as np
import pytest

from midi_synth.config import DEFAULT_ADSR
from midi_synth.engine import SynthEngine
from midi_synth.params import CONTINUOUS, build_registry, format_seconds

SR, BLOCK = 44100, 256
IDS = ["amp_attack", "amp_decay", "amp_sustain", "amp_release"]


@pytest.fixture
def rig():
    engine = SynthEngine(sr=SR, block_size=BLOCK, max_voices=3)
    return engine, build_registry(engine)


def make_engine():
    engine = SynthEngine(sr=SR, block_size=BLOCK, max_voices=3)
    engine.set_lpf_cutoff(20000.0)
    return engine


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))))


def render_blocks(engine, count):
    return [engine.render(BLOCK, apply_effects=False)[:, 0] for _ in range(count)]


def held_rms(engine, blocks):
    return rms(np.concatenate(render_blocks(engine, blocks)))


# ---- registry ---------------------------------------------------------

def test_registry_has_envelope_params_in_order(rig):
    _, reg = rig
    ids = [p.id for p in reg if p.group == "Amp Envelope"]
    assert ids == IDS
    for pid in IDS:
        assert reg[pid].kind == CONTINUOUS
        assert reg[pid].widget == "slider"
        assert reg[pid].tooltip


def test_registry_ranges_scales_defaults(rig):
    engine, reg = rig
    expected = {
        "amp_attack": ("Attack", 0.001, 5.0, "log", DEFAULT_ADSR["attack"]),
        "amp_decay": ("Decay", 0.001, 5.0, "log", DEFAULT_ADSR["decay"]),
        "amp_sustain": ("Sustain", 0.0, 1.0, "linear", DEFAULT_ADSR["sustain"]),
        "amp_release": ("Release", 0.001, 10.0, "log", DEFAULT_ADSR["release"]),
    }
    for pid, (label, lo, hi, scale, default) in expected.items():
        p = reg[pid]
        assert (p.label, p.minimum, p.maximum, p.scale) == (label, lo, hi, scale)
        assert reg.get(pid) == default
        assert engine.params[pid] == default


def test_other_params_default_to_knob(rig):
    _, reg = rig
    assert all(p.widget == "knob" for p in reg if p.group not in ("Amp Envelope", "Filter Env", "Mod Matrix"))


def test_set_reaches_engine_and_every_voice(rig):
    engine, reg = rig
    reg.set("amp_attack", 0.5)
    reg.set("amp_decay", 0.7)
    reg.set("amp_sustain", 0.3)
    reg.set("amp_release", 2.0)
    for v in engine.voices:
        assert v.env.attack == 0.5
        assert v.env.decay == 0.7
        assert v.env.sustain == 0.3
        assert v.env.release == 2.0


def test_voices_start_with_default_adsr(rig):
    engine, _ = rig
    for v in engine.voices:
        assert v.env.attack == DEFAULT_ADSR["attack"]
        assert v.env.decay == DEFAULT_ADSR["decay"]
        assert v.env.sustain == DEFAULT_ADSR["sustain"]
        assert v.env.release == DEFAULT_ADSR["release"]


def test_engine_setters_clamp(rig):
    engine, _ = rig
    engine.set_amp_attack(100.0)
    engine.set_amp_decay(0.0)
    engine.set_amp_sustain(3.0)
    engine.set_amp_release(100.0)
    assert engine.params["amp_attack"] == 5.0
    assert engine.params["amp_decay"] == 0.001
    assert engine.params["amp_sustain"] == 1.0
    assert engine.params["amp_release"] == 10.0
    engine.set_amp_sustain(-1.0)
    engine.set_amp_attack(0.0)
    engine.set_amp_release(0.0)
    assert engine.params["amp_sustain"] == 0.0
    assert engine.params["amp_attack"] == 0.001
    assert engine.params["amp_release"] == 0.001


def test_status_has_envelope_values(rig):
    engine, _ = rig
    engine.set_amp_release(1.25)
    st = engine.status()
    assert st["amp_attack"] == DEFAULT_ADSR["attack"]
    assert st["amp_decay"] == DEFAULT_ADSR["decay"]
    assert st["amp_sustain"] == DEFAULT_ADSR["sustain"]
    assert st["amp_release"] == 1.25


def test_no_default_midi_bindings():
    from midi_synth.bindings import default_profile

    profile = default_profile()
    for pid in IDS:
        assert profile.source_for(pid) is None


def test_from_midi_log_ranges(rig):
    _, reg = rig
    for pid in ("amp_attack", "amp_decay", "amp_release"):
        p = reg[pid]
        assert reg.from_midi(pid, 0) == pytest.approx(p.minimum)
        assert reg.from_midi(pid, 127) == pytest.approx(p.maximum)
        assert reg.from_midi(pid, 64) == pytest.approx(
            (p.minimum * p.maximum) ** 0.5, rel=0.1)
    assert reg.from_midi("amp_sustain", 127) == 1.0


def test_time_formatter_strings(rig):
    _, reg = rig
    assert format_seconds(0.006) == "6 ms"
    assert format_seconds(0.120) == "120 ms"
    assert format_seconds(0.001) == "1 ms"
    assert format_seconds(1.5) == "1.50 s"
    assert format_seconds(10.0) == "10.00 s"
    assert format_seconds(0.9999) == "1.00 s"
    for pid in ("amp_attack", "amp_decay", "amp_release"):
        assert reg[pid].formatter is format_seconds
    assert reg["amp_sustain"].formatter is None


# ---- audible behaviour ------------------------------------------------

def test_long_attack_quiets_first_block():
    fast, slow = make_engine(), make_engine()
    fast.set_amp_attack(0.001)
    slow.set_amp_attack(5.0)
    fast.note_on(60, 100)
    slow.note_on(60, 100)
    ratio = rms(render_blocks(slow, 1)[0]) / rms(render_blocks(fast, 1)[0])
    assert ratio < 0.2


def test_zero_sustain_goes_silent_after_decay():
    engine, ref = make_engine(), make_engine()
    engine.set_amp_decay(0.001)
    engine.set_amp_sustain(0.0)
    ref.set_amp_decay(0.001)
    ref.set_amp_sustain(1.0)
    engine.note_on(60, 100)
    ref.note_on(60, 100)
    skip = int(0.1 * SR / BLOCK) + 1
    render_blocks(engine, skip)
    render_blocks(ref, skip)
    assert held_rms(engine, 4) < 1e-3 * held_rms(ref, 4)


def test_release_length_controls_tail():
    long_tail, short_tail, held = make_engine(), make_engine(), make_engine()
    long_tail.set_amp_release(5.0)
    short_tail.set_amp_release(0.001)
    for e in (long_tail, short_tail, held):
        e.note_on(60, 100)
        render_blocks(e, 20)
    held_level = held_rms(held, 4)
    long_tail.note_off(60)
    short_tail.note_off(60)
    blocks = int(0.5 * SR / BLOCK)
    render_blocks(long_tail, blocks)
    render_blocks(short_tail, blocks)
    assert held_rms(long_tail, 4) > 0.1 * held_level
    assert held_rms(short_tail, 4) < 1e-3


def test_changes_affect_sounding_note():
    engine = make_engine()
    engine.set_amp_sustain(1.0)
    engine.note_on(60, 100)
    render_blocks(engine, 40)
    before = held_rms(engine, 4)
    engine.set_amp_sustain(0.2)
    render_blocks(engine, 2)
    after = held_rms(engine, 4)
    assert after < 0.5 * before


def test_release_change_applies_to_note_already_held():
    engine, held = make_engine(), make_engine()
    for e in (engine, held):
        e.note_on(60, 100)
        render_blocks(e, 20)
    engine.set_amp_release(5.0)
    engine.note_off(60)
    render_blocks(engine, int(0.5 * SR / BLOCK))
    assert held_rms(engine, 4) > 0.1 * held_rms(held, 4)


def test_console_adsr_command(monkeypatch, capsys):
    import builtins

    from run import console_loop

    feed = iter(["adsr 0.5 0.6 0.4 2", "adsr 1 2 3", "adsr 1 2 3 4 5", "adsr a b c d", "quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    engine = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    console_loop(engine)
    out = capsys.readouterr().out
    assert out.count("bad arguments") == 3
    assert (engine.params["amp_attack"], engine.params["amp_decay"],
            engine.params["amp_sustain"], engine.params["amp_release"]) == (0.5, 0.6, 0.4, 2.0)
