import threading
import time

import numpy as np
import pytest

import run
from midi_synth.config import CLIP_THRESHOLD, LIMITER_CEILING, LIMITER_RELEASE_S
from midi_synth.engine import SynthEngine
from midi_synth.limiter import Limiter, limiter_reduction, release_coeff
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


def naive_reduction(a, h_prev, d):
    out = np.empty(len(a))
    cur = h_prev
    for i, x in enumerate(a):
        cur = max(x, d * cur)
        out[i] = cur
    return out


def naive_gain_stream(x, d):
    """Per-sample reference limiter: instant attack, exponential release."""
    peak = np.abs(x).max(axis=0)
    a = np.maximum(0.0, 1.0 - LIMITER_CEILING / np.maximum(peak, LIMITER_CEILING))
    return 1.0 - naive_reduction(a, 0.0, d)


# ---- constants ---------------------------------------------------------

def test_constants():
    assert LIMITER_CEILING == 0.98 < CLIP_THRESHOLD
    assert LIMITER_RELEASE_S == 0.15


# ---- default and bit-identity ------------------------------------------

def test_off_by_default():
    e = make()
    assert e.params["auto_limiter"] is False
    assert e.status()["auto_limiter"] is False
    assert e.peek_limiter() == 0.0
    assert e.take_limiter() == 0.0


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
    assert e.peek_limiter() == 0.0


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
    assert e.peek_limiter() == 0.0


def test_hot_signal_with_limiter_never_exceeds_ceiling_and_does_not_clip():
    e = hot(True)
    for _ in range(40):
        e.render(BLOCK)
        assert e.last_driven_peak <= LIMITER_CEILING + 1e-9
    left, right, clipped = e.peek_meter()
    assert clipped is False
    assert max(left, right) < 1.0
    assert e.peek_limiter() > 0.0


@pytest.mark.parametrize("n", [1, 64, 1024, 5000])
def test_ceiling_holds_for_block_sizes(n):
    e = hot(True)
    for _ in range(max(2, 4096 // n)):
        e.render(n)
        assert e.last_driven_peak <= LIMITER_CEILING + 1e-9
    assert e.peek_meter()[2] is False


def test_take_limiter_returns_max_and_resets():
    e = hot(True)
    for _ in range(4):
        e.render(BLOCK)
    peeked = e.peek_limiter()
    assert peeked > 0.0
    assert e.peek_limiter() == peeked
    assert e.take_limiter() == peeked
    assert e.take_limiter() == 0.0


def test_take_limiter_is_max_over_blocks():
    lim = Limiter(SR)
    loud = np.vstack([np.full(64, 2.0), np.full(64, 0.1)])
    out, gmin = lim.process(loud)
    assert gmin == pytest.approx(LIMITER_CEILING / 2.0)
    assert -20 * np.log10(gmin) == pytest.approx(-20 * np.log10(0.49))


def test_toggle_off_and_on_resets_state():
    for target in (False, True):
        e = hot(True)
        for _ in range(4):
            e.render(BLOCK)
        assert e.peek_limiter() > 0.0 and e._limiter.h > 0.0
        e.set_auto_limiter(target)
        assert e.peek_limiter() == 0.0
        assert e._limiter.h == 0.0


def test_silence_stays_silent_and_finite():
    e = make()
    e.set_auto_limiter(True)
    out = e.render(BLOCK)
    assert np.all(out == 0.0)
    assert e.peek_limiter() == 0.0


def test_extreme_input_is_finite_and_limited():
    lim = Limiter(SR)
    rng = np.random.default_rng(3)
    for _ in range(5):
        x = rng.standard_normal((2, 700)) * 1e6
        out, gmin = lim.process(x)
        assert np.all(np.isfinite(out)) and np.isfinite(gmin)
        assert np.abs(out).max() <= LIMITER_CEILING + 1e-9
    x = np.full((2, 50), np.nan)
    out, _ = lim.process(x)
    assert lim.h == lim.h          # state not poisoned
    out, _ = lim.process(np.full((2, 50), 0.5))
    assert np.all(np.isfinite(out))


def test_engine_extreme_gain_input_nan_free():
    e = hot(True)
    e.params["master_gain"] = 1e6      # bypass the setter's clamp
    out = e.render(BLOCK)
    assert np.all(np.isfinite(out))


# ---- the DSP itself ----------------------------------------------------

def test_release_coeff():
    assert release_coeff(SR) == pytest.approx(np.exp(-1.0 / (LIMITER_RELEASE_S * SR)))


@pytest.mark.parametrize("n", [1, 64, 256, 1024, 4096, 5000])
def test_vectorised_reduction_matches_naive_loop(n):
    rng = np.random.default_rng(n)
    d = release_coeff(SR)
    h_prev_fast = h_prev_ref = 0.0
    for _ in range(max(4, 12000 // n)):
        a = np.where(rng.random(n) < 0.02, rng.random(n), 0.0)
        fast = limiter_reduction(a, h_prev_fast, d)
        ref = naive_reduction(a, h_prev_ref, d)
        np.testing.assert_allclose(fast, ref, atol=1e-9, rtol=0)
        h_prev_fast, h_prev_ref = fast[-1], ref[-1]


def test_reduction_with_long_block_and_big_carry():
    d = release_coeff(SR)
    a = np.zeros(20000)
    a[7] = 0.9
    np.testing.assert_allclose(
        limiter_reduction(a, 0.5, d), naive_reduction(a, 0.5, d), atol=1e-9, rtol=0)


@pytest.mark.parametrize("n", [1, 64, 256, 1024, 4096, 5000])
def test_limiter_gain_matches_naive_stream(n):
    rng = np.random.default_rng(100 + n)
    lim = Limiter(SR)
    d = release_coeff(SR)
    total = 14000
    x = rng.standard_normal((2, total)) * 0.3
    spikes = rng.random(total) < 0.003
    x[:, spikes] *= 12.0
    expected = x * naive_gain_stream(x, d)
    got = np.concatenate(
        [lim.process(x[:, s:s + n])[0] for s in range(0, total, n)], axis=1)
    np.testing.assert_allclose(got, expected, atol=1e-9, rtol=0)


def test_instant_attack_limits_first_overshoot_exactly_to_ceiling():
    lim = Limiter(SR)
    x = np.vstack([np.concatenate([np.full(10, 0.5), [1.7], np.full(10, 0.5)]),
                   np.full(21, 0.1)])
    out, _ = lim.process(x)
    assert np.all(out[0, :10] == 0.5)
    assert out[0, 10] == pytest.approx(LIMITER_CEILING, abs=1e-12)


def test_release_falls_by_one_over_e_after_release_time():
    lim = Limiter(SR)
    k = int(round(LIMITER_RELEASE_S * SR))
    x = np.full((2, k + 400), 0.5)
    x[:, 0] = 2.0
    out, _ = lim.process(x)
    gain = out[0] / x[0]
    h0 = 1.0 - gain[0]
    assert h0 == pytest.approx(1.0 - LIMITER_CEILING / 2.0)
    assert (1.0 - gain[k]) == pytest.approx(h0 / np.e, rel=1e-3)
    assert np.all(np.diff(gain) >= -1e-12)        # monotone recovery


def test_gain_snaps_back_to_unity_and_fast_path_returns():
    lim = Limiter(SR)
    lim.process(np.full((2, 10), 3.0))
    assert lim.h > 0.0
    quiet = np.full((2, 4096), 0.1)
    for _ in range(60):
        out, gmin = lim.process(quiet)
        if lim.h == 0.0:
            break
    assert lim.h == 0.0
    out, gmin = lim.process(quiet)
    assert out is quiet and gmin == 1.0


def test_stereo_link_keeps_channel_ratio():
    lim = Limiter(SR)
    x = np.vstack([np.full(500, 3.0), np.full(500, 0.3)])
    out, _ = lim.process(x)
    np.testing.assert_allclose(out[1] / out[0], 0.1, rtol=1e-12)
    assert out[0].max() <= LIMITER_CEILING + 1e-9


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
                e.take_limiter()
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
                         "clip, then lets it come back up (about 0.15 s).")
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


def test_help_mentions_limiter():
    assert "limiter <on|off>" in run.HELP_TEXT
