import numpy as np
from scipy.signal import lfilter

TWO_PI = 2.0 * np.pi


CHORUS_MAX_DEPTH_MS = 8.0


def _chunks(n, limit):
    """Yield (start, stop) slices of [0, n) no longer than `limit` samples."""
    limit = max(int(limit), 1)
    for start in range(0, n, limit):
        yield start, min(start + limit, n)


def _ring_read(buf, idx, n):
    """Return buf[idx : idx + n] with wrap-around (a copy)."""
    if idx + n <= len(buf):
        return buf[idx:idx + n].copy()
    return buf.take(np.arange(idx, idx + n), mode="wrap")


def _ring_write(buf, idx, vals):
    """Write vals into buf starting at idx with wrap-around."""
    n = len(vals)
    if idx + n <= len(buf):
        buf[idx:idx + n] = vals
    else:
        np.put(buf, np.arange(idx, idx + n), vals, mode="wrap")


def _interp_read(buf, idx, n, delay):
    """Fractional-delay read for n samples starting at write position idx.

    `delay` is a scalar or an array of n delays in samples. All n samples are
    read before anything is written, so n must not exceed the shortest delay.
    """
    size = len(buf)
    pos = (idx + np.arange(n)) - delay
    pos = np.where(pos < 0.0, pos + size, pos)
    i0 = pos.astype(np.int64)
    frac = pos - i0
    i1 = i0 + 1
    i1 = np.where(i1 >= size, 0, i1)
    return buf[i0] * (1.0 - frac) + buf[i1] * frac


class Chorus:
    def __init__(self, sr, enabled=False, mix=0.5, rate=0.5, amount=0.3,
                 base_ms=14.0, feedback=0.15):
        self.sr = sr
        self.enabled = enabled
        self.mix = mix
        self.feedback = feedback
        self.base = base_ms * sr / 1000.0
        self.rate = rate
        self.inc = TWO_PI * rate / sr
        self.set_depth(amount)
        maxlen = int((base_ms + CHORUS_MAX_DEPTH_MS + 5.0) * sr / 1000.0) + 4
        self.buf = np.zeros(maxlen, dtype=np.float64)
        self.idx = 0
        self.phase = 0.0

    def set_depth(self, a):
        self.amount = min(max(float(a), 0.0), 1.0)
        self.depth = self.amount * CHORUS_MAX_DEPTH_MS * self.sr / 1000.0

    def process(self, x):
        if not self.enabled:
            return x
        n = len(x)
        out = np.empty(n, dtype=np.float64)
        limit = int(self.base - self.depth) - 2
        for a, b in _chunks(n, limit):
            out[a:b] = self._process_chunk(x[a:b])
        return out

    def _process_chunk(self, x):
        n = len(x)
        buf = self.buf
        idx = self.idx
        phases = self.phase + self.inc * np.arange(n)
        delay = self.base + self.depth * np.sin(phases)
        wet = _interp_read(buf, idx, n, delay)
        _ring_write(buf, idx, x + wet * self.feedback)
        self.idx = (idx + n) % len(buf)
        self.phase = float(np.mod(self.phase + self.inc * n, TWO_PI))
        return x + wet * self.mix


class Delay:
    def __init__(self, sr, enabled=False, mix=0.35, time_ms=300.0, feedback=0.35,
                 damp=0.25):
        self.sr = sr
        self.enabled = enabled
        self.mix = mix
        self.feedback = feedback
        self.damp = damp
        self.time_ms = time_ms
        self.time = time_ms * sr / 1000.0
        maxlen = int(sr * 4.0) + 4
        self.buf = np.zeros(maxlen, dtype=np.float64)
        self.idx = 0
        self.filter = 0.0

    def set_time_ms(self, time_ms):
        self.time_ms = min(max(float(time_ms), 1.0), 4000.0)
        self.time = self.time_ms * self.sr / 1000.0

    def process(self, x):
        if not self.enabled:
            return x
        n = len(x)
        out = np.empty(n, dtype=np.float64)
        for a, b in _chunks(n, int(self.time)):
            out[a:b] = self._process_chunk(x[a:b])
        return out

    def _process_chunk(self, x):
        n = len(x)
        buf = self.buf
        idx = self.idx
        damp = self.damp
        wet = _interp_read(buf, idx, n, self.time)
        filt, _ = lfilter([1.0 - damp], [1.0, -damp], wet,
                          zi=[damp * self.filter])
        _ring_write(buf, idx, x + filt * self.feedback)
        self.idx = (idx + n) % len(buf)
        self.filter = float(filt[-1])
        return x + wet * self.mix


class _Comb:
    def __init__(self, delay, feedback=0.84, damp=0.2):
        self.buf = np.zeros(int(delay), dtype=np.float64)
        self.idx = 0
        self.fb = feedback
        self.damp = damp
        self.filter = 0.0

    def process(self, x):
        """Process a block no longer than the buffer; returns the delayed read."""
        n = len(x)
        buf = self.buf
        damp = self.damp
        y = _ring_read(buf, self.idx, n)
        filt, _ = lfilter([1.0 - damp], [1.0, -damp], y,
                          zi=[damp * self.filter])
        _ring_write(buf, self.idx, x + filt * self.fb)
        self.idx = (self.idx + n) % len(buf)
        self.filter = float(filt[-1])
        return y


class _Allpass:
    def __init__(self, delay, feedback=0.5):
        self.buf = np.zeros(int(delay), dtype=np.float64)
        self.idx = 0
        self.fb = feedback

    def process(self, x):
        """Process a block no longer than the buffer."""
        n = len(x)
        buf = self.buf
        y = _ring_read(buf, self.idx, n)
        _ring_write(buf, self.idx, x + y * self.fb)
        self.idx = (self.idx + n) % len(buf)
        return y - x


class Reverb:
    def __init__(self, sr, enabled=False, mix=0.3, room=0.84, damp=0.25,
                 scale=1.0):
        self.sr = sr
        self.enabled = enabled
        self.mix = mix
        self.room = room
        self.damp = damp
        comb_delays = [1116, 1188, 1277, 1356, 1422, 1491]
        ap_delays = [556, 441, 341]
        k = sr / 44100.0 * scale
        self.combs = [_Comb(d * k, room, damp) for d in comb_delays]
        self.allpasses = [_Allpass(d * k, 0.5) for d in ap_delays]
        self._inv = 1.0 / len(self.combs)

    def set_amount(self, v):
        self.mix = min(max(float(v), 0.0), 1.0)

    def process(self, x):
        if not self.enabled:
            return x
        n = len(x)
        out = np.empty(n, dtype=np.float64)
        limit = min(len(u.buf) for u in self.combs + self.allpasses)
        for a, b in _chunks(n, limit):
            out[a:b] = self._process_chunk(x[a:b])
        return out

    def _process_chunk(self, x):
        s = np.zeros(len(x), dtype=np.float64)
        for c in self.combs:
            s += c.process(x)
        s *= self._inv
        for a in self.allpasses:
            s = a.process(s)
        return x + s * self.mix


class Bitcrusher:
    def __init__(self, sr, enabled=False, mix=1.0, bits=8, downsample=4):
        self.sr = sr
        self.enabled = enabled
        self.mix = mix
        self.bits = bits
        self.downsample = max(int(downsample), 1)
        self.hold = 0.0
        self.counter = 0
        self.amount = 0.5

    def set_amount(self, a):
        self.amount = min(max(float(a), 0.0), 1.0)
        self.bits = max(2, int(round(16 - 16 * self.amount)))
        self.downsample = max(1, int(round(1 + 6 * self.amount)))

    def process(self, x):
        if not self.enabled:
            return x
        n = len(x)
        if n == 0:
            return np.empty(0, dtype=np.float64)
        levels = float(2 ** max(int(self.bits), 1))
        down = self.downsample
        counter = self.counter
        first = counter if counter > 0 else 0
        refresh = np.arange(first, n, down)
        if len(refresh):
            src = np.full(n, -1, dtype=np.int64)
            src[refresh] = refresh
            src = np.maximum.accumulate(src)
            held = np.where(src >= 0, x[np.maximum(src, 0)], self.hold)
            self.counter = down - n + int(refresh[-1])
        else:
            held = np.full(n, self.hold, dtype=np.float64)
            self.counter = counter - n
        self.hold = float(held[-1])
        return np.round(held * levels) / levels


class EffectChain:
    def __init__(self, sr):
        self.chorus = Chorus(sr)
        self.delay = Delay(sr)
        self.reverb = Reverb(sr)
        self.bitcrush = Bitcrusher(sr)
        self.bitcrush.set_amount(0.5)
        self.order = ["chorus", "delay", "reverb", "bitcrush"]

    def get(self, name):
        return getattr(self, name)

    def process(self, x):
        for name in self.order:
            fx = getattr(self, name)
            if fx.enabled:
                x = fx.process(x)
        return x
