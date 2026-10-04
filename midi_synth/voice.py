import numpy as np

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

    def note_off(self):
        self.gate = False
        self.env.note_off()

    def render(self, n, params):
        freq = self.freq * params["pitch_ratio"]
        mod = self.osc1.generate(freq, n)
        sec_freq = freq * semitones_to_ratio(
            params["detune2_semitones"], params["detune2_cents"]
        )
        phase_mod = mod * params["mod_index"]
        sec = self.osc2.generate(sec_freq, n, phase_mod=phase_mod)
        mix = params["osc1_level"] * mod + params["osc2_level"] * sec
        env = self.env.process(n)
        amp = 0.22 * (0.3 + 0.7 * self.velocity)
        return mix * env * amp
