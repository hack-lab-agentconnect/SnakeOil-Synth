import numpy as np
import pytest

from midi_synth.config import (
    LFO_FILTER_OCTAVES, LFO_PITCH_SEMITONES, LFO_PWM_RANGE)
from midi_synth.engine import SynthEngine
from midi_synth.lfo import LFO
from midi_synth.params import CHOICE, CONTINUOUS, TOGGLE, build_registry
from midi_synth.patches import apply, capture
from midi_synth.voice import Voice

SR, BLOCK = 44100, 256
WAVES = ("sine", "triangle", "saw", "square", "random")
DESTS = ("pitch", "filter", "pwm", "amp")


def make_engine(**setup):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=4)
    e.set_osc1_square(False)
    e.set_lpf_cutoff(20000)
    e.set_amp_release(0.001)
    for k, v in setup.items():
        getattr(e, "set_" + k)(v)
    return e


def blocks(engine, count):
    return np.concatenate(
        [engine.render(BLOCK, apply_effects=False)[:, 0] for _ in range(count)])


def segments(x, blocks_per_seg):
    size = blocks_per_seg * BLOCK
    return [x[i:i + size] for i in range(0, len(x) - size + 1, size)]


def dominant(x):
    pad = 1 << 16
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), pad))
    return float(np.argmax(spec) * SR / pad)


def centroid(x):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float(np.sum(freqs * spec) / np.sum(spec))


def harmonic(x, f):
    t = np.arange(len(x)) / SR
    return float(abs(np.sum(x * np.exp(-2j * np.pi * f * t))))


# ---- LFO generator ----------------------------------------------------

@pytest.mark.parametrize("wave", WAVES)
def test_lfo_range_and_array(wave):
    lfo = LFO()
    for _ in range(400):
        mid, arr = lfo.next_block(BLOCK, SR, 7.3, wave, want_array=True)
        assert -1.0 <= mid <= 1.0
        assert len(arr) == BLOCK
        assert arr.min() >= -1.0 and arr.max() <= 1.0
        assert 0.0 <= lfo.phase < 1.0


def test_lfo_no_array_by_default():
    mid, arr = LFO().next_block(BLOCK, SR, 5.0, "sine")
    assert arr is None and isinstance(mid, float)


def test_lfo_period_follows_phase_advance():
    lfo = LFO()
    for _ in range(50):
        lfo.next_block(441, SR, 1.0, "sine")
    assert lfo.phase == pytest.approx(0.5)
    for _ in range(50):
        lfo.next_block(441, SR, 1.0, "sine")
    assert lfo.phase == pytest.approx(0.0, abs=1e-9) or lfo.phase == pytest.approx(1.0)


def test_lfo_shapes():
    def mids(wave, rate=1.0, count=100):
        lfo = LFO()
        return np.array([lfo.next_block(441, SR, rate, wave)[0] for _ in range(count)])
    sine = mids("sine")
    assert sine[24] > 0.99 and sine[74] < -0.99          # peak at 1/4, trough at 3/4
    saw = mids("saw")
    assert np.all(np.diff(saw) > 0) and saw[0] < -0.97 and saw[-1] > 0.97
    sq = mids("square")
    assert set(np.round(sq, 6)) == {1.0, -1.0}
    assert np.all(sq[:49] == 1.0) and np.all(sq[51:] == -1.0)
    tri = mids("triangle")
    assert tri.max() > 0.97 and tri.min() < -0.97
    assert abs(tri[0]) < 0.05                              # starts at zero, rising


def test_sample_and_hold_holds_and_is_deterministic():
    def run():
        lfo = LFO()
        return [lfo.next_block(64, SR, 2.0, "random")[0] for _ in range(1000)]
    a, b = run(), run()
    assert a == b
    changes = [i for i in range(1, len(a)) if a[i] != a[i - 1]]
    assert 1 <= len(changes) <= 4                           # ~2.9 cycles in 1000 blocks
    spacing = np.diff(changes)
    assert all(abs(int(s) - 344) <= 2 for s in spacing)


@pytest.mark.parametrize("wave", WAVES)
def test_lfo_array_agrees_with_mid(wave):
    lfo = LFO()
    for _ in range(30):
        mid, arr = lfo.next_block(BLOCK, SR, 3.1, wave, want_array=True)
        assert abs(arr[BLOCK // 2] - mid) < 1e-9


# ---- params, setters, status -----------------------------------------

def test_registry_params():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    reg = build_registry(e)
    r = reg["lfo_rate"]
    assert (r.kind, r.group, r.label, r.scale, r.fmt) == (
        CONTINUOUS, "LFO 1", "Rate", "log", "{:.2f} Hz")
    assert (r.minimum, r.maximum) == (0.05, 20.0) and reg.get("lfo_rate") == 5.0
    d = reg["lfo_depth"]
    assert (d.kind, d.group, d.label, d.minimum, d.maximum) == (
        CONTINUOUS, "LFO 1", "Depth", 0.0, 1.0) and reg.get("lfo_depth") == 0.0
    w = reg["lfo_wave"]
    assert (w.kind, w.group, w.label, w.choices) == (CHOICE, "LFO 1", "Wave", WAVES)
    assert reg.get("lfo_wave") == "sine"
    t = reg["lfo_dest"]
    assert (t.kind, t.group, t.label, t.choices) == (CHOICE, "LFO 1", "Dest", DESTS)
    assert reg.get("lfo_dest") == "pitch"
    g = reg["glide_time"]
    assert (g.kind, g.group, g.label, g.scale, g.fmt, g.minimum, g.maximum) == (
        CONTINUOUS, "Glide", "Time", "linear", "{:.2f} s", 0.0, 2.0)
    assert reg.get("glide_time") == 0.0
    lg = reg["glide_legato"]
    assert (lg.kind, lg.group, lg.label) == (TOGGLE, "Glide", "Legato only")
    assert reg.get("glide_legato") is False


def test_setters_clamp_and_validate():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    e.set_lfo_rate(100)
    assert e.params["lfo_rate"] == 20.0
    e.set_lfo_rate(0)
    assert e.params["lfo_rate"] == 0.05
    e.set_lfo_depth(3)
    assert e.params["lfo_depth"] == 1.0
    e.set_lfo_depth(-1)
    assert e.params["lfo_depth"] == 0.0
    e.set_glide_time(9)
    assert e.params["glide_time"] == 2.0
    e.set_glide_time(-1)
    assert e.params["glide_time"] == 0.0
    e.set_glide_legato(1)
    assert e.params["glide_legato"] is True
    with pytest.raises(ValueError):
        e.set_lfo_wave("noise")
    with pytest.raises(ValueError):
        e.set_lfo_dest("nowhere")
    assert e.set_lfo_wave("saw") == "saw" and e.set_lfo_dest("amp") == "amp"


def test_status_and_patch_capture():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    reg = build_registry(e)
    st = e.status()
    for k in ("lfo_rate", "lfo_depth", "lfo_wave", "lfo_dest",
              "glide_time", "glide_legato"):
        assert k in st
    values = capture(reg)
    for k in ("lfo_rate", "lfo_depth", "lfo_wave", "lfo_dest",
              "glide_time", "glide_legato"):
        assert k in values
    defaults = dict(values)
    reg.set("lfo_dest", "amp")
    reg.set("glide_time", 1.0)
    apply(reg, defaults, defaults)
    assert e.params["lfo_dest"] == "pitch" and e.params["glide_time"] == 0.0


def test_constants():
    assert (LFO_PITCH_SEMITONES, LFO_FILTER_OCTAVES, LFO_PWM_RANGE) == (2.0, 3.0, 0.25)


# ---- destinations -----------------------------------------------------

def chord_render(engine, count=40, note=57):
    engine.note_on(note, 100)
    return blocks(engine, count)


def depth0_reference(setup, count=40):
    return chord_render(make_engine(**setup), count)


@pytest.mark.parametrize("dest", DESTS)
@pytest.mark.parametrize("master", [False, True])
def test_depth_zero_is_bit_identical(dest, master):
    setup = {"lpf_cutoff": 1500.0}
    if master:
        setup["lpf_mode"] = "master"
    ref = depth0_reference(setup)
    e = make_engine(**setup)
    e.set_lfo_dest(dest)
    e.set_lfo_wave("triangle")
    e.set_lfo_rate(8.0)
    assert np.array_equal(chord_render(e), ref)


@pytest.mark.parametrize("dest", DESTS)
def test_returning_to_depth_zero_restores_audio(dest):
    ref = depth0_reference({"lpf_cutoff": 1500.0})
    e = make_engine(lpf_cutoff=1500.0)
    e.set_lfo_dest(dest)
    e.set_lfo_depth(1.0)
    blocks(e, 5)
    e.set_lfo_depth(0.0)
    assert np.array_equal(chord_render(e), ref)


@pytest.mark.parametrize("dest", DESTS)
@pytest.mark.parametrize("master", [False, True])
def test_depth_one_changes_audio(dest, master):
    setup = {"lpf_cutoff": 1500.0}
    if master:
        setup["lpf_mode"] = "master"
    ref = depth0_reference(setup)
    e = make_engine(**setup)
    e.set_lfo_dest(dest)
    e.set_lfo_depth(1.0)
    e.set_lfo_rate(4.0)
    if dest == "pwm":
        e.set_osc1_square(True)
        ref = chord_render(make_engine(osc1_square=True, **setup))
    out = chord_render(e)
    assert out.shape == ref.shape
    assert not np.allclose(out, ref, atol=1e-3)


def test_pitch_destination_sweeps_frequency():
    e = make_engine(lfo_depth=1.0, lfo_rate=1.0)
    e.set_lfo_dest("pitch")
    e.note_on(57, 100)
    x = blocks(e, 175)[BLOCK * 10:]
    freqs = np.array([dominant(s) for s in segments(x, 8)])
    spread = (freqs.max() - freqs.min()) / freqs.mean()
    assert spread > 0.1                                   # about 24% expected
    assert freqs.mean() == pytest.approx(220.0, rel=0.05)
    # pitch bend value itself is never overwritten
    assert e.params["pitch_bend"] == 0.0 and e.params["pitch_ratio"] == 1.0


def test_amp_destination_tremolo():
    e = make_engine(lfo_depth=1.0, lfo_rate=2.0)
    e.set_lfo_dest("amp")
    e.note_on(57, 100)
    x = blocks(e, 350)[BLOCK * 60:]
    rms = np.array([np.sqrt(np.mean(s ** 2)) for s in segments(x, 4)])
    assert rms.min() / rms.max() < 0.7
    flat = make_engine()
    flat.note_on(57, 100)
    y = blocks(flat, 350)[BLOCK * 60:]
    rms0 = np.array([np.sqrt(np.mean(s ** 2)) for s in segments(y, 4)])
    assert rms0.min() / rms0.max() > 0.9


def test_pwm_destination_varies_second_harmonic():
    e = make_engine()
    e.set_osc_levels(0.0, 1.0)
    e.set_mod_mode("off")
    e.set_osc2_octave_up(False)
    e.set_lfo_dest("pwm")
    e.set_lfo_depth(1.0)
    e.set_lfo_rate(2.0)
    e.note_on(60, 100)
    x = blocks(e, 350)[BLOCK * 20:]
    f0 = 440.0 * 2 ** (-9 / 12)
    h2 = np.array([harmonic(s, 2 * f0) for s in segments(x, 4)])
    assert (h2.max() - h2.min()) / h2.mean() > 0.3


@pytest.mark.parametrize("master", [False, True])
def test_filter_destination_sweeps_centroid(master):
    e = make_engine(lpf_cutoff=1000.0)
    if master:
        e.set_lpf_mode("master")
    e.set_lfo_dest("filter")
    e.set_lfo_depth(1.0)
    e.set_lfo_rate(2.0)
    e.note_on(48, 100)
    x = blocks(e, 350)[BLOCK * 20:]
    c = np.array([centroid(s) for s in segments(x, 4)])
    assert c.max() / c.min() > 1.3


# ---- glide ------------------------------------------------------------

def glide_engine(time=0.5, legato=False):
    e = make_engine()
    e.set_glide_time(time)
    e.set_glide_legato(legato)
    return e


def test_glide_converges_to_target():
    e = glide_engine(0.5)
    e.note_on(60, 100)
    blocks(e, 20)
    e.note_off(60)
    blocks(e, 20)
    e.note_on(72, 100)
    x = blocks(e, 120)
    first = dominant(x[:4 * BLOCK])
    mid = dominant(x[40 * BLOCK:44 * BLOCK])
    late = dominant(x[100 * BLOCK:104 * BLOCK])
    f60, f72 = 440.0 * 2 ** (-9 / 12), 440.0 * 2 ** (3 / 12)
    assert first == pytest.approx(f60, rel=0.08)
    assert f60 * 1.2 < mid < f72 * 0.9
    assert late == pytest.approx(f72, rel=0.02)


def test_glide_zero_identical_to_default():
    ref = make_engine()
    e = make_engine(glide_legato=False)
    e.set_glide_legato(True)
    for eng in (ref, e):
        eng.note_on(60, 100)
    a, b = blocks(ref, 10), blocks(e, 10)
    for eng in (ref, e):
        eng.note_on(72, 100)
    a2, b2 = blocks(ref, 10), blocks(e, 10)
    assert np.array_equal(a, b) and np.array_equal(a2, b2)


def test_legato_glides_only_when_a_note_is_held():
    e = glide_engine(0.5, legato=True)
    e.note_on(60, 100)
    blocks(e, 10)
    e.note_on(72, 100)                     # 60 still held -> glide
    v72 = next(v for v in e.voices if v.active and v.note == 72)
    assert v72.glide_from == pytest.approx(440.0 * 2 ** (-9 / 12))
    assert v72.glide_total == 0.5
    e.all_notes_off()
    blocks(e, 20)                          # everything released and silent
    e.note_on(64, 100)
    v64 = next(v for v in e.voices if v.active and v.note == 64)
    assert v64.glide_from is None
    # audio: played after a full release -> starts on its own pitch
    e2 = glide_engine(0.5, legato=True)
    e2.note_on(60, 100)
    blocks(e2, 10)
    e2.note_off(60)
    blocks(e2, 20)
    e2.note_on(72, 100)
    x = blocks(e2, 6)
    assert dominant(x[:4 * BLOCK]) == pytest.approx(440.0 * 2 ** (3 / 12), rel=0.03)


def test_first_note_never_glides():
    e = glide_engine(0.5)
    e.note_on(72, 100)
    assert next(v for v in e.voices if v.active).glide_from is None


def test_voice_note_on_signature_compatible():
    v = Voice(SR)
    v.note_on(60, 0.8, 3)
    assert v.glide_from is None
    v.note_on(64, 0.8, order=4, glide_from=220.0, glide_time=0.25)
    assert (v.glide_from, v.glide_total, v.glide_pos) == (220.0, 0.25, 0.0)
    v.note_on(64, 0.8, order=5, glide_from=220.0)       # no time -> no glide
    assert v.glide_from is None


def test_voice_glide_path_is_log_linear():
    v = Voice(SR)
    params = SynthEngine(sr=SR, block_size=BLOCK, max_voices=1).params
    f_from, f_to = 220.0, 440.0
    v.note_on(69, 1.0, 1, glide_from=f_from, glide_time=1.0)
    seen = []
    orig = v.osc1.advance

    def spy(freq, n):
        seen.append(freq)
        return orig(freq, n)

    v.osc1.advance = spy
    for _ in range(3):
        v.render(BLOCK, params)
    dt = BLOCK / SR
    for i, f in enumerate(seen):
        frac = 1.0 - (i + 0.5) * dt / 1.0
        expect = np.exp(np.log(f_to) + (np.log(f_from) - np.log(f_to)) * frac)
        assert f == pytest.approx(expect, rel=1e-9)
    v.glide_pos = 5.0
    seen.clear()
    v.render(BLOCK, params)
    assert seen[0] == v.freq


# ---- console and GUI --------------------------------------------------

def test_console_lfo_and_glide(monkeypatch, capsys):
    import builtins
    import run
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    lines = iter(["lfo 3 0.5", "lfo 7 1 square amp", "glide 0.4", "lfo 1 1 bogus", "quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    run.console_loop(e)
    out = capsys.readouterr().out
    assert (e.params["lfo_rate"], e.params["lfo_depth"]) == (7.0, 1.0)
    assert (e.params["lfo_wave"], e.params["lfo_dest"]) == ("square", "amp")
    assert e.params["glide_time"] == 0.4
    assert "bad arguments" in out
    assert "lfo <rate> <depth>" in run.HELP_TEXT and "glide <seconds>" in run.HELP_TEXT


def test_gui_has_lfo_and_glide_groups(tmp_path):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QGroupBox
    from midi_synth.gui.bridge import Bridge
    from midi_synth.gui.main_window import GROUP_POSITIONS, MainWindow
    from midi_synth.midi_router import MidiRouter
    from midi_synth.profiles import ProfileStore

    QApplication.instance() or QApplication([])
    e = SynthEngine(sr=SR, block_size=64, max_voices=2)
    reg = build_registry(e)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(reg, store.open_active())
    window = MainWindow(e, reg, router, store, [], Bridge(reg, router))
    assert "LFO 1" in GROUP_POSITIONS and "Glide" in GROUP_POSITIONS
    assert set(window.controls) == set(reg.ids())
    titles = {b.title() for b in window.findChildren(QGroupBox)}
    assert {"LFO 1", "LFO 2", "Glide"} <= titles
    window.close()
