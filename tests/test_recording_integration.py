import builtins
import os
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from midi_synth.recorder import Recorder, recording_path
from run import CallbackState, console_loop, render_into


class GoodEngine:
    sr = 44100

    def render(self, frames):
        return np.full((frames, 2), 0.25, dtype=np.float32)


class RaisingRecorder:
    active = True

    def push(self, block):
        raise RuntimeError("recorder exploded")


def test_callback_state_has_optional_recorder():
    assert CallbackState().recorder is None


def test_render_into_pushes_engine_block_when_active(tmp_path):
    rec = Recorder()
    rec.start(tmp_path / "cb.wav", 44100)
    state = CallbackState()
    state.recorder = rec
    out = np.zeros((32, 2), dtype=np.float32)
    for _ in range(3):
        render_into(out, GoodEngine(), 32, state)
    rec.stop()
    assert np.all(out == 0.25)
    with wave.open(str(tmp_path / "cb.wav"), "rb") as w:
        assert w.getnframes() == 96 and w.getnchannels() == 2


def test_render_into_does_not_push_when_inactive():
    class Spy:
        active = False
        pushed = 0

        def push(self, block):
            self.pushed += 1

    state = CallbackState()
    state.recorder = Spy()
    render_into(np.zeros((8, 2), dtype=np.float32), GoodEngine(), 8, state)
    assert state.recorder.pushed == 0


def test_render_into_pushes_stereo_block_for_wider_output():
    seen = []

    class Spy:
        active = True

        def push(self, block):
            seen.append(block)

    state = CallbackState()
    state.recorder = Spy()
    out = np.zeros((8, 4), dtype=np.float32)
    render_into(out, GoodEngine(), 8, state)
    assert seen[0].shape == (8, 2) and seen[0].dtype == np.float32


def test_render_into_never_raises_when_push_raises(capsys):
    state = CallbackState()
    state.recorder = RaisingRecorder()
    out = np.ones((8, 2), dtype=np.float32)
    render_into(out, GoodEngine(), 8, state)
    render_into(out, GoodEngine(), 8, state)
    assert capsys.readouterr().out.count("recorder exploded") == 1


def test_recording_path_format_and_uniqueness(tmp_path):
    import datetime

    now = datetime.datetime(2026, 10, 5, 14, 3, 9)
    p = recording_path(tmp_path, now)
    assert p == tmp_path / "recordings" / "snakeoil-20261005-140309.wav"
    assert p.parent.is_dir()
    p.write_bytes(b"x")
    assert recording_path(tmp_path, now) == (
        tmp_path / "recordings" / "snakeoil-20261005-140309-1.wav")


# ---- console ------------------------------------------------------------

def drive(monkeypatch, capsys, lines, recorder, config_dir):
    feed = iter(list(lines) + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    console_loop(GoodEngine(), recorder=recorder, config_dir=config_dir)
    return capsys.readouterr().out


def test_console_rec_start_stop_with_path(monkeypatch, capsys, tmp_path):
    rec = Recorder()
    target = tmp_path / "sub" / "take one.wav"
    out = drive(monkeypatch, capsys,
                ["rec start %s" % target, "rec stop"], rec, tmp_path)
    assert target.exists() and not rec.active
    assert str(target) in out
    with wave.open(str(target), "rb") as w:
        assert w.getframerate() == 44100 and w.getnchannels() == 2


def test_console_rec_default_path_in_config_dir(monkeypatch, capsys, tmp_path):
    rec = Recorder()
    drive(monkeypatch, capsys, ["rec start"], rec, tmp_path)
    assert rec.path.parent == tmp_path / "recordings"
    assert rec.path.exists()
    rec.stop()


def test_console_rec_usage_and_errors(monkeypatch, capsys, tmp_path):
    rec = Recorder()
    out = drive(monkeypatch, capsys,
                ["rec", "rec banana", "rec stop", "rec start", "rec start"],
                rec, tmp_path)
    assert out.count("usage: rec start [path] | rec stop") == 2
    assert "not recording" in out
    assert "already recording" in out
    rec.stop()


def test_console_rec_without_recorder(monkeypatch, capsys, tmp_path):
    out = drive(monkeypatch, capsys, ["rec start"], None, tmp_path)
    assert "recording unavailable" in out


def test_console_rec_bad_path_reports_error(monkeypatch, capsys, tmp_path):
    rec = Recorder()
    blocker = tmp_path / "file"
    blocker.write_text("x")
    out = drive(monkeypatch, capsys,
                ["rec start %s" % (blocker / "x.wav")], rec, tmp_path)
    assert not rec.active
    assert "bad arguments" not in out and out.strip().splitlines()[-1]


# ---- GUI ----------------------------------------------------------------

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.bridge import Bridge  # noqa: E402
from midi_synth.gui.main_window import MainWindow  # noqa: E402
from midi_synth.midi_router import MidiRouter  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402
from midi_synth.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_window(tmp_path, recorder):
    engine = SynthEngine(sr=48000, block_size=64, max_voices=2)
    registry = build_registry(engine)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, store.open_active())
    return MainWindow(engine, registry, router, store, [], Bridge(registry, router),
                      recorder=recorder)


def test_no_rec_button_without_recorder(qapp, tmp_path):
    window = make_window(tmp_path, None)
    assert window.rec_btn is None


def test_rec_toggle_creates_and_finalises_file(qapp, tmp_path):
    rec = Recorder()
    window = make_window(tmp_path, rec)
    assert window.rec_btn.text() == "Rec" and window.rec_btn.isCheckable()
    window.rec_btn.setChecked(True)
    assert rec.active
    path = Path(rec.path)
    assert path.parent == tmp_path / "cfg" / "recordings"
    assert path.name.startswith("snakeoil-") and path.suffix == ".wav"
    assert str(path) in window.statusBar().currentMessage()
    rec.push(np.zeros((48000, 2), dtype=np.float32))
    import time
    deadline = time.monotonic() + 5.0
    while rec.frames_written == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert rec.frames_written > 0
    window._tick()
    assert window.rec_label.text().startswith("REC")
    window.rec_btn.setChecked(False)
    assert not rec.active
    assert "Saved" in window.statusBar().currentMessage()
    assert str(path) in window.statusBar().currentMessage()
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getframerate(), w.getnframes()) == (2, 48000, 48000)
    assert window.rec_label.text() == ""


def test_rec_start_error_goes_to_status_bar(qapp, tmp_path):
    rec = Recorder()

    def boom(*a, **k):
        raise OSError("disk full")

    rec.start = boom
    window = make_window(tmp_path, rec)
    window.rec_btn.setChecked(True)
    assert not window.rec_btn.isChecked()
    assert "disk full" in window.statusBar().currentMessage()


def test_close_stops_recording(qapp, tmp_path):
    rec = Recorder()
    window = make_window(tmp_path, rec)
    window.rec_btn.setChecked(True)
    window.close()
    assert not rec.active


def test_patch_capture_unaffected_by_recorder(qapp, tmp_path):
    from midi_synth.patches import capture

    window = make_window(tmp_path, Recorder())
    assert "fx_reverb_size" in capture(window.registry)
