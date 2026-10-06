import datetime
import queue
import threading
import wave
from pathlib import Path

import numpy as np

MAX_QUEUED_BLOCKS = 400
STOP_TIMEOUT = 5.0


def recording_path(directory, now=None):
    """Return a fresh `<directory>/recordings/snakeoil-YYYYmmdd-HHMMSS.wav`.

    Creates the recordings folder; adds -1, -2, ... if the name is taken.
    """
    folder = Path(directory) / "recordings"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.datetime.now()).strftime("snakeoil-%Y%m%d-%H%M%S")
    path = folder / (stamp + ".wav")
    n = 0
    while path.exists():
        n += 1
        path = folder / ("%s-%d.wav" % (stamp, n))
    return path


class Recorder:
    """Records audio blocks to a 16-bit PCM WAV file on a background thread.

    `push` is meant for the audio callback: it only copies the block into a
    queue and never blocks or raises. When the writer falls more than
    MAX_QUEUED_BLOCKS behind, blocks are dropped and counted in `overruns`.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._queue = None
        self._thread = None
        self._active = False
        self._path = None
        self._samplerate = 0
        self._channels = 2
        self._frames = 0
        self._overruns = 0
        self.error = None

    @property
    def active(self):
        return self._active

    @property
    def path(self):
        return self._path

    @property
    def frames_written(self):
        return self._frames

    @property
    def overruns(self):
        return self._overruns

    @property
    def elapsed(self):
        if not self._samplerate:
            return 0.0
        return self._frames / self._samplerate

    def problem_summary(self):
        """Describe write errors and dropped blocks; empty when all went well."""
        parts = []
        if self.error is not None:
            parts.append("write error: %s" % self.error)
        if self._overruns:
            parts.append("%d blocks dropped" % self._overruns)
        return "; ".join(parts)

    def start(self, path, samplerate, channels=2):
        with self._lock:
            if self._active:
                raise RuntimeError("already recording to %s" % self._path)
            handle = open(path, "wb")
            try:
                wav = wave.open(handle, "wb")
                wav.setnchannels(channels)
                wav.setsampwidth(2)
                wav.setframerate(int(samplerate))
            except Exception:
                handle.close()
                raise
            self._path = path
            self._samplerate = int(samplerate)
            self._channels = channels
            self._frames = 0
            self._overruns = 0
            self.error = None
            self._queue = queue.SimpleQueue()
            self._thread = threading.Thread(
                target=self._run, args=(wav, handle, self._queue),
                name="wav-recorder", daemon=True)
            self._active = True
            self._thread.start()

    def stop(self):
        with self._lock:
            if not self._active:
                return
            self._active = False
            self._queue.put(None)
            thread = self._thread
        thread.join(STOP_TIMEOUT)

    def push(self, block):
        if not self._active:
            return
        try:
            if self._queue.qsize() > MAX_QUEUED_BLOCKS:
                self._overruns += 1
                return
            self._queue.put(np.array(block, dtype=np.float32, copy=True))
        except Exception:
            self._overruns += 1

    def _run(self, wav, handle, q):
        try:
            while True:
                block = q.get()
                if block is None:
                    break
                try:
                    self._write_block(wav, block)
                except Exception as exc:
                    self.error = exc
        finally:
            try:
                wav.close()
            finally:
                handle.close()

    def _write_block(self, wav, block):
        block = block.reshape(-1, self._channels)
        pcm = np.rint(np.clip(np.nan_to_num(block), -1.0, 1.0) * 32767.0)
        wav.writeframes(pcm.astype("<i2").tobytes())
        self._frames += block.shape[0]
