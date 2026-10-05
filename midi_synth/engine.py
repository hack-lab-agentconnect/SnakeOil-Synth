import threading

import numpy as np

from .config import (
    SAMPLE_RATE,
    BLOCK_SIZE,
    MAX_VOICES,
    MODES,
    DEFAULT_MODE,
    DEFAULT_MODE_DEPTH,
    FM_INDEX_MAX,
    PITCH_BEND_RANGE,
    SEMITONE_MIN,
    SEMITONE_MAX,
    CENTS_MIN,
    CENTS_MAX,
    LPF_MODES,
    DEFAULT_PWM,
    DEFAULT_LPF_MODE,
    DEFAULT_LPF_CUTOFF,
    DEFAULT_ADSR,
    DEFAULT_FLT_ENV,
    FIXED_VELOCITY,
    LFO_WAVES,
    LFO_DESTS,
    LFO_RATE_MIN,
    LFO_RATE_MAX,
    DEFAULT_LFO_RATE,
    LFO_PITCH_SEMITONES,
    LFO_FILTER_OCTAVES,
    LFO_PWM_RANGE,
    GLIDE_MAX,
    AMP_TIME_MIN,
    AMP_ATTACK_MAX,
    AMP_DECAY_MAX,
    AMP_RELEASE_MAX,
    UNISON_MAX,
    UNISON_DETUNE_MAX,
    DEFAULT_UNISON_DETUNE,
    DEFAULT_UNISON_SPREAD,
)
from .filters import LowPass, LPF_MIN_HZ, LPF_MAX_HZ, lpf_coefficients
from .lfo import LFO
from .voice import IDLE, Voice, midi_note_to_freq
from .effects import EffectChain


class SynthEngine:
    def __init__(self, sr=SAMPLE_RATE, block_size=BLOCK_SIZE, max_voices=MAX_VOICES):
        self.sr = sr
        self.block_size = block_size
        self.max_voices = max_voices
        self.lock = threading.RLock()
        self.voices = [Voice(sr) for _ in range(max_voices)]
        self.effects = EffectChain(sr)
        self.master_lpf = LowPass(sr)
        self.master_lpf_r = LowPass(sr)
        self.params = {
            "osc1_level": 1.0,
            "osc2_level": 0.0,
            "osc1_square": True,
            "osc1_pwm": DEFAULT_PWM,
            "osc2_pwm": DEFAULT_PWM,
            "mod_mode": DEFAULT_MODE,
            "fm_depth": 0.0,
            "mod_index": 0.0,
            "detune2_semitones": 0.0,
            "detune2_cents": 0.0,
            "osc1_octave_down": False,
            "osc2_octave_up": True,
            "pitch_bend": 0.0,
            "pitch_ratio": 1.0,
            "master_gain": 0.8,
            "lpf_cutoff": DEFAULT_LPF_CUTOFF,
            "lpf_resonance": 0.0,
            "lpf_mode": DEFAULT_LPF_MODE,
            "lpf_coeffs": None,
            "amp_attack": DEFAULT_ADSR["attack"],
            "amp_decay": DEFAULT_ADSR["decay"],
            "amp_sustain": DEFAULT_ADSR["sustain"],
            "amp_release": DEFAULT_ADSR["release"],
            "velocity_on": True,
            "flt_env_amount": 0.0,
            "flt_keytrack": 0.0,
            "flt_vel": 0.0,
            "flt_attack": DEFAULT_FLT_ENV["attack"],
            "flt_decay": DEFAULT_FLT_ENV["decay"],
            "flt_sustain": DEFAULT_FLT_ENV["sustain"],
            "flt_release": DEFAULT_FLT_ENV["release"],
            "lfo_rate": DEFAULT_LFO_RATE,
            "lfo_depth": 0.0,
            "lfo_wave": "sine",
            "lfo_dest": "pitch",
            "glide_time": 0.0,
            "glide_legato": False,
            "unison_voices": 1,
            "unison_detune": DEFAULT_UNISON_DETUNE,
            "unison_spread": DEFAULT_UNISON_SPREAD,
            "lfo_pitch_ratio": 1.0,
            "lfo_filter_oct": 0.0,
            "lfo_pwm": 0.0,
            "lfo_amp": None,
        }
        self.lfo = LFO()
        self._last_freq = None
        self._master_bypassed = False
        self._order = 0
        self._group_counter = 0
        self._rng = np.random.default_rng(1234)
        self.sustain = False
        self._sustained = set()
        self._update_lpf()
        self._apply_envelope()

    def _refresh_derived(self):
        self.params["mod_index"] = self.params["fm_depth"] * FM_INDEX_MAX
        self.params["pitch_ratio"] = 2.0 ** (self.params["pitch_bend"] / 12.0)

    def set_osc1_square(self, on):
        with self.lock:
            self.params["osc1_square"] = bool(on)

    def set_osc1_pwm(self, duty):
        with self.lock:
            self.params["osc1_pwm"] = min(max(float(duty), 0.0), 0.5)

    def set_osc2_pwm(self, duty):
        with self.lock:
            self.params["osc2_pwm"] = min(max(float(duty), 0.0), 0.5)

    def set_osc_levels(self, osc1_level, osc2_level):
        with self.lock:
            self.params["osc1_level"] = min(max(osc1_level, 0.0), 1.0)
            self.params["osc2_level"] = min(max(osc2_level, 0.0), 1.0)

    def set_osc_level(self, osc, level):
        with self.lock:
            key = "osc%d_level" % osc
            if key not in self.params:
                raise KeyError(key)
            self.params[key] = min(max(level, 0.0), 1.0)
            return self.params[key]

    def set_fm_depth(self, depth):
        with self.lock:
            self.params["fm_depth"] = min(max(depth, 0.0), 1.0)
            self._refresh_derived()

    def set_mod_mode(self, mode):
        if mode not in MODES:
            raise ValueError("unknown mode: %r (choose from %s)" % (mode, ", ".join(MODES)))
        with self.lock:
            self.params["mod_mode"] = mode
            if mode != "off" and self.params["fm_depth"] == 0.0:
                self.params["fm_depth"] = DEFAULT_MODE_DEPTH
                self._refresh_derived()
            return mode

    def set_detune2(self, semitones, cents=None):
        with self.lock:
            self.params["detune2_semitones"] = min(
                max(semitones, SEMITONE_MIN), SEMITONE_MAX
            )
            if cents is not None:
                self.params["detune2_cents"] = min(
                    max(cents, CENTS_MIN), CENTS_MAX
                )

    def set_osc1_octave_down(self, on):
        with self.lock:
            self.params["osc1_octave_down"] = bool(on)

    def set_osc2_octave_up(self, on):
        with self.lock:
            self.params["osc2_octave_up"] = bool(on)

    def _update_lpf(self, force_reset=False):
        p = self.params
        was_bypassed = p["lpf_coeffs"] is None
        if p["lpf_cutoff"] >= LPF_MAX_HZ / 1.01:
            p["lpf_coeffs"] = None
        else:
            p["lpf_coeffs"] = lpf_coefficients(p["lpf_cutoff"], p["lpf_resonance"], self.sr)
        if force_reset or was_bypassed != (p["lpf_coeffs"] is None):
            self.master_lpf.reset()
            self.master_lpf_r.reset()
            for v in self.voices:
                v.lpf.reset()

    def set_lpf_cutoff(self, hz):
        with self.lock:
            self.params["lpf_cutoff"] = min(max(float(hz), LPF_MIN_HZ), LPF_MAX_HZ)
            self._update_lpf()

    def set_lpf_resonance(self, resonance):
        with self.lock:
            self.params["lpf_resonance"] = min(max(float(resonance), 0.0), 1.0)
            self._update_lpf()

    def set_lpf_mode(self, mode):
        if mode not in LPF_MODES:
            raise ValueError("unknown filter mode: %r (choose from %s)" % (mode, ", ".join(LPF_MODES)))
        with self.lock:
            self.params["lpf_mode"] = mode
            self._update_lpf(force_reset=True)
            return mode

    def _apply_envelope(self):
        p = self.params
        for v in self.voices:
            v.env.set_shape(p["amp_attack"], p["amp_decay"],
                            p["amp_sustain"], p["amp_release"])
            v.flt_env.set_shape(p["flt_attack"], p["flt_decay"],
                                p["flt_sustain"], p["flt_release"])

    def _set_envelope(self, key, value, lo, hi):
        with self.lock:
            self.params[key] = min(max(float(value), lo), hi)
            self._apply_envelope()

    def set_velocity_on(self, on):
        with self.lock:
            self.params["velocity_on"] = bool(on)

    def _set_unit(self, key, value, lo, hi):
        with self.lock:
            self.params[key] = min(max(float(value), lo), hi)

    def set_flt_env_amount(self, amount):
        self._set_unit("flt_env_amount", amount, -1.0, 1.0)

    def set_flt_keytrack(self, amount):
        self._set_unit("flt_keytrack", amount, 0.0, 1.0)

    def set_flt_vel(self, amount):
        self._set_unit("flt_vel", amount, 0.0, 1.0)

    def set_flt_attack(self, seconds):
        self._set_envelope("flt_attack", seconds, AMP_TIME_MIN, AMP_ATTACK_MAX)

    def set_flt_decay(self, seconds):
        self._set_envelope("flt_decay", seconds, AMP_TIME_MIN, AMP_DECAY_MAX)

    def set_flt_sustain(self, level):
        self._set_envelope("flt_sustain", level, 0.0, 1.0)

    def set_flt_release(self, seconds):
        self._set_envelope("flt_release", seconds, AMP_TIME_MIN, AMP_RELEASE_MAX)

    def set_amp_attack(self, seconds):
        self._set_envelope("amp_attack", seconds, AMP_TIME_MIN, AMP_ATTACK_MAX)

    def set_amp_decay(self, seconds):
        self._set_envelope("amp_decay", seconds, AMP_TIME_MIN, AMP_DECAY_MAX)

    def set_amp_sustain(self, level):
        self._set_envelope("amp_sustain", level, 0.0, 1.0)

    def set_amp_release(self, seconds):
        self._set_envelope("amp_release", seconds, AMP_TIME_MIN, AMP_RELEASE_MAX)

    def _clear_lfo_mod(self):
        p = self.params
        p["lfo_pitch_ratio"] = 1.0
        p["lfo_filter_oct"] = 0.0
        p["lfo_pwm"] = 0.0
        p["lfo_amp"] = None

    def set_lfo_rate(self, hz):
        self._set_unit("lfo_rate", hz, LFO_RATE_MIN, LFO_RATE_MAX)

    def set_lfo_depth(self, depth):
        with self.lock:
            self.params["lfo_depth"] = min(max(float(depth), 0.0), 1.0)
            self._clear_lfo_mod()

    def set_lfo_wave(self, wave):
        if wave not in LFO_WAVES:
            raise ValueError("unknown LFO wave: %r (choose from %s)" % (wave, ", ".join(LFO_WAVES)))
        with self.lock:
            self.params["lfo_wave"] = wave
            return wave

    def set_lfo_dest(self, dest):
        if dest not in LFO_DESTS:
            raise ValueError("unknown LFO destination: %r (choose from %s)" % (dest, ", ".join(LFO_DESTS)))
        with self.lock:
            self.params["lfo_dest"] = dest
            self._clear_lfo_mod()
            return dest

    def set_glide_time(self, seconds):
        self._set_unit("glide_time", seconds, 0.0, GLIDE_MAX)

    def set_glide_legato(self, on):
        with self.lock:
            self.params["glide_legato"] = bool(on)

    def set_unison_voices(self, n):
        try:
            count = int(n)
            if isinstance(n, float) and n != count:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("unison voices must be a whole number 1-%d, got %r"
                             % (UNISON_MAX, n)) from None
        if not 1 <= count <= UNISON_MAX:
            raise ValueError("unison voices must be 1-%d, got %r" % (UNISON_MAX, n))
        with self.lock:
            self.params["unison_voices"] = count
            return count

    def set_unison_detune(self, cents):
        self._set_unit("unison_detune", cents, 0.0, UNISON_DETUNE_MAX)

    def set_unison_spread(self, spread):
        self._set_unit("unison_spread", spread, 0.0, 1.0)

    def set_master_gain(self, gain):
        with self.lock:
            self.params["master_gain"] = min(max(gain, 0.0), 1.5)

    def set_pitch_bend(self, normalized):
        with self.lock:
            self.params["pitch_bend"] = normalized * PITCH_BEND_RANGE
            self._refresh_derived()

    def _allocate_voice(self):
        for v in self.voices:
            if not v.active:
                return v
        return min(self.voices, key=lambda v: (v.gate, v.trigger_order))

    def _allocate_group(self, count):
        """Pick ``count`` voices: idle ones first, then whole stolen groups."""
        chosen = [v for v in self.voices if not v.active][:count]
        if len(chosen) >= count:
            return chosen
        groups = {}
        for i, v in enumerate(self.voices):
            if v.active:
                key = v.group if v.group is not None else ("single", i)
                groups.setdefault(key, []).append(v)
        victims = sorted(
            groups.values(),
            key=lambda g: (any(v.gate for v in g), min(v.trigger_order for v in g)))
        for g in victims:
            chosen.extend(g)
            if len(chosen) >= count:
                break
        return chosen

    def _note_on_unison(self, note, vel, count, glide_from, glide_time):
        p = self.params
        pool = self._allocate_group(count)
        voices = pool[:count]
        for v in pool[count:]:
            v.note_off()
        self._group_counter += 1
        spread_pos = np.linspace(-1.0, 1.0, count)
        gain = 1.0 / np.sqrt(count)
        for v, pos in zip(voices, spread_pos):
            v.note_on(note, vel, self._order, glide_from, glide_time,
                      detune_cents=float(pos * p["unison_detune"]),
                      pan=float(pos * p["unison_spread"]), gain=float(gain),
                      group=self._group_counter, random_phase=True, rng=self._rng)

    def note_on(self, note, velocity=100):
        with self.lock:
            self._sustained.discard(note)
            held = any(v.gate for v in self.voices)
            for v in self.voices:
                if v.active and v.note == note and v.gate:
                    v.gate = False
                    v.env.note_off()
            self._order += 1
            vel = velocity / 127.0 if self.params["velocity_on"] else FIXED_VELOCITY
            count = min(self.params["unison_voices"], self.max_voices)
            if count == 1:
                voice = self._allocate_voice()
            glide_time = self.params["glide_time"]
            glide_from = None
            if (glide_time > 0.0 and self._last_freq is not None
                    and (not self.params["glide_legato"] or held)):
                glide_from = self._last_freq
            self._last_freq = midi_note_to_freq(note)
            if count == 1:
                voice.note_on(note, vel, self._order, glide_from, glide_time)
            else:
                self._note_on_unison(note, vel, count, glide_from, glide_time)

    def note_off(self, note):
        with self.lock:
            if self.sustain:
                self._sustained.add(note)
                return
            for v in self.voices:
                if v.note == note and v.gate:
                    v.note_off()

    def all_notes_off(self):
        with self.lock:
            self._sustained.clear()
            for v in self.voices:
                if v.active:
                    v.note_off()

    def set_sustain(self, on):
        with self.lock:
            on = bool(on)
            self.sustain = on
            if not on:
                deferred, self._sustained = self._sustained, set()
                for v in self.voices:
                    if v.gate and v.note in deferred:
                        v.note_off()

    def panic(self):
        """Silence every voice immediately and clear the sustain state."""
        with self.lock:
            for v in self.voices:
                v.gate = False
                v.env.stage = IDLE
                v.env.level = 0.0
            self._sustained.clear()
            self.sustain = False

    def reset_controllers(self):
        with self.lock:
            self.set_pitch_bend(0.0)
            self.set_sustain(False)

    def active_note_count(self):
        with self.lock:
            return sum(1 for v in self.voices if v.active)

    def set_effect(self, name, enabled):
        with self.lock:
            self.effects.get(name).enabled = bool(enabled)

    def set_chorus_depth(self, a):
        with self.lock:
            self.effects.chorus.set_depth(a)

    def set_delay_time(self, ms):
        with self.lock:
            self.effects.delay.set_time_ms(ms)

    def set_delay_pingpong(self, on):
        with self.lock:
            self.effects.delay.set_pingpong(on)

    def set_reverb_amount(self, v):
        with self.lock:
            self.effects.reverb.set_amount(v)

    def set_crush_amount(self, a):
        with self.lock:
            self.effects.bitcrush.set_amount(a)

    def toggle_effect(self, name):
        with self.lock:
            fx = self.effects.get(name)
            fx.enabled = not fx.enabled
            return fx.enabled

    def _run_lfo(self, n):
        """Advance the LFO one block and publish its per-block modulation.

        Returns True when the destination is the filter.
        """
        p = self.params
        dest = p["lfo_dest"]
        depth = p["lfo_depth"]
        mid, arr = self.lfo.next_block(
            n, self.sr, p["lfo_rate"], p["lfo_wave"], want_array=dest == "amp")
        if dest == "pitch":
            p["lfo_pitch_ratio"] = 2.0 ** (depth * LFO_PITCH_SEMITONES * mid / 12.0)
        elif dest == "filter":
            p["lfo_filter_oct"] = depth * LFO_FILTER_OCTAVES * mid
        elif dest == "pwm":
            p["lfo_pwm"] = depth * LFO_PWM_RANGE * mid
        else:
            p["lfo_amp"] = 1.0 - depth * (0.5 - 0.5 * arr)
        return dest == "filter"

    def _master_lfo_coeffs(self):
        p = self.params
        cutoff = p["lpf_cutoff"] * 2.0 ** p["lfo_filter_oct"]
        cutoff = min(max(cutoff, LPF_MIN_HZ), 0.45 * self.sr)
        if cutoff >= LPF_MAX_HZ / 1.01:
            return None
        return lpf_coefficients(cutoff, p["lpf_resonance"], self.sr)

    def render(self, n=None, apply_effects=True):
        if n is None:
            n = self.block_size
        with self.lock:
            mix = np.zeros(n, dtype=np.float64)
            params = self.params
            lfo_filter = False
            if params["lfo_depth"] > 0.0:
                lfo_filter = self._run_lfo(n)
            panned = []
            stereo = False
            for v in self.voices:
                if v.active:
                    out_v = v.render(n, params)
                    if v.pan != 0.0:
                        stereo = True
                    panned.append((v.pan, out_v))
                    if not stereo:
                        mix += out_v
            coeffs = params["lpf_coeffs"]
            if lfo_filter and params["lpf_mode"] == "master":
                coeffs = self._master_lfo_coeffs()
                if coeffs is None:
                    self._master_bypassed = True
                elif self._master_bypassed:
                    self.master_lpf.reset()
                    self.master_lpf_r.reset()
                    self._master_bypassed = False
            master = coeffs is not None and params["lpf_mode"] == "master"
            if stereo:
                left = np.zeros(n, dtype=np.float64)
                right = np.zeros(n, dtype=np.float64)
                for pan, out_v in panned:
                    left += out_v * (1.0 - max(0.0, pan))
                    right += out_v * (1.0 + min(0.0, pan))
                if master:
                    left = self.master_lpf.process(left, coeffs)
                    right = self.master_lpf_r.process(right, coeffs)
                out = np.vstack([left, right])
            else:
                if master:
                    mix = self.master_lpf.process(mix, coeffs)
                out = np.vstack([mix, mix])
            if apply_effects:
                out = self.effects.process(out)
            out = np.tanh(out * params["master_gain"])
            return np.ascontiguousarray(out.T).astype(np.float32)

    def status(self):
        with self.lock:
            fx = {
                name: getattr(self.effects, name).enabled
                for name in self.effects.order
            }
            return {
                "osc1_level": self.params["osc1_level"],
                "osc1_square": self.params["osc1_square"],
                "osc1_pwm": self.params["osc1_pwm"],
                "osc2_level": self.params["osc2_level"],
                "osc2_pwm": self.params["osc2_pwm"],
                "mod_mode": self.params["mod_mode"],
                "fm_depth": self.params["fm_depth"],
                "detune2_semitones": self.params["detune2_semitones"],
                "detune2_cents": self.params["detune2_cents"],
                "osc1_octave_down": self.params["osc1_octave_down"],
                "osc2_octave_up": self.params["osc2_octave_up"],
                "master_gain": self.params["master_gain"],
                "lpf_cutoff": self.params["lpf_cutoff"],
                "lpf_resonance": self.params["lpf_resonance"],
                "lpf_mode": self.params["lpf_mode"],
                "amp_attack": self.params["amp_attack"],
                "amp_decay": self.params["amp_decay"],
                "amp_sustain": self.params["amp_sustain"],
                "amp_release": self.params["amp_release"],
                "velocity_on": self.params["velocity_on"],
                "flt_env_amount": self.params["flt_env_amount"],
                "flt_keytrack": self.params["flt_keytrack"],
                "flt_vel": self.params["flt_vel"],
                "flt_attack": self.params["flt_attack"],
                "flt_decay": self.params["flt_decay"],
                "flt_sustain": self.params["flt_sustain"],
                "flt_release": self.params["flt_release"],
                "lfo_rate": self.params["lfo_rate"],
                "lfo_depth": self.params["lfo_depth"],
                "lfo_wave": self.params["lfo_wave"],
                "lfo_dest": self.params["lfo_dest"],
                "glide_time": self.params["glide_time"],
                "glide_legato": self.params["glide_legato"],
                "unison_voices": self.params["unison_voices"],
                "unison_detune": self.params["unison_detune"],
                "unison_spread": self.params["unison_spread"],
                "chorus_depth": self.effects.chorus.amount,
                "delay_time": self.effects.delay.time_ms,
                "delay_pingpong": self.effects.delay.pingpong,
                "reverb_amount": self.effects.reverb.mix,
                "crush_amount": self.effects.bitcrush.amount,
                "effects": fx,
                "sustain": self.sustain,
                "active_voices": sum(1 for v in self.voices if v.active),
            }
