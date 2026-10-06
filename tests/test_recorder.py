import threading
import time
import wave

import numpy as np
import pytest

from midi_synth import recorder as recorder_module
from midi_synth.recorder import Recorder

SR = 44100


def blocks(n_blocks, frames=64, value=0.25):
    return [np.full((frames, 2), value, dtype=np.float32) for _ in range(n_blocks)]


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes(), data


def test_idle_state(tmp_path):
    r = Recorder()
    assert r.active is False and r.path is None
    assert r.frames_written == 0 and r.elapsed == 0.0 and r.overruns == 0


def test_writes_valid_wav_with_exact_frames(tmp_path):
    path = tmp_path / "a.wav"
    r = Recorder()
    r.start(path, SR)
    assert r.active and r.path == path
    for b in blocks(10, 100):
        r.push(b)
    r.stop()
    assert not r.active
    ch, width, rate, frames, data = read_wav(path)
    assert (ch, width, rate, frames) == (2, 2, SR, 1000)
    assert r.frames_written == 1000
    assert np.all(data == int(round(0.25 * 32767)))


def test_interleaving_and_little_endian(tmp_path):
    path = tmp_path / "lr.wav"
    block = np.zeros((4, 2), dtype=np.float32)
    block[:, 0] = 0.5
    block[:, 1] = -0.5
    r = Recorder()
    r.start(path, SR)
    r.push(block)
    r.stop()
    data = read_wav(path)[4]
    assert list(data[0::2]) == [16384] * 4 or list(data[0::2]) == [16383] * 4
    assert list(data[1::2]) == [-16384] * 4 or list(data[1::2]) == [-16383] * 4


def test_clipping(tmp_path):
    path = tmp_path / "clip.wav"
    block = np.array([[2.0, -2.0], [1.0, -1.0], [np.inf, -np.inf]], dtype=np.float32)
    r = Recorder()
    r.start(path, SR)
    r.push(block)
    r.stop()
    data = read_wav(path)[4].reshape(-1, 2)
    assert np.all(data[:, 0] == 32767)
    assert np.all(data[:, 1] <= -32767)


def test_push_copies_block(tmp_path):
    path = tmp_path / "copy.wav"
    r = Recorder()
    r.start(path, SR)
    b = np.full((8, 2), 0.5, dtype=np.float32)
    r.push(b)
    b[:] = 0.0
    r.stop()
    assert np.all(read_wav(path)[4] != 0)


def test_elapsed_from_frames(tmp_path):
    r = Recorder()
    r.start(tmp_path / "e.wav", 1000)
    r.push(np.zeros((500, 2), dtype=np.float32))
    r.stop()
    assert r.elapsed == pytest.approx(0.5)


def test_start_twice_raises_and_stop_idle_is_noop(tmp_path):
    r = Recorder()
    r.stop()
    r.start(tmp_path / "a.wav", SR)
    with pytest.raises(RuntimeError):
        r.start(tmp_path / "b.wav", SR)
    r.stop()
    r.stop()
    assert not (tmp_path / "b.wav").exists()


def test_push_when_idle_is_ignored(tmp_path):
    r = Recorder()
    r.push(np.zeros((8, 2), dtype=np.float32))
    assert r.frames_written == 0 and r.overruns == 0


def test_restart_after_stop(tmp_path):
    r = Recorder()
    r.start(tmp_path / "a.wav", SR)
    r.push(np.zeros((10, 2), dtype=np.float32))
    r.stop()
    r.start(tmp_path / "b.wav", SR)
    assert r.frames_written == 0
    r.push(np.zeros((20, 2), dtype=np.float32))
    r.stop()
    assert read_wav(tmp_path / "b.wav")[3] == 20


def test_start_failure_leaves_recorder_idle(tmp_path):
    r = Recorder()
    with pytest.raises(OSError):
        r.start(tmp_path / "missing_dir" / "x.wav", SR)
    assert not r.active


def test_mono_channels(tmp_path):
    r = Recorder()
    r.start(tmp_path / "m.wav", SR, channels=1)
    r.push(np.full((10, 1), 0.1, dtype=np.float32))
    r.stop()
    assert read_wav(tmp_path / "m.wav")[:4] == (1, 2, SR, 10)


def test_overruns_counted_with_stalled_writer(tmp_path, monkeypatch):
    gate = threading.Event()
    original = recorder_module.Recorder._write_block

    def stalled(self, wav, block):
        gate.wait(5)
        original(self, wav, block)

    monkeypatch.setattr(recorder_module.Recorder, "_write_block", stalled)
    r = Recorder()
    r.start(tmp_path / "o.wav", SR)
    start = time.perf_counter()
    for b in blocks(500, 16):
        r.push(b)
    assert time.perf_counter() - start < 2.0
    assert r.overruns >= 90
    gate.set()
    r.stop()
    assert read_wav(tmp_path / "o.wav")[3] == (500 - r.overruns) * 16


def test_push_never_raises_on_bad_input(tmp_path):
    r = Recorder()
    r.start(tmp_path / "bad.wav", SR)
    r.push(None)
    r.push("junk")
    r.push(np.zeros((4, 2), dtype=np.float32))
    r.stop()
    assert r.overruns >= 1  # the unconvertible block is counted as dropped
    assert read_wav(tmp_path / "bad.wav")[3] == 4


def test_stop_joins_with_timeout_when_writer_hangs(tmp_path, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(recorder_module, "STOP_TIMEOUT", 0.2)
    monkeypatch.setattr(recorder_module.Recorder, "_write_block",
                        lambda self, wav, block: gate.wait(5))
    r = Recorder()
    r.start(tmp_path / "h.wav", SR)
    r.push(np.zeros((4, 2), dtype=np.float32))
    time.sleep(0.05)
    t0 = time.perf_counter()
    r.stop()
    assert time.perf_counter() - t0 < 2.0
    assert not r.active
    gate.set()
