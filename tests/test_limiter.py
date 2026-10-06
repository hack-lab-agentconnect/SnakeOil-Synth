import threading
import time

import numpy as np
import pytest

import run
from midi_synth.config import (
    CLIP_THRESHOLD, LIMITER_CEILING, LIMITER_SILENCE_S, LIMITER_SILENCE_THRESHOLD)
from midi_synth.engine import SynthEngine
from midi_synth.limiter import Limiter
from midi_synth.params import TOGGLE, build_registry

SR = 44100
BLOCK = 256
HOT_NOTES = (48, 55, 60, 64, 67, 72)


def make(voices=8):
    return SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices)


def hot(limiter, voices=8):
    e = make(voices)
    e.set_auto_limiter(limiter)
    e.set_osc_levels(1.0, 1.0)
    e.set_master_gain(1.5)
    for note in HOT_NOTES:
        e.note_on(note, 127)
    return e


def naive_hold_stream(x, h0=0.0):
    """Per-sample reference limiter: instant attack, hold (cumulative max)."""
    peak = np.abs(x).max(axis=0)
    h = h0
    gain = np.empty(len(peak))
    for i, pk in enumerate(peak):
        a = 1.0 - min(1.0, LIMITER_CEILING / pk) if pk > 0 else 0.0
        h = max(h, a)
        gain[i] = 1.0 - h
    return gain


def burst(level=3.0, n=64):
    return np.full((2, n), level)


def tone(level=0.05, n=BLOCK):
    return np.full((2, n), level)


# ---- constants ---------------------------------------------------------

def test_constants():
    assert LIMITER_CEILING == 0.98 < CLIP_THRESHOLD
    assert LIMITER_SILENCE_THRESHOLD == 0.001
    assert LIMITER_SILENCE_S == 0.5
    import midi_synth.config as config
    import midi_synth.limiter as limiter_mod
    assert not hasattr(config, "LIMITER_RELEASE_S")
    assert not hasattr(limiter_mod, "release_coeff")
    assert not hasattr(limiter_mod, "limiter_reduction")


# ---- default and bit-identity ------------------------------------------

def test_off_by_default():
    e = make()
    assert e.params["auto_limiter"] is False
    assert e.status()["auto_limiter"] is False
    assert e.limiter_reduction_db() == 0.0
    assert not hasattr(e, "take_limiter") and not hasattr(e, "peek_limiter")


def test_setter_coerces_to_bool():
    e = make()
    e.set_auto_limiter(1)
    assert e.params["auto_limiter"] is True
    e.set_auto_limiter(0)
    assert e.params["auto_limiter"] is False


def render_quiet(limiter):
    e = make()
    e.set_auto_limiter(limiter)
    e.set_master_gain(0.2)
    e.note_on(60, 90)
    return np.concatenate([e.render(BLOCK) for _ in range(6)]), e


def test_quiet_signal_bit_identical_with_limiter_on():
    off, _ = render_quiet(False)
    on, e = render_quiet(True)
    assert np.array_equal(off, on)
    assert e.limiter_reduction_db() == 0.0


def test_fast_path_returns_input_object():
    lim = Limiter(SR)
    quiet = tone(0.5, 1000)
    out, peak = lim.process(quiet)
    assert out is quiet and peak == 0.5


def test_hot_signal_changes_only_when_limiter_on():
    def tail(e):
        return [e.render(BLOCK) for _ in range(6)][-1]

    assert np.array_equal(tail(hot(False)), tail(hot(False)))
    assert not np.array_equal(tail(hot(False)), tail(hot(True)))


# ---- engine behaviour on a hot signal ---------------------------------

def test_hot_signal_without_limiter_exceeds_and_clips():
    e = hot(False)
    peaks = []
    for _ in range(6):
        e.render(BLOCK)
        peaks.append(e.last_driven_peak)
    assert max(peaks) > 1.0
    assert e.peek_meter()[2] is True
    assert e.limiter_reduction_db() == 0.0


def test_hot_signal_with_limiter_never_exceeds_ceiling_and_does_not_clip():
    e = hot(True)
    for _ in range(40):
        e.render(BLOCK)
        assert e.last_driven_peak <= LIMITER_CEILING + 1e-9
    left, right, clipped = e.peek_meter()
    assert clipped is False
    assert max(left, right) < 1.0
    assert e.limiter_reduction_db() > 0.0


@pytest.mark.parametrize("n", [1, 64, 1024, 5000])
def test_ceiling_holds_for_block_sizes(n):
    e = hot(True)
    for _ in range(max(2, 4096 // n)):
        e.render(n)
        assert e.last_driven_peak <= LIMITER_CEILING + 1e-9
    assert e.peek_meter()[2] is False


def test_reduction_db_is_the_held_value_and_stable():
    e = make()
    e.set_auto_limiter(True)
    e._run_limiter(burst(2.0))
    expected = -20 * np.log10(LIMITER_CEILING / 2.0)
    assert e.limiter_reduction_db() == pytest.approx(expected)
    assert e.limiter_reduction_db() == e.limiter_reduction_db()
    e._run_limiter(tone(0.05))
    assert e.limiter_reduction_db() == pytest.approx(expected)


def test_reduction_db_zero_when_off_even_if_held():
    e = make()
    e.set_auto_limiter(True)
    e._run_limiter(burst(2.0))
    e.params["auto_limiter"] = False
    assert e.limiter_reduction_db() == 0.0


def test_toggle_off_and_on_resets_state():
    for target in (False, True):
        e = hot(True)
        for _ in range(4):
            e.render(BLOCK)
        assert e.limiter_reduction_db() > 0.0 and e._limiter.h > 0.0
        e._limiter_silent_s = 0.3
        e.set_auto_limiter(target)
        assert e.limiter_reduction_db() == 0.0
        assert e._limiter.h == 0.0
        assert e._limiter_silent_s == 0.0


def test_silence_stays_silent_and_finite():
    e = make()
    e.set_auto_limiter(True)
    out = e.render(BLOCK)
    assert np.all(out == 0.0)
    assert e.limiter_reduction_db() == 0.0


def test_extreme_input_is_finite_and_limited():
    lim = Limiter(SR)
    rng = np.random.default_rng(3)
    for _ in range(5):
        x = rng.standard_normal((2, 700)) * 1e6
        out, _ = lim.process(x)
        assert np.all(np.isfinite(out))
        assert np.abs(out).max() <= LIMITER_CEILING + 1e-9
    h = lim.h
    out, _ = lim.process(np.full((2, 50), np.nan))
    assert lim.h == h and lim.h == lim.h          # state not poisoned
    out, _ = lim.process(np.full((2, 50), 0.5))
    assert np.all(np.isfinite(out))


def test_engine_extreme_gain_input_nan_free():
    e = hot(True)
    e.params["master_gain"] = 1e6      # bypass the setter's clamp
    out = e.render(BLOCK)
    assert np.all(np.isfinite(out))


# ---- the DSP itself: hold ------------------------------------------------

@pytest.mark.parametrize("n", [1, 64, 256, 1024, 4096, 5000])
def test_limiter_gain_matches_naive_stream(n):
    rng = np.random.default_rng(100 + n)
    lim = Limiter(SR)
    total = 14000
    x = rng.standard_normal((2, total)) * 0.3
    spikes = rng.random(total) < 0.003
    x[:, spikes] *= 12.0
    expected = x * naive_hold_stream(x)
    got = np.concatenate(
        [lim.process(x[:, s:s + n])[0] for s in range(0, total, n)], axis=1)
    np.testing.assert_allclose(got, expected, atol=1e-12, rtol=0)
    assert np.abs(got).max() <= LIMITER_CEILING + 1e-9


def test_reduction_holds_after_burst_while_quiet_tone_plays_5s():
    lim = Limiter(SR)
    lim.process(burst(2.0, 100))
    h = 1.0 - LIMITER_CEILING / 2.0
    assert lim.h == pytest.approx(h)
    quiet = tone(0.05, 4410)
    for _ in range(50):                      # 5 s
        out, _ = lim.process(quiet)
        np.testing.assert_allclose(out, quiet * (1.0 - h), rtol=1e-12, atol=0)
        assert lim.h == pytest.approx(h)


def test_louder_burst_deepens_quieter_burst_does_not():
    lim = Limiter(SR)
    lim.process(burst(2.0))
    h1 = lim.h
    lim.process(burst(1.5))
    assert lim.h == h1
    lim.process(burst(4.0))
    assert lim.h == pytest.approx(1.0 - LIMITER_CEILING / 4.0)
    assert lim.h > h1


def test_instant_attack_limits_first_overshoot_exactly_to_ceiling():
    lim = Limiter(SR)
    x = np.vstack([np.concatenate([np.full(10, 0.5), [1.7], np.full(10, 0.5)]),
                   np.full(21, 0.1)])
    out, _ = lim.process(x)
    assert np.all(out[0, :10] == 0.5)
    assert out[0, 10] == pytest.approx(LIMITER_CEILING, abs=1e-12)
    assert out[0, 11:] == pytest.approx(0.5 * LIMITER_CEILING / 1.7)


def test_stereo_link_keeps_channel_ratio():
    lim = Limiter(SR)
    x = np.vstack([np.full(500, 3.0), np.full(500, 0.3)])
    out, _ = lim.process(x)
    np.testing.assert_allclose(out[1] / out[0], 0.1, rtol=1e-12)
    assert out[0].max() <= LIMITER_CEILING + 1e-9


def test_reset_clears_hold():
    lim = Limiter(SR)
    lim.process(burst(3.0))
    lim.reset()
    assert lim.h == 0.0
    quiet = tone(0.5, 100)
    assert lim.process(quiet)[0] is quiet


# ---- silence reset ---------------------------------------------------------

def held_engine():
    e = make()
    e.set_auto_limiter(True)
    e._run_limiter(burst(3.0))
    assert e._limiter.h > 0.0
    return e


def silent_block(n):
    return np.full((2, n), 1e-4)


def test_silence_for_half_a_second_resets():
    e = held_engine()
    for _ in range(int(0.5 * SR / BLOCK) + 1):
        e._run_limiter(silent_block(BLOCK))
    assert e._limiter.h == 0.0
    assert e.limiter_reduction_db() == 0.0
    assert e._limiter_silent_s == 0.0


def test_short_silence_does_not_reset_and_signal_restarts_the_timer():
    e = held_engine()
    for _ in range(int(0.4 * SR / BLOCK)):
        e._run_limiter(silent_block(BLOCK))
    assert e._limiter.h > 0.0
    e._run_limiter(tone(0.002))
    assert e._limiter_silent_s == 0.0
    for _ in range(int(0.4 * SR / BLOCK)):
        e._run_limiter(silent_block(BLOCK))
    assert e._limiter.h > 0.0                       # 0.8 s total but not contiguous
    for _ in range(int(0.2 * SR / BLOCK) + 2):
        e._run_limiter(silent_block(BLOCK))
    assert e._limiter.h == 0.0


def test_threshold_is_inclusive_signal_at_threshold_is_not_silence():
    e = held_engine()
    for _ in range(int(1.0 * SR / BLOCK)):
        e._run_limiter(tone(LIMITER_SILENCE_THRESHOLD))
    assert e._limiter.h > 0.0


def test_timer_counts_input_peak_not_limited_output():
    e = held_engine()
    e._limiter.h = 0.99                              # output = input * 0.01
    quiet = tone(0.05)                               # input above, output 0.0005 below
    out = e._run_limiter(quiet)
    assert np.abs(out).max() < LIMITER_SILENCE_THRESHOLD
    for _ in range(int(2.0 * SR / BLOCK)):
        e._run_limiter(quiet)
    assert e._limiter.h == pytest.approx(0.99)


def test_effect_tail_counts_as_audio():
    def tail_run(limiter_on):
        e = make()
        e.set_effect("reverb", True)
        e.set_osc_levels(1.0, 1.0)
        e.set_master_gain(1.5)
        for note in HOT_NOTES:
            e.note_on(note, 127)
        for _ in range(20):
            e.render(BLOCK)
        e.panic()                                    # voices off, tail rings on
        e.set_auto_limiter(limiter_on)
        if limiter_on:
            e._limiter.h = 0.5
        peaks = []
        for _ in range(int(0.6 * SR / BLOCK)):
            e.render(BLOCK)
            peaks.append(e.last_driven_peak)
        return e, peaks

    _, off_peaks = tail_run(False)
    assert min(off_peaks) > LIMITER_SILENCE_THRESHOLD    # the tail really is audible
    e, _ = tail_run(True)
    assert e._limiter.h > 0.0


def test_reduction_does_not_jump_up_during_a_decaying_tail():
    e = held_engine()
    h = e._limiter.h
    for k in range(100):
        e._run_limiter(tone(0.5 * 0.95 ** k, 441))
    assert e._limiter.h == pytest.approx(h)


# ---- manual reset, panic -----------------------------------------------------

def test_reset_limiter_clears_everything():
    e = held_engine()
    e._limiter_silent_s = 0.3
    e.reset_limiter()
    assert e._limiter.h == 0.0 and e._limiter_silent_s == 0.0
    assert e.limiter_reduction_db() == 0.0
    assert e.params["auto_limiter"] is True


def test_panic_resets_limiter():
    e = held_engine()
    e.panic()
    assert e._limiter.h == 0.0 and e.limiter_reduction_db() == 0.0


def test_reset_limiter_takes_the_lock():
    e = held_engine()
    done = threading.Event()

    def worker():
        e.reset_limiter()
        done.set()

    with e.lock:
        t = threading.Thread(target=worker)
        t.start()
        assert not done.wait(0.2)
    t.join(2)
    assert done.is_set()


# ---- thread safety ------------------------------------------------------

def test_render_while_toggling_smoke():
    e = hot(True)
    errors = []
    stop = threading.Event()

    def renderer():
        try:
            while not stop.is_set():
                out = e.render(BLOCK)
                assert np.all(np.isfinite(out))
        except Exception as exc:       # pragma: no cover
            errors.append(exc)

    def toggler():
        try:
            on = False
            while not stop.is_set():
                e.set_auto_limiter(on)
                e.reset_limiter()
                e.limiter_reduction_db()
                on = not on
        except Exception as exc:       # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=renderer), threading.Thread(target=toggler)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    stop.set()
    for t in threads:
        t.join()
    assert errors == []


# ---- registry, console ---------------------------------------------------

def test_registry_entry_and_order():
    e = make()
    reg = build_registry(e)
    p = reg["auto_limiter"]
    assert p.kind == TOGGLE and p.group == "Master" and p.label == "Auto Limiter"
    assert p.tooltip == ("Automatically turns the volume down when the signal would "
                         "clip and holds it there until silence, a patch change or a reset.")
    master = [q.id for q in reg if q.group == "Master"]
    assert master == ["master_gain", "velocity_on", "auto_limiter"]
    assert reg.get("auto_limiter") is False
    reg.set("auto_limiter", True)
    assert e.params["auto_limiter"] is True


def run_console(monkeypatch, capsys, lines, **kwargs):
    import builtins
    feed = iter(lines + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    run.console_loop(**kwargs)
    return capsys.readouterr().out


def test_console_limiter_command(monkeypatch, capsys):
    e = make()
    run_console(monkeypatch, capsys, ["limiter on"], engine=e)
    assert e.params["auto_limiter"] is True
    run_console(monkeypatch, capsys, ["limiter off"], engine=e)
    assert e.params["auto_limiter"] is False
    out = run_console(monkeypatch, capsys, ["limiter", "limiter maybe"], engine=e)
    assert out.count("usage: limiter") == 2
    assert e.params["auto_limiter"] is False


def test_console_limiter_reset(monkeypatch, capsys):
    e = held_engine()
    run_console(monkeypatch, capsys, ["limiter reset"], engine=e)
    assert e._limiter.h == 0.0
    assert e.params["auto_limiter"] is True


def test_help_mentions_limiter():
    assert "limiter <on|off>" in run.HELP_TEXT
    assert "limiter reset" in run.HELP_TEXT


# ---- patch-change reset ---------------------------------------------------------

def reg_with_held():
    e = held_engine()
    return e, build_registry(e)


def test_registry_patch_hook_calls_listeners_and_swallows_errors():
    reg = build_registry(make())
    calls = []

    def bad():
        raise RuntimeError("boom")

    reg.add_patch_listener(bad)
    reg.add_patch_listener(lambda: calls.append(1))
    reg.patch_applied()
    assert calls == [1]


def test_apply_triggers_patch_hook_once_even_with_warnings():
    from midi_synth.patches import apply, capture
    e, reg = reg_with_held()
    calls = []
    reg.add_patch_listener(lambda: calls.append(1))
    warnings = apply(reg, {"nope": 1}, capture(reg))
    assert warnings and calls == [1]


def test_apply_resets_the_limiter_and_a_failing_listener_does_not_break_it():
    from midi_synth.patches import apply, capture
    e, reg = reg_with_held()
    reg.add_patch_listener(lambda: 1 / 0)
    assert apply(reg, {"osc1_level": 0.3}, capture(reg)) == []
    assert e._limiter.h == 0.0 and e.params["auto_limiter"] is True
    assert e.params["osc1_level"] == pytest.approx(0.3)


def test_patch_hook_runs_after_params_are_applied():
    from midi_synth.patches import apply, capture
    e, reg = reg_with_held()
    seen = []
    reg.add_patch_listener(lambda: seen.append(e.params["osc1_level"]))
    apply(reg, {"osc1_level": 0.31}, capture(reg))
    assert seen == [pytest.approx(0.31)]


def test_console_patch_load_resets_limiter(monkeypatch, capsys, tmp_path):
    from midi_synth.patches import PatchStore, capture
    e, reg = reg_with_held()
    store = PatchStore(tmp_path)
    defaults = capture(reg)
    store.ensure_init(defaults)
    run_console(monkeypatch, capsys, ["patch load Init"], engine=e, registry=reg,
                patch_store=store, patch_defaults=defaults)
    assert e._limiter.h == 0.0


def test_startup_patch_resets_limiter(tmp_path):
    from midi_synth.patches import PatchStore, capture
    e, reg = reg_with_held()
    store = PatchStore(tmp_path)
    defaults = capture(reg)
    store.ensure_init(defaults)
    run.load_startup_patch(reg, store, defaults, "Init")
    assert e._limiter.h == 0.0
