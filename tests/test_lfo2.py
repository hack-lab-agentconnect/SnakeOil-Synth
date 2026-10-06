import numpy as np
import pytest

from midi_synth.engine import SynthEngine
from midi_synth.params import CHOICE, CONTINUOUS, build_registry
from midi_synth.patches import apply, capture

SR, BLOCK = 44100, 256
DET_WAVES = ("sine", "triangle", "saw", "square")
DESTS = ("pitch", "filter", "pwm", "amp")
DESTS2 = DESTS + ("lfo1-rate",)


def make_engine(**setup):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=4)
    e.set_osc1_square(True)
    e.set_osc1_pwm(0.25)
    e.set_lpf_cutoff(2000)
    e.set_amp_release(0.001)
    for k, v in setup.items():
        getattr(e, "set_" + k)(v)
    return e


def play(e, count=30, note=57):
    e.note_on(note, 100)
    return np.concatenate([e.render(BLOCK, apply_effects=False) for _ in range(count)])


def configure(e, n, depth, wave, dest, rate=3.3):
    pre = "lfo2" if n == 2 else "lfo"
    getattr(e, "set_%s_rate" % pre)(rate)
    getattr(e, "set_%s_depth" % pre)(depth)
    getattr(e, "set_%s_wave" % pre)(wave)
    getattr(e, "set_%s_dest" % pre)(dest)


def render_all(engines, count):
    for _ in range(count):
        for e in engines:
            e.render(BLOCK, apply_effects=False)


# ---- registry / engine params -----------------------------------------

def test_registry():
    e = make_engine()
    reg = build_registry(e)
    ids = reg.ids()
    for grp, pre in (("LFO 1", "lfo"), ("LFO 2", "lfo2")):
        members = [p for p in reg if p.group == grp]
        assert [p.label for p in members] == ["Rate", "Depth", "Wave", "Dest"]
        assert [p.id for p in members] == [pre + s for s in ("_rate", "_depth", "_wave", "_dest")]
    assert not [p for p in reg if p.group == "LFO"]
    assert ids.index("lfo_dest") < ids.index("lfo2_rate")
    r = reg["lfo2_rate"]
    assert (r.kind, r.scale, r.fmt, r.minimum, r.maximum) == (
        CONTINUOUS, "log", "{:.2f} Hz", 0.05, 20.0)
    assert reg["lfo2_depth"].kind == CONTINUOUS
    assert (reg["lfo2_depth"].minimum, reg["lfo2_depth"].maximum) == (0.0, 1.0)
    assert reg["lfo2_wave"].kind == CHOICE
    assert reg["lfo2_wave"].choices == ("sine", "triangle", "saw", "square", "random", "random-glide")
    assert reg["lfo2_dest"].choices == DESTS2
    assert (reg.get("lfo2_rate"), reg.get("lfo2_depth"), reg.get("lfo2_wave"),
            reg.get("lfo2_dest")) == (5.0, 0.0, "sine", "filter")


def test_setters_clamp_and_validate():
    e = make_engine()
    e.set_lfo2_rate(1000)
    assert e.params["lfo2_rate"] == 20.0
    e.set_lfo2_rate(0.0001)
    assert e.params["lfo2_rate"] == 0.05
    e.set_lfo2_depth(5)
    assert e.params["lfo2_depth"] == 1.0
    e.set_lfo2_depth(-1)
    assert e.params["lfo2_depth"] == 0.0
    with pytest.raises(ValueError):
        e.set_lfo2_wave("bogus")
    with pytest.raises(ValueError):
        e.set_lfo2_dest("bogus")
    e.set_lfo2_wave("random")
    e.set_lfo2_dest("amp")
    st = e.status()
    assert (st["lfo2_wave"], st["lfo2_dest"], st["lfo2_depth"]) == ("random", "amp", 0.0)
    assert "lfo2_rate" in st


# ---- LFO 2 alone equals LFO 1 alone -----------------------------------

@pytest.mark.parametrize("mode", ["voice", "master"])
@pytest.mark.parametrize("dest", DESTS)
@pytest.mark.parametrize("wave", DET_WAVES)
def test_lfo2_alone_matches_lfo1_alone(wave, dest, mode):
    a = make_engine(lpf_mode=mode)
    b = make_engine(lpf_mode=mode)
    configure(a, 1, 0.8, wave, dest)
    configure(b, 2, 0.8, wave, dest)
    x, y = play(a), play(b)
    assert np.array_equal(x, y)
    assert not np.array_equal(x, play(make_engine(lpf_mode=mode)))


def test_random_waves_differ_between_lfos():
    a = make_engine()
    b = make_engine()
    configure(a, 1, 1.0, "random", "pitch", rate=20.0)
    configure(b, 2, 1.0, "random", "pitch", rate=20.0)
    assert not np.array_equal(play(a, 60), play(b, 60))


# ---- combining ---------------------------------------------------------

def test_pitch_ratios_multiply():
    both, only1, only2 = make_engine(), make_engine(), make_engine()
    configure(both, 1, 0.7, "sine", "pitch", rate=2.0)
    configure(both, 2, 0.5, "triangle", "pitch", rate=3.0)
    configure(only1, 1, 0.7, "sine", "pitch", rate=2.0)
    configure(only2, 2, 0.5, "triangle", "pitch", rate=3.0)
    for _ in range(5):
        render_all((both, only1, only2), 1)
        s = (12 * np.log2(only1.params["lfo_pitch_ratio"])
             + 12 * np.log2(only2.params["lfo_pitch_ratio"]))
        assert both.params["lfo_pitch_ratio"] == pytest.approx(2.0 ** (s / 12.0), rel=1e-12)
        assert both.params["lfo_pitch_ratio"] != 1.0


@pytest.mark.parametrize("dest,key", [("filter", "lfo_filter_oct"), ("pwm", "lfo_pwm")])
def test_filter_octaves_and_pwm_add(dest, key):
    both, o1, o2 = make_engine(), make_engine(), make_engine()
    configure(both, 1, 0.9, "saw", dest, rate=2.0)
    configure(both, 2, 0.6, "square", dest, rate=4.0)
    configure(o1, 1, 0.9, "saw", dest, rate=2.0)
    configure(o2, 2, 0.6, "square", dest, rate=4.0)
    for _ in range(6):
        render_all((both, o1, o2), 1)
        assert both.params[key] == pytest.approx(o1.params[key] + o2.params[key], abs=1e-12)
        assert o1.params[key] != 0.0


def test_amp_gains_multiply():
    both, o1, o2 = make_engine(), make_engine(), make_engine()
    configure(both, 1, 0.9, "sine", "amp", rate=5.0)
    configure(both, 2, 0.6, "triangle", "amp", rate=7.0)
    configure(o1, 1, 0.9, "sine", "amp", rate=5.0)
    configure(o2, 2, 0.6, "triangle", "amp", rate=7.0)
    for _ in range(6):
        render_all((both, o1, o2), 1)
        assert np.allclose(both.params["lfo_amp"],
                           o1.params["lfo_amp"] * o2.params["lfo_amp"], rtol=0, atol=1e-12)


def test_different_destinations_both_apply():
    e, o1, o2 = make_engine(), make_engine(), make_engine()
    configure(e, 1, 0.8, "sine", "pitch")
    configure(e, 2, 0.8, "sine", "amp")
    configure(o1, 1, 0.8, "sine", "pitch")
    configure(o2, 2, 0.8, "sine", "amp")
    render_all((e, o1, o2), 4)
    assert e.params["lfo_pitch_ratio"] == o1.params["lfo_pitch_ratio"] != 1.0
    assert np.array_equal(e.params["lfo_amp"], o2.params["lfo_amp"])
    assert o1.params["lfo_amp"] is None and o2.params["lfo_pitch_ratio"] == 1.0


def test_master_filter_with_only_lfo2_on_filter():
    a = make_engine(lpf_mode="master", lpf_cutoff=3000)
    b = make_engine(lpf_mode="master", lpf_cutoff=3000)
    configure(a, 1, 0.0, "sine", "pitch")
    configure(a, 2, 1.0, "sine", "filter")
    configure(b, 1, 1.0, "sine", "filter")
    assert np.array_equal(play(a), play(b))


# ---- neutrality ---------------------------------------------------------

def test_lfo1_unchanged_when_lfo2_depth_zero():
    a, b = make_engine(), make_engine()
    configure(a, 1, 0.8, "sine", "pitch")
    configure(b, 1, 0.8, "sine", "pitch")
    configure(b, 2, 0.0, "random", "amp")
    assert np.array_equal(play(a), play(b))


@pytest.mark.parametrize("last", [1, 2])
def test_both_depths_back_to_zero_is_bit_identical_to_fresh(last):
    e = make_engine()
    for dest in DESTS:
        configure(e, 1, 0.9, "sine", dest)
        configure(e, 2, 0.9, "triangle", dest)
        render_all((e,), 3)
    order = (1, 2) if last == 2 else (2, 1)
    for n in order:
        configure(e, n, 0.0, "sine", "amp")
    p = e.params
    assert (p["lfo_pitch_ratio"], p["lfo_filter_oct"], p["lfo_pwm"], p["lfo_amp"]) == (
        1.0, 0.0, 0.0, None)
    assert np.array_equal(play(e, 20, 60), play(make_engine(), 20, 60))


def test_changing_one_lfo_clears_stale_modulation():
    e = make_engine()
    configure(e, 1, 1.0, "sine", "amp")
    render_all((e,), 1)
    assert e.params["lfo_amp"] is not None
    e.set_lfo_depth(0.0)
    assert e.params["lfo_amp"] is None
    configure(e, 2, 0.5, "sine", "pwm")
    render_all((e,), 2)
    assert e.params["lfo_pwm"] != 0.0
    e.set_lfo2_dest("pitch")
    assert e.params["lfo_pwm"] == 0.0


# ---- patches / console -------------------------------------------------

def test_patch_round_trip_and_old_patch():
    e = make_engine()
    reg = build_registry(e)
    values = capture(reg)
    for k in ("lfo2_rate", "lfo2_depth", "lfo2_wave", "lfo2_dest"):
        assert k in values
    defaults = dict(values)
    reg.set("lfo2_depth", 0.6)
    reg.set("lfo2_dest", "amp")
    reg.set("lfo2_wave", "square")
    reg.set("lfo2_rate", 9.0)
    saved = capture(reg)
    apply(reg, defaults, defaults)
    assert e.params["lfo2_depth"] == 0.0
    apply(reg, saved, defaults)
    assert (e.params["lfo2_depth"], e.params["lfo2_dest"], e.params["lfo2_wave"]) == (
        0.6, "amp", "square")
    old = {k: v for k, v in saved.items() if not k.startswith("lfo2_")}
    apply(reg, old, defaults)
    assert (e.params["lfo2_rate"], e.params["lfo2_depth"], e.params["lfo2_wave"],
            e.params["lfo2_dest"]) == (5.0, 0.0, "sine", "filter")


def test_console_lfo2(monkeypatch, capsys):
    import builtins
    import run
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    lines = iter(["lfo2 3 0.5", "lfo2 7 1 square amp", "lfo2 1 1 bogus", "quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    run.console_loop(e)
    out = capsys.readouterr().out
    assert (e.params["lfo2_rate"], e.params["lfo2_depth"]) == (7.0, 1.0)
    assert (e.params["lfo2_wave"], e.params["lfo2_dest"]) == ("square", "amp")
    assert e.params["lfo_depth"] == 0.0
    assert "bad arguments" in out
    assert "lfo2 <rate> <depth>" in run.HELP_TEXT


# ---- GUI layout --------------------------------------------------------

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
    w.show()
    QApplication.processEvents()
    yield w
    w.close()


def test_lfo_groups_are_single_columns(window):
    from PySide6.QtCore import QPoint
    for grp, pre in (("LFO 1", "lfo"), ("LFO 2", "lfo2")):
        ids = [pre + s for s in ("_rate", "_depth", "_wave", "_dest")]
        box = window.controls[ids[0]].parentWidget()
        while box is not None and getattr(box, "title", lambda: None)() != "LFO":
            box = box.parentWidget()
        assert box is not None
        pts = [window.controls[i].mapTo(box, QPoint(0, 0)) for i in ids]
        assert len({p.x() for p in pts}) == 1
        ys = [p.y() for p in pts]
        assert ys == sorted(ys) and len(set(ys)) == 4
        for i in ids:
            c = window.controls[i]
            assert box.rect().contains(c.mapTo(box, QPoint(0, 0)))
            assert box.rect().contains(c.mapTo(box, QPoint(c.width() - 1, c.height() - 1)))


def test_window_hint_and_group_positions(window):
    from midi_synth.gui.main_window import GROUP_POSITIONS, MERGED_GROUPS
    assert MERGED_GROUPS == {"LFO 1": ("LFO", 0), "LFO 2": ("LFO", 1)}
    assert "LFO" in GROUP_POSITIONS and "LFO 1" not in GROUP_POSITIONS
    hint = window.sizeHint()
    assert hint.width() <= 1700 and hint.height() <= 900
    cells = set()
    for r, c, rs, cs in GROUP_POSITIONS.values():
        for rr in range(r, r + rs):
            for cc in range(c, c + cs):
                assert (rr, cc) not in cells
                cells.add((rr, cc))
