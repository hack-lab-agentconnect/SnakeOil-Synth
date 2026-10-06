import numpy as np
import pytest

from midi_synth.effects import Delay, Reverb
from midi_synth.engine import SynthEngine
from midi_synth.params import build_registry
from midi_synth.patches import apply, capture

NEW = {
    "fx_reverb_size": ("fx_reverb", "Size", 0.5, 0.98, 0.84),
    "fx_reverb_damp": ("fx_reverb", "Damping", 0.0, 0.9, 0.25),
    "fx_delay_feedback": ("fx_delay", "Feedback", 0.0, 0.95, 0.35),
    "fx_delay_damp": ("fx_delay", "Tone", 0.0, 0.9, 0.25),
}


def test_reverb_set_room_updates_every_comb_in_both_banks():
    r = Reverb(44100)
    r.set_room(0.6)
    assert r.room == 0.6
    assert len(r.combs) == len(r.combs_r) == 6
    assert all(c.fb == 0.6 for c in r.combs + r.combs_r)


def test_reverb_set_damp_updates_every_comb_in_both_banks():
    r = Reverb(44100)
    r.set_damp(0.7)
    assert r.damp == 0.7
    assert all(c.damp == 0.7 for c in r.combs + r.combs_r)


def test_delay_setters():
    d = Delay(44100)
    d.set_feedback(0.6)
    d.set_damp(0.4)
    assert d.feedback == 0.6 and d.damp == 0.4


def test_reverb_size_changes_tail():
    x = np.zeros(8000)
    x[0] = 1.0

    def tail(room):
        r = Reverb(44100, enabled=True)
        r.set_room(room)
        return float(np.sum(r.process(np.stack([x, x]))[0][4000:] ** 2))

    assert tail(0.98) > tail(0.5)


def test_defaults_match_constructor_values():
    e = SynthEngine(sr=44100, block_size=64, max_voices=2)
    reg = build_registry(e)
    for pid, (_, _, _, _, default) in NEW.items():
        assert reg.get(pid) == pytest.approx(default)


def test_registry_entries():
    reg = build_registry(SynthEngine(sr=44100, block_size=64, max_voices=2))
    ids = reg.ids()
    for pid, (under, label, lo, hi, _) in NEW.items():
        p = reg[pid]
        assert p.kind == "continuous" and p.group == "Effects"
        assert p.label == label and p.under == under
        assert (p.minimum, p.maximum) == (lo, hi)
        assert p.tooltip
        assert ids.index(pid) > ids.index(under)
    assert "darker" in reg["fx_delay_damp"].tooltip
    assert reg["fx_delay_pingpong"].under == "fx_delay_time"


def test_params_reach_effects_and_clamp():
    e = SynthEngine(sr=44100, block_size=64, max_voices=2)
    reg = build_registry(e)
    reg.set("fx_reverb_size", 0.9)
    reg.set("fx_reverb_damp", 0.5)
    reg.set("fx_delay_feedback", 0.7)
    reg.set("fx_delay_damp", 0.6)
    rv, dl = e.effects.reverb, e.effects.delay
    assert rv.room == 0.9 and all(c.fb == 0.9 for c in rv.combs + rv.combs_r)
    assert rv.damp == 0.5 and all(c.damp == 0.5 for c in rv.combs + rv.combs_r)
    assert dl.feedback == 0.7 and dl.damp == 0.6
    e.set_reverb_size(5)
    e.set_reverb_damp(-1)
    e.set_delay_feedback(5)
    e.set_delay_damp(-1)
    assert rv.room == 0.98 and rv.damp == 0.0
    assert dl.feedback == 0.95 and dl.damp == 0.0
    e.set_reverb_size(0.0)
    assert rv.room == 0.5


def test_status_reports_new_values():
    e = SynthEngine(sr=44100, block_size=64, max_voices=2)
    e.set_reverb_size(0.7)
    e.set_reverb_damp(0.1)
    e.set_delay_feedback(0.5)
    e.set_delay_damp(0.3)
    s = e.status()
    assert s["reverb_size"] == 0.7 and s["reverb_damp"] == 0.1
    assert s["delay_feedback"] == 0.5 and s["delay_damp"] == 0.3


def test_patches_capture_and_apply_new_params():
    e = SynthEngine(sr=44100, block_size=64, max_voices=2)
    reg = build_registry(e)
    defaults = capture(reg)
    for pid in NEW:
        assert pid in defaults
    reg.set("fx_reverb_size", 0.6)
    reg.set("fx_delay_damp", 0.8)
    snap = capture(reg)
    reg.set("fx_reverb_size", 0.9)
    reg.set("fx_delay_damp", 0.1)
    apply(reg, snap, defaults)
    assert reg.get("fx_reverb_size") == 0.6 and reg.get("fx_delay_damp") == 0.8
    apply(reg, {}, defaults)
    assert reg.get("fx_reverb_size") == pytest.approx(0.84)
