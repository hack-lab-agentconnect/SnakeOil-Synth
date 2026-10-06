import numpy as np
import pytest

from midi_synth.config import LFO_RATE_MOD_OCTAVES
from midi_synth.engine import SynthEngine
from midi_synth.params import build_registry
from midi_synth.patches import apply, capture

SR, BLOCK = 44100, 256
BASE = ("pitch", "filter", "pwm", "amp")


def make_engine():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=4)
    e.set_osc1_square(True)
    e.set_lpf_cutoff(2000)
    e.set_amp_release(0.001)
    return e


def blocks(e, count, note=57):
    e.note_on(note, 100)
    return np.concatenate([e.render(BLOCK, apply_effects=False) for _ in range(count)])


def run_blocks(e, count):
    e.note_on(60, 100)
    for _ in range(count):
        e.render(BLOCK, apply_effects=False)
        yield


def test_constant():
    assert LFO_RATE_MOD_OCTAVES == 2.0


def test_choices_append_new_destination():
    reg = build_registry(make_engine())
    assert reg["lfo_dest"].choices == BASE + ("lfo2-rate",)
    assert reg["lfo2_dest"].choices == BASE + ("lfo1-rate",)


def test_dest_validation():
    e = make_engine()
    assert e.set_lfo_dest("lfo2-rate") == "lfo2-rate"
    assert e.set_lfo2_dest("lfo1-rate") == "lfo1-rate"
    with pytest.raises(ValueError):
        e.set_lfo_dest("lfo1-rate")
    with pytest.raises(ValueError):
        e.set_lfo2_dest("lfo2-rate")


def test_lfo1_modulates_lfo2_rate():
    e = make_engine()
    e.set_lfo_rate(2.0)
    e.set_lfo_depth(0.5)
    e.set_lfo_dest("lfo2-rate")
    e.set_lfo2_rate(5.0)
    e.set_lfo2_depth(0.5)
    rates, vals = [], []
    for _ in run_blocks(e, 600):
        rates.append(e.lfo_rate_eff[1])
        vals.append(e._lfo_last[0])
    rates = np.array(rates)
    assert rates.max() > 5.0 * 1.2 and rates.min() < 5.0 / 1.2
    assert rates.max() <= 5.0 * 2 ** (0.5 * 2.0) + 1e-9
    assert rates.min() >= 5.0 * 2 ** (-0.5 * 2.0) - 1e-9
    # previous-block semantics: block k uses LFO 1's value from block k-1
    for k in range(1, 600):
        want = 5.0 * 2.0 ** (0.5 * vals[k - 1] * 2.0)
        assert rates[k] == pytest.approx(want)
    assert e.lfo_rate_eff[0] == 2.0


def test_lfo2_modulates_lfo1_rate_symmetric():
    e = make_engine()
    e.set_lfo2_rate(2.0)
    e.set_lfo2_depth(1.0)
    e.set_lfo2_dest("lfo1-rate")
    e.set_lfo_rate(4.0)
    e.set_lfo_depth(0.3)
    e.set_lfo_dest("pitch")
    rates = []
    for _ in run_blocks(e, 600):
        rates.append(e.lfo_rate_eff[0])
    rates = np.array(rates)
    assert rates.max() > 4.0 * 1.5 and rates.min() < 4.0 / 1.5
    assert rates.max() <= 4.0 * 4.0 + 1e-9
    assert rates.min() >= 4.0 / 4.0 - 1e-9
    assert e.lfo_rate_eff[1] == 2.0


def test_no_crossmod_keeps_rates_constant():
    e = make_engine()
    e.set_lfo_rate(3.0)
    e.set_lfo_depth(0.5)
    e.set_lfo2_rate(6.0)
    e.set_lfo2_depth(0.5)
    for _ in run_blocks(e, 50):
        assert e.lfo_rate_eff == [3.0, 6.0]


def test_zero_depth_modulator_does_nothing():
    e = make_engine()
    e.set_lfo_depth(0.0)
    e.set_lfo_dest("lfo2-rate")
    e.set_lfo2_depth(0.5)
    e.set_lfo2_rate(6.0)
    for _ in run_blocks(e, 20):
        assert e.lfo_rate_eff[1] == 6.0


def _square_mod(base_rate):
    e = make_engine()
    e.set_lfo_rate(20.0)
    e.set_lfo_depth(1.0)
    e.set_lfo_wave("square")
    e.set_lfo_dest("lfo2-rate")
    e.params["lfo2_rate"] = base_rate  # below the knob range, to reach the floor
    e.set_lfo2_depth(0.5)
    seen = set()
    for _ in run_blocks(e, 300):
        seen.add(e.lfo_rate_eff[1])
    return seen


def test_clamped_to_range():
    assert max(_square_mod(20.0)) == 40.0
    assert min(_square_mod(0.02)) == 0.01


def test_mutual_modulation_is_stable_and_finite():
    e = make_engine()
    for pre, other in (("lfo", "lfo2-rate"), ("lfo2", "lfo1-rate")):
        getattr(e, "set_%s_rate" % pre)(10.0)
        getattr(e, "set_%s_depth" % pre)(1.0)
        getattr(e, "set_%s_dest" % pre)(other)
    e.set_lfo_wave("random-glide")
    e.note_on(60, 100)
    for _ in range(3000):
        out = e.render(BLOCK, apply_effects=True)
        assert np.all(np.isfinite(out))
        assert all(0.01 <= r <= 40.0 for r in e.lfo_rate_eff)
        assert all(-1.0 <= v <= 1.0 for v in e._lfo_last)


def test_crossmod_publishes_neutral_voice_modulation():
    e = make_engine()
    e.set_lfo_rate(3.0)
    e.set_lfo_depth(1.0)
    e.set_lfo_dest("lfo2-rate")
    for _ in run_blocks(e, 20):
        pass
    p = e.params
    assert (p["lfo_pitch_ratio"], p["lfo_filter_oct"], p["lfo_pwm"], p["lfo_amp"]) == (
        1.0, 0.0, 0.0, None)


def test_crossmod_output_equals_no_lfo_when_lfo2_off():
    a, b = make_engine(), make_engine()
    a.set_lfo_depth(1.0)
    a.set_lfo_dest("lfo2-rate")
    assert np.array_equal(blocks(a, 40), blocks(b, 40))


def test_changing_dest_clears_stale_values():
    e = make_engine()
    e.set_lfo_depth(1.0)
    e.set_lfo_dest("amp")
    for _ in run_blocks(e, 3):
        pass
    e.set_lfo_dest("lfo2-rate")
    assert e.params["lfo_amp"] is None
    assert e._lfo_last == [0.0, 0.0]


def test_crossmod_other_lfo_still_drives_its_own_dest():
    e = make_engine()
    e.set_lfo_depth(0.5)
    e.set_lfo_dest("lfo2-rate")
    e.set_lfo2_depth(0.5)
    e.set_lfo2_dest("amp")
    for _ in run_blocks(e, 5):
        pass
    assert e.params["lfo_amp"] is not None


def test_patch_round_trip_with_new_choices():
    e = make_engine()
    reg = build_registry(e)
    defaults = capture(reg)
    reg.set("lfo_dest", "lfo2-rate")
    reg.set("lfo2_dest", "lfo1-rate")
    saved = capture(reg)
    apply(reg, defaults, defaults)
    assert e.params["lfo_dest"] == "pitch"
    apply(reg, saved, defaults)
    assert (e.params["lfo_dest"], e.params["lfo2_dest"]) == ("lfo2-rate", "lfo1-rate")


def test_console_commands(monkeypatch, capsys):
    import builtins
    import run
    e = make_engine()
    lines = iter(["lfo 1 0.5 sine lfo2-rate", "lfo2 2 0.4 triangle lfo1-rate",
                  "lfo 1 1 sine lfo1-rate", "quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    run.console_loop(e)
    out = capsys.readouterr().out
    assert e.params["lfo_dest"] == "lfo2-rate"
    assert e.params["lfo2_dest"] == "lfo1-rate"
    assert "bad arguments" in out
    assert "lfo2-rate" in run.HELP_TEXT and "lfo1-rate" in run.HELP_TEXT


# ---- GUI ---------------------------------------------------------------

@pytest.fixture
def window(tmp_path):
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
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
    w.resize(1500, 900)
    w.show()
    QApplication.processEvents()
    yield w
    w.close()


def test_single_lfo_box_with_two_stacks(window):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QGroupBox, QLabel

    titles = [b.title() for b in window.findChildren(QGroupBox)]
    assert titles.count("LFO") == 1
    assert "LFO 1" not in titles and "LFO 2" not in titles
    box = next(b for b in window.findChildren(QGroupBox) if b.title() == "LFO")
    stacks = []
    for pre in ("lfo", "lfo2"):
        ids = [pre + s for s in ("_rate", "_depth", "_wave", "_dest")]
        pts = [window.controls[i].mapTo(box, QPoint(0, 0)) for i in ids]
        assert box.isAncestorOf(window.controls[ids[0]])
        assert len({p.x() for p in pts}) == 1
        ys = [p.y() for p in pts]
        assert ys == sorted(ys) and len(set(ys)) == 4
        stacks.append(pts)
    assert stacks[0][0].x() < stacks[1][0].x()
    headers = {lab.text(): lab for lab in box.findChildren(QLabel)
               if lab.text() in ("LFO 1", "LFO 2")}
    assert set(headers) == {"LFO 1", "LFO 2"}
    for i, name in enumerate(("LFO 1", "LFO 2")):
        hp = headers[name].mapTo(box, QPoint(0, 0))
        assert hp.y() < stacks[i][0].y()
        assert hp.x() <= stacks[i][0].x() + 20


def test_matrix_cell_is_free_and_hint_fits(window):
    from midi_synth.gui.main_window import GROUP_POSITIONS, MOD_MATRIX_CELL
    assert MOD_MATRIX_CELL == (1, 4, 1, 1)
    assert GROUP_POSITIONS["LFO"] == (1, 3, 1, 1)
    r, c, rs, cs = MOD_MATRIX_CELL
    for rr, cc, rrs, ccs in GROUP_POSITIONS.values():
        assert not (rr < r + rs and r < rr + rrs and cc < c + cs and c < cc + ccs)
    hint = window.sizeHint()
    assert hint.width() <= 1500 and hint.height() <= 900
