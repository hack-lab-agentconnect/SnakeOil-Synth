import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import builtins

import mido
import numpy as np
import pytest

from midi_synth.config import (
    DEFAULT_DELAY_DIVISION,
    DELAY_DIVISION_BEATS,
    DELAY_DIVISION_NAMES,
)
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput
from midi_synth.params import CHOICE, CONTINUOUS, TOGGLE, build_registry
from midi_synth.patches import apply, capture
from midi_synth.tempo import TempoTracker


def feed(tracker, bpm, pulses, start=100.0, jitter=0.0, seed=1, mode="stamp"):
    """Feed synthetic clock pulses; returns the timestamp of the last pulse."""
    interval = 60.0 / (24 * bpm)
    rng = np.random.default_rng(seed)
    t = start
    for i in range(pulses):
        if mode == "stamp":
            stamp = start + i * interval + rng.uniform(-jitter, jitter) * interval
        else:
            stamp = t
            t += interval * (1 + rng.uniform(-jitter, jitter))
        tracker.on_clock(stamp)
    return start + (pulses - 1) * interval


# ---- tracker -------------------------------------------------------------


@pytest.mark.parametrize("bpm", [120.0, 90.0, 174.0, 60.0, 200.0])
def test_tracker_reads_steady_tempo(bpm):
    t = TempoTracker()
    last = feed(t, bpm, 60)
    assert t.external_bpm(now=last) == pytest.approx(bpm, abs=0.3)


@pytest.mark.parametrize("bpm", [90.0, 120.0, 174.0])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_tracker_survives_arrival_jitter(bpm, seed):
    """Each pulse arrives up to 15% of an interval early or late."""
    t = TempoTracker()
    last = feed(t, bpm, 240, jitter=0.15, seed=seed)
    assert t.external_bpm(now=last) == pytest.approx(bpm, abs=1.0)


@pytest.mark.parametrize("bpm", [90.0, 120.0, 174.0])
def test_tracker_tolerates_accumulating_interval_jitter(bpm):
    """Independent +/-15% on every interval is a harsher model: the tempo
    still lands within 3 BPM."""
    t = TempoTracker()
    last = feed(t, bpm, 240, jitter=0.15, mode="interval", seed=1)
    assert t.external_bpm(now=last) == pytest.approx(bpm, abs=3.0)


def test_dropped_pulses_do_not_skew_the_tempo():
    t = TempoTracker()
    interval = 60.0 / (24 * 120.0)
    last = 0.0
    for i in range(120):
        if i % 17 == 5:
            continue  # a lost clock byte
        last = 100.0 + i * interval
        t.on_clock(last)
    assert t.external_bpm(now=last) == pytest.approx(120.0, abs=0.5)


def test_reported_value_is_quantised_to_tenths():
    t = TempoTracker()
    last = feed(t, 123.456, 80)
    value = t.external_bpm(now=last)
    assert round(value * 10) == pytest.approx(value * 10)


def test_fewer_than_24_pulses_is_none():
    t = TempoTracker()
    last = feed(t, 120.0, 23)
    assert t.external_bpm(now=last) is None
    t.on_clock(last + 0.5 / 24)
    assert t.external_bpm(now=last + 0.5 / 24) == pytest.approx(120.0, abs=0.3)


def test_no_clock_is_none():
    assert TempoTracker().external_bpm(now=5.0) is None


def test_timeout_falls_back_to_manual():
    t = TempoTracker()
    last = feed(t, 150.0, 60)
    assert t.effective_bpm(100.0, now=last + 0.5) == pytest.approx(150.0, abs=0.3)
    assert t.external_bpm(now=last + 1.01) is None
    assert t.effective_bpm(100.0, now=last + 1.01) == 100.0


def test_external_defaults_to_perf_counter(monkeypatch):
    import midi_synth.tempo as tempo

    t = TempoTracker()
    last = feed(t, 120.0, 40)
    monkeypatch.setattr(tempo.time, "perf_counter", lambda: last + 0.1)
    assert t.external_bpm() == pytest.approx(120.0, abs=0.3)
    monkeypatch.setattr(tempo.time, "perf_counter", lambda: last + 3.0)
    assert t.external_bpm() is None
    assert t.effective_bpm(77.0) == 77.0


def test_gap_restarts_estimate():
    t = TempoTracker()
    last = feed(t, 120.0, 60)
    last2 = feed(t, 80.0, 60, start=last + 5.0)
    assert t.external_bpm(now=last2) == pytest.approx(80.0, abs=0.3)


def test_tempo_change_follows_with_smoothing():
    t = TempoTracker()
    last = feed(t, 100.0, 60)
    last = feed(t, 140.0, 200, start=last + 0.02)
    assert t.external_bpm(now=last) == pytest.approx(140.0, abs=0.5)


def test_start_stop_continue_flags():
    t = TempoTracker()
    assert t.running is False
    t.on_start()
    assert t.running is True
    t.on_stop()
    assert t.running is False
    t.on_continue()
    assert t.running is True


def test_history_is_bounded():
    t = TempoTracker()
    feed(t, 120.0, 500)
    assert len(t._stamps) == 49


# ---- beats table ---------------------------------------------------------


def test_beats_table():
    assert DELAY_DIVISION_NAMES == (
        "1/1", "1/2", "1/2.", "1/4", "1/4.", "1/4T", "1/8", "1/8.", "1/8T",
        "1/16", "1/16.")
    b = DELAY_DIVISION_BEATS
    assert b["1/1"] == 4 and b["1/2"] == 2 and b["1/2."] == 3 and b["1/4"] == 1
    assert b["1/4."] == 1.5 and b["1/4T"] == pytest.approx(2 / 3)
    assert b["1/8"] == 0.5 and b["1/8."] == 0.75 and b["1/8T"] == pytest.approx(1 / 3)
    assert b["1/16"] == 0.25 and b["1/16."] == 0.375
    assert DEFAULT_DELAY_DIVISION == "1/8"


# ---- registry ------------------------------------------------------------


def test_registry_params():
    reg = build_registry(SynthEngine(sr=44100, block_size=64, max_voices=2))
    t = reg["tempo_bpm"]
    assert (t.kind, t.group, t.label, t.minimum, t.maximum, t.fmt, t.scale) == (
        CONTINUOUS, "Tempo", "BPM", 40.0, 240.0, "{:.0f}", "linear")
    assert reg.get("tempo_bpm") == 120.0
    s = reg["fx_delay_sync"]
    assert (s.kind, s.group, s.label, s.under) == (TOGGLE, "Effects", "Sync", "fx_delay_time")
    assert s.tooltip and reg.get("fx_delay_sync") is False
    d = reg["fx_delay_division"]
    assert (d.kind, d.group, d.label, d.under) == (CHOICE, "Effects", "Division", "fx_delay_time")
    assert d.choices == DELAY_DIVISION_NAMES
    assert reg.get("fx_delay_division") == "1/8"
    ids = reg.ids()
    assert ids.index("fx_delay_damp") < ids.index("fx_delay_sync") < ids.index("fx_delay_division")
    assert ids.index("fx_delay_division") < ids.index("fx_reverb")


def test_registry_set_clamps_and_validates():
    e = SynthEngine(sr=44100, block_size=64, max_voices=2)
    reg = build_registry(e)
    reg.set("tempo_bpm", 999)
    assert e.params["tempo_bpm"] == 240.0
    reg.set("tempo_bpm", 1)
    assert e.params["tempo_bpm"] == 40.0
    reg.set("fx_delay_division", "1/4T")
    assert e.params["delay_division"] == "1/4T"
    with pytest.raises(ValueError):
        reg.set("fx_delay_division", "1/3")
    with pytest.raises(ValueError):
        e.set_delay_division("bogus")


def test_patch_round_trip_includes_tempo_params():
    e = SynthEngine(sr=44100, block_size=64, max_voices=2)
    reg = build_registry(e)
    defaults = capture(reg)
    for pid in ("tempo_bpm", "fx_delay_sync", "fx_delay_division"):
        assert pid in defaults
    reg.set("tempo_bpm", 90.0)
    reg.set("fx_delay_sync", True)
    reg.set("fx_delay_division", "1/8.")
    values = capture(reg)
    reg.set("tempo_bpm", 150.0)
    reg.set("fx_delay_sync", False)
    reg.set("fx_delay_division", "1/1")
    assert apply(reg, values, defaults) == []
    assert capture(reg) == values


def test_status_reports_tempo_fields():
    e = SynthEngine(sr=44100, block_size=64, max_voices=2)
    s = e.status()
    assert s["tempo_bpm"] == 120.0 and s["delay_sync"] is False
    assert s["delay_division"] == "1/8" and s["effective_bpm"] == 120.0
    e.set_tempo_bpm(100.0)
    assert e.status()["effective_bpm"] == 100.0


# ---- engine sync ---------------------------------------------------------


def make_engine():
    return SynthEngine(sr=44100, block_size=64, max_voices=2)


def test_sync_sets_delay_time():
    e = make_engine()
    e.set_delay_sync(True)
    e.render()
    assert e.effects.delay.time_ms == pytest.approx(250.0)
    e.set_tempo_bpm(60.0)
    e.set_delay_division("1/4")
    e.render()
    assert e.effects.delay.time_ms == pytest.approx(1000.0)
    e.set_tempo_bpm(120.0)
    e.set_delay_division("1/4T")
    e.render()
    assert e.effects.delay.time_ms == pytest.approx(1000.0 / 3.0, abs=0.5)
    e.set_delay_division("1/8.")
    e.render()
    assert e.effects.delay.time_ms == pytest.approx(375.0)


def test_sync_clamps_to_4000():
    e = make_engine()
    e.set_tempo_bpm(40.0)
    e.set_delay_division("1/1")
    e.set_delay_sync(True)
    e.render()
    assert e.effects.delay.time_ms == 4000.0


def test_sync_off_restores_manual_time():
    e = make_engine()
    e.set_delay_time(420.0)
    e.set_delay_sync(True)
    e.render()
    assert e.effects.delay.time_ms == pytest.approx(250.0)
    reg = build_registry(e)
    assert reg.get("fx_delay_time") == pytest.approx(420.0)
    e.set_delay_sync(False)
    assert e.effects.delay.time_ms == pytest.approx(420.0)
    e.render()
    assert e.effects.delay.time_ms == pytest.approx(420.0)


def test_manual_time_set_while_synced_applies_on_unsync():
    e = make_engine()
    e.set_delay_sync(True)
    e.set_delay_time(900.0)
    e.render()
    assert e.effects.delay.time_ms == pytest.approx(250.0)
    e.set_delay_sync(False)
    assert e.effects.delay.time_ms == pytest.approx(900.0)


def test_sync_off_leaves_delay_untouched(monkeypatch):
    e = make_engine()
    calls = []
    monkeypatch.setattr(e.effects.delay, "set_time_ms", lambda ms: calls.append(ms))
    for _ in range(5):
        e.render()
    assert calls == []


def test_no_repeated_set_time_calls():
    e = make_engine()
    calls = []
    real = e.effects.delay.set_time_ms

    def spy(ms):
        calls.append(ms)
        real(ms)

    e.effects.delay.set_time_ms = spy
    e.set_delay_sync(True)
    for _ in range(20):
        e.render()
    assert len(calls) == 1
    e.set_tempo_bpm(121.0)  # 247.9 ms: moved by more than 0.5 ms
    e.render()
    e.render()
    assert len(calls) == 2
    e.set_tempo_bpm(120.9)  # ~0.2 ms away from the current value: ignored
    e.render()
    assert len(calls) == 2


def test_external_clock_overrides_manual_bpm():
    import time

    e = make_engine()
    e.set_tempo_bpm(60.0)
    e.set_delay_sync(True)
    now = time.perf_counter()
    interval = 60.0 / (24 * 150.0)
    for i in range(48):
        e.tempo.on_clock(now - (47 - i) * interval)
    e.render()
    assert e.effects.delay.time_ms == pytest.approx(200.0, abs=0.6)  # 1/8 at 150 BPM
    assert e.status()["effective_bpm"] == pytest.approx(150.0, abs=0.3)
    assert e.params["tempo_bpm"] == 60.0


def test_sync_does_not_change_knob_value():
    e = make_engine()
    reg = build_registry(e)
    reg.set("fx_delay_time", 700.0)
    reg.set("fx_delay_sync", True)
    e.render()
    assert reg.get("fx_delay_time") == pytest.approx(700.0)


# ---- MidiInput -----------------------------------------------------------


def test_midi_input_forwards_clock_messages():
    e = make_engine()
    midi = MidiInput(e)
    midi._on_message(mido.Message("start"))
    assert e.tempo.running is True
    midi._on_message(mido.Message("stop"))
    assert e.tempo.running is False
    midi._on_message(mido.Message("continue"))
    assert e.tempo.running is True
    stamps = []
    e.tempo.on_clock = stamps.append
    midi._on_message(mido.Message("clock"))
    assert len(stamps) == 1 and isinstance(stamps[0], float)


def test_midi_input_clock_ignores_channel_filter():
    e = make_engine()
    midi = MidiInput(e, channel=3)
    midi._on_message(mido.Message("start"))
    assert e.tempo.running is True
    for _ in range(30):
        midi._on_message(mido.Message("clock"))
    midi._on_message(mido.Message("stop"))
    assert e.tempo.running is False


def test_midi_input_clock_skips_router_and_callback():
    e = make_engine()
    midi = MidiInput(e)

    class Boom:
        def __getattr__(self, name):
            raise AssertionError("router used for clock")

    midi.router = Boom()
    midi._on_message(mido.Message("clock"))
    midi._on_message(mido.Message("start"))


# ---- console -------------------------------------------------------------


def run_console(monkeypatch, engine, lines):
    import run

    it = iter(list(lines) + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(it))
    run.console_loop(engine)


def test_console_tempo_and_delaysync(monkeypatch, capsys):
    e = make_engine()
    run_console(monkeypatch, e, ["tempo 95", "delaysync on 1/4.", "delaysync off"])
    assert e.params["tempo_bpm"] == 95.0
    assert e.params["delay_sync"] is False
    assert e.params["delay_division"] == "1/4."
    run_console(monkeypatch, e, ["delaysync on"])
    assert e.params["delay_sync"] is True and e.params["delay_division"] == "1/4."


def test_console_delaysync_bad_division_prints_usage(monkeypatch, capsys):
    e = make_engine()
    run_console(monkeypatch, e, ["delaysync on 1/3", "delaysync maybe", "tempo"])
    out = capsys.readouterr().out
    assert e.params["delay_sync"] is False
    assert out.count("usage: delaysync") == 2
    assert "usage: tempo" in out


def test_help_mentions_new_commands():
    import run

    assert "tempo <" in run.HELP_TEXT and "delaysync <on|off>" in run.HELP_TEXT


# ---- GUI -----------------------------------------------------------------


def make_window(tmp_path):
    from PySide6.QtWidgets import QApplication

    from midi_synth.gui.bridge import Bridge
    from midi_synth.gui.main_window import MainWindow
    from midi_synth.midi_router import MidiRouter
    from midi_synth.profiles import ProfileStore

    QApplication.instance() or QApplication([])
    engine = make_engine()
    registry = build_registry(engine)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, store.open_active())
    bridge = Bridge(registry, router)
    window = MainWindow(engine, registry, router, store, [], bridge)
    return engine, registry, window


def test_gui_tempo_group_and_label(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QGroupBox

    engine, registry, window = make_window(tmp_path)
    assert set(window.controls) == {p.id for p in registry if p.group != "Mod Matrix"}
    box = next(b for b in window.findChildren(QGroupBox) if b.title() == "Tempo")
    assert window.controls["tempo_bpm"].parent() is box
    assert window.tempo_label.parent() is box
    from midi_synth.gui.main_window import GROUP_POSITIONS

    assert GROUP_POSITIONS["Tempo"] not in [
        v for k, v in GROUP_POSITIONS.items() if k != "Tempo"]
    window._tick()
    assert window.tempo_label.text() == "120 BPM (manual)"
    engine.set_tempo_bpm(97.0)
    window._tick()
    assert window.tempo_label.text() == "97 BPM (manual)"


def test_gui_tempo_label_follows_external_clock(tmp_path):
    import time

    pytest.importorskip("PySide6")
    engine, _, window = make_window(tmp_path)
    now = time.perf_counter()
    interval = 60.0 / (24 * 133.0)
    for i in range(48):
        engine.tempo.on_clock(now - (47 - i) * interval)
    window._tick()
    assert window.tempo_label.text() == "133.0 BPM (MIDI clock)"


def test_gui_delay_block_layout(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QGroupBox

    _, _, window = make_window(tmp_path)
    box = next(b for b in window.findChildren(QGroupBox) if b.title() == "Effects")
    layout = box.layout()

    def rc(pid):
        return layout.getItemPosition(layout.indexOf(window.controls[pid]))[:2]

    d = rc("fx_delay")[1]
    assert rc("fx_delay_sync") == (1, d + 4)
    assert rc("fx_delay_division") == (1, d + 5)


# ---- golden --------------------------------------------------------------


def test_default_render_unchanged_by_tempo_machinery():
    a, b = make_engine(), make_engine()
    b.set_tempo_bpm(200.0)
    b.set_delay_division("1/16")  # sync stays off
    for e in (a, b):
        e.set_effect("delay", True)
        e.note_on(60, 100)
    for _ in range(10):
        assert np.array_equal(a.render(), b.render())
