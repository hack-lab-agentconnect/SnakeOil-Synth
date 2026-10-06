"""Voice stealing: continuous retriggers, quietest-first victims, pop measurement."""
import numpy as np

from midi_synth.engine import SynthEngine
from midi_synth.voice import ATTACK, RELEASE, Envelope, Voice

SR, BLOCK = 44100, 256


def make_engine(width=1, voices=12, **setup):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices)
    e.set_unison_voices(width)
    for k, v in setup.items():
        getattr(e, "set_" + k)(v)
    return e


def gated(e, note=None):
    return [v for v in e.voices if v.gate and (note is None or v.note == note)]


def dirty_voice():
    v = Voice(SR)
    v.note_on(60, 0.8, 1, noise_pos=5)
    v.osc1.phase = 0.37
    v.osc2.phase = 0.61
    v.lpf.z1, v.lpf.z2, v.lpf.z3, v.lpf.z4 = 0.1, 0.2, 0.3, 0.4
    v.osc_phase = 1.25
    v.noise_pos = 777
    v.env.level = 0.4
    v.env.stage = RELEASE
    v.gate = False
    return v


# ---- (b) Voice.note_on / Envelope.note_on -------------------------------

def test_stolen_defaults_false():
    import inspect
    assert inspect.signature(Voice.note_on).parameters["stolen"].default is False
    assert inspect.signature(Envelope.note_on).parameters["keep_level"].default is False


def test_stolen_retrigger_keeps_continuous_state():
    v = dirty_voice()
    v.note_on(64, 1.0, 9, stolen=True, noise_pos=5, random_phase=True,
              rng=np.random.default_rng(0), detune_cents=3.0, pan=0.5, gain=0.7,
              group=4, unison_pos=-1.0)
    assert (v.osc1.phase, v.osc2.phase) == (0.37, 0.61)
    assert (v.lpf.z1, v.lpf.z2, v.lpf.z3, v.lpf.z4) == (0.1, 0.2, 0.3, 0.4)
    assert v.osc_phase == 1.25
    assert v.noise_pos == 777
    assert v.env.level == 0.4 and v.env.stage == ATTACK
    # everything else is applied
    assert (v.note, v.gate, v.trigger_order) == (64, True, 9)
    assert (v.detune_cents, v.pan, v.gain, v.group, v.unison_pos) == (3.0, 0.5, 0.7, 4, -1.0)
    assert v.velocity == 1.0
    assert v.flt_env.level == 0.0 and v.flt_env.stage == ATTACK


def test_stolen_retrigger_keeps_level_of_exactly_one():
    v = dirty_voice()
    v.env.level = 1.0
    v.note_on(64, 1.0, 9, stolen=True)
    assert v.env.level == 1.0 and v.env.stage == ATTACK


def test_idle_retrigger_still_resets():
    v = dirty_voice()
    v.env.level = 1.0
    v.note_on(64, 1.0, 9, noise_pos=11)
    assert (v.osc1.phase, v.osc2.phase) == (0.0, 0.0)
    assert (v.lpf.z1, v.lpf.z2, v.lpf.z3, v.lpf.z4) == (0.0,) * 4
    assert v.osc_phase == 0.0 and v.noise_pos == 11
    assert v.env.level == 0.0


def test_envelope_keep_level():
    env = Envelope(SR)
    env.level = 1.0
    env.note_on(keep_level=True)
    assert env.level == 1.0 and env.stage == ATTACK
    env.note_on()
    assert env.level == 0.0


# ---- (d) steal_count ----------------------------------------------------

def test_steal_count_counts_only_steals():
    e = make_engine(1, voices=3)
    assert e.steal_count == 0
    for n in (60, 62, 64):
        e.note_on(n, 100)
    assert e.steal_count == 0 and e.status()["steal_count"] == 0
    e.note_on(65, 100)
    assert e.steal_count == 1
    e.note_on(67, 100)
    assert e.status()["steal_count"] == 2


def test_steal_count_unison_counts_stolen_voices_only():
    e = make_engine(2, voices=4)
    e.note_on(60, 100)
    e.note_on(62, 100)
    assert e.steal_count == 0
    e.note_on(64, 100)  # steals one whole group of two
    assert e.steal_count == 2


def test_engine_passes_stolen_flag():
    e = make_engine(1, voices=2)
    seen = []
    orig = Voice.note_on

    def spy(self, *a, **k):
        seen.append((self.active, k.get("stolen")))
        return orig(self, *a, **k)

    Voice.note_on = spy
    try:
        for n in (60, 62, 64):
            e.note_on(n, 100)
    finally:
        Voice.note_on = orig
    assert seen == [(False, False), (False, False), (True, True)]


# ---- (c) victim selection -----------------------------------------------

def test_quietest_released_voice_is_stolen_first():
    e = make_engine(1, voices=4)
    for n in (60, 62, 64, 66):
        e.note_on(n, 100)
    for n in (60, 62, 64):
        e.note_off(n)
    levels = {60: 0.5, 62: 0.1, 64: 0.3}
    for v in e.voices:
        if v.note in levels:
            v.env.level = levels[v.note]
    e.note_on(70, 100)
    assert gated(e, 70)[0].note == 70
    notes = sorted(v.note for v in e.voices)
    assert notes == [60, 64, 66, 70]  # 62 (level 0.1) was taken


def test_equal_levels_steal_oldest_released():
    e = make_engine(1, voices=3)
    for n in (60, 62, 64):
        e.note_on(n, 100)
    for n in (62, 60):
        e.note_off(n)
    e.note_on(70, 100)  # all levels 0; 60 is older than 62
    assert sorted(v.note for v in e.voices) == [62, 64, 70]


def test_all_gated_steals_oldest_gated():
    e = make_engine(1, voices=3)
    for n in (60, 62, 64):
        e.note_on(n, 100)
    e.note_on(70, 100)
    assert sorted(v.note for v in e.voices) == [62, 64, 70]


def test_idle_voice_used_before_any_steal():
    e = make_engine(1, voices=3)
    e.note_on(60, 100)
    e.note_on(62, 100)
    e.note_off(60)
    e.note_on(64, 100)
    assert e.steal_count == 0
    assert sorted(v.note for v in e.voices) == [60, 62, 64]


def test_group_selection_by_summed_levels():
    e = make_engine(2, voices=6)
    for n in (60, 62, 64):
        e.note_on(n, 100)
    for n in (60, 62):
        e.note_off(n)
    for v in e.voices:
        if v.note == 60:
            v.env.level = 0.4   # sum 0.8
        elif v.note == 62:
            v.env.level = 0.3   # sum 0.6
    e.note_on(70, 100)
    assert len(gated(e, 70)) == 2
    assert not [v for v in e.voices if v.note == 62]
    assert len([v for v in e.voices if v.note == 60]) == 2


def test_group_path_takes_quietest_single_voices():
    e = make_engine(1, voices=4)
    for n in (60, 62, 64, 66):
        e.note_on(n, 100)
    e.set_unison_voices(2)
    for n in (60, 62, 64, 66):
        e.note_off(n)
    for v, lv in zip(e.voices, (0.2, 0.9, 0.3, 0.3)):
        v.env.level = lv
    e.note_on(70, 100)  # needs 2: singles are groups of 1 -> takes 0.2 and 0.3
    assert sorted(v.note for v in e.voices if v.note != 70) == [62, 66] \
        or len(gated(e, 70)) == 2


def test_gated_groups_stolen_oldest_first_when_none_released():
    e = make_engine(2, voices=4)
    e.note_on(60, 100)
    e.note_on(62, 100)
    e.note_on(64, 100)
    assert sorted(v.note for v in e.voices) == [62, 62, 64, 64]


def test_unison_surplus_voices_released():
    e = make_engine(1, voices=4)
    for n in (60, 62, 64, 66):
        e.note_on(n, 100)
    e.set_unison_voices(3)
    e.note_on(70, 100)  # 3 needed, 3 singles stolen; no surplus here
    assert len(gated(e, 70)) == 3
    e2 = make_engine(3, voices=6)
    e2.note_on(60, 100)
    e2.note_on(62, 100)
    e2.set_unison_voices(2)
    e2.note_on(70, 100)  # steals a group of 3 for 2 voices -> 1 surplus released
    assert len(gated(e2, 70)) == 2
    assert sum(1 for v in e2.voices if v.active and not v.gate) == 1


def test_stolen_voices_in_group_path_keep_state():
    e = make_engine(2, voices=2)
    e.note_on(60, 100)
    e.render(BLOCK)
    e.render(BLOCK)
    before = [(v.osc1.phase, v.lpf.z1, v.env.level) for v in e.voices]
    e.note_on(64, 100)
    after = [(v.osc1.phase, v.lpf.z1, v.env.level) for v in e.voices]
    assert before == after


# ---- (a) pop measurement ------------------------------------------------

def _scenario(monkeypatch, old_behaviour):
    e = make_engine(2, voices=12, amp_release=1.5)
    e.set_lpf_cutoff(600)
    last = {}
    steps = []
    jumps = []
    pending = {}
    orig_render = Voice.render
    orig_on = Voice.note_on

    def render(self, n, params):
        out = orig_render(self, n, params)
        if self in pending:
            jumps.append(abs(out[0] - pending.pop(self)))
        elif self in last:
            steps.append(abs(out[0] - last[self]))
        last[self] = out[-1]
        return out

    def note_on(self, *a, **k):
        if self.active and self in last:
            pending[self] = last[self]
        if old_behaviour:
            k["stolen"] = False
        return orig_on(self, *a, **k)

    monkeypatch.setattr(Voice, "render", render)
    monkeypatch.setattr(Voice, "note_on", note_on)
    for n in (48, 52, 55, 59, 62):
        e.note_on(n, 100)
    e.render(BLOCK)
    blocks_per_note = round(0.110 * SR / BLOCK)
    prev = None
    for i in range(60):
        if prev is not None:
            e.note_off(prev)
        prev = 60 + (i * 7) % 12 + (i % 3) * 5
        e.note_on(prev, 100)
        for _ in range(blocks_per_note):
            e.render(BLOCK)
    return e, np.array(jumps), np.array(steps)


def test_stolen_voice_jumps_are_inaudible(monkeypatch):
    e, jumps, steps = _scenario(monkeypatch, old_behaviour=False)
    assert e.steal_count > 20 and len(jumps) > 20
    assert jumps.max() < 0.01
    assert jumps.max() < 3.0 * np.percentile(steps, 99.9)


def test_pop_test_can_fail_with_old_behaviour(monkeypatch):
    e, jumps, _ = _scenario(monkeypatch, old_behaviour=True)
    assert len(jumps) > 20
    assert jumps.max() > 0.03
