import math

import numpy as np

from . import noise
from .config import DEFAULT_SQUARE_LEVEL, FORCED_RELEASE_S, FLT_ENV_OCTAVES, FLT_VEL_OCTAVES
from .filters import (
    LADDER_OSC_LEVEL, LADDER_OSC_START, LPF_MAX_HZ, LPF_MIN_HZ, LowPass,
    filter_coefficients,
)

ATTACK, DECAY, SUSTAIN, RELEASE, IDLE = range(5)


class Envelope:
    def __init__(self, sr, attack=0.006, decay=0.120, sustain=0.75, release=0.180):
        self.sr = sr
        self.set_shape(attack, decay, sustain, release)
        self.stage = IDLE
        self.level = 0.0
        self.release_override = None

    def set_shape(self, attack, decay, sustain, release):
        self.attack = max(attack, 1.0 / self.sr)
        self.decay = max(decay, 1.0 / self.sr)
        self.sustain = min(max(sustain, 0.0), 1.0)
        self.release = max(release, 1.0 / self.sr)

    def note_on(self, keep_level=False):
        self.stage = ATTACK
        self.release_override = None
        if self.level >= 1.0 and not keep_level:
            self.level = 0.0

    def note_off(self, release_s=None):
        """Start the release; ``release_s`` overrides the release time until
        the envelope restarts or goes idle."""
        if self.stage != IDLE:
            self.stage = RELEASE
            if release_s is not None:
                self.release_override = max(release_s, 1.0 / self.sr)

    @property
    def active(self):
        return self.stage != IDLE

    @staticmethod
    def _ramp(level, inc, count):
        """Levels after 1..count repeated ``level += inc`` steps (bit-exact)."""
        steps = np.full(count, inc, dtype=np.float64)
        steps[0] += level
        return np.cumsum(steps)

    def process(self, n):
        out = np.empty(n, dtype=np.float64)
        att_inc = 1.0 / (self.attack * self.sr)
        dec_inc = (1.0 - self.sustain) / (self.decay * self.sr)
        release = self.release if self.release_override is None else self.release_override
        rel_inc = 1.0 / (release * self.sr)
        level = self.level
        stage = self.stage
        sustain = self.sustain
        pos = 0
        while pos < n:
            remaining = n - pos
            if stage == ATTACK:
                seg = self._ramp(level, att_inc, remaining)
                hit = seg >= 1.0
                target, nxt = 1.0, DECAY
            elif stage == DECAY:
                seg = self._ramp(level, -dec_inc, remaining)
                hit = seg <= sustain
                target, nxt = sustain, SUSTAIN
            elif stage == RELEASE:
                seg = self._ramp(level, -rel_inc, remaining)
                hit = seg <= 0.0
                target, nxt = 0.0, IDLE
            else:
                out[pos:] = sustain if stage == SUSTAIN else level
                if stage == SUSTAIN:
                    level = sustain
                break
            k = int(np.argmax(hit))
            if hit[k]:
                out[pos:pos + k] = seg[:k]
                out[pos + k] = target
                level = target
                stage = nxt
                if nxt == IDLE:
                    self.release_override = None
                pos += k + 1
            else:
                out[pos:] = seg
                level = float(seg[-1])
                pos = n
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

        self.osc1 = Oscillator(sr, "saw")
        self.osc2 = Oscillator(sr, "square")
        self.env = Envelope(sr)
        self.flt_env = Envelope(sr)
        self.lpf = LowPass(sr)
        self.note = -1
        self.gate = False
        self.freq = 0.0
        self.velocity = 0.0
        self.trigger_order = 0
        self._lpf_bypassed = False
        self.osc_phase = 0.0
        self._eff_cutoff = None
        self.glide_from = None
        self.glide_total = 0.0
        self.glide_pos = 0.0
        self.detune_cents = 0.0
        self.pan = 0.0
        self.gain = 1.0
        self.group = None
        self.unison_pos = 0.0
        self.noise_pos = 0

    @property
    def active(self):
        return self.env.active

    def note_on(self, note, velocity, order, glide_from=None, glide_time=0.0,
                detune_cents=0.0, pan=0.0, gain=1.0, group=None,
                random_phase=False, rng=None, unison_pos=0.0, noise_pos=0,
                stolen=False):
        """Start a note. ``stolen`` retriggers a still-sounding voice without
        resetting phases, filter, noise position or envelope level, so the
        output stays continuous (no pop)."""
        self.note = note
        self.gate = True
        self.freq = midi_note_to_freq(note)
        self.velocity = velocity
        self.trigger_order = order
        if glide_from is not None and glide_time > 0.0:
            self.glide_from = glide_from
            self.glide_total = glide_time
        else:
            self.glide_from = None
            self.glide_total = 0.0
        self.glide_pos = 0.0
        self.detune_cents = detune_cents
        self.pan = pan
        self.gain = gain
        self.group = group
        self.unison_pos = unison_pos
        if stolen:
            self.env.note_on(keep_level=True)
            self.flt_env.level = 0.0
            self.flt_env.note_on()
            return
        self.noise_pos = noise_pos
        if random_phase:
            self.osc1.phase = rng.random()
            self.osc2.phase = rng.random()
        else:
            self.osc1.reset()
            self.osc2.reset()
        self.env.note_on()
        self.flt_env.level = 0.0
        self.flt_env.note_on()
        self.lpf.reset()
        self.osc_phase = 0.0

    def note_off(self):
        self.gate = False
        self.env.note_off()
        self.flt_env.note_off()

    def force_release(self, seconds=FORCED_RELEASE_S):
        """Release quickly (a short linear fade) instead of cutting the voice."""
        self.gate = False
        self.env.note_off(release_s=seconds)
        self.flt_env.note_off()

    def _voice_coeffs(self, n, params):
        """Low-pass coefficients for this block, or None for no filtering.

        Uses the shared coefficients unless a per-voice modulation is active.
        """
        shared = params["lpf_coeffs"]
        self._eff_cutoff = None
        amount = params.get("flt_env_amount", 0.0)
        keytrack = params.get("flt_keytrack", 0.0)
        vel_amt = params.get("flt_vel", 0.0)
        lfo_oct = params.get("lfo_filter_oct", 0.0)
        if not (amount or keytrack or vel_amt or lfo_oct
                or params.get("mod_filter")):
            return shared
        octaves = lfo_oct
        if amount:
            octaves += amount * FLT_ENV_OCTAVES * float(np.mean(self.flt_env.process(n)))
        if keytrack:
            octaves += keytrack * (self.note - 60) / 12.0
        if vel_amt:
            octaves += vel_amt * FLT_VEL_OCTAVES * (self.velocity - 0.5)
        cutoff = params["lpf_cutoff"] * 2.0 ** octaves
        cutoff = min(max(cutoff, LPF_MIN_HZ), 0.45 * self.sr)
        if cutoff >= LPF_MAX_HZ / 1.01:
            return None
        self._eff_cutoff = cutoff
        return filter_coefficients(cutoff, params["lpf_resonance"], self.sr,
                                   params.get("lpf_slope", "12 dB"))

    def _whistle(self, n, resonance, params):
        """The 24 dB filter's self-oscillation: a sine at the effective cutoff.

        Phase-continuous across blocks; fades in over the top of the
        resonance range.
        """
        cutoff = self._eff_cutoff
        if cutoff is None:
            cutoff = min(max(params["lpf_cutoff"], LPF_MIN_HZ), 0.45 * self.sr)
        t = min((resonance - LADDER_OSC_START) / (1.0 - LADDER_OSC_START), 1.0)
        level = LADDER_OSC_LEVEL * t * t * (3.0 - 2.0 * t)
        step = 2.0 * math.pi * cutoff / self.sr
        wave = np.sin(self.osc_phase + step * np.arange(1, n + 1))
        self.osc_phase = (self.osc_phase + step * n) % (2.0 * math.pi)
        return level * wave

    def _noise_chunk(self, n, params):
        """The next ``n`` samples of this voice's noise stream (wrapping)."""
        tbl = noise.table(params.get("noise_color", "white"))
        size = len(tbl)
        pos = self.noise_pos % size
        end = pos + n
        if end <= size:
            chunk = tbl[pos:end]
        else:
            chunk = np.take(tbl, np.arange(pos, end), mode="wrap")
        self.noise_pos = end % size
        return chunk

    def render(self, n, params):
        self.osc1.layer_square = params["osc1_square"]
        self.osc1.square_level = params.get("osc1_square_level", DEFAULT_SQUARE_LEVEL)
        lfo_pwm = params.get("lfo_pwm", 0.0)
        if lfo_pwm:
            self.osc1.duty = min(max(params["osc1_pwm"] + lfo_pwm, 0.0), 0.5)
            self.osc2.duty = min(max(params["osc2_pwm"] + lfo_pwm, 0.0), 0.5)
        else:
            self.osc1.duty = params["osc1_pwm"]
            self.osc2.duty = params["osc2_pwm"]
        base = self.freq
        if self.glide_from is not None:
            centre = self.glide_pos + 0.5 * n / self.sr
            remaining = max(0.0, 1.0 - centre / self.glide_total)
            if remaining > 0.0:
                base = math.exp(math.log(base) + (
                    math.log(self.glide_from) - math.log(base)) * remaining)
            self.glide_pos += n / self.sr
            if self.glide_pos >= self.glide_total:
                self.glide_from = None
        freq = base * params["pitch_ratio"]
        lfo_pitch = params.get("lfo_pitch_ratio", 1.0)
        if lfo_pitch != 1.0:
            freq *= lfo_pitch
        f2 = freq * semitones_to_ratio(
            params["detune2_semitones"], params["detune2_cents"]
        ) * (2.0 if params["osc2_octave_up"] else 1.0)
        f1 = freq * (0.5 if params["osc1_octave_down"] else 1.0)
        if self.detune_cents != 0.0:
            ud = 2.0 ** (self.detune_cents / 1200.0)
            f1 *= ud
            f2 *= ud
        limit = 0.45 * self.sr
        f1 = min(f1, limit)
        f2 = min(f2, limit)
        mode = params["mod_mode"]
        depth = params["fm_depth"]
        level2 = params["osc2_level"]
        audible2 = level2 != 0.0
        if mode == "sync":
            t1 = self.osc1.advance(f1, n)
            mod = self.osc1.shape(t1, f1)
            if audible2:
                sec_free = self.osc2.generate(f2, n)
                ratio = (f2 / f1) if f1 else 1.0
                sec_sync = self.osc2.shape(np.mod(t1 * ratio, 1.0), f2)
                sec = sec_free * (1.0 - depth) + sec_sync * depth
            else:
                self.osc2.advance(f2, n)
        else:
            mod = self.osc1.generate(f1, n)
            if not audible2:
                self.osc2.advance(f2, n)
            elif mode == "fm":
                sec = self.osc2.generate(
                    f2, n, phase_mod=mod * params["mod_index"])
            else:
                sec = self.osc2.generate(f2, n)
                if mode == "am":
                    sec = sec * (1.0 - 0.5 * depth + 0.5 * depth * mod)
                elif mode == "ring":
                    sec = sec * ((1.0 - depth) + depth * mod)
        mix = params["osc1_level"] * mod
        if audible2:
            mix = mix + level2 * sec
        noise_level = params.get("noise_level", 0.0)
        if noise_level > 0.0:
            mix = mix + noise_level * self._noise_chunk(n, params)
        if params["lpf_mode"] == "voice":
            coeffs = self._voice_coeffs(n, params)
            if coeffs is not None:
                if self._lpf_bypassed:
                    self.lpf.reset()
                mix = self.lpf.process(mix, coeffs)
                if (params.get("lpf_slope") == "24 dB"
                        and params["lpf_resonance"] > LADDER_OSC_START):
                    mix = mix + self._whistle(n, params["lpf_resonance"], params)
            self._lpf_bypassed = coeffs is None
        env = self.env.process(n)
        amp = 0.22 * (0.3 + 0.7 * self.velocity)
        out = mix * env * amp
        lfo_amp = params.get("lfo_amp")
        if lfo_amp is not None:
            out = out * lfo_amp
        if self.gain != 1.0:
            out = out * self.gain
        return out
