"""Noise generator: shared tables, per-voice mixing, params, matrix, console, GUI."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import builtins
import subprocess
import sys
import time

import numpy as np
import pytest

from midi_synth import noise
from midi_synth.config import NOISE_RMS, NOISE_TABLE_LEN
from midi_synth.engine import SynthEngine
from midi_synth.params import CHOICE, CONTINUOUS, build_registry
from midi_synth.patches import apply, capture
from midi_synth.voice import Voice

SR = 44100
BLOCK = 256


def make_engine(voices=6, **params):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices)
    reg = build_registry(e)
    for pid, value in params.items():
        reg.set(pid, value)
    return e, reg


def noise_only(e, reg):
    reg.set("osc1_level", 0.0)
    reg.set("osc2_level", 0.0)
    reg.set("lpf_cutoff", 20000.0)
    reg.set("amp_sustain", 1.0)
    reg.set("amp_attack", 0.001)


def render(e, blocks):
    return np.concatenate([e.render(BLOCK, apply_effects=False) for _ in range(blocks)])


# ---- tables ---------------------------------------------------------------

def test_constants_and_colors():
    assert noise.NOISE_COLORS == ("white", "pink", "brown")
    assert NOISE_TABLE_LEN == 2 ** 18
    assert NOISE_RMS == 0.5


@pytest.mark.parametrize("color", noise.NOISE_COLORS)
def test_table_properties(color):
    t = noise.table(color)
    assert t.dtype == np.float64 and t.shape == (NOISE_TABLE_LEN,)
    assert np.all(np.isfinite(t))
    assert abs(float(np.mean(t))) < 1e-9
    rms = float(np.sqrt(np.mean(t * t)))
    assert rms == pytest.approx(NOISE_RMS, rel=0.01)
    assert noise.table(color) is t


def test_table_unknown_color():
    with pytest.raises(KeyError):
        noise.table("blue")


def test_generation_is_fast_and_deterministic_across_processes():
    code = ("import time, hashlib\n"
            "from midi_synth import noise\n"
            "t0 = time.perf_counter()\n"
            "h = hashlib.sha1()\n"
            "for c in noise.NOISE_COLORS: h.update(noise.table(c).tobytes())\n"
            "print(time.perf_counter() - t0, h.hexdigest())\n")
    outs = [subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           check=True).stdout.split() for _ in range(2)]
    assert outs[0][1] == outs[1][1]
    assert all(float(o[0]) < 0.5 for o in outs)
    import hashlib
    h = hashlib.sha1()
    for c in noise.NOISE_COLORS:
        h.update(noise.table(c).tobytes())
    assert h.hexdigest() == outs[0][1]


def _slope(x):
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    p = np.abs(np.fft.rfft(x)) ** 2
    sel = (f >= 100.0) & (f <= 10000.0)
    # average in log-spaced bins so low bins do not dominate the fit
    edges = np.geomspace(100.0, 10000.0, 40)
    fc, pc = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (f >= a) & (f < b)
        fc.append(np.sqrt(a * b))
        pc.append(np.mean(p[m]))
    assert sel.any()
    return np.polyfit(np.log10(fc), np.log10(pc), 1)[0]


@pytest.mark.parametrize("color,expected", [("white", 0.0), ("pink", -1.0), ("brown", -2.0)])
def test_spectral_slope(color, expected):
    assert _slope(noise.table(color)) == pytest.approx(expected, abs=0.15)


@pytest.mark.parametrize("color", noise.NOISE_COLORS)
def test_seamless_loop(color):
    t = noise.table(color)
    d = np.abs(np.diff(t))
    wrap = abs(t[0] - t[-1])
    assert wrap < np.percentile(d, 99.9) * 1.5
    assert wrap < 6 * np.std(np.diff(t))


def test_centroid_ordering():
    def centroid(x):
        p = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1.0 / SR)
        return float(np.sum(f * p) / np.sum(p))
    c = [centroid(noise.table(k)) for k in noise.NOISE_COLORS]
    assert c[0] > c[1] > c[2]


# ---- voice ----------------------------------------------------------------

def _factor(velocity):
    return 0.22 * (0.3 + 0.7 * velocity)


@pytest.mark.parametrize("color", noise.NOISE_COLORS)
def test_voice_direct_rms_exact_factor(color):
    v = Voice(SR)
    v.note_on(60, 100 / 127.0, 1)
    v.env.set_shape(0.001, 0.1, 1.0, 0.2)
    params = _voice_params(noise_level=0.5, noise_color=color)
    for _ in range(8):
        v.render(BLOCK, params)
    # one full trip around the table, so the low-frequency colors average out
    out = np.concatenate([v.render(4096, params) for _ in range(NOISE_TABLE_LEN // 4096)])
    expected = 0.5 * NOISE_RMS * _factor(100 / 127.0)
    assert float(np.sqrt(np.mean(out ** 2))) == pytest.approx(expected, rel=0.05)


def _voice_params(**extra):
    e, reg = make_engine(voices=1)
    noise_only(e, reg)
    p = dict(e.params)
    p.update(extra)
    return p


def test_voices_have_independent_noise():
    e, reg = make_engine(voices=2)
    reg.set("noise_level", 1.0)
    e.note_on(60, 100)
    e.note_on(64, 100)
    a, b = e.voices[0], e.voices[1]
    assert a.noise_pos != b.noise_pos
    params = _voice_params(noise_level=1.0)
    a.env.set_shape(0.001, 0.1, 1.0, 0.2)
    b.env.set_shape(0.001, 0.1, 1.0, 0.2)
    xa = np.concatenate([a.render(BLOCK, params) for _ in range(60)])[2000:]
    xb = np.concatenate([b.render(BLOCK, params) for _ in range(60)])[2000:]
    corr = abs(np.corrcoef(xa, xb)[0, 1])
    assert corr < 0.05


def test_unison_voices_get_different_noise_positions():
    e, reg = make_engine(voices=6)
    reg.set("unison_voices", "4")
    e.note_on(60, 100)
    pos = [v.noise_pos for v in e.voices if v.active]
    assert len(pos) == 4 and len(set(pos)) == 4


def test_noise_rng_does_not_disturb_unison_phases():
    e1, _ = make_engine(voices=4, unison_voices="3")
    e2, _ = make_engine(voices=4, unison_voices="3")
    e1.note_on(60, 100)
    e2.note_on(60, 100)
    p1 = [(v.osc1.phase, v.osc2.phase) for v in e1.voices if v.active]
    p2 = [(v.osc1.phase, v.osc2.phase) for v in e2.voices if v.active]
    assert p1 == p2
    # and the unison sequence equals what a bare seeded rng produces
    rng = np.random.default_rng(1234)
    expected = [(rng.random(), rng.random()) for _ in range(3)]
    assert sorted(p1) == sorted(expected)


def test_deterministic_across_fresh_engines():
    outs = []
    for _ in range(2):
        e, reg = make_engine(voices=4)
        reg.set("noise_level", 0.5)
        reg.set("noise_color", "pink")
        e.note_on(60, 100)
        e.note_on(67, 90)
        outs.append(render(e, 20))
    assert np.array_equal(outs[0], outs[1])


def test_wrap_around_table_boundary(monkeypatch):
    short = np.tile(np.linspace(-1, 1, 1000), 1)
    short = np.concatenate([short, short[::-1]])
    monkeypatch.setattr(noise, "table", lambda color: short)
    v = Voice(SR)
    v.note_on(60, 1.0, 1)
    v.noise_pos = len(short) - 100
    v.env.set_shape(0.001, 0.1, 1.0, 0.2)
    params = _voice_params(noise_level=1.0)
    out = np.concatenate([v.render(4096, params) for _ in range(3)])
    assert np.all(np.isfinite(out))
    assert 0 <= v.noise_pos < len(short)


def test_long_note_crosses_table_boundary_smoothly():
    e, reg = make_engine(voices=1)
    noise_only(e, reg)
    reg.set("noise_level", 1.0)
    reg.set("noise_color", "brown")
    e.note_on(60, 100)
    e.voices[0].noise_pos = NOISE_TABLE_LEN - 2048
    out = np.concatenate([e.render(4096, apply_effects=False) for _ in range(3)])
    assert np.all(np.isfinite(out))
    d = np.abs(np.diff(out[:, 0] if out.ndim > 1 else out))
    assert d.max() < 8 * np.std(d) + 1e-9


def test_level_zero_does_no_noise_work(monkeypatch):
    calls = []
    orig = noise.table
    monkeypatch.setattr(noise, "table", lambda c: (calls.append(c), orig(c))[1])
    e, reg = make_engine(voices=3)
    e.note_on(60, 100)
    render(e, 10)
    assert calls == []
    reg.set("noise_level", 0.3)
    render(e, 2)
    assert calls


def test_level_zero_is_bit_identical_to_pre_feature_voice():
    e1, _ = make_engine(voices=3)
    e2, reg2 = make_engine(voices=3)
    reg2.set("noise_color", "brown")
    for e in (e1, e2):
        e.note_on(60, 100)
        e.note_on(64, 80)
    assert np.array_equal(render(e1, 30), render(e2, 30))


def test_noise_added_on_top_of_oscillators():
    e1, _ = make_engine(voices=1)
    e2, reg2 = make_engine(voices=1)
    reg2.set("noise_level", 0.4)
    for e in (e1, e2):
        e.params["lpf_cutoff"] = 20000.0
        e.set_lpf_cutoff(20000.0)
        e.note_on(60, 100)
    a, b = render(e1, 20), render(e2, 20)
    assert not np.array_equal(a, b)


def _hf_energy(x):
    p = np.abs(np.fft.rfft(x[len(x) // 4:])) ** 2
    f = np.fft.rfftfreq(len(x[len(x) // 4:]), 1.0 / SR)
    return float(np.sum(p[f > 8000.0]))


def test_noise_passes_through_the_lpf():
    outs = {}
    for cutoff in (20000.0, 500.0):
        e, reg = make_engine(voices=1)
        noise_only(e, reg)
        reg.set("lpf_cutoff", cutoff)
        reg.set("noise_level", 1.0)
        e.note_on(60, 100)
        x = render(e, 80)
        outs[cutoff] = x[:, 0] if x.ndim > 1 else x
    assert _hf_energy(outs[500.0]) < 0.01 * _hf_energy(outs[20000.0])


def test_noise_follows_the_amp_envelope():
    e, reg = make_engine(voices=1)
    noise_only(e, reg)
    reg.set("amp_release", 0.01)
    reg.set("noise_level", 1.0)
    e.note_on(60, 100)
    render(e, 20)
    e.note_off(60)
    render(e, 10)
    tail = render(e, 4)
    assert float(np.max(np.abs(tail))) == 0.0
    assert not e.voices[0].active


def test_attack_shapes_noise():
    e, reg = make_engine(voices=1)
    noise_only(e, reg)
    reg.set("amp_attack", 0.5)
    reg.set("noise_level", 1.0)
    e.note_on(60, 100)
    x = render(e, 40)
    x = x[:, 0] if x.ndim > 1 else x
    early = np.sqrt(np.mean(x[:1000] ** 2))
    late = np.sqrt(np.mean(x[-1000:] ** 2))
    assert early < 0.2 * late


def test_noise_level_zero_with_osc_silent_is_silent():
    e, reg = make_engine(voices=1)
    noise_only(e, reg)
    e.note_on(60, 100)
    assert float(np.max(np.abs(render(e, 10)))) == 0.0


# ---- params ---------------------------------------------------------------

def test_registry_entries():
    e, reg = make_engine()
    lvl, col = reg["noise_level"], reg["noise_color"]
    assert (lvl.group, lvl.kind, lvl.label, lvl.fmt) == ("Noise", CONTINUOUS, "Level", "{:.2f}")
    assert (lvl.minimum, lvl.maximum) == (0.0, 1.0)
    assert (col.group, col.kind, col.label) == ("Noise", CHOICE, "Color")
    assert col.choices == ("white", "pink", "brown")
    assert reg.get("noise_level") == 0.0 and reg.get("noise_color") == "white"
    assert e.params["noise_level"] == 0.0 and e.params["noise_color"] == "white"


def test_setters_validate_and_clamp():
    e, _ = make_engine()
    e.set_noise_level(2.0)
    assert e.params["noise_level"] == 1.0
    e.set_noise_level(-1.0)
    assert e.params["noise_level"] == 0.0
    e.set_noise_color("pink")
    assert e.params["noise_color"] == "pink"
    with pytest.raises(ValueError):
        e.set_noise_color("blue")
    assert e.params["noise_color"] == "pink"


def test_registry_rejects_bad_choice_and_clamps_level():
    _, reg = make_engine()
    with pytest.raises(ValueError):
        reg.set("noise_color", "blue")
    reg.set("noise_level", 5)
    assert reg.get("noise_level") == 1.0


def test_status_has_noise():
    e, reg = make_engine()
    reg.set("noise_level", 0.25)
    reg.set("noise_color", "brown")
    s = e.status()
    assert s["noise_level"] == 0.25 and s["noise_color"] == "brown"


def test_setters_take_the_lock():
    e, _ = make_engine()
    import threading
    done = []
    with e.lock:
        t = threading.Thread(target=lambda: (e.set_noise_level(0.5), done.append(1)))
        t.start()
        t.join(0.2)
        assert not done
    t.join(2)
    assert done


def test_patch_round_trip_and_old_patch_defaults():
    e, reg = make_engine()
    defaults = capture(reg)
    reg.set("noise_level", 0.7)
    reg.set("noise_color", "pink")
    values = capture(reg)
    assert values["noise_level"] == 0.7 and values["noise_color"] == "pink"
    e2, reg2 = make_engine()
    apply(reg2, values, defaults)
    assert reg2.get("noise_level") == 0.7 and reg2.get("noise_color") == "pink"
    old = {k: v for k, v in values.items() if not k.startswith("noise_")}
    apply(reg2, old, defaults)
    assert reg2.get("noise_level") == 0.0 and reg2.get("noise_color") == "white"


# ---- matrix ---------------------------------------------------------------

def test_matrix_destination_table():
    from midi_synth.modmatrix import DESTINATIONS, destination
    names = [d.name for d in DESTINATIONS]
    assert names.index("Osc 2: PWM") + 1 == names.index("Noise: Level")
    assert names.index("Noise: Level") + 1 == names.index("Modulation Amount")
    d = destination("Noise: Level")
    assert (d.param_id, d.kind, d.lo, d.hi) == ("noise_level", "voice", 0.0, 1.0)


def _matrix_rms(base, scale, wheel):
    e, reg = make_engine(voices=1)
    noise_only(e, reg)
    reg.set("noise_level", base)
    e.set_mod_src(1, "Mod Wheel")
    e.set_mod_amt(1, scale)
    e.set_mod_dst(1, "Noise: Level")
    e.set_mod_wheel(wheel)
    e.note_on(60, 100)
    render(e, 30)
    x = render(e, 100)
    return float(np.sqrt(np.mean(x ** 2)))


def test_matrix_noise_level_relative_and_clamped():
    unmod = _matrix_rms(0.5, 0.0, 1.0)
    full = _matrix_rms(0.5, 1.0, 1.0)
    assert full == pytest.approx(2 * unmod, rel=0.05)
    over = _matrix_rms(0.8, 1.0, 1.0)
    one = _matrix_rms(1.0, 0.0, 0.0)
    assert over == pytest.approx(one, rel=0.05)
    assert _matrix_rms(0.0, 1.0, 1.0) == 0.0


def test_matrix_header_present_once():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from midi_synth.gui.controls import ParamControl

    QApplication.instance() or QApplication([])
    e, reg = make_engine()
    control = ParamControl(reg, reg["mod1_dst"], compact=True)
    combo = control.editor
    model = combo.model()
    headers = [model.item(r).text() for r in range(model.rowCount())
               if not model.item(r).flags() & Qt.ItemIsEnabled]
    assert headers.count("Noise") == 1
    assert headers.index("Noise") == headers.index("Osc 2") + 1


# ---- console --------------------------------------------------------------

def run_console(monkeypatch, engine, lines):
    import run

    it = iter(list(lines) + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
    run.console_loop(engine)


def test_console_noise(monkeypatch, capsys):
    e, _ = make_engine()
    run_console(monkeypatch, e, ["noise 0.4 pink"])
    assert e.params["noise_level"] == 0.4 and e.params["noise_color"] == "pink"
    run_console(monkeypatch, e, ["noise 0.2"])
    assert e.params["noise_level"] == 0.2 and e.params["noise_color"] == "pink"
    capsys.readouterr()
    run_console(monkeypatch, e, ["noise", "noise x", "noise 0.5 blue", "noise 1 2 3"])
    out = capsys.readouterr().out
    assert out.count("usage: noise") >= 3
    assert e.params["noise_level"] == 0.2 and e.params["noise_color"] == "pink"


def test_help_mentions_noise():
    import run
    assert "noise <" in run.HELP_TEXT


# ---- GUI ------------------------------------------------------------------

def test_gui_noise_group_and_layout():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QGroupBox

    from midi_synth.gui.controls import ParamControl
    from midi_synth.gui.main_window import GROUP_POSITIONS
    from tests.test_gui_window import _make_rig
    import tempfile
    import pathlib

    QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as d:
        _, reg, _, _, window = _make_rig(pathlib.Path(d), 2)
        assert "Noise" in GROUP_POSITIONS
        assert "noise_level" in window.controls and "noise_color" in window.controls
        hint = window.sizeHint()
        assert hint.width() <= 1700 and hint.height() <= 900
        window.resize(1700, 1000)
        window.show()
        QApplication.processEvents()
        box = next(b for b in window.findChildren(QGroupBox) if b.title() == "Noise")
        assert box.isAncestorOf(window.controls["noise_level"])
        assert box.isAncestorOf(window.controls["noise_color"])
        rects = [window.controls[k].geometry() for k in ("noise_level", "noise_color")]
        assert box.rect().contains(rects[0]) and box.rect().contains(rects[1])
        assert not rects[0].intersects(rects[1])
        # no two group boxes overlap
        boxes = [b for b in window.findChildren(QGroupBox)]
        tops = [(b.title(), b.mapTo(window, b.rect().topLeft()), b.size()) for b in boxes]
        from PySide6.QtCore import QRect
        qr = [(t, QRect(p, s)) for t, p, s in tops]
        for i in range(len(qr)):
            for j in range(i + 1, len(qr)):
                assert not qr[i][1].intersects(qr[j][1]), (qr[i][0], qr[j][0])
        window.close()


def test_bench_has_noise_case():
    import bench
    assert any("noise" in label for label, _ in bench.CASES)
