import numpy as np

TWO_PI = 2.0 * np.pi


class Chorus:
    def __init__(self, sr, enabled=False, mix=0.5, rate=0.5, depth_ms=6.0,
                 base_ms=14.0, feedback=0.15):
        self.sr = sr
        self.enabled = enabled
        self.mix = mix
        self.feedback = feedback
        self.base = base_ms * sr / 1000.0
        self.depth = depth_ms * sr / 1000.0
        self.inc = TWO_PI * rate / sr
        maxlen = int((base_ms + depth_ms + 5.0) * sr / 1000.0) + 4
        self.buf = np.zeros(maxlen, dtype=np.float64)
        self.idx = 0
        self.phase = 0.0

    def process(self, x):
        if not self.enabled:
            return x
        n = len(x)
        out = np.empty(n, dtype=np.float64)
        buf = self.buf
        size = len(buf)
        base = self.base
        depth = self.depth
        fb = self.feedback
        inc = self.inc
        mix = self.mix
        phase = self.phase
        idx = self.idx
        for i in range(n):
            lfo = np.sin(phase)
            delay = base + depth * lfo
            read = idx - delay
            while read < 0.0:
                read += size
            i0 = int(read)
            frac = read - i0
            i1 = i0 + 1
            if i1 >= size:
                i1 = 0
            wet = buf[i0] * (1.0 - frac) + buf[i1] * frac
            buf[idx] = x[i] + wet * fb
            idx += 1
            if idx >= size:
                idx = 0
            phase += inc
            if phase >= TWO_PI:
                phase -= TWO_PI
            out[i] = x[i] + wet * mix
        self.idx = idx
        self.phase = phase
        return out


class Delay:
    def __init__(self, sr, enabled=False, mix=0.35, time_ms=300.0, feedback=0.35,
                 damp=0.25):
        self.sr = sr
        self.enabled = enabled
        self.mix = mix
        self.feedback = feedback
        self.damp = damp
        self.time = time_ms * sr / 1000.0
        maxlen = int(sr * 4.0) + 4
        self.buf = np.zeros(maxlen, dtype=np.float64)
        self.idx = 0
        self.filter = 0.0

    def set_time_ms(self, time_ms):
        self.time = min(max(time_ms, 1.0), 4000.0) * self.sr / 1000.0

    def process(self, x):
        if not self.enabled:
            return x
        n = len(x)
        out = np.empty(n, dtype=np.float64)
        buf = self.buf
        size = len(buf)
        fb = self.feedback
        damp = self.damp
        filt = self.filter
        idx = self.idx
        mix = self.mix
        delay = self.time
        for i in range(n):
            read = idx - delay
            while read < 0.0:
                read += size
            i0 = int(read)
            frac = read - i0
            i1 = i0 + 1
            if i1 >= size:
                i1 = 0
            wet = buf[i0] * (1.0 - frac) + buf[i1] * frac
            filt = wet * (1.0 - damp) + filt * damp
            buf[idx] = x[i] + filt * fb
            idx += 1
            if idx >= size:
                idx = 0
            out[i] = x[i] + wet * mix
        self.idx = idx
        self.filter = filt
        return out


class _Comb:
    def __init__(self, delay, feedback=0.84, damp=0.2):
        self.buf = np.zeros(int(delay), dtype=np.float64)
        self.idx = 0
        self.fb = feedback
        self.damp = damp
        self.filter = 0.0

    def process(self, x):
        buf = self.buf
        y = buf[self.idx]
        self.filter = y * (1.0 - self.damp) + self.filter * self.damp
        buf[self.idx] = x + self.filter * self.fb
        self.idx += 1
        if self.idx >= len(buf):
            self.idx = 0
        return y


class _Allpass:
    def __init__(self, delay, feedback=0.5):
        self.buf = np.zeros(int(delay), dtype=np.float64)
        self.idx = 0
        self.fb = feedback

    def process(self, x):
        buf = self.buf
        y = buf[self.idx]
        buf[self.idx] = x + y * self.fb
        self.idx += 1
        if self.idx >= len(buf):
            self.idx = 0
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

    def process(self, x):
        if not self.enabled:
            return x
        n = len(x)
        out = np.empty(n, dtype=np.float64)
        combs = self.combs
        aps = self.allpasses
        inv = self._inv
        mix = self.mix
        for i in range(n):
            xi = x[i]
            s = 0.0
            for c in combs:
                s += c.process(xi)
            s *= inv
            for a in aps:
                s = a.process(s)
            out[i] = xi + s * mix
        return out


class Bitcrusher:
    def __init__(self, sr, enabled=False, mix=1.0, bits=8, downsample=4):
        self.sr = sr
        self.enabled = enabled
        self.mix = mix
        self.bits = bits
        self.downsample = max(int(downsample), 1)
        self.hold = 0.0
        self.counter = 0

    def process(self, x):
        if not self.enabled:
            return x
        n = len(x)
        out = np.empty(n, dtype=np.float64)
        levels = float(2 ** max(int(self.bits), 1))
        down = self.downsample
        hold = self.hold
        counter = self.counter
        for i in range(n):
            if counter <= 0:
                hold = x[i]
                counter = down
            counter -= 1
            q = np.round(hold * levels) / levels
            out[i] = q
        self.hold = hold
        self.counter = counter
        return out


class EffectChain:
    def __init__(self, sr):
        self.chorus = Chorus(sr)
        self.delay = Delay(sr)
        self.reverb = Reverb(sr)
        self.bitcrush = Bitcrusher(sr)
        self.order = ["chorus", "delay", "reverb", "bitcrush"]

    def get(self, name):
        return getattr(self, name)

    def process(self, x):
        for name in self.order:
            fx = getattr(self, name)
            if fx.enabled:
                x = fx.process(x)
        return x
