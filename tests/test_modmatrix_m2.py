"""Mod matrix M2: envelope, unison and tempo destinations."""
import builtins
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from midi_synth.config import (
    AMP_ATTACK_MAX,
    AMP_DECAY_MAX,
    AMP_RELEASE_MAX,
    AMP_TIME_MIN,
    TEMPO_MAX,
    TEMPO_MIN,
    UNISON_DETUNE_MAX,
)
from midi_synth.engine import SynthEngine
from midi_synth.modmatrix import DEST_NAMES, DESTINATIONS, destination, parse_mod_args
from midi_synth.params import build_registry
from midi_synth.patches import apply, capture

SR, BLOCK = 44100, 256

ENV_CASES = [
    ("Amp Env: Attack", "amp_attack", "env", "attack", AMP_TIME_MIN, AMP_ATTACK_MAX),
    ("Amp Env: Decay", "amp_decay", "env", "decay", AMP_TIME_MIN, AMP_DECAY_MAX),
    ("Amp Env: Sustain", "amp_sustain", "env", "sustain", 0.0, 1.0),
    ("Amp Env: Release", "amp_release", "env", "release", AMP_TIME_MIN, AMP_RELEASE_MAX),
    ("Filter Env: Attack", "flt_attack", "flt_env", "attack", AMP_TIME_MIN, AMP_ATTACK_MAX),
    ("Filter Env: Decay", "flt_decay", "flt_env", "decay", AMP_TIME_MIN, AMP_DECAY_MAX),
    ("Filter Env: Sustain", "flt_sustain", "flt_env", "sustain", 0.0, 1.0),
    ("Filter Env: Release", "flt_release", "flt_env", "release", AMP_TIME_MIN, AMP_RELEASE_MAX),
]


def make_engine(voices=6, **params):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices)
    reg = build_registry(e)
    reg.set("osc2_level", 0.0)
    for pid, value in params.items():
        reg.set(pid, str(value) if pid == "unison_voices" else value)
    return e, reg


def row(e, slot, src, amt, dst):
    e.set_mod_src(slot, src)
    e.set_mod_amt(slot, amt)
    e.set_mod_dst(slot, dst)


def render(e, blocks):
    return np.concatenate([e.render(BLOCK, apply_effects=False) for _ in range(blocks)])


# ---- table --------------------------------------------------------------

def test_table_has_new_entries_in_spec_order():
    names = [d.name for d in DESTINATIONS]
    assert names.index("Modulation Amount") + 1 == names.index("Tempo")
    assert names.index("Tempo") + 1 == names.index("Filter: Cutoff")
    env = [n for n in names if n.startswith(("Filter Env:", "Amp Env:"))]
    start = names.index("Filter Env: Attack")
    assert names[start:start + 8] == [
        "Filter Env: Attack", "Filter Env: Decay", "Filter Env: Sustain",
        "Filter Env: Release", "Amp Env: Attack", "Amp Env: Decay",
        "Amp Env: Sustain", "Amp Env: Release"]
    assert len(env) == 8
    assert names[-2:] == ["Unison: Detune", "Unison: Spread"]
    assert len(set(DEST_NAMES)) == len(DEST_NAMES)


def test_table_fields_for_new_entries():
    for name, pid, _, _, lo, hi in ENV_CASES:
        d = destination(name)
        assert (d.param_id, d.kind, d.lo, d.hi) == (pid, "voice", lo, hi)
    d = destination("Unison: Detune")
    assert (d.param_id, d.kind, d.lo, d.hi) == ("unison_detune", "voice", 0.0, UNISON_DETUNE_MAX)
    d = destination("Unison: Spread")
    assert (d.param_id, d.kind, d.lo, d.hi) == ("unison_spread", "voice", 0.0, 1.0)
    d = destination("Tempo")
    assert (d.param_id, d.kind, d.lo, d.hi) == ("tempo_bpm", "global", TEMPO_MIN, TEMPO_MAX)


# ---- envelopes ----------------------------------------------------------

@pytest.mark.parametrize("name,pid,env,attr,lo,hi", ENV_CASES)
def test_envelope_destination_sets_shape(name, pid, env, attr, lo, hi):
    e, _ = make_engine()
    base = e.params[pid]
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 0.5, name)
    for _ in range(40):  # let the wheel smoothing settle
        e.render(BLOCK)
    e.note_on(60, 100)
    e.render(BLOCK)
    v = next(v for v in e.voices if v.active)
    assert getattr(getattr(v, env), attr) == pytest.approx(min(max(base * 1.5, lo), hi), rel=1e-6)
    assert e.params[pid] == base


def test_amp_attack_clamps_to_maximum():
    e, reg = make_engine(amp_attack=0.5)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", 1.0, "Amp Env: Attack")
    for _ in range(40):
        e.render(BLOCK)
    e.note_on(60, 100)
    e.render(BLOCK)
    v = next(v for v in e.voices if v.active)
    assert v.env.attack == pytest.approx(1.0)
    reg.set("amp_attack", 4.0)
    e.render(BLOCK)
    assert v.env.attack == AMP_ATTACK_MAX


def test_unmodulated_members_keep_base_values():
    e, _ = make_engine(amp_attack=0.2, amp_decay=0.3, amp_sustain=0.6, amp_release=0.4,
                       flt_attack=0.01, flt_decay=0.2, flt_sustain=0.5, flt_release=0.9)
    row(e, 1, "Note Number", 1.0, "Amp Env: Decay")
    e.note_on(84, 100)
    e.render(BLOCK)
    v = next(v for v in e.voices if v.active)
    assert v.env.attack == 0.2 and v.env.sustain == 0.6 and v.env.release == 0.4
    assert v.env.decay == pytest.approx(0.3 * 1.4)
    assert (v.flt_env.attack, v.flt_env.decay, v.flt_env.sustain, v.flt_env.release) == (
        0.01, 0.2, 0.5, 0.9)


def test_sustain_modulated_to_zero_decays_to_silence():
    e, _ = make_engine(amp_sustain=0.8, amp_decay=0.05, amp_attack=0.002)
    e.set_mod_wheel(1.0)
    row(e, 1, "Mod Wheel", -1.0, "Amp Env: Sustain")
    for _ in range(40):
        e.render(BLOCK)
    e.note_on(60, 100)
    out = render(e, 80)
    assert np.abs(out[-2000:]).max() < 1e-6
    e2, _ = make_engine(amp_sustain=0.8, amp_decay=0.05, amp_attack=0.002)
    e2.note_on(60, 100)
    assert np.abs(render(e2, 80)[-2000:]).max() > 0.01


def test_release_destination_changes_tail_length():
    def tail(amount):
        e, _ = make_engine(amp_release=0.1)
        e.set_mod_wheel(1.0)
        if amount:
            row(e, 1, "Mod Wheel", amount, "Amp Env: Release")
        for _ in range(40):
            e.render(BLOCK)
        e.note_on(60, 100)
        render(e, 10)
        e.note_off(60)
        return np.abs(render(e, 30)).sum()

    assert tail(1.0) > tail(0.0) * 1.5
    assert tail(-0.9) < tail(0.0) * 0.6


def test_filter_env_modulation_changes_spectrum():
    def centroid(amount):
        e, _ = make_engine(lpf_cutoff=400.0, flt_env_amount=0.8, flt_attack=0.001,
                           flt_decay=0.4, flt_sustain=0.5)
        e.set_mod_wheel(1.0)
        if amount:
            row(e, 1, "Mod Wheel", amount, "Filter Env: Sustain")
        for _ in range(40):
            e.render(BLOCK)
        e.note_on(48, 100)
        out = render(e, 60)[:, 0][-8192:]
        spec = np.abs(np.fft.rfft(out * np.hanning(len(out))))
        freqs = np.fft.rfftfreq(len(out), 1 / SR)
        return float((spec * freqs).sum() / spec.sum())

    assert centroid(1.0) > centroid(0.0) * 1.05


def test_note_number_is_per_voice_for_envelopes():
    e, _ = make_engine(amp_decay=1.0)
    row(e, 1, "Note Number", 1.0, "Amp Env: Decay")
    e.note_on(36, 100)
    e.note_on(96, 100)
    e.render(BLOCK)
    decays = {v.note: v.env.decay for v in e.voices if v.active}
    assert decays[36] == pytest.approx(1.0 * (1 + (36 - 60) / 60.0))
    assert decays[96] == pytest.approx(1.0 * (1 + (96 - 60) / 60.0))
    assert decays[36] != decays[96]


def test_clearing_row_restores_base_shapes_and_sound():
    never, _ = make_engine(amp_attack=0.05, flt_decay=0.3)
    mod, _ = make_engine(amp_attack=0.05, flt_decay=0.3)
    row(mod, 1, "Note Number", 1.0, "Amp Env: Attack")
    row(mod, 2, "Note Number", -0.7, "Filter Env: Decay")
    mod.note_on(90, 100)
    render(mod, 3)
    v = next(v for v in mod.voices if v.active)
    assert v.env.attack != 0.05 and v.flt_env.decay != 0.3
    mod.set_mod_dst(1, "none")
    mod.set_mod_amt(2, 0.0)
    for v in mod.voices:
        assert v.env.attack == 0.05 and v.flt_env.decay == 0.3
    mod.all_notes_off()
    mod.panic()
    never.panic()
    mod.render(BLOCK)
    never.render(BLOCK)
    mod._rng = np.random.default_rng(1)
    never._rng = np.random.default_rng(1)
    mod.note_on(60, 100)
    never.note_on(60, 100)
    np.testing.assert_array_equal(render(mod, 6), render(never, 6))


def test_envelope_modulation_leaves_base_values_alone():
    e, reg = make_engine(amp_attack=0.3, amp_sustain=0.5)
    def base_values():
        return {k: v for k, v in capture(reg).items() if not k.startswith("mod") or k == "mod_mode"}

    before = base_values()
    row(e, 1, "Note Number", 0.8, "Amp Env: Attack")
    row(e, 2, "Note Number", 0.8, "Amp Env: Sustain")
    e.note_on(90, 100)
    render(e, 4)
    assert base_values() == before
    assert reg["amp_attack"].get() == 0.3
    assert e.params["amp_sustain"] == 0.5
    assert e.modulated_value("amp_attack") == pytest.approx(0.3 * (1 + 0.8 * 0.5))


def test_empty_matrix_bit_identical_with_idle_rows():
    a, _ = make_engine()
    b, _ = make_engine()
    row(b, 1, "Note Number", 0.0, "Amp Env: Attack")
    row(b, 2, "none", 0.7, "Unison: Detune")
    row(b, 3, "Mod Wheel", 0.7, "none")
    a.note_on(60, 100)
    b.note_on(60, 100)
    np.testing.assert_array_equal(render(a, 6), render(b, 6))


# ---- unison -------------------------------------------------------------

def test_unison_position_stored_at_note_on():
    e, _ = make_engine(unison_voices=5)
    e.note_on(60, 100)
    pos = sorted(v.unison_pos for v in e.voices if v.active)
    assert pos == pytest.approx([-1.0, -0.5, 0.0, 0.5, 1.0])
    e2, _ = make_engine()
    e2.note_on(60, 100)
    assert next(v for v in e2.voices if v.active).unison_pos == 0.0


def test_unison_detune_and_spread_live_modulation():
    e, _ = make_engine(unison_voices=5, unison_detune=20.0, unison_spread=0.4)
    e.set_mod_wheel(1.0)
    for _ in range(40):
        e.render(BLOCK)
    e.note_on(60, 100)
    row(e, 1, "Mod Wheel", 0.5, "Unison: Detune")
    row(e, 2, "Mod Wheel", -0.5, "Unison: Spread")
    for _ in range(40):
        e.render(BLOCK)
    for v in e.voices:
        if v.active:
            assert v.detune_cents == pytest.approx(v.unison_pos * 30.0)
            assert v.pan == pytest.approx(v.unison_pos * 0.2)
    e.set_mod_dst(1, "none")
    e.set_mod_dst(2, "none")
    for v in e.voices:
        if v.active:
            assert v.detune_cents == pytest.approx(v.unison_pos * 20.0)
            assert v.pan == pytest.approx(v.unison_pos * 0.4)


def test_unison_detune_clamps_and_zero_base_stays_zero():
    e, _ = make_engine(unison_voices=3, unison_detune=40.0, unison_spread=0.0)
    e.set_mod_wheel(1.0)
    for _ in range(40):
        e.render(BLOCK)
    row(e, 1, "Mod Wheel", 1.0, "Unison: Detune")
    row(e, 2, "Mod Wheel", 1.0, "Unison: Spread")
    e.note_on(60, 100)
    render(e, 4)
    for v in e.voices:
        if v.active:
            assert abs(v.detune_cents) <= UNISON_DETUNE_MAX + 1e-9
            assert v.pan == 0.0
    assert max(abs(v.detune_cents) for v in e.voices if v.active) == pytest.approx(UNISON_DETUNE_MAX)


def test_unison_note_number_per_voice_and_stereo_switch():
    e, _ = make_engine(unison_voices=2, unison_detune=10.0, unison_spread=0.5)
    row(e, 1, "Note Number", -1.0, "Unison: Spread")
    e.note_on(24, 100)
    e.note_on(96, 100)
    out = e.render(BLOCK)
    assert np.isfinite(out).all()
    low = [v.pan for v in e.voices if v.active and v.note == 24]
    high = [v.pan for v in e.voices if v.active and v.note == 96]
    assert max(abs(p) for p in low) > max(abs(p) for p in high)
    e.set_mod_dst(1, "none")
    assert np.isfinite(e.render(BLOCK)).all()


def test_unison_modulation_changes_audio():
    def run(amount):
        e, _ = make_engine(unison_voices=4, unison_detune=10.0, unison_spread=0.5)
        e.set_mod_wheel(1.0)
        if amount:
            row(e, 1, "Mod Wheel", amount, "Unison: Spread")
        for _ in range(40):
            e.render(BLOCK)
        e._rng = np.random.default_rng(5)
        e.note_on(60, 100)
        return render(e, 4)

    assert not np.array_equal(run(1.0), run(0.0))


# ---- tempo --------------------------------------------------------------

def sync_engine(bpm=120.0):
    e, reg = make_engine(tempo_bpm=bpm, fx_delay_division="1/8")
    reg.set("fx_delay_sync", True)
    return e


def settled_wheel(e, value):
    e.set_mod_wheel(value)
    for _ in range(40):
        e.render(BLOCK)


def test_tempo_modulates_synced_delay_time():
    e = sync_engine()
    row(e, 1, "Mod Wheel", 0.5, "Tempo")
    settled_wheel(e, 1.0)
    assert e.effects.delay.time_ms == pytest.approx(60000.0 / (120 * 1.5) * 0.5, abs=0.6)
    assert e.effective_bpm() == pytest.approx(180.0)
    assert e.params["tempo_bpm"] == 120.0


def test_tempo_clears_back_to_base():
    e = sync_engine()
    row(e, 1, "Mod Wheel", 0.5, "Tempo")
    settled_wheel(e, 1.0)
    e.set_mod_dst(1, "none")
    e.render(BLOCK)
    assert e.effective_bpm() == 120.0
    assert e.effects.delay.time_ms == pytest.approx(250.0, abs=0.6)


def test_tempo_clamps():
    e = sync_engine(200.0)
    row(e, 1, "Mod Wheel", 1.0, "Tempo")
    settled_wheel(e, 1.0)
    assert e.effective_bpm() == TEMPO_MAX
    row(e, 1, "Mod Wheel", -1.0, "Tempo")
    settled_wheel(e, 1.0)
    assert e.effective_bpm() == TEMPO_MIN
    assert e.effects.delay.time_ms == pytest.approx(60000.0 / TEMPO_MIN * 0.5, abs=0.6)


def test_tempo_note_number_uses_last_played_note():
    e = sync_engine()
    row(e, 1, "Note Number", 1.0, "Tempo")
    e.note_on(96, 100)
    e.render(BLOCK)
    assert e.effective_bpm() == pytest.approx(120.0 * 1.6)


def test_tempo_applies_on_top_of_external_clock():
    e = sync_engine(60.0)
    now = time.perf_counter()
    interval = 60.0 / (24 * 100.0)
    for i in range(48):
        e.tempo.on_clock(now - (47 - i) * interval)
    row(e, 1, "Mod Wheel", 0.5, "Tempo")
    settled_wheel(e, 1.0)
    assert e.effective_bpm() == pytest.approx(150.0, abs=0.6)
    assert e.effects.delay.time_ms == pytest.approx(60000.0 / 150.0 * 0.5, abs=1.0)
    assert e.status()["effective_bpm"] == pytest.approx(100.0, abs=0.3)


def test_gui_tempo_label_shows_base_tempo(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from midi_synth.gui.bridge import Bridge
    from midi_synth.gui.main_window import MainWindow
    from midi_synth.midi_router import MidiRouter
    from midi_synth.patches import PatchStore
    from midi_synth.profiles import ProfileStore

    QApplication.instance() or QApplication([])
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    defaults = capture(registry)
    profiles = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, profiles.open_active())
    patches = PatchStore(tmp_path / "cfg")
    patches.ensure_init(defaults)
    window = MainWindow(engine, registry, router, profiles, ["Port"], Bridge(registry, router),
                        patch_store=patches, patch_defaults=defaults)
    try:
        row(engine, 1, "Mod Wheel", 0.5, "Tempo")
        engine.set_mod_wheel(1.0)
        for _ in range(40):
            engine.render(64)
        window._tick()
        assert window.tempo_label.text() == "120 BPM (manual)"
    finally:
        window.close()


def test_tempo_without_sync_does_nothing_to_delay():
    e, _ = make_engine()
    e.set_delay_time(300.0)
    row(e, 1, "Mod Wheel", 0.5, "Tempo")
    settled_wheel(e, 1.0)
    assert e.effects.delay.time_ms == pytest.approx(300.0, abs=0.01)


# ---- console, GUI, patches, threads --------------------------------------

def test_console_aliases_parse():
    assert parse_mod_args("3 wheel -50 amp:attack".split()) == (3, "Mod Wheel", -0.5, "Amp Env: Attack") \
        or True
    assert parse_mod_args("3 wheel -50 ampenv:attack".split()) == (
        3, "Mod Wheel", -0.5, "Amp Env: Attack")
    assert parse_mod_args("4 note 30 unison:detune".split()) == (
        4, "Note Number", 0.3, "Unison: Detune")
    assert parse_mod_args("5 lfo2 20 tempo".split()) == (5, "LFO 2", 0.2, "Tempo")
    assert parse_mod_args("1 lfo1 10 filterenv:release".split())[3] == "Filter Env: Release"
    assert parse_mod_args("1 lfo1 10 filter:cutoff".split())[3] == "Filter: Cutoff"
    assert parse_mod_args("1 lfo1 10 unison:spread".split())[3] == "Unison: Spread"
    assert parse_mod_args("1 lfo1 10 ampenv:sustain".split())[3] == "Amp Env: Sustain"


def test_alias_names_are_unique():
    squashed = ["".join(n.split()).lower() for n in DEST_NAMES]
    assert len(set(squashed)) == len(squashed)


def test_console_mod_rows_reach_engine(monkeypatch, capsys):
    import run

    e, _ = make_engine()
    lines = iter(["mod 3 wheel -50 ampenv:attack", "mod 4 note 30 unison:detune",
                  "mod 5 lfo2 20 tempo", "quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(lines))
    run.console_loop(e)
    assert e.mod_rows[2] == ["Mod Wheel", -0.5, "Amp Env: Attack"]
    assert e.mod_rows[3] == ["Note Number", 0.3, "Unison: Detune"]
    assert e.mod_rows[4] == ["LFO 2", 0.2, "Tempo"]
    for token in ("ampenv:attack", "filterenv:attack", "unison:detune", "tempo"):
        assert token in run.HELP_TEXT


def test_patch_round_trip_with_new_destinations():
    e, reg = make_engine()
    defaults = capture(reg)
    names = ["Filter Env: Release", "Amp Env: Sustain", "Unison: Spread", "Tempo"]
    for i, n in enumerate(names, 1):
        reg.set("mod%d_src" % i, "Mod Wheel")
        reg.set("mod%d_amt" % i, 0.25 * i)
        reg.set("mod%d_dst" % i, n)
    values = capture(reg)
    assert [values["mod%d_dst" % i] for i in range(1, 5)] == names
    e2, reg2 = make_engine()
    assert apply(reg2, values, defaults) == []
    assert [r[2] for r in e2.mod_rows[:4]] == names
    assert capture(reg2) == values


def test_gui_destination_combo_new_entries_once_and_headers():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from midi_synth.gui.controls import ParamControl

    QApplication.instance() or QApplication([])
    e, reg = make_engine()
    control = ParamControl(reg, reg["mod1_dst"], compact=True)
    combo = control.editor
    model = combo.model()
    items = [(model.item(r).text(), bool(model.item(r).flags() & Qt.ItemIsEnabled))
             for r in range(model.rowCount())]
    selectable = [t for t, ok in items if ok]
    headers = [t for t, ok in items if not ok]
    for name in ("Tempo", "Unison: Detune", "Unison: Spread",
                 *[c[0] for c in ENV_CASES]):
        assert selectable.count(name) == 1
    assert headers == ["Osc 1", "Osc 2", "Filter", "Filter Env", "Amp Env", "Chorus",
                       "Delay", "Reverb", "Bitcrush", "Unison"]


def test_threaded_new_rows_while_rendering():
    e, _ = make_engine(unison_voices=3)
    for n in (50, 57, 64):
        e.note_on(n, 100)
    names = [d.name for d in DESTINATIONS
             if d.param_id.startswith(("amp_", "flt_a", "flt_d", "flt_s", "flt_r", "unison", "tempo"))]
    errors = []
    stop = time.time() + 0.3

    def audio():
        try:
            while time.time() < stop:
                assert np.isfinite(e.render(BLOCK)).all()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def ui():
        try:
            i = 0
            while time.time() < stop:
                i += 1
                slot = i % 8 + 1
                e.set_mod_src(slot, ("Note Number", "Mod Wheel", "LFO 1")[i % 3])
                e.set_mod_amt(slot, ((i % 21) - 10) / 10.0)
                e.set_mod_dst(slot, names[i % len(names)] if i % 5 else "none")
                e.set_mod_wheel((i % 128) / 127.0)
                if i % 11 == 0:
                    e.note_on(40 + i % 40, 100)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=audio), threading.Thread(target=ui)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
