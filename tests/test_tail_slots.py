"""Hybrid voice engine: playable voices plus tail slots with forced short releases."""
import threading

import numpy as np
import pytest

from midi_synth.config import FORCED_RELEASE_S
from midi_synth.engine import SynthEngine
from midi_synth.voice import ATTACK, IDLE, RELEASE, Envelope, Voice

SR, BLOCK = 44100, 256


def make(width=1, voices=12, tails=6, capacity=12, **setup):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices,
                    tail_slots=tails, tail_capacity=capacity)
    e.set_unison_voices(width)
    for k, v in setup.items():
        getattr(e, "set_" + k)(v)
    return e


def gated(e, note=None):
    return [v for v in e.voices if v.gate and (note is None or v.note == note)]


def render(e, blocks=1):
    out = None
    for _ in range(blocks):
        out = e.render(BLOCK)
    return out


# ---- (a) classic mode ------------------------------------------------------

def test_defaults_are_classic():
    e = SynthEngine(sr=SR, block_size=BLOCK)
    assert e.tail_slots == 0 and len(e.voices) == e.max_voices == 12
    assert e.forced_releases == 0


def test_pool_size_follows_capacity_not_slots():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=12, tail_slots=2,
                    tail_capacity=12)
    assert len(e.voices) == 24 and e.tail_slots == 2
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=12, tail_slots=6)
    assert len(e.voices) == 18 and e.tail_slots == 6
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=12, tail_slots=20,
                    tail_capacity=12)
    assert e.tail_slots == 12


def _drive(e):
    log = []
    for i in range(40):
        e.note_on(40 + (i * 5) % 30, 100)
        if i % 3 == 0:
            e.note_off(40 + ((i - 3) * 5) % 30)
        render(e, 3)
        log.append((e.steal_count, e.active_note_count(),
                    tuple(sorted(v.note for v in e.voices if v.active))))
    return log, render(e)


@pytest.mark.parametrize("width", [1, 2])
def test_classic_with_capacity_matches_plain_engine(width):
    plain = SynthEngine(sr=SR, block_size=BLOCK, max_voices=6)
    ext = SynthEngine(sr=SR, block_size=BLOCK, max_voices=6, tail_slots=0,
                      tail_capacity=12)
    for e in (plain, ext):
        e.set_unison_voices(width)
        e.set_amp_release(1.0)
    la, oa = _drive(plain)
    lb, ob = _drive(ext)
    assert la == lb
    assert np.array_equal(oa, ob)
    assert all(not v.active for v in ext.voices[6:])


# ---- (c) forced release -----------------------------------------------------

def test_constant():
    assert FORCED_RELEASE_S == 0.010


def test_force_release_method():
    v = Voice(SR)
    v.note_on(60, 1.0, 1)
    v.force_release()
    assert v.gate is False and v.env.stage == RELEASE
    assert v.env.release_override == FORCED_RELEASE_S
    assert v.flt_env.stage == RELEASE
    v2 = Voice(SR)
    v2.note_on(60, 1.0, 1)
    v2.force_release(0.5)
    assert v2.env.release_override == 0.5


def test_over_limit_force_releases_oldest_single():
    e = make(1, voices=12)
    for i in range(12):
        e.note_on(48 + i, 100)
    render(e, 2)
    oldest = [v for v in e.voices if v.note == 48][0]
    e.note_on(70, 100)
    assert oldest.gate is False
    assert oldest.env.release_override == FORCED_RELEASE_S
    assert e.forced_releases == 1 and e.steal_count == 0
    new = gated(e, 70)
    assert len(new) == 1 and new[0] is not oldest
    assert e.gated_count() == 12 and e.tail_count() == 1
    assert e.active_note_count() == 13


def test_forced_release_fades_linearly_to_zero_in_10ms():
    e = make(1, voices=3, tails=2, capacity=2)
    for n in (60, 62, 64):
        e.note_on(n, 100)
    render(e, 40)  # into sustain
    victim = [v for v in e.voices if v.note == 60][0]
    outs = []
    orig = Envelope.process

    def spy(self, n):
        out = orig(self, n)
        if self is victim.env:
            outs.append(out.copy())
        return out

    Envelope.process = spy
    try:
        e.note_on(70, 100)
        blocks = int(np.ceil(FORCED_RELEASE_S * SR / BLOCK)) + 1
        render(e, blocks)
    finally:
        Envelope.process = orig
    assert victim.env.stage == IDLE and not victim.active
    env = np.concatenate(outs)
    assert env[-1] == 0.0
    start = 0.75
    tail = env[env > 0.0]
    steps = np.diff(np.concatenate([[start], tail]))
    assert np.all(steps < 0)
    assert np.allclose(steps[:-1], steps[0], rtol=1e-6)
    assert len(tail) <= int(FORCED_RELEASE_S * SR) + 2
    assert abs(steps).max() <= 1.0 / (FORCED_RELEASE_S * SR) * 1.0001


def test_unison_group_force_released_whole():
    e = make(2, voices=4)
    e.note_on(60, 100)
    e.note_on(62, 100)
    e.note_on(64, 100)
    assert e.steal_count == 0 and e.forced_releases == 2
    old = [v for v in e.voices if v.note == 60]
    assert len(old) == 2 and all(not v.gate for v in old)
    assert all(v.env.release_override == FORCED_RELEASE_S for v in old)
    assert len(gated(e, 64)) == 2 and len(gated(e, 62)) == 2
    assert e.gated_count() == 4


def test_sustained_voice_is_not_retriggered_in_normal_use():
    e = make(1, voices=2, tails=2, capacity=2)
    e.note_on(60, 100)
    e.note_on(62, 100)
    render(e, 5)
    snap = {v.note: (v.osc1.phase, v.env.level) for v in e.voices}
    e.note_on(64, 100)
    new = gated(e, 64)[0]
    assert new.note == 64
    assert snap[62][0] == [v for v in e.voices if v.note == 62][0].osc1.phase


# ---- (d) active-cap exhaustion ---------------------------------------------

def test_cap_exhaustion_steals_quietest_tails_continuously():
    e = make(1, voices=4, tails=2, capacity=2, amp_release=5.0)
    for n in range(60, 64):
        e.note_on(n, 100)
    render(e, 3)
    for n in range(60, 64):
        e.note_off(n)
    render(e, 3)
    assert e.tail_count() == 4  # above the slot count: gated slots unused
    for n in range(70, 78):
        e.note_on(n, 100)
        out = render(e, 2)
        assert np.isfinite(out).all()
    assert e.steal_count > 0
    assert e.active_note_count() <= 4 + 2
    assert e.forced_releases >= 2


def test_steal_prefers_not_force_released_voices():
    e = make(1, voices=2, tails=1, capacity=1, amp_release=5.0)
    e.note_on(60, 100)
    e.note_on(62, 100)
    render(e, 2)
    e.note_off(60)          # a tail: uses the one tail slot
    render(e, 2)
    e.note_on(64, 100)      # gated 62, 64; tail 60 -> active 3 == cap
    assert e.steal_count == 0
    e.note_on(66, 100)      # force-release 62, steal tail 60 (not 62)
    assert e.forced_releases == 1
    assert e.steal_count == 1
    forced = [v for v in e.voices if v.note == 62][0]
    assert forced.env.release_override == FORCED_RELEASE_S
    assert not [v for v in e.voices if v.note == 60]


def test_no_exceptions_under_random_play():
    rng = np.random.default_rng(3)
    e = make(2, voices=6, tails=3, capacity=6, amp_release=2.0)
    held = []
    for _ in range(400):
        if held and rng.random() < 0.4:
            e.note_off(held.pop(int(rng.integers(len(held)))))
        else:
            n = int(rng.integers(36, 84))
            held.append(n)
            e.note_on(n, 100)
        out = render(e)
        assert np.isfinite(out).all()
        assert e.gated_count() <= 6
        assert e.active_note_count() <= 6 + 3 + 1


# ---- (e) API ----------------------------------------------------------------

def test_set_tail_slots_clamps_and_validates():
    e = make(tails=6, capacity=12)
    assert e.set_tail_slots(12) == 12 and e.tail_slots == 12
    assert e.set_tail_slots(99) == 12
    assert e.set_tail_slots(-3) == 0 and e.tail_slots == 0
    assert e.set_tail_slots(4.0) == 4
    for bad in ("x", None, float("nan"), 2.5):
        with pytest.raises(ValueError):
            e.set_tail_slots(bad)
    assert e.tail_slots == 4
    noextra = SynthEngine(sr=SR, block_size=BLOCK, max_voices=4)
    assert noextra.set_tail_slots(6) == 0


def test_set_tail_slots_does_not_cut_sounding_voices():
    e = make(tails=6, amp_release=3.0)
    for n in (60, 62, 64):
        e.note_on(n, 100)
    render(e, 2)
    for n in (60, 62, 64):
        e.note_off(n)
    render(e, 2)
    e.set_tail_slots(0)
    assert e.tail_count() == 3 and e.active_note_count() == 3


def test_status_fields_and_counts():
    e = make(1, voices=3, tails=2, capacity=4)
    s = e.status()
    assert (s["tail_slots"], s["tails_active"], s["gated_voices"],
            s["forced_releases"]) == (2, 0, 0, 0)
    for n in (60, 62, 64):
        e.note_on(n, 100)
    e.note_off(60)
    e.note_on(66, 100)
    s = e.status()
    assert s["gated_voices"] == 3 and s["tails_active"] == 1
    assert e.gated_count() == 3 and e.tail_count() == 1
    e.note_on(68, 100)
    assert e.status()["forced_releases"] == 1


def test_sustain_pedal_notes_count_as_gated_and_release_later():
    e = make(1, voices=3, tails=2, capacity=4)
    e.set_sustain(True)
    for n in (60, 62, 64):
        e.note_on(n, 100)
    for n in (60, 62, 64):
        e.note_off(n)
    assert e.gated_count() == 3
    e.note_on(66, 100)   # force-releases the oldest pedal-held note
    assert e.forced_releases == 1 and e.gated_count() == 3
    render(e, 3)
    e.set_sustain(False)
    assert [v.note for v in gated(e)] == [66]
    assert e.tail_count() >= 2
    assert e._sustained == set()


def test_all_notes_off_and_panic_with_tails():
    e = make(1, voices=3, tails=2, capacity=4, amp_release=2.0)
    for n in (60, 62, 64, 66):
        e.note_on(n, 100)
    render(e, 2)
    e.all_notes_off()
    assert e.gated_count() == 0
    render(e, 2)
    assert e.tail_count() >= 3
    e.panic()
    assert e.active_note_count() == 0 and e.tail_count() == 0
    e.note_on(70, 100)
    assert e.gated_count() == 1
    assert np.isfinite(render(e)).all()


def test_stale_override_cleared_after_panic_and_note_on():
    e = make(1, voices=1, tails=1, capacity=1)
    e.note_on(60, 100)
    e.note_on(62, 100)
    e.panic()
    e.note_on(64, 100)
    assert all(v.env.release_override is None for v in gated(e))


# ---- (f) envelope override ---------------------------------------------------

def test_envelope_override_linear_fade():
    env = Envelope(SR, sustain=1.0, release=5.0)
    env.note_on()
    env.process(5000)
    env.note_off(release_s=0.010)
    assert env.release_override == 0.010
    out = env.process(1000)
    n = int(0.010 * SR)
    assert out[n - 1] > 0.0 and out[n] == 0.0 or out[n - 1] == 0.0
    assert env.stage == IDLE and env.release_override is None
    assert np.allclose(np.diff(out[:n - 1]), -1.0 / (0.010 * SR), rtol=1e-6)


def test_envelope_override_cleared_by_note_on():
    env = Envelope(SR)
    env.note_on()
    env.process(100)
    env.note_off(release_s=0.01)
    env.note_on()
    assert env.release_override is None and env.stage == ATTACK


def test_envelope_override_survives_set_shape_and_plain_note_off():
    env = Envelope(SR)
    env.note_on()
    env.process(100)
    env.note_off(release_s=0.01)
    env.set_shape(0.1, 0.1, 0.5, 9.0)
    env.note_off()
    assert env.release_override == 0.01
    env.process(int(0.01 * SR) + 5)
    assert env.stage == IDLE


def test_envelope_default_unchanged():
    env = Envelope(SR)
    assert env.release_override is None
    env.note_on()
    env.process(5000)
    env.note_off()
    out = env.process(10)
    assert np.allclose(np.diff(out), -1.0 / (env.release * SR))


def test_note_off_on_idle_envelope_ignores_override():
    env = Envelope(SR)
    env.note_off(release_s=0.01)
    assert env.stage == IDLE and env.release_override is None


# ---- (b) the repro scenario --------------------------------------------------

def _scenario(monkeypatch, tails, capacity=12, release=0.6, steps_n=60, interval=0.110):
    if tails is None:
        e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=12)
    else:
        e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=12,
                        tail_slots=tails, tail_capacity=capacity)
    e.set_unison_voices(2)
    e.set_amp_release(release)
    e.set_lpf_cutoff(600)
    last, jumps, pending = {}, [], {}
    orig_render, orig_on = Voice.render, Voice.note_on

    def r(self, n, params):
        out = orig_render(self, n, params)
        if self in pending:
            jumps.append(abs(out[0] - pending.pop(self)))
        last[self] = out[-1]
        return out

    def on(self, *a, **k):
        if self.active and self in last:
            pending[self] = last[self]
        return orig_on(self, *a, **k)

    monkeypatch.setattr(Voice, "render", r)
    monkeypatch.setattr(Voice, "note_on", on)
    held = [48, 52, 55, 59, 62]
    for n in held:
        e.note_on(n, 100)
    render(e)
    per = round(interval * SR / BLOCK)
    for i in range(steps_n):
        e.note_off(held.pop(0))
        n = 60 + (i * 7) % 12 + (i % 3) * 5
        held.append(n)
        e.note_on(n, 100)
        render(e, per)
    return e, jumps


def test_hybrid_steals_far_less_than_classic(monkeypatch):
    classic, _ = _scenario(monkeypatch, None)
    h6, j6 = _scenario(monkeypatch, 6)
    h12, j12 = _scenario(monkeypatch, 12)
    assert classic.steal_count > 20
    assert h6.steal_count < classic.steal_count / 3
    assert h12.steal_count <= h6.steal_count
    assert h12.steal_count == 0 and h12.forced_releases == 0
    assert not j12


def test_no_steal_when_cap_never_reached(monkeypatch):
    e, jumps = _scenario(monkeypatch, 12, release=0.3)
    assert e.steal_count == 0 and not jumps
    e, jumps = _scenario(monkeypatch, 6, release=0.2)
    assert e.steal_count == 0 and not jumps


# ---- (i) threads ---------------------------------------------------------------

def test_render_while_toggling_tail_slots_and_playing():
    e = make(2, voices=6, tails=6, capacity=12, amp_release=0.5)
    stop = threading.Event()
    errors = []

    def play():
        i = 0
        while not stop.is_set():
            try:
                e.note_on(40 + i % 40, 100)
                e.note_off(40 + (i - 4) % 40)
                e.set_tail_slots((0, 6, 12)[i % 3])
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            i += 1

    t = threading.Thread(target=play)
    t.start()
    try:
        for _ in range(150):
            assert np.isfinite(e.render(BLOCK)).all()
    finally:
        stop.set()
        t.join()
    assert not errors


# ---- (g) command line ------------------------------------------------------------

def test_cli_tail_slots_option():
    import run

    assert run.parse_args([]).tail_slots == 6
    assert run.parse_args(["--tail-slots", "12"]).tail_slots == 12
    assert run.parse_args(["--tail-slots", "0"]).tail_slots == 0
    for bad in ("13", "-1", "x"):
        with pytest.raises(SystemExit):
            run.parse_args(["--tail-slots", bad])


class _Stop(Exception):
    pass


def _construct_via_main(monkeypatch, argv):
    import sys
    import types

    import run
    from midi_synth import audio_backend

    seen = {}

    class Spy:
        def __init__(self, *a, **k):
            seen.update(k)
            raise _Stop

    monkeypatch.setitem(sys.modules, "sounddevice", types.ModuleType("sounddevice"))
    monkeypatch.setattr(audio_backend, "resolve_output",
                        lambda *a, **k: {"device": None})
    monkeypatch.setattr(audio_backend, "default_samplerate", lambda *a, **k: 44100)
    monkeypatch.setattr(run, "SynthEngine", Spy)
    with pytest.raises(_Stop):
        run.main(["--no-asio"] + argv)
    return seen


def test_main_builds_engine_with_tail_slots(monkeypatch):
    seen = _construct_via_main(monkeypatch, [])
    assert seen["max_voices"] == 12
    assert seen["tail_slots"] == 6 and seen["tail_capacity"] == 12
    seen = _construct_via_main(monkeypatch, ["--voices", "8", "--tail-slots", "0"])
    assert seen["max_voices"] == 8 and seen["tail_slots"] == 0
    assert seen["tail_capacity"] == 12
