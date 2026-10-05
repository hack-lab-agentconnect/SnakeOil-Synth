"""Regression tests for the code-review findings: patch/tempo robustness,
startup patch handling, filter envelope reset, Init protection, recorder
reporting and the delaysync parser."""
import builtins
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import mido
import numpy as np
import pytest

import run
from midi_synth.config import TEMPO_MAX, TEMPO_MIN
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput
from midi_synth.params import build_registry
from midi_synth.patches import PatchError, PatchStore, apply, capture
from midi_synth.recorder import Recorder
from midi_synth.tempo import TempoTracker


def make_registry():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    return engine, build_registry(engine)


def small_engine():
    return SynthEngine(sr=44100, block_size=64, max_voices=1)


@pytest.fixture
def store(tmp_path):
    return PatchStore(tmp_path / "cfg")


def run_console(monkeypatch, capsys, lines, **kwargs):
    feed = iter(list(lines) + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    run.console_loop(**kwargs)
    return capsys.readouterr().out


# ---- 1. bad patch values ---------------------------------------------------

def test_registry_rejects_non_finite_continuous_values():
    _, registry = make_registry()
    before = registry.get("osc1_level")
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            registry.set("osc1_level", bad)
    assert registry.get("osc1_level") == before


def test_apply_skips_nan_and_huge_ints_with_warnings():
    engine, registry = make_registry()
    defaults = capture(registry)
    registry.set("osc1_level", 0.3)
    registry.set("lpf_cutoff", 900.0)
    registry.set("fx_delay", True)
    warnings = apply(registry, {
        "osc1_level": float("nan"), "lpf_cutoff": 10 ** 400,
        "fx_delay": float("nan"), "lfo_rate": float("inf")}, defaults)
    for pid in ("osc1_level", "lpf_cutoff", "fx_delay", "lfo_rate"):
        assert any(pid in w for w in warnings), pid
    assert engine.params["lpf_cutoff"] == pytest.approx(900.0)
    assert engine.effects.delay.enabled is True
    assert np.isfinite(engine.params["lfo_rate"])
    engine.note_on(60, 100)
    assert np.all(np.isfinite(engine.render(64)))


def test_patch_file_with_nan_and_huge_int_loads_with_warnings(store):
    engine, registry = make_registry()
    defaults = capture(registry)
    store.ensure_init(defaults)
    store.save("Bad", {"osc1_level": float("nan"), "lpf_cutoff": 10 ** 400})
    store.set_last_used("Bad")
    warnings, applied = run.load_startup_patch(registry, store, defaults)
    assert any("osc1_level" in w for w in warnings)
    assert any("lpf_cutoff" in w for w in warnings)
    assert np.isfinite(engine.params["osc1_level"])
    engine.note_on(60, 100)
    assert np.all(np.isfinite(engine.render(64)))


def test_startup_helper_survives_arbitrary_exceptions(store):
    class Exploding(PatchStore):
        def load(self, name):
            raise ZeroDivisionError("boom")

    exploding = Exploding(store.directory)
    _, registry = make_registry()
    defaults = capture(registry)
    exploding.ensure_init(defaults)
    exploding.save("X", {})
    warnings, applied = run.load_startup_patch(registry, exploding, defaults, "X")
    assert applied is None
    assert any("boom" in w for w in warnings)
    assert exploding.last_used() == "Init"


# ---- 2. tempo tracker ------------------------------------------------------

def in_range_or_none(value):
    return value is None or TEMPO_MIN <= value <= TEMPO_MAX


def test_tracker_batched_pairs_do_not_raise():
    t = TempoTracker()
    stamp = 10.0
    stamps = [stamp]
    for i in range(48):
        stamp += 0.0001 if i % 2 == 0 else 0.0415
        stamps.append(stamp)
    for s in stamps:
        t.on_clock(s)
    assert in_range_or_none(t.external_bpm(now=stamps[-1]))
    assert in_range_or_none(t.effective_bpm(120.0, now=stamps[-1]))


def test_tracker_interleaved_streams_stay_in_range():
    t = TempoTracker()
    a = [100.0 + i * 60.0 / (24 * 120) for i in range(60)]
    b = [100.003 + i * 60.0 / (24 * 97) for i in range(60)]
    for s in sorted(a + b):
        t.on_clock(s)
        assert in_range_or_none(t.external_bpm(now=s))


@pytest.mark.parametrize("gap", [1e-9, 1e-6, 5.0, 1e6])
def test_tracker_extreme_gaps(gap):
    t = TempoTracker()
    stamp = 1.0
    for _ in range(60):
        t.on_clock(stamp)
        assert in_range_or_none(t.external_bpm(now=stamp))
        stamp += gap
    assert in_range_or_none(t.effective_bpm(120.0, now=stamp - gap))


def test_tracker_ignores_non_finite_timestamps():
    t = TempoTracker()
    t.on_clock(float("nan"))
    t.on_clock(float("inf"))
    assert t.external_bpm(now=0.0) is None


def test_tracker_clamps_output():
    t = TempoTracker()
    t._bpm, t._last = 5000.0, 1.0
    assert t.external_bpm(now=1.0) == TEMPO_MAX
    assert t.effective_bpm(120.0, now=1.0) == TEMPO_MAX
    t._bpm = 1.0
    assert t.external_bpm(now=1.0) == TEMPO_MIN


def test_midi_input_realtime_exception_does_not_escape(capsys):
    midi = MidiInput(small_engine())

    class Bad:
        def __getattr__(self, name):
            def boom(*args):
                raise RuntimeError("tempo exploded")
            return boom

    midi.engine.tempo = Bad()
    for kind in ("clock", "start", "stop", "continue"):
        midi._on_message(mido.Message(kind))
    assert "tempo exploded" in capsys.readouterr().err


# ---- 3. startup patch vs GUI -----------------------------------------------

def test_startup_returns_applied_name(store):
    _, registry = make_registry()
    defaults = capture(registry)
    store.ensure_init(defaults)
    store.save("Lead", {"osc1_level": 0.4})
    assert run.load_startup_patch(registry, store, defaults, "lead") == ([], "Lead")
    assert run.load_startup_patch(registry, store, defaults, "Init") == ([], "Init")


def test_startup_missing_or_corrupt_resets_last_used_to_init(store):
    _, registry = make_registry()
    defaults = capture(registry)
    store.ensure_init(defaults)
    store.save("Lead", {"osc1_level": 0.4})
    lead = (store.patches_dir / "Lead.json").read_bytes()
    warnings, applied = run.load_startup_patch(registry, store, defaults, "missing")
    assert applied is None and warnings
    assert store.last_used() == "Init"
    (store.patches_dir / "Broken.json").write_text("{")
    store.set_last_used("Broken")
    warnings, applied = run.load_startup_patch(registry, store, defaults)
    assert applied is None and warnings
    assert store.last_used() == "Init"
    assert (store.patches_dir / "Lead.json").read_bytes() == lead


def test_startup_nothing_requested_applies_nothing(store):
    _, registry = make_registry()
    assert run.load_startup_patch(registry, store, capture(registry)) == ([], None)


pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from midi_synth.gui.bridge import Bridge  # noqa: E402
from midi_synth.gui.main_window import MainWindow  # noqa: E402
from midi_synth.midi_router import MidiRouter  # noqa: E402
from midi_synth.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_window(tmp_path, patches=None, recorder=None, **kwargs):
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    defaults = capture(registry)
    profiles = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, profiles.open_active())
    if patches is not None:
        patches.ensure_init(defaults)
    return MainWindow(engine, registry, router, profiles, [], Bridge(registry, router),
                      patch_store=patches, patch_defaults=defaults,
                      recorder=recorder, **kwargs)


def ghost_checks(window):
    assert window.patch_box.currentText() == "Init"
    assert window.patch_name == "Init"
    for key in ("save", "rename", "delete"):
        assert not window.patch_btn[key].isEnabled()


def test_gui_ghost_initial_patch_falls_back_to_init(qapp, tmp_path):
    patches = PatchStore(tmp_path / "cfg")
    patches.ensure_init(capture(make_registry()[1]))
    patches.save("Lead", {"osc1_level": 0.4})
    lead = (patches.patches_dir / "Lead.json").read_bytes()
    ghost_checks(make_window(tmp_path, patches, initial_patch="missing"))
    patches.set_last_used("Ghost")
    ghost_checks(make_window(tmp_path, patches))
    assert (patches.patches_dir / "Lead.json").read_bytes() == lead


def test_gui_initial_patch_is_selected(qapp, tmp_path):
    patches = PatchStore(tmp_path / "cfg")
    patches.ensure_init(capture(make_registry()[1]))
    patches.save("Lead", {})
    window = make_window(tmp_path, patches, initial_patch="lead")
    assert window.patch_box.currentText() == "Lead"
    assert window.patch_btn["save"].isEnabled()


def test_gui_reload_with_ghost_name_disables_buttons(qapp, tmp_path):
    window = make_window(tmp_path, PatchStore(tmp_path / "cfg"))
    window._reload_patches("Nope")
    ghost_checks(window)


def test_gui_buttons_disabled_when_nothing_selectable(qapp, tmp_path):
    patches = PatchStore(tmp_path / "cfg")
    patches.save("Other", {})
    window = make_window(tmp_path, patches)
    (patches.patches_dir / "Init.json").unlink()
    window._reload_patches("Init")
    for key in ("save", "rename", "delete"):
        assert not window.patch_btn[key].isEnabled()


# ---- 4. filter envelope carry-over -----------------------------------------

def test_retriggered_voice_starts_filter_attack_from_zero():
    engine = small_engine()
    engine.set_amp_release(0.05)
    engine.set_flt_release(5.0)
    engine.set_flt_attack(0.5)
    engine.set_flt_env_amount(1.0)
    voice = engine.voices[0]
    engine.note_on(60, 100)
    for _ in range(40):
        engine.render(64)
    engine.note_off(60)
    for _ in range(200):
        engine.render(64)
        if not voice.active:
            break
    assert not voice.active
    assert voice.flt_env.level > 0.0
    engine.note_on(60, 100)
    assert voice.flt_env.level == 0.0


def test_panic_resets_filter_envelopes():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    engine.set_flt_env_amount(1.0)
    engine.note_on(60, 100)
    engine.render(64)
    engine.panic()
    for v in engine.voices:
        assert not v.flt_env.active and v.flt_env.level == 0.0


# ---- 5. Init protection ----------------------------------------------------

@pytest.mark.parametrize("name", ["Init", "init", "INIT"])
def test_store_refuses_to_write_init(store, name):
    store.ensure_init({"x": 1})
    with pytest.raises(PatchError):
        store.save(name, {"x": 2})
    with pytest.raises(PatchError):
        store.create_from(name, {"x": 2})
    store.save("Other", {})
    with pytest.raises(PatchError):
        store.duplicate("Other", name)
    assert store.load("Init") == {"x": 1}


def test_create_from_refuses_init_when_missing(store):
    with pytest.raises(PatchError):
        store.create_from("init", {"x": 2})
    assert store.names() == []


def test_reset_init_and_ensure_init_still_write(store):
    store.ensure_init({"x": 1})
    assert store.load("Init") == {"x": 1}
    store.reset_init({"x": 2})
    assert store.load("Init") == {"x": 2}


def test_console_patch_save_init_is_an_error(monkeypatch, capsys, store):
    engine, registry = make_registry()
    defaults = capture(registry)
    store.ensure_init(defaults)
    engine.set_osc_level(1, 0.25)
    kw = dict(engine=engine, registry=registry, patch_store=store,
              patch_defaults=defaults)
    out = run_console(monkeypatch, capsys, ["patch save init"], **kw)
    assert "read-only" in out and "saved patch" not in out
    assert store.load("Init") == defaults


def test_console_patch_reset_restores_init(monkeypatch, capsys, store):
    engine, registry = make_registry()
    defaults = capture(registry)
    store.ensure_init(defaults)
    store._write("Init", {"osc1_level": 0.1})
    kw = dict(engine=engine, registry=registry, patch_store=store,
              patch_defaults=defaults)
    out = run_console(monkeypatch, capsys, ["patch reset"], **kw)
    assert store.load("Init") == defaults
    assert "reset" in out.lower()
    assert "patch reset" in run.HELP_TEXT


# ---- 6. recorder surfacing -------------------------------------------------

def test_console_rec_stop_reports_problems(monkeypatch, capsys, tmp_path):
    rec = Recorder()
    rec.start(tmp_path / "t.wav", 44100)
    rec._overruns = 3
    rec.error = OSError("disk full")
    out = run_console(monkeypatch, capsys, ["rec stop"], engine=small_engine(),
                      recorder=rec, config_dir=tmp_path)
    assert "3 blocks dropped" in out and "disk full" in out


def test_console_rec_start_refuses_existing_file(monkeypatch, capsys, tmp_path):
    rec = Recorder()
    target = tmp_path / "keep.wav"
    target.write_bytes(b"precious")
    out = run_console(monkeypatch, capsys, ["rec start %s" % target],
                      engine=small_engine(), recorder=rec, config_dir=tmp_path)
    assert "exists" in out
    assert not rec.active
    assert target.read_bytes() == b"precious"


def test_gui_rec_stop_warns_about_dropped_blocks_and_errors(qapp, tmp_path):
    rec = Recorder()
    window = make_window(tmp_path, recorder=rec)
    window.rec_btn.setChecked(True)
    rec._overruns = 4
    rec.error = OSError("disk full")
    window.rec_btn.setChecked(False)
    message = window.statusBar().currentMessage()
    assert "4 blocks dropped" in message and "disk full" in message


# ---- 8. delaysync division case -------------------------------------------

class Spy:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def rec(*args):
            self.calls.append((name, args))
        return rec


def test_console_delaysync_division_is_case_insensitive(monkeypatch, capsys):
    feed = iter(["delaysync on 1/4t", "delaysync off 1/8T", "quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    engine = Spy()
    run.console_loop(engine)
    assert ("set_delay_division", ("1/4T",)) in engine.calls
    assert ("set_delay_division", ("1/8T",)) in engine.calls
    assert "usage" not in capsys.readouterr().out
