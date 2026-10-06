"""Mod matrix M3: effect destinations, base-value store and ramped delay time."""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from midi_synth.engine import SynthEngine
from midi_synth.modmatrix import DEST_NAMES, DESTINATIONS, destination, parse_mod_args
from midi_synth.params import build_registry
from midi_synth.patches import apply, capture

SR, BLOCK = 44100, 256

# name, registry id, status key, base value, live getter, lo, hi
FX_CASES = [
    ("Chorus: Depth", "fx_chorus_depth", "chorus_depth", 0.4,
     lambda e: e.effects.chorus.amount, 0.0, 1.0),
    ("Delay: Time", "fx_delay_time", "delay_time", 400.0,
     lambda e: e.effects.delay.time_ms, 1.0, 4000.0),
    ("Delay: Feedback", "fx_delay_feedback", "delay_feedback", 0.4,
     lambda e: e.effects.delay.feedback, 0.0, 0.95),
    ("Delay: Tone", "fx_delay_damp", "delay_damp", 0.4,
     lambda e: e.effects.delay.damp, 0.0, 0.9),
    ("Reverb: Amount", "fx_reverb_amount", "reverb_amount", 0.4,
     lambda e: e.effects.reverb.mix, 0.0, 1.0),
    ("Reverb: Size", "fx_reverb_size", "reverb_size", 0.7,
     lambda e: e.effects.reverb.room, 0.5, 0.98),
    ("Reverb: Damping", "fx_reverb_damp", "reverb_damp", 0.4,
     lambda e: e.effects.reverb.damp, 0.0, 0.9),
    ("Bitcrush: Crush", "fx_bitcrush_amount", "crush_amount", 0.4,
     lambda e: e.effects.bitcrush.amount, 0.0, 1.0),
]
IDS = [c[0] for c in FX_CASES]


def make_engine(effects=("chorus", "delay", "reverb", "bitcrush")):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=4)
    reg = build_registry(e)
    for name in effects:
        e.set_effect(name, True)
    return e, reg


def row(e, slot, src, amt, dst):
    e.set_mod_src(slot, src)
    e.set_mod_amt(slot, amt)
    e.set_mod_dst(slot, dst)


def blocks(e, count=1):
    for _ in range(count):
        e.render(BLOCK)


def set_base(reg, pid, value):
    reg.set(pid, value)


def base_values(reg):
    """Captured patch values without the matrix rows themselves."""
    return {k: v for k, v in capture(reg).items() if not k.startswith(("mod1_", "mod2_"))}


# ---- table --------------------------------------------------------------

def test_effect_entries_in_spec_order():
    names = [d.name for d in DESTINATIONS]
    start = names.index("Chorus: Depth")
    assert names[start - 1] == "Amp Env: Release"
    assert names[start:start + 8] == [c[0] for c in FX_CASES]
    assert names[start + 8] == "Unison: Detune"
    assert len(set(DEST_NAMES)) == len(DEST_NAMES)


def test_effect_groups_are_contiguous():
    names = [d.name for d in DESTINATIONS]
    seen, last = [], None
    for n in names:
        g = n.split(":")[0] if ":" in n else None
        if g != last:
            assert g is None or g not in seen, "group %s split" % g
            seen.append(g)
            last = g


def test_table_fields():
    for name, pid, _, _, _, lo, hi in FX_CASES:
        d = destination(name)
        assert (d.param_id, d.kind, d.lo, d.hi) == (pid, "global", lo, hi)


def test_registry_choices_include_effect_destinations():
    _, reg = make_engine()
    for name, *_ in FX_CASES:
        assert name in reg["mod1_dst"].choices


def test_console_aliases_unique_and_parse():
    aliases = ["".join(n.split()).lower() for n in DEST_NAMES]
    assert len(set(aliases)) == len(aliases)
    for word, name in (("chorus:depth", "Chorus: Depth"), ("delay:time", "Delay: Time"),
                       ("delay:feedback", "Delay: Feedback"), ("delay:tone", "Delay: Tone"),
                       ("reverb:amount", "Reverb: Amount"), ("reverb:size", "Reverb: Size"),
                       ("reverb:damping", "Reverb: Damping"),
                       ("bitcrush:crush", "Bitcrush: Crush")):
        assert parse_mod_args(["1", "wheel", "50", word]) == (1, "Mod Wheel", 0.5, name)


def test_console_help_lists_effect_destinations():
    import run
    text = run.HELP_TEXT
    for word in ("chorus:depth", "delay:time", "reverb:amount", "bitcrush:crush"):
        assert word in text


# ---- base store ---------------------------------------------------------

def test_base_store_initialised_from_defaults():
    e, _ = make_engine()
    assert e.fx_base == {
        "fx_chorus_depth": 0.3, "fx_delay_time": 300.0, "fx_delay_feedback": 0.35,
        "fx_delay_damp": 0.25, "fx_reverb_amount": 0.3, "fx_reverb_size": 0.84,
        "fx_reverb_damp": 0.25, "fx_bitcrush_amount": 0.5}


@pytest.mark.parametrize("name,pid,key,base,live,lo,hi", FX_CASES, ids=IDS)
def test_wheel_row_modulates_live_and_keeps_base(name, pid, key, base, live, lo, hi):
    e, reg = make_engine()
    set_base(reg, pid, base)
    before = base_values(reg)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, name)
    blocks(e)
    assert live(e) == pytest.approx(min(max(base * 1.5, lo), hi), abs=1e-9)
    assert reg[pid].get() == pytest.approx(base)
    assert base_values(reg) == before
    assert e.status()[key] == pytest.approx(base)
    assert e.fx_base[pid] == pytest.approx(base)


@pytest.mark.parametrize("name,pid,key,base,live,lo,hi", FX_CASES, ids=IDS)
def test_negative_scale_and_clamping(name, pid, key, base, live, lo, hi):
    e, reg = make_engine()
    set_base(reg, pid, base)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", -1.0, name)
    blocks(e)
    want = lo
    assert live(e) == pytest.approx(want, abs=1e-9)
    row(e, 1, "Mod Wheel", 1.0, name)
    row(e, 2, "Mod Wheel", 1.0, name)
    blocks(e)
    assert live(e) == pytest.approx(min(max(base * 3.0, lo), hi), abs=1e-9)


@pytest.mark.parametrize("name,pid,key,base,live,lo,hi", FX_CASES, ids=IDS)
def test_clearing_restores_base_exactly(name, pid, key, base, live, lo, hi):
    e, reg = make_engine()
    set_base(reg, pid, base)
    live_before = live(e)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, name)
    blocks(e)
    assert live(e) != live_before
    e.set_mod_dst(1, "none")
    blocks(e)
    assert live(e) == live_before
    row(e, 1, "Mod Wheel", 0.5, name)
    blocks(e)
    e.set_mod_amt(1, 0.0)
    blocks(e)
    assert live(e) == live_before


@pytest.mark.parametrize("name,pid,key,base,live,lo,hi", FX_CASES, ids=IDS)
def test_base_change_while_modulated(name, pid, key, base, live, lo, hi):
    e, reg = make_engine()
    set_base(reg, pid, base)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, name)
    blocks(e)
    new = base * 0.8
    set_base(reg, pid, new)
    assert e.fx_base[pid] == pytest.approx(new)
    assert reg[pid].get() == pytest.approx(new)
    blocks(e)
    assert live(e) == pytest.approx(min(max(new * 1.5, lo), hi), abs=1e-9)
    e.set_mod_dst(1, "none")
    blocks(e)
    assert live(e) == pytest.approx(new)


@pytest.mark.parametrize("name,pid,key,base,live,lo,hi", FX_CASES, ids=IDS)
def test_unmodulated_setter_applies_live_immediately(name, pid, key, base, live, lo, hi):
    e, reg = make_engine()
    set_base(reg, pid, base)
    assert live(e) == pytest.approx(base)


def test_base_zero_stays_zero():
    e, reg = make_engine()
    set_base(reg, "fx_reverb_amount", 0.0)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 1.0, "Reverb: Amount")
    blocks(e, 3)
    assert e.effects.reverb.mix == 0.0


def test_note_number_uses_last_note():
    e, reg = make_engine()
    set_base(reg, "fx_reverb_size", 0.8)
    row(e, 1, "Note Number", 0.3, "Reverb: Size")
    e.note_on(96, 100)
    blocks(e)
    assert e.effects.reverb.room == pytest.approx(0.8 * (1 + 0.3 * 0.6))
    e.note_on(24, 100)
    blocks(e)
    assert e.effects.reverb.room == pytest.approx(0.8 * (1 - 0.3 * 0.6))


def test_lfo_source_drives_destination_over_blocks():
    e, reg = make_engine()
    set_base(reg, "fx_reverb_amount", 0.5)
    e.set_lfo_rate(4.0)
    row(e, 1, "LFO 1", 0.8, "Reverb: Amount")
    seen = []
    for _ in range(60):
        blocks(e)
        seen.append(e.effects.reverb.mix)
    assert max(seen) > 0.5 * 1.5 and min(seen) < 0.5 * 0.5
    assert all(0.0 <= v <= 1.0 for v in seen)
    assert reg["fx_reverb_amount"].get() == 0.5


def test_reverb_size_applies_to_every_comb():
    e, reg = make_engine()
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", -0.5, "Reverb: Size")
    blocks(e)
    room = e.effects.reverb.room
    assert all(c.fb == room for c in e.effects.reverb.combs + e.effects.reverb.combs_r)
    e.set_mod_dst(1, "none")
    blocks(e)
    assert all(c.fb == 0.84 for c in e.effects.reverb.combs + e.effects.reverb.combs_r)


def test_effect_modulation_changes_audio():
    def run(scale):
        e, reg = make_engine(("reverb",))
        e.set_mod_wheel(1.0)
        if scale:
            row(e, 1, "Mod Wheel", scale, "Reverb: Amount")
        e.note_on(60, 100)
        return np.concatenate([e.render(BLOCK) for _ in range(6)])
    assert not np.array_equal(run(0.0), run(1.0))


def test_empty_matrix_leaves_effects_bit_identical_after_clear():
    def run(modulate):
        e, reg = make_engine(("chorus", "reverb", "bitcrush"))
        e.set_mod_wheel(1.0)
        e.note_on(60, 100)
        out = [e.render(BLOCK) for _ in range(2)]
        if modulate:
            row(e, 1, "Mod Wheel", 0.5, "Chorus: Depth")
            row(e, 2, "Mod Wheel", 0.5, "Reverb: Size")
            row(e, 3, "Mod Wheel", 0.5, "Bitcrush: Crush")
            out += [e.render(BLOCK) for _ in range(3)]
            for s in (1, 2, 3):
                e.set_mod_dst(s, "none")
            e.render(BLOCK)
        return e
    a, b = run(False), run(True)
    assert a.effects.chorus.amount == b.effects.chorus.amount
    assert a.effects.chorus.depth == b.effects.chorus.depth
    assert a.effects.reverb.room == b.effects.reverb.room
    assert a.effects.bitcrush.amount == b.effects.bitcrush.amount
    assert a.effects.bitcrush.bits == b.effects.bitcrush.bits
    assert a.effects.bitcrush.downsample == b.effects.bitcrush.downsample


# ---- delay time ---------------------------------------------------------

def test_delay_time_ramps_to_modulated_time_and_back():
    e, reg = make_engine(("delay",))
    set_base(reg, "fx_delay_time", 400.0)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, "Delay: Time")
    blocks(e)
    assert e.effects.delay.time_ms == pytest.approx(600.0)
    assert e.effects.delay.time == pytest.approx(600.0 * SR / 1000.0)
    e.set_mod_dst(1, "none")
    assert e.effects.delay.target_ms == pytest.approx(400.0)
    blocks(e)
    assert e.effects.delay.time_ms == pytest.approx(400.0)
    assert reg["fx_delay_time"].get() == 400.0


def test_delay_time_move_is_a_ramp_not_a_jump():
    e, reg = make_engine(("delay",))
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, "Delay: Time")
    blocks(e)
    assert e.effects.delay.target_ms is None   # consumed by the block
    set_base(reg, "fx_delay_time", 800.0)
    # the manual knob never jumps the live time while modulated
    assert e.effects.delay.time_ms == pytest.approx(450.0)
    blocks(e)
    assert e.effects.delay.time_ms == pytest.approx(1200.0)


def test_delay_time_unmodulated_knob_jumps_as_before():
    e, reg = make_engine(("delay",))
    set_base(reg, "fx_delay_time", 700.0)
    assert e.effects.delay.time_ms == 700.0
    assert e.effects.delay.target_ms is None


def test_delay_time_clamps_to_engine_limits_not_knob_minimum():
    e, reg = make_engine(("delay",))
    set_base(reg, "fx_delay_time", 400.0)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", -0.99, "Delay: Time")
    blocks(e)
    assert e.effects.delay.time_ms == pytest.approx(4.0)
    row(e, 1, "Mod Wheel", 1.0, "Delay: Time")
    row(e, 2, "Mod Wheel", 1.0, "Delay: Time")
    set_base(reg, "fx_delay_time", 3000.0)
    blocks(e)
    assert e.effects.delay.time_ms == 4000.0


def test_delay_time_relative_to_synced_time_in_force():
    e, reg = make_engine(("delay",))
    reg.set("tempo_bpm", 120.0)
    reg.set("fx_delay_division", "1/8")
    reg.set("fx_delay_sync", True)
    set_base(reg, "fx_delay_time", 900.0)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, "Delay: Time")
    blocks(e)
    assert e.effects.delay.time_ms == pytest.approx(250.0 * 1.5)
    blocks(e, 3)
    assert e.effects.delay.time_ms == pytest.approx(250.0 * 1.5)
    assert reg["fx_delay_time"].get() == 900.0
    e.set_mod_dst(1, "none")
    blocks(e)
    assert e.effects.delay.time_ms == pytest.approx(250.0)
    # sync off: the manual time is the base again
    reg.set("fx_delay_sync", False)
    assert e.effects.delay.time_ms == pytest.approx(900.0)


def test_status_reports_base_values_while_modulated():
    e, reg = make_engine(("delay",))
    set_base(reg, "fx_delay_time", 400.0)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, "Delay: Time")
    blocks(e)
    assert e.status()["delay_time"] == 400.0
    e.set_mod_dst(1, "none")
    blocks(e)
    assert e.status()["delay_time"] == 400.0


def test_delay_lfo_modulation_stays_finite_across_block_sizes():
    for block in (64, 256, 1024):
        e = SynthEngine(sr=SR, block_size=block, max_voices=4)
        e.set_effect("delay", True)
        e.set_delay_pingpong(True)
        e.set_delay_feedback(0.7)
        row(e, 1, "LFO 1", 0.5, "Delay: Time")
        row(e, 2, "LFO 1", 0.4, "Delay: Feedback")
        e.set_lfo_rate(3.0)
        e.note_on(57, 110)
        for _ in range(int(2 * SR / block)):
            out = e.render(block)
            assert np.isfinite(out).all()
            assert np.abs(out).max() <= 1.0


# ---- patches, threads, GUI ----------------------------------------------

def test_patch_round_trip_with_effect_destinations():
    e, reg = make_engine()
    defaults = capture(reg)
    for i, (name, pid, _, base, *_rest) in enumerate(FX_CASES, 1):
        set_base(reg, pid, base)
        row(e, i, "Mod Wheel", 0.1 * i, name)
    e.set_mod_wheel(1.0)
    blocks(e)
    values = capture(reg)
    assert values["mod3_dst"] == "Delay: Feedback"
    e2, reg2 = make_engine()
    assert apply(reg2, values, defaults) == []
    assert capture(reg2) == values
    e2.set_mod_wheel(1.0)
    blocks(e2)
    for _, pid, _, base, live, lo, hi in FX_CASES:
        assert reg2[pid].get() == pytest.approx(base)


def test_threaded_rows_edited_while_rendering():
    e, reg = make_engine()
    errors = []
    stop = threading.Event()

    def audio():
        try:
            while not stop.is_set():
                out = e.render(64)
                assert np.isfinite(out).all()
        except Exception as exc:  # noqa: BLE001 - reported to the main thread
            errors.append(exc)

    t = threading.Thread(target=audio)
    t.start()
    try:
        names = [c[0] for c in FX_CASES]
        for k in range(300):
            row(e, 1 + k % 8, "LFO 1" if k % 2 else "Mod Wheel", 0.5, names[k % 8])
            reg.set("fx_delay_time", 200.0 + k)
            e.set_mod_wheel((k % 10) / 10.0)
            if k % 7 == 0:
                e.set_mod_dst(1 + k % 8, "none")
    finally:
        stop.set()
        t.join()
    assert not errors


def test_gui_destination_combo_lists_new_names_once():
    from PySide6.QtWidgets import QApplication

    from midi_synth.gui.controls import ParamControl
    QApplication.instance() or QApplication([])
    e, reg = make_engine()
    ctl = ParamControl(reg, reg["mod1_dst"], compact=True)
    combo = ctl.editor
    items = [(combo.itemText(i), True)
             for i in range(combo.count())]
    texts = [t for t, _ in items]
    for name, *_ in FX_CASES:
        assert texts.count(name) == 1
    for header in ("Chorus", "Delay", "Reverb", "Bitcrush"):
        assert texts.count(header) == 1
        assert texts[texts.index(header) + 1].startswith(header + ":")
