import numpy as np
import pytest

from midi_synth.engine import SynthEngine
from midi_synth.params import CHOICE, CONTINUOUS, build_registry
from midi_synth.patches import apply, capture
from midi_synth.voice import IDLE, Voice

SR, BLOCK = 44100, 256


def make_engine(width=1, voices=12, **setup):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices)
    e.set_unison_voices(width)
    for k, v in setup.items():
        getattr(e, "set_" + k)(v)
    return e


def gated(e, note=None):
    return [v for v in e.voices if v.gate and (note is None or v.note == note)]


def render(e, count, effects=False):
    return np.concatenate(
        [e.render(BLOCK, apply_effects=effects) for _ in range(count)])


# ---- params / registry ------------------------------------------------

def test_params_registered():
    e = SynthEngine(sr=SR, block_size=BLOCK)
    reg = build_registry(e)
    v = reg["unison_voices"]
    assert (v.kind, v.group, v.label) == (CHOICE, "Unison", "Voices")
    assert v.choices == tuple(str(i) for i in range(1, 13))
    assert reg.get("unison_voices") == "1"
    d = reg["unison_detune"]
    assert (d.kind, d.group, d.label, d.fmt, d.minimum, d.maximum) == (
        CONTINUOUS, "Unison", "Detune", "{:.0f} ct", 0.0, 50.0)
    assert reg.get("unison_detune") == 15.0
    s = reg["unison_spread"]
    assert (s.kind, s.group, s.label, s.minimum, s.maximum) == (
        CONTINUOUS, "Unison", "Spread", 0.0, 1.0)
    assert reg.get("unison_spread") == 0.5


def test_registry_choice_round_trip():
    e = SynthEngine(sr=SR, block_size=BLOCK)
    reg = build_registry(e)
    reg.set("unison_voices", "7")
    assert e.params["unison_voices"] == 7
    assert isinstance(e.params["unison_voices"], int)
    assert reg.get("unison_voices") == "7"
    assert e.status()["unison_voices"] == 7


def test_setters_validate_and_clamp():
    e = SynthEngine(sr=SR, block_size=BLOCK)
    e.set_unison_voices("5")
    assert e.params["unison_voices"] == 5
    for bad in (0, 13, "x", -1):
        with pytest.raises(ValueError):
            e.set_unison_voices(bad)
    assert e.params["unison_voices"] == 5
    e.set_unison_detune(99)
    assert e.params["unison_detune"] == 50.0
    e.set_unison_detune(-3)
    assert e.params["unison_detune"] == 0.0
    e.set_unison_spread(5)
    assert e.params["unison_spread"] == 1.0
    st = e.status()
    assert st["unison_detune"] == 0.0 and st["unison_spread"] == 1.0


def test_patch_round_trip_includes_unison():
    e = SynthEngine(sr=SR, block_size=BLOCK)
    reg = build_registry(e)
    defaults = capture(reg)
    assert defaults["unison_voices"] == "1"
    reg.set("unison_voices", "6")
    reg.set("unison_detune", 33.0)
    reg.set("unison_spread", 0.9)
    saved = capture(reg)
    e2 = SynthEngine(sr=SR, block_size=BLOCK)
    reg2 = build_registry(e2)
    assert apply(reg2, saved, defaults) == []
    assert e2.params["unison_voices"] == 6
    assert e2.params["unison_detune"] == 33.0
    assert e2.params["unison_spread"] == 0.9


# ---- voice ------------------------------------------------------------

def test_voice_defaults_and_note_on_kwargs():
    v = Voice(SR)
    assert (v.detune_cents, v.pan, v.gain, v.group) == (0.0, 0.0, 1.0, None)
    v.note_on(60, 0.5, 1, None, 0.0, detune_cents=7.0, pan=-0.5, gain=0.25, group=3)
    assert (v.detune_cents, v.pan, v.gain, v.group) == (7.0, -0.5, 0.25, 3)
    v.note_on(60, 0.5, 2)
    assert (v.detune_cents, v.pan, v.gain, v.group) == (0.0, 0.0, 1.0, None)


def test_voice_random_phase_and_default_reset():
    v = Voice(SR)
    v.osc1.phase = 0.3
    v.osc2.phase = 0.4
    v.note_on(60, 0.5, 1)
    assert v.osc1.phase == 0.0 and v.osc2.phase == 0.0
    rng = np.random.default_rng(5)
    v.note_on(60, 0.5, 2, random_phase=True, rng=rng)
    rng2 = np.random.default_rng(5)
    assert v.osc1.phase == rng2.random()
    assert v.osc2.phase == rng2.random()


# ---- allocation -------------------------------------------------------

@pytest.mark.parametrize("n", [2, 3, 5, 12])
def test_group_allocation_values(n):
    e = make_engine(n, unison_detune=20.0, unison_spread=0.8)
    e.note_on(60, 90)
    g = gated(e)
    assert len(g) == n
    assert len({v.group for v in g}) == 1 and g[0].group is not None
    assert {v.note for v in g} == {60}
    assert len({v.velocity for v in g}) == 1
    det = [v.detune_cents for v in g]
    pan = [v.pan for v in g]
    assert det == pytest.approx(list(np.linspace(-20.0, 20.0, n)))
    assert pan == pytest.approx(list(np.linspace(-0.8, 0.8, n)))
    assert det == pytest.approx([-d for d in reversed(det)])
    assert pan == pytest.approx([-d for d in reversed(pan)])
    steps = np.diff(det)
    assert steps == pytest.approx(np.full(n - 1, steps[0]))
    assert all(v.gain == pytest.approx(1 / np.sqrt(n)) for v in g)


def test_width_one_is_neutral():
    e = make_engine(1, unison_detune=30.0)
    e.note_on(60, 100)
    (v,) = gated(e)
    assert (v.detune_cents, v.pan, v.gain) == (0.0, 0.0, 1.0)
    assert v.group is None


def test_width_clamped_to_max_voices():
    e = make_engine(8, voices=4)
    e.note_on(60, 100)
    assert len(gated(e)) == 4


def test_polyphony_and_whole_group_stealing():
    e = make_engine(4)
    for note in (60, 62, 64):
        e.note_on(note, 100)
    assert len(gated(e)) == 12
    e.note_on(65, 100)
    assert gated(e, 60) == []
    assert len(gated(e, 65)) == 4
    assert len(gated(e, 62)) == 4 and len(gated(e, 64)) == 4
    groups = {}
    for v in e.voices:
        groups.setdefault(v.group, []).append(v)
    assert all(len(vs) == 4 for vs in groups.values())


def test_steal_prefers_released_groups():
    e = make_engine(4)
    for note in (60, 62, 64):
        e.note_on(note, 100)
    e.note_off(64)
    e.note_on(65, 100)
    assert len(gated(e, 60)) == 4 and len(gated(e, 62)) == 4
    assert gated(e, 64) == []
    assert len(gated(e, 65)) == 4


def test_steal_with_idle_remainder_takes_whole_groups():
    e = make_engine(5)  # 12 voices: two groups of 5 + 2 idle
    e.note_on(60, 100)
    e.note_on(62, 100)
    e.note_on(64, 100)  # needs 5, only 2 idle -> steal oldest group
    assert gated(e, 60) == []
    assert len(gated(e, 62)) == 5 and len(gated(e, 64)) == 5
    assert sum(1 for v in e.voices if v.gate) == 10


def test_steal_single_voices_counted_as_groups():
    e = make_engine(1)
    for note in range(48, 60):
        e.note_on(note, 100)
    e.set_unison_voices(3)
    e.note_on(70, 100)
    assert len(gated(e, 70)) == 3
    assert gated(e, 48) == [] and gated(e, 49) == [] and gated(e, 50) == []
    assert len(gated(e, 51)) == 1


def test_retrigger_same_note_releases_old_group():
    e = make_engine(3)
    e.note_on(60, 100)
    first = {v.group for v in gated(e)}
    e.note_on(60, 100)
    assert len(gated(e)) == 3
    assert {v.group for v in gated(e)}.isdisjoint(first)


def test_note_off_releases_whole_group():
    e = make_engine(4)
    e.note_on(60, 100)
    e.note_on(64, 100)
    e.note_off(60)
    assert gated(e, 60) == [] and len(gated(e, 64)) == 4


def test_sustain_defers_whole_group():
    e = make_engine(4)
    e.set_sustain(True)
    e.note_on(60, 100)
    e.note_off(60)
    assert len(gated(e, 60)) == 4
    e.set_sustain(False)
    assert gated(e) == []


def test_all_notes_off_and_panic_cover_groups():
    e = make_engine(4)
    e.note_on(60, 100)
    e.note_on(64, 100)
    render(e, 2)
    e.all_notes_off()
    assert gated(e) == []
    e.note_on(67, 100)
    e.panic()
    assert gated(e) == []
    assert all(v.env.stage == IDLE for v in e.voices)
    assert e.active_note_count() == 0


def test_group_counter_increments_per_note():
    e = make_engine(2)
    e.note_on(60, 100)
    e.note_on(62, 100)
    gs = sorted({v.group for v in gated(e)})
    assert len(gs) == 2 and gs[1] == gs[0] + 1


def test_glide_start_shared_by_unison_voices():
    e = make_engine(3, glide_time=0.5)
    e.note_on(60, 100)
    e.note_on(67, 100)
    new = gated(e, 67)
    assert len(new) == 3
    assert all(v.glide_from == pytest.approx(new[0].glide_from) for v in new)
    assert new[0].glide_from == pytest.approx(440.0 * 2 ** (-9 / 12))


# ---- rendering --------------------------------------------------------

def play(width, spread=0.5, detune=15.0, blocks=40, **kw):
    e = make_engine(width, unison_spread=spread, unison_detune=detune, **kw)
    e.note_on(57, 100)
    return render(e, blocks)


def test_width_one_bit_identical_to_fresh_engine():
    a = SynthEngine(sr=SR, block_size=BLOCK)
    b = SynthEngine(sr=SR, block_size=BLOCK)
    b.set_unison_voices(1)
    b.set_unison_detune(40.0)
    b.set_unison_spread(1.0)
    for e in (a, b):
        for n in (48, 52, 55):
            e.note_on(n, 100)
    for _ in range(30):
        assert np.array_equal(a.render(BLOCK), b.render(BLOCK))


def test_spread_zero_is_mono_and_spread_makes_stereo():
    out0 = play(5, spread=0.0)
    assert np.array_equal(out0[:, 0], out0[:, 1])
    out = play(5, spread=1.0)
    assert not np.allclose(out[:, 0], out[:, 1])
    rl = np.sqrt(np.mean(out[:, 0] ** 2))
    rr = np.sqrt(np.mean(out[:, 1] ** 2))
    assert 0.6 < rl / rr < 1.67


def test_loudness_within_3db():
    def rms(x):
        return np.sqrt(np.mean(x[len(x) // 2:] ** 2))
    one = play(1, blocks=80)
    twelve = play(12, blocks=80)
    ratio = (rms(twelve[:, 0]) + rms(twelve[:, 1])) / (rms(one[:, 0]) + rms(one[:, 1]))
    assert abs(20 * np.log10(ratio)) < 3.0


def test_detune_broadens_spectrum():
    def mono(detune):
        e = make_engine(5, unison_spread=0.0, unison_detune=detune,
                        osc1_square=False, lpf_cutoff=20000.0)
        e.note_on(69, 100)
        return render(e, 120)[:, 0]
    narrow = mono(0.0)
    wide = mono(30.0)
    # more energy outside the narrow peak (spectral spreading)
    def outside(x):
        seg = x[len(x) // 2:]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        freqs = np.fft.rfftfreq(len(seg), 1.0 / SR)
        band = (freqs > 400) & (freqs < 480)
        core = band & (np.abs(freqs - 440) < 1.5)
        return spec[band & ~core].sum() / spec[band].sum()
    assert outside(wide) > outside(narrow) * 1.5


def test_random_phases_differ_but_deterministic():
    def phases():
        e = make_engine(6)
        e.note_on(60, 100)
        return [v.osc1.phase for v in gated(e)] + [v.osc2.phase for v in gated(e)]
    a, b = phases(), phases()
    assert a == b
    assert len(set(a[:6])) == 6
    assert any(p != 0.0 for p in a)


def test_deterministic_render_across_engines():
    a = play(7)
    b = play(7)
    assert np.array_equal(a, b)


def test_master_lpf_stereo_path():
    e = make_engine(5, unison_spread=1.0, unison_detune=25.0,
                    lpf_cutoff=300.0, osc1_square=False)
    e.set_lpf_mode("master")
    e.note_on(72, 100)
    out = render(e, 60)
    assert np.isfinite(out).all()
    assert not np.allclose(out[:, 0], out[:, 1])
    ref = make_engine(5, unison_spread=1.0, unison_detune=25.0, osc1_square=False,
                      lpf_cutoff=20000.0)
    ref.set_lpf_mode("master")
    ref.note_on(72, 100)
    full = render(ref, 60)
    for ch in (0, 1):
        spec = np.abs(np.fft.rfft(out[1000:, ch]))
        spec_ref = np.abs(np.fft.rfft(full[1000:, ch]))
        freqs = np.fft.rfftfreq(len(out[1000:, ch]), 1.0 / SR)
        hi = freqs > 3000
        assert spec[hi].sum() < 0.1 * spec_ref[hi].sum()


def test_master_lpf_both_states_reset_on_mode_switch():
    e = make_engine(3, unison_spread=1.0, lpf_cutoff=500.0)
    e.set_lpf_mode("master")
    e.note_on(60, 100)
    render(e, 5)
    assert e.master_lpf.z1 != 0.0 and e.master_lpf_r.z1 != 0.0
    e.set_lpf_mode("voice")
    assert e.master_lpf.z1 == 0.0 and e.master_lpf_r.z1 == 0.0
    assert e.master_lpf.z2 == 0.0 and e.master_lpf_r.z2 == 0.0


def test_master_lpf_lfo_filter_stereo_finite():
    e = make_engine(4, unison_spread=1.0, lpf_cutoff=800.0)
    e.set_lpf_mode("master")
    e.set_lfo_depth(1.0)
    e.set_lfo_dest("filter")
    e.note_on(60, 100)
    out = render(e, 30)
    assert np.isfinite(out).all() and np.abs(out).max() > 0


def test_effects_accept_stereo_unison():
    e = make_engine(4, unison_spread=1.0)
    for fx in ("chorus", "delay", "reverb", "bitcrush"):
        e.set_effect(fx, True)
    e.note_on(60, 100)
    out = render(e, 20, effects=True)
    assert out.shape == (20 * BLOCK, 2) and np.isfinite(out).all()


# ---- GUI --------------------------------------------------------------

def test_gui_unison_group(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QGroupBox
    from midi_synth.gui.bridge import Bridge
    from midi_synth.gui.main_window import GROUP_POSITIONS, MainWindow
    from midi_synth.midi_router import MidiRouter
    from midi_synth.profiles import ProfileStore

    QApplication.instance() or QApplication([])
    e = SynthEngine(sr=SR, block_size=BLOCK)
    reg = build_registry(e)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(reg, store.open_active())
    window = MainWindow(e, reg, router, store, [], Bridge(reg, router))
    assert "Unison" in GROUP_POSITIONS
    cells = list(GROUP_POSITIONS.values())
    assert len(set(cells)) == len(cells)
    for pid in ("unison_voices", "unison_detune", "unison_spread"):
        assert pid in window.controls
    assert set(window.controls) == {p.id for p in reg}
    assert "Unison" in {b.title() for b in window.findChildren(QGroupBox)}
    window.close()
