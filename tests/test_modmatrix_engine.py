"""Mod matrix engine: sources, relative scaling, voice-level destinations."""
import threading
import time

import mido
import numpy as np
import pytest

from midi_synth.bindings import CC, PRESSURE, Profile, Source, default_profile
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput
from midi_synth.midi_router import MidiRouter
from midi_synth.modmatrix import DEST_NAMES, NUM_SLOTS, SOURCES, destination
from midi_synth.params import CHOICE, CONTINUOUS, build_registry
from midi_synth.patches import apply, capture

SR, BLOCK = 44100, 256


def make_engine(**params):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=6)
    reg = build_registry(e)
    reg.set("osc2_level", 0.0)
    for pid, value in params.items():
        reg.set(pid, value)
    return e, reg


def play(e, note=84, blocks=14):
    e.note_on(note, 100)
    return np.concatenate([e.render(BLOCK, apply_effects=False) for _ in range(blocks)])


def row(e, slot, src, amt, dst):
    e.set_mod_src(slot, src)
    e.set_mod_amt(slot, amt)
    e.set_mod_dst(slot, dst)


# (destination, base setup). Note 84 -> source 0.4; scale -1 -> factor 0.6.
CASES = [
    ("Osc 1: Level", {"osc1_level": 1.0}),
    ("Osc 1: PWM", {"osc1_square": True, "osc1_pwm": 0.3, "osc1_square_level": 1.0}),
    ("Osc 1: Sq Level", {"osc1_square": True, "osc1_square_level": 0.8, "osc1_pwm": 0.2}),
    ("Osc 2: Level", {"osc2_level": 1.0, "mod_mode": "off"}),
    ("Osc 2: Tune", {"osc2_level": 1.0, "detune2_semitones": 7.0, "mod_mode": "off"}),
    ("Osc 2: Fine", {"osc2_level": 1.0, "detune2_cents": 0.4, "mod_mode": "off"}),
    ("Osc 2: PWM", {"osc2_level": 1.0, "osc2_pwm": 0.3, "mod_mode": "off"}),
    ("Modulation Amount", {"osc2_level": 1.0, "mod_mode": "fm", "fm_depth": 0.5}),
    ("Filter: Cutoff", {"lpf_cutoff": 1500.0}),
    ("Filter: Resonance", {"lpf_cutoff": 800.0, "lpf_resonance": 0.6}),
    ("Filter: Env Amount", {"lpf_cutoff": 400.0, "flt_env_amount": 0.7}),
    ("Filter: Key Trk", {"lpf_cutoff": 400.0, "flt_keytrack": 0.8}),
    ("Filter: Vel>Cut", {"lpf_cutoff": 400.0, "flt_vel": 0.8}),
    ("Filter: Cutoff", {"lpf_cutoff": 1500.0, "lpf_master": True}),
    ("Filter: Resonance", {"lpf_cutoff": 800.0, "lpf_resonance": 0.6, "lpf_master": True}),
]
CASE_IDS = [("%s%s" % (n, "/master" if s.get("lpf_master") else "")) for n, s in CASES]


def diff(a, b):
    return float(np.max(np.abs(a - b)))


@pytest.mark.parametrize("dst,setup", CASES, ids=CASE_IDS)
def test_destination_changes_audio(dst, setup):
    ref, _ = make_engine(**setup)
    mod, _ = make_engine(**setup)
    row(mod, 1, "Note Number", -1.0, dst)
    assert diff(play(ref), play(mod)) > 1e-4


@pytest.mark.parametrize("dst,setup", CASES, ids=CASE_IDS)
def test_scale_zero_is_bit_identical(dst, setup):
    ref, _ = make_engine(**setup)
    mod, _ = make_engine(**setup)
    row(mod, 1, "Note Number", 0.0, dst)
    assert np.array_equal(play(ref), play(mod))


@pytest.mark.parametrize("dst,setup", CASES, ids=CASE_IDS)
def test_zero_base_is_a_no_op(dst, setup):
    pid = destination(dst).param_id
    zero = dict(setup)
    zero[pid] = 0.0
    ref, _ = make_engine(**zero)
    mod, _ = make_engine(**zero)
    row(mod, 1, "Note Number", -1.0, dst)
    assert np.array_equal(play(ref), play(mod))


@pytest.mark.parametrize("dst,setup", CASES, ids=CASE_IDS)
def test_base_values_and_capture_unchanged(dst, setup):
    e, reg = make_engine(**setup)
    pid = destination(dst).param_id
    before = capture(reg)
    base = e.params[pid]
    row(e, 1, "Note Number", -1.0, dst)
    after_row = capture(reg)
    play(e)
    assert e.params[pid] == base
    assert reg.get(pid) == base
    assert capture(reg) == after_row
    assert {k: v for k, v in after_row.items() if not k.startswith("mod1_")} == \
        {k: v for k, v in before.items() if not k.startswith("mod1_")}


def test_clearing_a_row_returns_to_the_base_sound():
    setup = dict(CASES[0][1])
    ref, _ = make_engine(**setup)
    mod, _ = make_engine(**setup)
    row(mod, 1, "Note Number", -1.0, "Osc 1: Level")
    play(mod, note=72, blocks=4)
    mod.set_mod_dst(1, "none")
    mod.all_notes_off()
    play(mod, note=72, blocks=40)
    mod.panic()
    ref.panic()
    assert np.array_equal(play(ref, note=70), play(mod, note=70))


def test_empty_matrix_is_bit_identical_to_fresh_engine():
    a = SynthEngine(sr=SR, block_size=BLOCK, max_voices=6)
    b = SynthEngine(sr=SR, block_size=BLOCK, max_voices=6)
    for e in (a, b):
        e.note_on(55, 90)
    row(b, 2, "LFO 1", 1.0, "none")
    row(b, 3, "none", 1.0, "Osc 1: Level")
    for _ in range(10):
        assert np.array_equal(a.render(BLOCK), b.render(BLOCK))


def test_inactive_rows_do_not_run_lfos():
    e, _ = make_engine()
    row(e, 1, "LFO 1", 0.0, "Osc 1: Level")
    play(e, blocks=3)
    assert e._lfo_last == [0.0, 0.0]


# ---- sources -------------------------------------------------------------

def test_note_numbers_differ_per_voice():
    e, _ = make_engine()
    row(e, 1, "Note Number", 1.0, "Osc 1: Level")
    seen = {}
    for v in e.voices:
        def spy(n, p, v=v, orig=v.render):
            seen[v.note] = p
            return orig(n, p)
        v.render = spy
    e.note_on(48, 100)
    e.note_on(84, 100)
    e.render(BLOCK, apply_effects=False)
    assert seen[48]["osc1_level"] == pytest.approx(1.0 * (1 + (-0.2)))
    assert seen[84]["osc1_level"] == pytest.approx(1.0)  # 1.4 clamped
    assert seen[48] is not e.params and seen[84] is not e.params
    assert e.params["osc1_level"] == 1.0


def test_shared_view_when_no_note_dependence():
    e, _ = make_engine()
    row(e, 1, "Mod Wheel", 0.5, "Osc 2: Level")
    e.set_osc_level(2, 0.4)
    e.set_mod_wheel(1.0)
    views = []
    for v in e.voices:
        v.render = lambda n, p, orig=v.render: (views.append(p), orig(n, p))[1]
    e.note_on(50, 100)
    e.note_on(70, 100)
    e.render(BLOCK, apply_effects=False)
    assert len(views) == 2 and views[0] is views[1]
    assert views[0] is not e.params
    assert e.params["osc2_level"] == 0.4


def test_params_dict_itself_when_nothing_modulates():
    e, _ = make_engine()
    views = []
    for v in e.voices:
        v.render = lambda n, p, orig=v.render: (views.append(p), orig(n, p))[1]
    e.note_on(50, 100)
    e.render(BLOCK, apply_effects=False)
    assert views[0] is e.params


def test_fm_depth_modulation_updates_mod_index_in_view():
    e, _ = make_engine(osc2_level=1.0, mod_mode="fm", fm_depth=0.5)
    row(e, 1, "Note Number", -1.0, "Modulation Amount")
    seen = []
    for v in e.voices:
        v.render = lambda n, p, orig=v.render: (seen.append(p), orig(n, p))[1]
    e.note_on(84, 100)
    e.render(BLOCK, apply_effects=False)
    assert seen[0]["fm_depth"] == pytest.approx(0.3)
    assert seen[0]["mod_index"] == pytest.approx(0.3 * 8.0)
    assert e.params["mod_index"] == pytest.approx(0.5 * 8.0)


def test_wheel_smoothing_converges():
    e, _ = make_engine()
    row(e, 1, "Mod Wheel", 1.0, "Osc 1: Level")
    e.note_on(60, 100)
    e.set_mod_wheel(1.0)
    e.render(BLOCK, apply_effects=False)
    assert e.mod_sources()["Mod Wheel"] == pytest.approx(0.3)
    for _ in range(40):
        e.render(BLOCK, apply_effects=False)
    assert e.mod_sources()["Mod Wheel"] == pytest.approx(1.0, abs=1e-4)


def test_aftertouch_smoothing_and_clamp():
    e, _ = make_engine()
    row(e, 1, "Aftertouch", 1.0, "Osc 1: Level")
    e.note_on(60, 100)
    e.set_aftertouch(5.0)
    for _ in range(40):
        e.render(BLOCK, apply_effects=False)
    assert e.mod_sources()["Aftertouch"] == pytest.approx(1.0, abs=1e-4)
    e.set_aftertouch(-3.0)
    for _ in range(40):
        e.render(BLOCK, apply_effects=False)
    assert e.mod_sources()["Aftertouch"] == pytest.approx(0.0, abs=1e-4)


def test_wheel_set_before_row_starts_at_its_value():
    e, _ = make_engine()
    e.set_mod_wheel(0.8)
    row(e, 1, "Mod Wheel", 1.0, "Osc 1: Level")
    e.note_on(60, 100)
    e.render(BLOCK, apply_effects=False)
    assert e.mod_sources()["Mod Wheel"] == pytest.approx(0.8)


def test_lfo_source_runs_with_zero_depth_and_does_not_publish():
    e, _ = make_engine()
    row(e, 1, "LFO 1", 1.0, "Osc 1: Level")
    e.note_on(60, 100)
    values = []
    for _ in range(20):
        e.render(BLOCK, apply_effects=False)
        values.append(e.mod_sources()["LFO 1"])
    assert max(values) > 0.1 and min(values) < -0.1
    assert max(abs(v) for v in values) <= 1.0
    assert e.params["lfo_pitch_ratio"] == 1.0
    assert e.params["lfo_filter_oct"] == 0.0
    assert e.params["lfo_depth"] == 0.0


def test_lfo_source_independent_of_depth_knob():
    a, _ = make_engine()
    b, _ = make_engine(lfo_depth=0.3, lfo_dest="pwm")
    for e in (a, b):
        row(e, 1, "LFO 1", 1.0, "Osc 1: Level")
        e.note_on(60, 100)
    for _ in range(12):
        a.render(BLOCK, apply_effects=False)
        b.render(BLOCK, apply_effects=False)
        assert a.mod_sources()["LFO 1"] == b.mod_sources()["LFO 1"]


def test_lfo2_source_and_modulated_value():
    e, _ = make_engine(lfo2_rate=10.0)
    row(e, 1, "LFO 2", 0.5, "Osc 1: Level")
    e.set_osc_level(1, 0.6)
    e.note_on(60, 100)
    e.render(BLOCK, apply_effects=False)
    lfo2 = e.mod_sources()["LFO 2"]
    assert lfo2 != 0.0
    assert e.modulated_value("osc1_level") == pytest.approx(
        min(max(0.6 * (1 + 0.5 * lfo2), 0.0), 1.0))
    assert e.modulated_value("osc2_pwm") == e.params["osc2_pwm"]


def test_modulated_value_for_note():
    e, _ = make_engine()
    e.set_osc_level(1, 0.5)
    row(e, 1, "Note Number", 1.0, "Osc 1: Level")
    assert e.modulated_value("osc1_level", note=72) == pytest.approx(0.5 * 1.2)
    assert e.modulated_value("osc1_level", note=48) == pytest.approx(0.5 * 0.8)
    e.note_on(84, 100)
    assert e.modulated_value("osc1_level") == pytest.approx(0.5 * 1.4)
    assert e.mod_sources()["Note Number"] == pytest.approx(0.4)
    assert e.mod_sources(note=60)["Note Number"] == 0.0


def test_several_rows_on_one_destination_add():
    e, _ = make_engine()
    e.set_osc_level(1, 0.4)
    row(e, 1, "Note Number", 1.0, "Osc 1: Level")
    row(e, 2, "Note Number", 0.5, "Osc 1: Level")
    assert e.modulated_value("osc1_level", note=72) == pytest.approx(0.4 * (1 + 0.2 + 0.1))


def test_master_mode_uses_last_note():
    e, _ = make_engine(lpf_cutoff=1000.0, lpf_master=True)
    row(e, 1, "Note Number", 1.0, "Filter: Cutoff")
    e.note_on(72, 100)
    assert e.modulated_value("lpf_cutoff") == pytest.approx(1000 * 1.2)


# ---- setters / registry / status ------------------------------------------

def test_setters_validate_and_clamp():
    e, _ = make_engine()
    e.set_mod_amt(1, 5.0)
    assert e.mod_rows[0][1] == 1.0
    e.set_mod_amt(1, -5.0)
    assert e.mod_rows[0][1] == -1.0
    for bad in (
        lambda: e.set_mod_src(1, "bogus"),
        lambda: e.set_mod_dst(1, "bogus"),
        lambda: e.set_mod_src(0, "LFO 1"),
        lambda: e.set_mod_src(NUM_SLOTS + 1, "LFO 1"),
        lambda: e.set_mod_amt(1, float("nan")),
    ):
        with pytest.raises(ValueError):
            bad()


def test_status_has_matrix_rows():
    e, _ = make_engine()
    row(e, 3, "LFO 2", 0.25, "Filter: Cutoff")
    st = e.status()
    assert st["mod3_src"] == "LFO 2"
    assert st["mod3_amt"] == 0.25
    assert st["mod3_dst"] == "Filter: Cutoff"
    assert st["mod1_src"] == "none"


def test_registry_entries():
    e, reg = make_engine()
    ids = reg.ids()
    expected = []
    for i in range(1, NUM_SLOTS + 1):
        expected += ["mod%d_src" % i, "mod%d_amt" % i, "mod%d_dst" % i]
    start = ids.index("mod1_src")
    assert ids[start:start + 24] == expected
    for i in range(1, NUM_SLOTS + 1):
        src, amt, dst = reg["mod%d_src" % i], reg["mod%d_amt" % i], reg["mod%d_dst" % i]
        assert src.group == amt.group == dst.group == "Mod Matrix"
        assert src.kind == CHOICE and src.choices == SOURCES
        assert dst.kind == CHOICE and dst.choices == DEST_NAMES
        assert amt.kind == CONTINUOUS and (amt.minimum, amt.maximum) == (-1.0, 1.0)
        assert amt.label == "Scale"
        assert (src.get(), amt.get(), dst.get()) == ("none", 0.0, "none")
    f = reg["mod1_amt"].formatter
    assert f(0.37) == "+37%" and f(-1.0) == "-100%" and f(0.0) == "+0%"
    reg.set("mod2_src", "Mod Wheel")
    reg.set("mod2_amt", 2.0)
    reg.set("mod2_dst", "Osc 2: Level")
    assert e.mod_rows[1] == ["Mod Wheel", 1.0, "Osc 2: Level"]


def test_patch_round_trip_and_old_patch_defaults():
    e, reg = make_engine()
    defaults = capture(reg)
    row(e, 4, "Aftertouch", -0.5, "Filter: Resonance")
    patch = capture(reg)
    assert patch["mod4_src"] == "Aftertouch" and patch["mod4_amt"] == -0.5
    e2, reg2 = make_engine()
    assert apply(reg2, patch, defaults) == []
    assert e2.mod_rows[3] == ["Aftertouch", -0.5, "Filter: Resonance"]
    old = {k: v for k, v in patch.items() if not k.startswith("mod")}
    assert apply(reg2, old, defaults) == []
    assert e2.mod_rows[3] == ["none", 0.0, "none"]


# ---- MIDI ------------------------------------------------------------------

def _midi(profile):
    e, reg = make_engine()
    router = MidiRouter(reg, profile)
    return e, reg, MidiInput(e, router=router)


def test_default_profile_has_no_cc1():
    assert default_profile().param_for(CC, 1, 1) is None


def test_midi_feeds_wheel_and_aftertouch():
    e, _, midi = _midi(Profile("p"))
    midi._on_message(mido.Message("control_change", channel=0, control=1, value=127))
    midi._on_message(mido.Message("aftertouch", channel=0, value=64))
    assert e._mod_wheel == pytest.approx(1.0)
    assert e._mod_at == pytest.approx(64 / 127.0)


def test_midi_feeds_matrix_even_when_bound_and_binding_still_applies():
    prof = Profile("p", [(Source(CC, 1, None), "osc1_level"),
                         (Source(PRESSURE, 0, None), "master_gain")])
    e, reg, midi = _midi(prof)
    midi._on_message(mido.Message("control_change", channel=0, control=1, value=127))
    midi._on_message(mido.Message("aftertouch", channel=0, value=127))
    assert e._mod_wheel == pytest.approx(1.0)
    assert e._mod_at == pytest.approx(1.0)
    assert reg.get("osc1_level") == pytest.approx(1.0)
    assert reg.get("master_gain") == pytest.approx(1.2)


def test_midi_channel_filter_blocks_other_channels():
    e, reg = make_engine()
    midi = MidiInput(e, channel=2, router=MidiRouter(reg, Profile("p")))
    midi._on_message(mido.Message("control_change", channel=0, control=1, value=127))
    assert e._mod_wheel == 0.0


# ---- console ----------------------------------------------------------------

def run_console(monkeypatch, capsys, lines, engine):
    import builtins
    import run
    it = iter(list(lines) + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
    run.console_loop(engine)
    return capsys.readouterr().out


def test_console_mod_command(monkeypatch, capsys):
    e, _ = make_engine()
    out = run_console(monkeypatch, capsys, [
        "mod 1 lfo1 40 filter:cutoff",
        "mod 2 Note Number -25 Osc 1: Level",
        "mod 3 lfo 2 100 osc2:tune",
        "mod 4 wheel 10 modulationamount",
        "mod 5 aftertouch 5 filter:vel>cut",
    ], e)
    assert e.mod_rows[0] == ["LFO 1", 0.4, "Filter: Cutoff"]
    assert e.mod_rows[1] == ["Note Number", -0.25, "Osc 1: Level"]
    assert e.mod_rows[2] == ["LFO 2", 1.0, "Osc 2: Tune"]
    assert e.mod_rows[3] == ["Mod Wheel", 0.1, "Modulation Amount"]
    assert e.mod_rows[4] == ["Aftertouch", 0.05, "Filter: Vel>Cut"]
    assert "usage" not in out


def test_console_mod_none_and_clear(monkeypatch, capsys):
    e, _ = make_engine()
    row(e, 1, "LFO 1", 0.4, "Filter: Cutoff")
    row(e, 2, "LFO 2", 0.4, "Filter: Cutoff")
    run_console(monkeypatch, capsys, ["mod 1 none 0 none", "mod clear 2"], e)
    assert e.mod_rows[0] == ["none", 0.0, "none"]
    assert e.mod_rows[1] == ["none", 0.0, "none"]
    row(e, 3, "LFO 2", 0.4, "Filter: Cutoff")
    run_console(monkeypatch, capsys, ["mod clear"], e)
    assert all(r == ["none", 0.0, "none"] for r in e.mod_rows)


def test_console_mod_bad_input_prints_usage(monkeypatch, capsys):
    e, _ = make_engine()
    out = run_console(monkeypatch, capsys, [
        "mod 9 lfo1 10 filter:cutoff",
        "mod 1 bogus 10 filter:cutoff",
        "mod 1 lfo1 abc filter:cutoff",
        "mod 1 lfo1 10 nowhere",
        "mod 1 lfo1 500 filter:cutoff",
        "mod 1 lfo1 10",
    ], e)
    assert out.count("usage: mod") >= 6
    assert e.mod_rows[0] == ["none", 0.0, "none"]


def test_console_mod_single_number_still_sets_modulation_amount(monkeypatch, capsys):
    e, _ = make_engine()
    run_console(monkeypatch, capsys, ["mod 0.6"], e)
    assert e.params["fm_depth"] == pytest.approx(0.6)


def test_help_mentions_matrix():
    import run
    assert "mod <slot" in run.HELP_TEXT and "mod clear" in run.HELP_TEXT


# ---- threading ---------------------------------------------------------------

def test_threaded_rows_while_rendering():
    e, _ = make_engine(osc2_level=0.5, lpf_cutoff=900.0)
    e.set_lfo_depth(0.5)
    for n in (50, 57, 64):
        e.note_on(n, 100)
    errors = []
    stop = time.time() + 0.3

    def audio():
        try:
            while time.time() < stop:
                out = e.render(BLOCK)
                assert np.isfinite(out).all()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def ui():
        try:
            i = 0
            while time.time() < stop:
                i += 1
                slot = i % NUM_SLOTS + 1
                e.set_mod_src(slot, SOURCES[i % len(SOURCES)])
                e.set_mod_amt(slot, ((i % 21) - 10) / 10.0)
                e.set_mod_dst(slot, DEST_NAMES[i % len(DEST_NAMES)])
                e.set_mod_wheel((i % 128) / 127.0)
                e.set_lpf_mode("master" if i % 7 == 0 else "voice")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=audio), threading.Thread(target=ui)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
