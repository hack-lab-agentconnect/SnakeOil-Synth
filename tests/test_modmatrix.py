"""Pure mod-matrix logic: sources, destination table, relative scaling."""
import pytest

from midi_synth.config import MOD_SMOOTH
from midi_synth.modmatrix import (
    DEST_NAMES,
    DESTINATIONS,
    NUM_SLOTS,
    SOURCES,
    destination,
    effective,
    note_source,
    smooth,
)

M1_NAMES = (
    "Osc 1: Level", "Osc 1: PWM", "Osc 1: Sq Level",
    "Osc 2: Level", "Osc 2: Tune", "Osc 2: Fine", "Osc 2: PWM",
    "Modulation Amount",
    "Filter: Cutoff", "Filter: Resonance", "Filter: Env Amount",
    "Filter: Key Trk", "Filter: Vel>Cut",
)


def test_sources_exact():
    assert SOURCES == ("none", "Note Number", "LFO 1", "LFO 2", "Mod Wheel", "Aftertouch")
    assert NUM_SLOTS == 8
    assert MOD_SMOOTH == 0.3


def test_destination_names_start_with_none_and_cover_m1():
    assert DEST_NAMES[0] == "none"
    assert tuple(n for n in DEST_NAMES[1:] if n in M1_NAMES) == M1_NAMES
    assert len(set(DEST_NAMES)) == len(DEST_NAMES)


def test_destination_table_fields():
    for d in DESTINATIONS:
        assert d.kind in ("voice", "global")
        assert d.lo < d.hi
        assert destination(d.name) is d
    cutoff = destination("Filter: Cutoff")
    assert cutoff.param_id == "lpf_cutoff"
    assert (cutoff.lo, cutoff.hi) == (20.0, 20000.0)
    assert destination("Osc 2: Tune").param_id == "detune2_semitones"
    assert destination("Filter: Env Amount").lo == -1.0


def test_effective_relative_scaling():
    assert effective(0.5, [(1.0, 0.5)], 0.0, 1.0) == pytest.approx(0.75)
    assert effective(0.5, [(-1.0, 1.0)], 0.0, 1.0) == pytest.approx(0.0)
    assert effective(0.5, [(0.5, -1.0)], 0.0, 1.0) == pytest.approx(0.25)


def test_effective_clamps():
    assert effective(0.8, [(1.0, 1.0)], 0.0, 1.0) == 1.0
    assert effective(0.5, [(-1.0, 1.0), (-1.0, 1.0)], 0.0, 1.0) == 0.0
    assert effective(-0.8, [(1.0, 1.0)], -1.0, 1.0) == -1.0


def test_effective_terms_add_before_multiplying():
    assert effective(0.4, [(0.5, 1.0), (0.25, 1.0)], 0.0, 10.0) == pytest.approx(0.4 * 1.75)
    assert effective(0.4, [(0.5, 1.0), (-0.5, 1.0)], 0.0, 10.0) == pytest.approx(0.4)


def test_effective_zero_base_stays_zero_and_no_terms_is_base():
    assert effective(0.0, [(1.0, 1.0)], -1.0, 1.0) == 0.0
    assert effective(0.37, [], 0.0, 1.0) == 0.37


def test_effective_negative_base_scales_relatively():
    assert effective(-6.0, [(0.5, 1.0)], -12.0, 12.0) == pytest.approx(-9.0)


def test_note_source_values_and_clip():
    assert note_source(60) == 0.0
    assert note_source(72) == pytest.approx(0.2)
    assert note_source(48) == pytest.approx(-0.2)
    assert note_source(120) == 1.0
    assert note_source(127) == 1.0
    assert note_source(0) == -1.0
    assert note_source(-5) == -1.0
    assert note_source(None) == 0.0


def test_smooth_one_pole():
    assert smooth(0.0, 1.0) == pytest.approx(MOD_SMOOTH)
    assert smooth(1.0, 1.0) == 1.0
    v = 0.0
    for _ in range(40):
        v = smooth(v, 1.0)
    assert v == pytest.approx(1.0, abs=1e-5)
    assert smooth(0.5, 0.0, 1.0) == 0.0
