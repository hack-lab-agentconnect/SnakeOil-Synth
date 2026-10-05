import numpy as np

from .filters import LowPass

ATTACK, DECAY, SUSTAIN, RELEASE, IDLE = range(5)


class Envelope:
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


def midi_note_to_freq(note):
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def semitones_to_ratio(semitones, cents=0.0):
    return 2.0 ** ((semitones + cents / 100.0) / 12.0)


class Voice:
    def __init__(self, sr):
        self.sr = sr
        from .oscillators import Oscillator

        self.osc1 = Oscillator(sr, "sine")
        self.osc2 = Oscillator(sr, "sine")
        self.env = Envelope(sr)
        self.lpf = LowPass(sr)
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
