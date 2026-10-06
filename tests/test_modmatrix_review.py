"""Matrix review fixes: ramped tempo-synced delay, NaN guards, controller resets."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from midi_synth.engine import SynthEngine
from midi_synth.params import build_registry

SR, BLOCK = 44100, 256


def make_engine(**params):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=4)
    reg = build_registry(e)
    for k, v in params.items():
        reg.set(k, v)
    return e, reg


def row(e, slot, src, amt, dst):
    e.set_mod_src(slot, src)
    e.set_mod_amt(slot, amt)
    e.set_mod_dst(slot, dst)


# ---- tempo-synced delay glides -------------------------------------------

def _synced_tempo_lfo(division="1/8", scale=0.5):
    e, reg = make_engine(tempo_bpm=120.0, fx_delay_division=division)
    e.set_effect("delay", True)
    reg.set("fx_delay_sync", True)
    reg.set("lfo_rate", 3.0)
    row(e, 1, "LFO 1", scale, "Tempo")
    return e


def test_tempo_modulated_sync_uses_ramp_path():
    e = _synced_tempo_lfo()
    delay = e.effects.delay
    calls = {"jump": 0, "ramp": 0}
    jump, ramp = delay.set_time_ms, delay.set_time_target_ms

    def count_jump(ms):
        calls["jump"] += 1
        jump(ms)

    def count_ramp(ms):
        calls["ramp"] += 1
        ramp(ms)

    delay.set_time_ms, delay.set_time_target_ms = count_jump, count_ramp
    e.note_on(60, 100)
    for _ in range(100):
        e.render(BLOCK)
    assert calls["ramp"] > 10
    assert calls["jump"] == 0


def test_tempo_modulated_sync_lands_on_target():
    e, reg = make_engine(tempo_bpm=120.0, fx_delay_division="1/8")
    e.set_effect("delay", True)
    reg.set("fx_delay_sync", True)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, "Tempo")
    for _ in range(40):
        e.render(BLOCK)
    assert e.effects.delay.time_ms == pytest.approx(
        60000.0 / e.effective_bpm() * 0.5, abs=0.6)


def test_tempo_modulated_sync_is_continuous_audio():
    def run(ramped):
        e = _synced_tempo_lfo("1/4", 1.0)
        delay = e.effects.delay
        delay.mix, delay.feedback = 1.0, 0.0
        if not ramped:
            delay.set_time_target_ms = delay.set_time_ms   # the old stepped path
        real = e.effects.process
        t = [0]

        def sine_in(_):
            x = 0.5 * np.sin(2 * np.pi * 220.0 * (t[0] + np.arange(BLOCK)) / SR)
            t[0] += BLOCK
            return real(np.vstack([x, x]))

        e.effects.process = sine_in
        out = np.concatenate([e.render(BLOCK)[:, 0] for _ in range(100)])
        return np.abs(np.diff(out)).max()

    assert run(True) < 0.5 * run(False)


# ---- NaN guards -----------------------------------------------------------

@pytest.mark.parametrize("name", ["set_mod_wheel", "set_aftertouch"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_wheel_and_aftertouch_reject_non_finite(name, bad):
    e, _ = make_engine()
    row(e, 1, "Mod Wheel", 1.0, "Filter: Cutoff")
    row(e, 2, "Aftertouch", 1.0, "Filter: Resonance")
    getattr(e, name)(0.4)
    before = (e._mod_wheel, e._mod_at, e._wheel_s, e._at_s)
    with pytest.raises(ValueError):
        getattr(e, name)(bad)
    assert (e._mod_wheel, e._mod_at, e._wheel_s, e._at_s) == before
    e.note_on(60, 100)
    assert np.isfinite(e.render(BLOCK)).all()
    assert np.isfinite([e._wheel_s, e._at_s]).all()


# ---- controller resets ----------------------------------------------------

def _held(e):
    row(e, 1, "Mod Wheel", 0.5, "Filter: Cutoff")
    row(e, 2, "Aftertouch", 0.5, "Filter: Resonance")
    e.set_mod_wheel(0.8)
    e.set_aftertouch(0.6)
    e.note_on(60, 100)
    for _ in range(30):
        e.render(BLOCK)
    assert e._wheel_s > 0.5 and e._at_s > 0.4


def test_reset_controllers_zeroes_wheel_and_aftertouch():
    e, _ = make_engine()
    _held(e)
    e.reset_controllers()
    assert (e._mod_wheel, e._mod_at, e._wheel_s, e._at_s) == (0.0, 0.0, 0.0, 0.0)


def test_panic_zeroes_wheel_and_aftertouch():
    e, _ = make_engine()
    _held(e)
    e.panic()
    assert (e._mod_wheel, e._mod_at, e._wheel_s, e._at_s) == (0.0, 0.0, 0.0, 0.0)


def test_all_notes_off_clears_aftertouch_but_not_wheel():
    e, _ = make_engine()
    _held(e)
    wheel = e._mod_wheel, e._wheel_s
    e.all_notes_off()
    assert (e._mod_at, e._at_s) == (0.0, 0.0)
    assert (e._mod_wheel, e._wheel_s) == wheel


# ---- stale master-bus bypass ----------------------------------------------

def test_cleared_filter_row_resets_master_lpf_after_bypass():
    e, _ = make_engine(lpf_master=True, lpf_cutoff=12000.0)
    e.note_on(60, 100)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 1.0, "Filter: Cutoff")
    for _ in range(40):
        e.render(BLOCK)
    assert e._master_bypassed
    resets = []
    for f in (e.master_lpf, e.master_lpf_r):
        orig = f.reset
        f.reset = lambda orig=orig, f=f: (resets.append(f), orig())
    e.set_mod_row(1, "none", 0.0, "none")
    out = e.render(BLOCK)
    assert not e._master_bypassed
    assert e.master_lpf in resets and e.master_lpf_r in resets
    assert np.isfinite(out).all()
    assert np.isfinite([e.master_lpf.z1, e.master_lpf.z2]).all()


# ---- disabled delay snaps its target ---------------------------------------

def test_disabled_delay_target_snaps_instead_of_sweeping():
    e, _ = make_engine()
    delay = e.effects.delay
    assert not delay.enabled
    delay.set_time_ms(300.0)
    delay.set_time_target_ms(4000.0)
    assert delay.target_ms is None
    assert delay.time_ms == 4000.0
    e.set_effect("delay", True)
    delay.process(np.zeros((2, BLOCK)))
    assert delay.time_ms == 4000.0
    assert delay.time == pytest.approx(4000.0 * SR / 1000.0)


# ---- atomic row -------------------------------------------------------------

def test_set_mod_row_updates_all_three():
    e, _ = make_engine()
    e.set_mod_row(2, "Mod Wheel", 0.5, "Filter: Cutoff")
    assert e.mod_rows[1] == ["Mod Wheel", 0.5, "Filter: Cutoff"]
    e.set_mod_row("2", "none", 2.0, "none")
    assert e.mod_rows[1] == ["none", 1.0, "none"]


@pytest.mark.parametrize("args", [
    (9, "Mod Wheel", 0.5, "Filter: Cutoff"),
    (1, "bogus", 0.5, "Filter: Cutoff"),
    (1, "Mod Wheel", float("nan"), "Filter: Cutoff"),
    (1, "Mod Wheel", 0.5, "bogus"),
])
def test_set_mod_row_invalid_leaves_row_unchanged(args):
    e, _ = make_engine()
    e.set_mod_row(1, "LFO 1", 0.25, "Tempo")
    with pytest.raises(ValueError):
        e.set_mod_row(*args)
    assert e.mod_rows[0] == ["LFO 1", 0.25, "Tempo"]


def test_console_mod_uses_one_atomic_call():
    import run

    calls = []

    class Fake:
        def set_mod_row(self, *a):
            calls.append(a)

    run.mod_command(["mod", "1", "wheel", "50", "filter:", "cutoff"], Fake())
    run.mod_command(["mod", "clear", "3"], Fake())
    assert len(calls) == 2
    assert calls[-1] == (3, "none", 0.0, "none")


# ---- meter tick -------------------------------------------------------------

def test_meter_tick_reports_first_failure_once(tmp_path):
    from PySide6.QtWidgets import QApplication
    from tests.test_gui_window import _make_rig

    QApplication.instance() or QApplication([])
    engine, *_, window = _make_rig(tmp_path, 2)

    def boom():
        raise RuntimeError("meter broke")

    engine.take_meter = boom
    window._meter_tick()
    assert "meter broke" in window.statusBar().currentMessage()
    window.statusBar().showMessage("other")
    window._meter_tick()
    assert window.statusBar().currentMessage() == "other"
