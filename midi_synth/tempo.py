"""MIDI clock tracking: turn a stream of 24-ppqn clock pulses into a BPM."""

import statistics
import threading
import time
from collections import deque

from .config import CLOCK_PPQN

HISTORY = 49  # timestamps kept -> 48 intervals
MIN_PULSES = 24  # one beat of clock before the estimate is trusted
TIMEOUT_S = 1.0  # no pulse for this long = no external clock
EMA_ALPHA = 0.2


class TempoTracker:
    """Estimates the external tempo from MIDI clock pulses.

    One writer (the MIDI thread) calls ``on_*``; readers (audio/GUI threads)
    call ``external_bpm`` / ``effective_bpm``. Timestamps come from the caller
    (``time.perf_counter()`` in production) so tests can feed synthetic times.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._stamps = deque(maxlen=HISTORY)
        self._ema = None
        self._bpm = None
        self._last = None
        self.running = False

    def on_clock(self, timestamp):
        with self._lock:
            if self._stamps and timestamp - self._stamps[-1] > TIMEOUT_S:
                self._stamps.clear()
                self._ema = None
                self._bpm = None
            if self._stamps and timestamp <= self._stamps[-1]:
                return
            self._stamps.append(timestamp)
            self._last = timestamp
            if len(self._stamps) < MIN_PULSES:
                return
            stamps = list(self._stamps)
            intervals = [b - a for a, b in zip(stamps, stamps[1:])]
            # The median finds the typical interval and rejects stalls and
            # dropped pulses; the mean of the rest averages out delivery jitter
            # (timestamp noise telescopes, so the error shrinks with window length).
            typical = statistics.median(intervals)
            kept = [d for d in intervals if 0.5 * typical <= d <= 1.5 * typical]
            raw = 60.0 / (CLOCK_PPQN * statistics.fmean(kept))
            if self._ema is None:
                self._ema = raw
            else:
                self._ema += EMA_ALPHA * (raw - self._ema)
            self._bpm = round(self._ema, 1)

    def on_start(self):
        self.running = True

    def on_continue(self):
        self.running = True

    def on_stop(self):
        self.running = False

    def external_bpm(self, now=None):
        if now is None:
            now = time.perf_counter()
        bpm, last = self._bpm, self._last
        if bpm is None or last is None or now - last > TIMEOUT_S:
            return None
        return bpm

    def effective_bpm(self, manual_bpm, now=None):
        external = self.external_bpm(now)
        return manual_bpm if external is None else external
