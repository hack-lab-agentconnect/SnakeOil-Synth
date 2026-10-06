import numpy as np
import pytest

from midi_synth.engine import SynthEngine
from midi_synth.lfo import LFO
from midi_synth.params import build_registry
from midi_synth.patches import apply, capture

SR, BLOCK = 44100, 256
WAVE = "random-glide"
DESTS = ("pitch", "filter", "pwm", "amp")


def render(seed, rate, seconds, block, wave=WAVE):
    lfo = LFO(seed=seed)
    total = int(seconds * SR)
    out = []
    for _ in range(total // block):
        out.append(lfo.next_block(block, SR, rate, wave, want_array=True)[1])
    return np.concatenate(out)


def draws(seed, count):
    return np.random.default_rng(seed).uniform(-1.0, 1.0, count)


def make_engine():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=4)
    e.set_osc1_square(True)
    e.set_lpf_cutoff(2000)
    e.set_amp_release(0.001)
    return e


def play(e, count=60):
    e.note_on(57, 100)
    return np.concatenate([e.render(BLOCK, apply_effects=False) for _ in range(count)])


def test_choice_is_last_and_validated():
    from midi_synth.config import LFO_WAVES
    assert LFO_WAVES[-1] == WAVE and LFO_WAVES[:5] == (
        "sine", "triangle", "saw", "square", "random")
    e = make_engine()
    e.set_lfo_wave(WAVE)
    e.set_lfo2_wave(WAVE)
    assert (e.params["lfo_wave"], e.params["lfo2_wave"]) == (WAVE, WAVE)
    reg = build_registry(e)
    assert WAVE in reg["lfo_wave"].choices and WAVE in reg["lfo2_wave"].choices


def test_continuous_compared_to_sample_and_hold():
    x = render(1, 1.0, 5.0, 256)
    assert np.max(np.abs(np.diff(x))) < 0.01
    sh = render(1, 1.0, 5.0, 256, wave="random")
    assert np.max(np.abs(np.diff(sh))) > 0.05
    assert x.min() >= -1.0 and x.max() <= 1.0


def test_hits_targets_at_wraps():
    d = draws(1, 8)
    x = render(1, 1.0, 4.0, 64)
    assert x[0] == pytest.approx(d[0], abs=1e-6)
    for k in range(1, 4):
        i = k * SR
        assert x[i] == pytest.approx(d[k], abs=1e-3)
        assert x[i - 1] == pytest.approx(d[k], abs=1e-3)
    # mid-cycle is the midpoint of the two targets
    assert x[SR // 2] == pytest.approx((d[0] + d[1]) / 2, abs=1e-3)


def test_determinism_and_distinct_seeds():
    assert np.array_equal(render(1, 3.0, 2.0, 256), render(1, 3.0, 2.0, 256))
    assert not np.array_equal(render(1, 3.0, 2.0, 256), render(2, 3.0, 2.0, 256))
    a, b = make_engine(), make_engine()
    assert a.lfo.next_block(64, SR, 5.0, WAVE)[0] != a.lfo2.next_block(64, SR, 5.0, WAVE)[0]


def test_block_size_invariance():
    ref = render(1, 2.7, 3.0, 4096)
    for block in (1, 7, 64, 256):
        x = render(1, 2.7, 3.0, block)
        n = min(len(x), len(ref))
        assert np.allclose(x[:n], ref[:n], atol=1e-6)
    assert len(ref) > 100000


def test_large_block_with_multiple_wraps():
    lfo = LFO(seed=1)
    _, arr = lfo.next_block(4096, SR, 20.0, WAVE, want_array=True)
    assert len(arr) == 4096 and np.all(np.isfinite(arr))
    assert np.max(np.abs(np.diff(arr))) < 0.05
    assert 0.0 <= lfo.phase < 1.0


@pytest.mark.parametrize("block", (256, 4096))
def test_scalar_matches_array_centre(block):
    lfo = LFO(seed=2)
    for _ in range(40):
        mid, arr = lfo.next_block(block, SR, 3.1, WAVE, want_array=True)
        assert abs(arr[block // 2] - mid) < 1e-9


def test_rate_change_stays_continuous():
    lfo = LFO(seed=1)
    out = []
    for i in range(1200):
        rate = 1.0 if i < 300 else (13.0 if i < 600 else 0.2 if i < 900 else 5.0)
        out.append(lfo.next_block(64, SR, rate, WAVE, want_array=True)[1])
    x = np.concatenate(out)
    # fastest rate 13 Hz: max slope pi/2 * 2 * 13 / SR per sample
    assert np.max(np.abs(np.diff(x))) < 0.002
    assert np.all(np.abs(x) <= 1.0)


def test_switching_waves_is_safe():
    lfo = LFO()
    seq = ["sine", WAVE, "random", WAVE, "saw", WAVE]
    for i in range(300):
        mid, arr = lfo.next_block(128, SR, 9.0, seq[i // 50], want_array=True)
        assert np.isfinite(mid) and np.all(np.isfinite(arr))
        assert -1.0 <= mid <= 1.0


@pytest.mark.parametrize("which", [1, 2])
@pytest.mark.parametrize("dest", DESTS)
def test_destinations_respond(dest, which):
    pre = "lfo2" if which == 2 else "lfo"
    e = make_engine()
    getattr(e, "set_%s_rate" % pre)(8.0)
    getattr(e, "set_%s_depth" % pre)(1.0)
    getattr(e, "set_%s_wave" % pre)(WAVE)
    getattr(e, "set_%s_dest" % pre)(dest)
    x = play(e)
    assert np.all(np.isfinite(x))
    assert not np.array_equal(x, play(make_engine()))


def test_patch_round_trip():
    e = make_engine()
    reg = build_registry(e)
    defaults = capture(reg)
    reg.set("lfo_wave", WAVE)
    reg.set("lfo2_wave", WAVE)
    saved = capture(reg)
    apply(reg, defaults, defaults)
    assert e.params["lfo_wave"] == "sine"
    apply(reg, saved, defaults)
    assert (e.params["lfo_wave"], e.params["lfo2_wave"]) == (WAVE, WAVE)


def test_console(monkeypatch, capsys):
    import builtins
    import run
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    lines = iter(["lfo 2 0.5 random-glide filter", "lfo2 0.5 0.7 RANDOM-GLIDE pitch", "quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    run.console_loop(e)
    assert (e.params["lfo_wave"], e.params["lfo_dest"]) == (WAVE, "filter")
    assert (e.params["lfo2_wave"], e.params["lfo2_dest"]) == (WAVE, "pitch")
    assert "bad arguments" not in capsys.readouterr().out
    assert "random-glide" in run.HELP_TEXT


def test_gui_combo_lists_wave(tmp_path):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox
    from midi_synth.gui.bridge import Bridge
    from midi_synth.gui.main_window import MainWindow
    from midi_synth.midi_router import MidiRouter
    from midi_synth.profiles import ProfileStore

    QApplication.instance() or QApplication([])
    e = SynthEngine(sr=SR, block_size=64, max_voices=2)
    reg = build_registry(e)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(reg, store.open_active())
    w = MainWindow(e, reg, router, store, [], Bridge(reg, router))
    try:
        for pid in ("lfo_wave", "lfo2_wave"):
            combos = w.controls[pid].findChildren(QComboBox) or [w.controls[pid]]
            texts = [combos[0].itemText(i) for i in range(combos[0].count())]
            assert WAVE in texts
    finally:
        w.close()
