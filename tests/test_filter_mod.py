import numpy as np
import pytest

from midi_synth.config import DEFAULT_FLT_ENV, FIXED_VELOCITY
from midi_synth.engine import SynthEngine
from midi_synth.filters import lpf_coefficients
from midi_synth.params import CONTINUOUS, TOGGLE, build_registry
from midi_synth.patches import apply, capture

SR, BLOCK = 44100, 256
FLT_IDS = ["flt_attack", "flt_decay", "flt_sustain", "flt_release"]


def make_engine(cutoff=300.0):
    engine = SynthEngine(sr=SR, block_size=BLOCK, max_voices=4)
    engine.set_lpf_cutoff(cutoff)
    return engine


def blocks(engine, count):
    return np.concatenate(
        [engine.render(BLOCK, apply_effects=False)[:, 0] for _ in range(count)])


def centroid(x):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float(np.sum(freqs * spec) / np.sum(spec))


def attack_centroid(amount, **setup):
    engine = make_engine(300.0)
    engine.set_flt_attack(0.2)
    engine.set_flt_env_amount(amount)
    for k, v in setup.items():
        getattr(engine, "set_" + k)(v)
    engine.note_on(60, 100)
    return centroid(blocks(engine, 8))


# ---- registry ---------------------------------------------------------

def test_registry_params():
    reg = build_registry(SynthEngine(sr=SR, block_size=BLOCK, max_voices=2))
    v = reg["velocity_on"]
    assert (v.kind, v.group, v.label) == (TOGGLE, "Master", "Velocity")
    assert v.tooltip and reg.get("velocity_on") is True
    for pid, label, lo, hi in (("flt_env_amount", "Env Amt", -1.0, 1.0),
                               ("flt_keytrack", "Key Trk", 0.0, 1.0),
                               ("flt_vel", "Vel>Cut", 0.0, 1.0)):
        p = reg[pid]
        assert (p.kind, p.group, p.label, p.minimum, p.maximum) == (
            CONTINUOUS, "Filter", label, lo, hi)
        assert reg.get(pid) == 0.0
    assert reg["flt_env_amount"].fmt == "{:+.2f}"
    assert [p.id for p in reg if p.group == "Filter Env"] == FLT_IDS
    amp = {p.id[4:]: p for p in reg if p.group == "Amp Envelope"}
    assert list(amp) == ["attack", "decay", "sustain", "release"]
    for name in amp:
        a, f = amp[name], reg["flt_" + name]
        assert (f.label, f.minimum, f.maximum, f.scale, f.formatter, f.widget) == (
            a.label, a.minimum, a.maximum, a.scale, a.formatter, "slider")
        assert reg.get("flt_" + name) == DEFAULT_FLT_ENV[name]
    assert not [p for p in reg if p.group == "Envelope"]


def test_engine_setters_clamp():
    e = make_engine()
    e.set_flt_env_amount(5)
    e.set_flt_keytrack(-1)
    e.set_flt_vel(9)
    e.set_flt_attack(100)
    e.set_flt_decay(0)
    e.set_flt_sustain(3)
    e.set_flt_release(100)
    p = e.params
    assert (p["flt_env_amount"], p["flt_keytrack"], p["flt_vel"]) == (1.0, 0.0, 1.0)
    assert (p["flt_attack"], p["flt_decay"], p["flt_sustain"], p["flt_release"]) == (
        5.0, 0.001, 1.0, 10.0)
    e.set_flt_env_amount(-5)
    assert e.params["flt_env_amount"] == -1.0
    st = e.status()
    for key in ("velocity_on", "flt_env_amount", "flt_keytrack", "flt_vel",
                *FLT_IDS):
        assert key in st


def test_shapes_reach_all_voices():
    e = make_engine()
    for v in e.voices:
        assert v.flt_env.attack == DEFAULT_FLT_ENV["attack"]
        assert v.flt_env.release == DEFAULT_FLT_ENV["release"]
    e.set_flt_attack(0.5)
    e.set_flt_decay(0.7)
    e.set_flt_sustain(0.4)
    e.set_flt_release(2.0)
    for v in e.voices:
        assert (v.flt_env.attack, v.flt_env.decay, v.flt_env.sustain,
                v.flt_env.release) == (0.5, 0.7, 0.4, 2.0)
        assert v.env.attack != 0.5


def test_patch_round_trip_includes_new_params():
    e = make_engine()
    reg = build_registry(e)
    defaults = capture(reg)
    for pid in ("velocity_on", "flt_env_amount", "flt_keytrack", "flt_vel", *FLT_IDS):
        assert pid in defaults
    reg.set("velocity_on", False)
    reg.set("flt_env_amount", -0.4)
    reg.set("flt_attack", 0.9)
    saved = capture(reg)
    e2 = make_engine()
    reg2 = build_registry(e2)
    assert apply(reg2, saved, defaults) == []
    assert capture(reg2) == saved
    assert e2.voices[0].flt_env.attack == 0.9


# ---- velocity ---------------------------------------------------------

def test_velocity_off_ignores_velocity():
    outs = []
    for vel in (20, 120):
        e = make_engine(3000.0)
        e.set_velocity_on(False)
        e.note_on(60, vel)
        assert e.voices[0].velocity == FIXED_VELOCITY
        outs.append(blocks(e, 6))
    assert np.array_equal(outs[0], outs[1])


def test_velocity_on_differs():
    outs = []
    for vel in (20, 120):
        e = make_engine(3000.0)
        e.note_on(60, vel)
        outs.append(blocks(e, 6))
    assert not np.allclose(outs[0], outs[1])


# ---- filter envelope --------------------------------------------------

def test_positive_amount_opens_negative_closes():
    base = attack_centroid(0.0)
    assert attack_centroid(1.0) > base * 1.2
    assert attack_centroid(-0.5) < base


def test_flt_env_not_advanced_when_amount_zero():
    e = make_engine()
    e.set_flt_keytrack(0.5)
    e.note_on(60, 100)
    blocks(e, 5)
    env = e.voices[0].flt_env
    from midi_synth.voice import ATTACK
    assert env.stage == ATTACK
    assert env.level == 0.0


def test_flt_env_advances_when_amount_nonzero():
    e = make_engine()
    e.set_flt_env_amount(0.5)
    e.note_on(60, 100)
    blocks(e, 5)
    assert e.voices[0].flt_env.level > 0.0


def test_note_off_releases_filter_envelope():
    e = make_engine()
    e.set_flt_env_amount(0.5)
    e.note_on(60, 100)
    blocks(e, 2)
    e.note_off(60)
    from midi_synth.voice import RELEASE
    assert e.voices[0].flt_env.stage == RELEASE


# ---- key tracking / velocity -> cutoff --------------------------------

def helper_cutoff(engine, note, velocity=0.5):
    v = engine.voices[0]
    v.note_on(note, velocity, 1)
    coeffs = v._voice_coeffs(BLOCK, engine.params)
    return coeffs


def test_keytrack_doubles_cutoff_per_octave():
    e = make_engine(1000.0)
    e.set_flt_keytrack(1.0)
    assert helper_cutoff(e, 72) == pytest.approx(lpf_coefficients(2000.0, 0.0, SR))
    assert helper_cutoff(e, 60) == pytest.approx(lpf_coefficients(1000.0, 0.0, SR))
    assert helper_cutoff(e, 48) == pytest.approx(lpf_coefficients(500.0, 0.0, SR))
    e.set_flt_keytrack(0.5)
    assert helper_cutoff(e, 72) == pytest.approx(
        lpf_coefficients(1000.0 * 2 ** 0.5, 0.0, SR))


def test_keytrack_spectral():
    def cent(note):
        e = make_engine(500.0)
        e.set_flt_keytrack(1.0)
        e.note_on(note, 100)
        return centroid(blocks(e, 8))
    # With tracking the filter follows the note, so the brightness ratio
    # between octaves is about the pitch ratio, not much more.
    e = make_engine(500.0)
    e.note_on(72, 100)
    untracked = centroid(blocks(e, 8))
    assert cent(72) > untracked


def test_flt_vel_changes_cutoff():
    e = make_engine(1000.0)
    e.set_flt_vel(1.0)
    assert helper_cutoff(e, 60, 0.5) == pytest.approx(lpf_coefficients(1000.0, 0.0, SR))
    assert helper_cutoff(e, 60, 1.0) == pytest.approx(
        lpf_coefficients(1000.0 * 2 ** 3, 0.0, SR))
    assert helper_cutoff(e, 60, 0.0) == pytest.approx(
        lpf_coefficients(1000.0 / 2 ** 3, 0.0, SR))


def test_helper_bypass_and_none():
    e = make_engine(1000.0)
    v = e.voices[0]
    v.note_on(60, 0.5, 1)
    assert v._voice_coeffs(BLOCK, e.params) is e.params["lpf_coeffs"]
    e.set_flt_keytrack(1.0)
    e.set_lpf_cutoff(20000.0)
    v.note_on(60, 0.5, 1)
    assert v._voice_coeffs(BLOCK, e.params) is None
    e.set_lpf_cutoff(15000.0)
    v.note_on(96, 0.5, 1)
    assert v._voice_coeffs(BLOCK, e.params) is None


def test_master_mode_ignores_modulation():
    def run(mod):
        e = make_engine(800.0)
        e.set_lpf_mode("master")
        if mod:
            e.set_flt_env_amount(1.0)
            e.set_flt_keytrack(1.0)
            e.set_flt_vel(1.0)
        e.note_on(72, 40)
        return blocks(e, 6)
    assert np.array_equal(run(False), run(True))


def test_default_path_uses_shared_coeffs():
    e = make_engine(800.0)
    v = e.voices[0]
    v.note_on(60, 0.5, 1)
    assert v._voice_coeffs(BLOCK, e.params) is e.params["lpf_coeffs"]
