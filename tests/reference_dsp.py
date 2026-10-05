# Frozen copy of the pre-optimisation DSP implementation, used as the golden
# reference for regression tests. Do not edit.
import numpy as np

from midi_synth.config import DEFAULT_DUTY, LAYER_GAIN, MIN_DUTY
from midi_synth.filters import lpf_coefficients  # noqa: F401  (math is unchanged)
from midi_synth.voice import midi_note_to_freq, semitones_to_ratio

TWO_PI = 2.0 * np.pi


CHORUS_MAX_DEPTH_MS = 8.0


class RefChorus:
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


class RefDelay:
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


class _RefComb:
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


class _RefAllpass:
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


class RefReverb:
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
        self.combs = [_RefComb(d * k, room, damp) for d in comb_delays]
        self.allpasses = [_RefAllpass(d * k, 0.5) for d in ap_delays]
        self._inv = 1.0 / len(self.combs)

    def set_amount(self, v):
        self.mix = min(max(float(v), 0.0), 1.0)

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


class RefBitcrusher:
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


class RefLowPass:
    """Biquad filter (direct form II transposed) that keeps state across blocks."""

    def __init__(self, sr):
        self.sr = sr
        self.z1 = 0.0
        self.z2 = 0.0

    def reset(self):
        self.z1 = 0.0
        self.z2 = 0.0

    def process(self, x, coeffs):
        b0, b1, b2, a1, a2 = coeffs
        z1, z2 = self.z1, self.z2
        samples = x.tolist()
        for i, v in enumerate(samples):
            y = b0 * v + z1
            z1 = b1 * v - a1 * y + z2
            z2 = b2 * v - a2 * y
            samples[i] = y
        self.z1, self.z2 = z1, z2
        return np.array(samples, dtype=np.float64)


ATTACK, DECAY, SUSTAIN, RELEASE, IDLE = range(5)


class RefEnvelope:
    def __init__(self, sr, attack=0.006, decay=0.120, sustain=0.75, release=0.180):
        self.sr = sr
        self.set_shape(attack, decay, sustain, release)
        self.stage = IDLE
        self.level = 0.0

    def set_shape(self, attack, decay, sustain, release):
        self.attack = max(attack, 1.0 / self.sr)
        self.decay = max(decay, 1.0 / self.sr)
        self.sustain = min(max(sustain, 0.0), 1.0)
        self.release = max(release, 1.0 / self.sr)

    def note_on(self):
        self.stage = ATTACK
        if self.level >= 1.0:
            self.level = 0.0

    def note_off(self):
        if self.stage != IDLE:
            self.stage = RELEASE

    @property
    def active(self):
        return self.stage != IDLE

    def process(self, n):
        out = np.empty(n, dtype=np.float64)
        att_inc = 1.0 / (self.attack * self.sr)
        dec_inc = (1.0 - self.sustain) / (self.decay * self.sr)
        rel_inc = 1.0 / (self.release * self.sr)
        level = self.level
        stage = self.stage
        sustain = self.sustain
        for i in range(n):
            if stage == ATTACK:
                level += att_inc
                if level >= 1.0:
                    level = 1.0
                    stage = DECAY
            elif stage == DECAY:
                level -= dec_inc
                if level <= sustain:
                    level = sustain
                    stage = SUSTAIN
            elif stage == SUSTAIN:
                level = sustain
            elif stage == RELEASE:
                level -= rel_inc
                if level <= 0.0:
                    level = 0.0
                    stage = IDLE
            out[i] = level
        self.level = level
        self.stage = stage
        return out


def ref_poly_blep(t, dt):
    out = np.zeros_like(t)
    d = dt if dt > 1e-9 else 1e-9
    m = t < d
    if np.any(m):
        x = t[m] / d
        out[m] = 2.0 * x - x * x - 1.0
    m2 = t > 1.0 - d
    if np.any(m2):
        x = (t[m2] - 1.0) / d
        out[m2] = x * x + 2.0 * x + 1.0
    return out


def ref_saw_wave(t, inc):
    return 2.0 * t - 1.0 - ref_poly_blep(t, inc)


def ref_pulse_wave(t, inc, duty):
    duty = min(max(duty, MIN_DUTY), 0.5)
    s = np.where(t < duty, 1.0, -1.0)
    s = s + ref_poly_blep(t, inc) - ref_poly_blep(np.mod(t - duty, 1.0), inc)
    return (s - (2.0 * duty - 1.0)) / (2.0 - 2.0 * duty)


_WAVEFORMS = ("saw", "square")


class RefOscillator:
    def __init__(self, sr, waveform="saw"):
        if waveform not in _WAVEFORMS:
            raise ValueError("unknown waveform: %r" % (waveform,))
        self.sr = sr
        self.waveform = waveform
        self.phase = 0.0
        self.duty = DEFAULT_DUTY
        self.layer_square = False

    def reset(self):
        self.phase = 0.0

    def _shape(self, t, inc):
        if self.waveform == "saw":
            saw = ref_saw_wave(t, inc)
            if self.layer_square:
                return LAYER_GAIN * (saw + ref_pulse_wave(t, inc, self.duty))
            return saw
        return ref_pulse_wave(t, inc, self.duty)

    def advance(self, freq, n):
        inc = freq / self.sr
        t = np.mod(self.phase + inc * np.arange(n, dtype=np.float64), 1.0)
        self.phase = float(np.mod(self.phase + inc * n, 1.0))
        return t

    def shape(self, t, freq):
        return self._shape(t, freq / self.sr)

    def generate(self, freq, n, phase_mod=None):
        t = self.advance(freq, n)
        if phase_mod is not None:
            t = np.mod(t + phase_mod, 1.0)
        return self._shape(t, freq / self.sr)


class RefVoice:
    def __init__(self, sr):
        self.sr = sr
        self.osc1 = RefOscillator(sr, "saw")
        self.osc2 = RefOscillator(sr, "square")
        self.env = RefEnvelope(sr)
        self.lpf = RefLowPass(sr)
        self.note = -1
        self.gate = False
        self.freq = 0.0
        self.velocity = 0.0
        self.trigger_order = 0

    @property
    def active(self):
        return self.env.active

    def note_on(self, note, velocity, order):
        self.note = note
        self.gate = True
        self.freq = midi_note_to_freq(note)
        self.velocity = velocity
        self.trigger_order = order
        self.osc1.reset()
        self.osc2.reset()
        self.env.note_on()
        self.lpf.reset()

    def note_off(self):
        self.gate = False
        self.env.note_off()

    def render(self, n, params):
        self.osc1.layer_square = params["osc1_square"]
        self.osc1.duty = params["osc1_pwm"]
        self.osc2.duty = params["osc2_pwm"]
        freq = self.freq * params["pitch_ratio"]
        f2 = freq * semitones_to_ratio(
            params["detune2_semitones"], params["detune2_cents"]
        ) * (2.0 if params["osc2_octave_up"] else 1.0)
        f1 = freq * (0.5 if params["osc1_octave_down"] else 1.0)
        limit = 0.45 * self.sr
        f1 = min(f1, limit)
        f2 = min(f2, limit)
        mode = params["mod_mode"]
        depth = params["fm_depth"]
        if mode == "sync":
            t1 = self.osc1.advance(f1, n)
            mod = self.osc1.shape(t1, f1)
            sec_free = self.osc2.generate(f2, n)
            ratio = (f2 / f1) if f1 else 1.0
            sec_sync = self.osc2.shape(np.mod(t1 * ratio, 1.0), f2)
            sec = sec_free * (1.0 - depth) + sec_sync * depth
        elif mode == "fm":
            mod = self.osc1.generate(f1, n)
            sec = self.osc2.generate(f2, n, phase_mod=mod * params["mod_index"])
        else:
            mod = self.osc1.generate(f1, n)
            sec = self.osc2.generate(f2, n)
            if mode == "am":
                sec = sec * (1.0 - 0.5 * depth + 0.5 * depth * mod)
            elif mode == "ring":
                sec = sec * ((1.0 - depth) + depth * mod)
        mix = params["osc1_level"] * mod + params["osc2_level"] * sec
        coeffs = params["lpf_coeffs"]
        if coeffs is not None and params["lpf_mode"] == "voice":
            mix = self.lpf.process(mix, coeffs)
        env = self.env.process(n)
        amp = 0.22 * (0.3 + 0.7 * self.velocity)
        return mix * env * amp
