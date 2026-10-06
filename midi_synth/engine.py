import math
import threading

import numpy as np

from .config import (
    CLIP_THRESHOLD,
    LIMITER_SILENCE_S,
    LIMITER_SILENCE_THRESHOLD,
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
    LPF_SLOPES,
    DEFAULT_LPF_SLOPE,
    DEFAULT_PWM,
    DEFAULT_SQUARE_LEVEL,
    DEFAULT_LPF_MODE,
    DEFAULT_LPF_CUTOFF,
    DEFAULT_ADSR,
    DEFAULT_FLT_ENV,
    FIXED_VELOCITY,
    LFO_WAVES,
    LFO1_DESTS,
    LFO2_DESTS,
    LFO_RATE_MOD_OCTAVES,
    LFO_RATE_FLOOR,
    LFO_RATE_CEIL,
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
    TEMPO_MIN,
    TEMPO_MAX,
    DEFAULT_TEMPO,
    DELAY_DIVISION_BEATS,
    DEFAULT_DELAY_DIVISION,
    MOD_SMOOTH,
)
from .filters import LowPass, LPF_MIN_HZ, LPF_MAX_HZ, filter_coefficients
from . import noise
from .lfo import LFO
from .voice import IDLE, Voice, midi_note_to_freq
from .effects import EffectChain
from .limiter import Limiter
from .tempo import TempoTracker
from .modmatrix import (
    DEST_NAMES,
    NUM_SLOTS,
    SOURCES,
    SRC_AFTERTOUCH,
    SRC_LFO1,
    SRC_LFO2,
    SRC_NOTE,
    SRC_WHEEL,
    DELAY_TIME_PARAM,
    ENVELOPE_PARAMS,
    FX_PARAMS,
    TEMPO_PARAM,
    UNISON_PARAMS,
    destination,
    effective,
    note_source,
    smooth,
)


def _victim_key(group):
    """Steal order for a voice group: released and quiet first, then oldest."""
    oldest = min(v.trigger_order for v in group)
    if any(v.gate for v in group):
        return (True, 0.0, oldest)
    return (False, sum(v.env.level for v in group), oldest)


class SynthEngine:
    def __init__(self, sr=SAMPLE_RATE, block_size=BLOCK_SIZE, max_voices=MAX_VOICES,
                 tail_slots=0, tail_capacity=None):
        """``max_voices`` is the number of playable (held) voices. The pool
        also has ``tail_capacity`` extra voices for released tails (default:
        ``tail_slots``), of which ``tail_slots`` are in use."""
        self.sr = sr
        self.block_size = block_size
        self.max_voices = max_voices
        capacity = max(int(tail_slots if tail_capacity is None else tail_capacity), 0)
        self.tail_capacity = capacity
        self.tail_slots = min(max(int(tail_slots), 0), capacity)
        self.steal_count = 0
        self.forced_releases = 0
        self.lock = threading.RLock()
        self._meter_post = np.zeros(2)
        self._meter_clip = False
        self._limiter = Limiter(sr)
        self._limiter_silent_s = 0.0
        self.last_driven_peak = 0.0
        self.voices = [Voice(sr) for _ in range(max_voices + capacity)]
        self.effects = EffectChain(sr)
        self.master_lpf = LowPass(sr)
        self.master_lpf_r = LowPass(sr)
        self.params = {
            "osc1_level": 1.0,
            "osc2_level": 0.0,
            "noise_level": 0.0,
            "noise_color": "white",
            "osc1_square": True,
            "osc1_square_level": DEFAULT_SQUARE_LEVEL,
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
            "lpf_slope": DEFAULT_LPF_SLOPE,
            "lpf_coeffs": None,
            "amp_attack": DEFAULT_ADSR["attack"],
            "amp_decay": DEFAULT_ADSR["decay"],
            "amp_sustain": DEFAULT_ADSR["sustain"],
            "amp_release": DEFAULT_ADSR["release"],
            "velocity_on": True,
            "auto_limiter": False,
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
            "lfo2_rate": DEFAULT_LFO_RATE,
            "lfo2_depth": 0.0,
            "lfo2_wave": "sine",
            "lfo2_dest": "filter",
            "glide_time": 0.0,
            "glide_legato": False,
            "unison_voices": 1,
            "unison_detune": DEFAULT_UNISON_DETUNE,
            "unison_spread": DEFAULT_UNISON_SPREAD,
            "tempo_bpm": DEFAULT_TEMPO,
            "delay_sync": False,
            "delay_division": DEFAULT_DELAY_DIVISION,
            "lfo_pitch_ratio": 1.0,
            "lfo_filter_oct": 0.0,
            "lfo_pwm": 0.0,
            "lfo_amp": None,
        }
        self.lfo = LFO()
        self.lfo2 = LFO(seed=2)
        # last block value of each LFO, and the rate each actually ran at
        self._lfo_last = [0.0, 0.0]
        self.lfo_rate_eff = [DEFAULT_LFO_RATE, DEFAULT_LFO_RATE]
        self.tempo = TempoTracker()
        fx = self.effects
        # base values of the effect dials: what the knobs, patches and status
        # show; modulation only ever changes the live effect attributes
        self.fx_base = {
            "fx_chorus_depth": fx.chorus.amount,
            "fx_delay_time": fx.delay.time_ms,
            "fx_delay_feedback": fx.delay.feedback,
            "fx_delay_damp": fx.delay.damp,
            "fx_reverb_amount": fx.reverb.mix,
            "fx_reverb_size": fx.reverb.room,
            "fx_reverb_damp": fx.reverb.damp,
            "fx_bitcrush_amount": fx.bitcrush.amount,
        }
        self._fx_setters = {
            "fx_chorus_depth": fx.chorus.set_depth,
            "fx_delay_feedback": fx.delay.set_feedback,
            "fx_delay_damp": fx.delay.set_damp,
            "fx_reverb_amount": fx.reverb.set_amount,
            "fx_reverb_size": fx.reverb.set_room,
            "fx_reverb_damp": fx.reverb.set_damp,
            "fx_bitcrush_amount": fx.bitcrush.set_amount,
        }
        self._mod_fx = ()
        self._fx_modulated = set()
        self._fx_live = {}
        self._last_freq = None
        self._last_note = None
        self.mod_rows = [["none", 0.0, "none"] for _ in range(NUM_SLOTS)]
        self._mod_dsts = ()
        self._mod_env = ()
        self._mod_uni = ()
        self._mod_tempo = None
        self._env_modulated = False
        self._uni_modulated = {"unison_detune": False, "unison_spread": False}
        self._mod_lfo = [False, False]
        self._mod_wheel_used = False
        self._mod_at_used = False
        self._mod_wheel = self._mod_at = 0.0
        self._wheel_s = self._at_s = 0.0
        self._master_bypassed = False
        self._order = 0
        self._group_counter = 0
        self._rng = np.random.default_rng(1234)
        self._noise_rng = np.random.default_rng(777)
        self.sustain = False
        self._sustained = set()
        self._update_lpf()
        self._apply_envelope()

    @property
    def delay_manual_ms(self):
        """The manual delay time (the base value of the Time knob)."""
        return self.fx_base["fx_delay_time"]

    def _refresh_derived(self):
        self.params["mod_index"] = self.params["fm_depth"] * FM_INDEX_MAX
        self.params["pitch_ratio"] = 2.0 ** (self.params["pitch_bend"] / 12.0)

    def set_osc1_square(self, on):
        with self.lock:
            self.params["osc1_square"] = bool(on)

    def set_osc1_square_level(self, level):
        with self.lock:
            self.params["osc1_square_level"] = min(max(float(level), 0.0), 1.0)

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

    def set_noise_level(self, level):
        with self.lock:
            self.params["noise_level"] = min(max(float(level), 0.0), 1.0)
            if self.params["noise_level"] > 0.0:
                noise.table(self.params["noise_color"])

    def set_noise_color(self, color):
        if color not in noise.NOISE_COLORS:
            raise ValueError("unknown noise color: %r (choose from %s)"
                             % (color, ", ".join(noise.NOISE_COLORS)))
        with self.lock:
            self.params["noise_color"] = color
            if self.params["noise_level"] > 0.0:
                noise.table(color)
            return color

    def _noise_start(self):
        return int(self._noise_rng.integers(noise.NOISE_TABLE_LEN))

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
            p["lpf_coeffs"] = filter_coefficients(
                p["lpf_cutoff"], p["lpf_resonance"], self.sr, p["lpf_slope"])
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

    def set_lpf_slope(self, slope):
        if slope not in LPF_SLOPES:
            raise ValueError("unknown filter slope: %r (choose from %s)" % (slope, ", ".join(LPF_SLOPES)))
        with self.lock:
            self.params["lpf_slope"] = slope
            self._update_lpf(force_reset=True)
            return slope

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

    def set_auto_limiter(self, on):
        with self.lock:
            self.params["auto_limiter"] = bool(on)
            self._reset_limiter()

    def _reset_limiter(self):
        self._limiter.reset()
        self._limiter_silent_s = 0.0

    def reset_limiter(self):
        """Drop the held gain reduction and restart the silence timer."""
        with self.lock:
            self._reset_limiter()

    def _run_limiter(self, driven):
        """Limit ``driven``; reset the hold after LIMITER_SILENCE_S of silent input."""
        limited, in_peak = self._limiter.process(driven)
        if in_peak < LIMITER_SILENCE_THRESHOLD:
            self._limiter_silent_s += driven.shape[1] / self.sr
            if self._limiter_silent_s >= LIMITER_SILENCE_S:
                self._reset_limiter()
        else:
            self._limiter_silent_s = 0.0
        return limited

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
        self._lfo_last = [0.0, 0.0]

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
        if dest not in LFO1_DESTS:
            raise ValueError("unknown LFO destination: %r (choose from %s)" % (dest, ", ".join(LFO1_DESTS)))
        with self.lock:
            self.params["lfo_dest"] = dest
            self._clear_lfo_mod()
            return dest

    def set_lfo2_rate(self, hz):
        self._set_unit("lfo2_rate", hz, LFO_RATE_MIN, LFO_RATE_MAX)

    def set_lfo2_depth(self, depth):
        with self.lock:
            self.params["lfo2_depth"] = min(max(float(depth), 0.0), 1.0)
            self._clear_lfo_mod()

    def set_lfo2_wave(self, wave):
        if wave not in LFO_WAVES:
            raise ValueError("unknown LFO wave: %r (choose from %s)" % (wave, ", ".join(LFO_WAVES)))
        with self.lock:
            self.params["lfo2_wave"] = wave
            return wave

    def set_lfo2_dest(self, dest):
        if dest not in LFO2_DESTS:
            raise ValueError("unknown LFO destination: %r (choose from %s)" % (dest, ", ".join(LFO2_DESTS)))
        with self.lock:
            self.params["lfo2_dest"] = dest
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

    def _refresh_mod(self):
        """Rebuild the cached active-row tables after a matrix change."""
        by_dst = {}
        lfo = [False, False]
        wheel = at = False
        for src, amt, dst in self.mod_rows:
            if src == "none" or dst == "none" or amt == 0.0:
                continue
            si = SOURCES.index(src)
            if si == SRC_LFO1:
                lfo[0] = True
            elif si == SRC_LFO2:
                lfo[1] = True
            elif si == SRC_WHEEL:
                wheel = True
            elif si == SRC_AFTERTOUCH:
                at = True
            d = destination(dst)
            by_dst.setdefault(d.param_id, (d, []))[1].append((amt, si))
        if wheel and not self._mod_wheel_used:
            self._wheel_s = self._mod_wheel
        if at and not self._mod_at_used:
            self._at_s = self._mod_at
        self._mod_wheel_used = wheel
        self._mod_at_used = at
        self._mod_lfo = lfo
        view, env, uni, tempo, fxs = [], [], [], None, []
        for pid, (d, terms) in by_dst.items():
            item = (d, tuple(terms), any(s == SRC_NOTE for _, s in terms))
            if pid in ENVELOPE_PARAMS:
                env.append((pid,) + item)
            elif pid in UNISON_PARAMS:
                uni.append((pid,) + item)
            elif pid == TEMPO_PARAM:
                tempo = item
            elif pid in FX_PARAMS:
                fxs.append((pid,) + item)
            else:
                view.append(item)
        self._mod_dsts = tuple(view)
        self._mod_env = tuple(env)
        self._mod_uni = tuple(uni)
        self._mod_tempo = tempo
        self._mod_fx = tuple(fxs)
        if self._env_modulated and not env:
            self._apply_envelope()
        self._env_modulated = bool(env)
        active = {pid for pid, *_ in uni}
        for pid, was in self._uni_modulated.items():
            if was and pid not in active:
                self._restore_unison(pid)
            self._uni_modulated[pid] = pid in active
        now = {pid for pid, *_ in fxs}
        for pid in self._fx_modulated - now:
            self._restore_fx(pid)
        self._fx_modulated = now

    def _restore_fx(self, pid):
        """Put an effect destination back to its base value (once)."""
        self._fx_live.pop(pid, None)
        if pid == DELAY_TIME_PARAM:
            self.effects.delay.set_time_target_ms(self._delay_base_ms())
        else:
            self._fx_setters[pid](self.fx_base[pid])

    def _delay_base_ms(self):
        """Delay time in force: the synced time when sync is on, else the knob."""
        if self.params["delay_sync"]:
            return self._synced_ms()
        return self.fx_base[DELAY_TIME_PARAM]

    def _apply_fx(self, vals):
        """Set the live effect values for this block from the matrix."""
        note_val = note_source(self._last_note)
        for pid, d, terms, note_dep in self._mod_fx:
            nv = note_val if note_dep else 0.0
            if pid == DELAY_TIME_PARAM:
                eff = self._mod_eff(d, terms, vals, nv, self._delay_base_ms())
                self.effects.delay.set_time_target_ms(eff)
            else:
                eff = self._mod_eff(d, terms, vals, nv, self.fx_base[pid])
                if self._fx_live.get(pid) != eff:
                    self._fx_live[pid] = eff
                    self._fx_setters[pid](eff)

    def _restore_unison(self, pid):
        base = self.params[pid]
        for v in self.voices:
            if pid == "unison_detune":
                v.detune_cents = v.unison_pos * base
            else:
                v.pan = v.unison_pos * base

    @staticmethod
    def _mod_slot(slot):
        try:
            index = int(slot)
        except (TypeError, ValueError):
            raise ValueError("mod slot must be 1-%d, got %r" % (NUM_SLOTS, slot)) from None
        if not 1 <= index <= NUM_SLOTS:
            raise ValueError("mod slot must be 1-%d, got %r" % (NUM_SLOTS, slot))
        return index - 1

    def set_mod_src(self, slot, name):
        index = self._mod_slot(slot)
        if name not in SOURCES:
            raise ValueError("unknown mod source: %r (choose from %s)"
                             % (name, ", ".join(SOURCES)))
        with self.lock:
            self.mod_rows[index][0] = name
            self._refresh_mod()
            return name

    def set_mod_amt(self, slot, value):
        index = self._mod_slot(slot)
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError("mod scale must be a finite number, got %r" % (value,))
        with self.lock:
            self.mod_rows[index][1] = min(max(number, -1.0), 1.0)
            self._refresh_mod()
            return self.mod_rows[index][1]

    def set_mod_dst(self, slot, name):
        index = self._mod_slot(slot)
        if name not in DEST_NAMES:
            raise ValueError("unknown mod destination: %r (choose from %s)"
                             % (name, ", ".join(DEST_NAMES)))
        with self.lock:
            self.mod_rows[index][2] = name
            self._refresh_mod()
            return name

    def set_mod_row(self, slot, src, amt, dst):
        """Set a whole matrix row atomically (all validated before any change)."""
        index = self._mod_slot(slot)
        if src not in SOURCES:
            raise ValueError("unknown mod source: %r (choose from %s)"
                             % (src, ", ".join(SOURCES)))
        number = float(amt)
        if not math.isfinite(number):
            raise ValueError("mod scale must be a finite number, got %r" % (amt,))
        if dst not in DEST_NAMES:
            raise ValueError("unknown mod destination: %r (choose from %s)"
                             % (dst, ", ".join(DEST_NAMES)))
        with self.lock:
            self.mod_rows[index][:] = [src, min(max(number, -1.0), 1.0), dst]
            self._refresh_mod()

    @staticmethod
    def _finite_unit(value, what):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("%s must be a finite number, got %r" % (what, value))
        return min(max(number, 0.0), 1.0)

    def set_mod_wheel(self, value):
        number = self._finite_unit(value, "mod wheel")
        with self.lock:
            self._mod_wheel = number
            if not self._mod_wheel_used:
                self._wheel_s = self._mod_wheel

    def set_aftertouch(self, value):
        number = self._finite_unit(value, "aftertouch")
        with self.lock:
            self._mod_at = number
            if not self._mod_at_used:
                self._at_s = self._mod_at

    def _mod_values(self):
        """Per-block source values indexed like SOURCES (note slot unused)."""
        last = self._lfo_last
        return (0.0, 0.0, last[0], last[1], self._wheel_s, self._at_s)

    def mod_sources(self, note=None):
        """Current value of every matrix source (note None = last played)."""
        with self.lock:
            vals = self._mod_values()
            return {
                "Note Number": note_source(self._last_note if note is None else note),
                "LFO 1": vals[SRC_LFO1],
                "LFO 2": vals[SRC_LFO2],
                "Mod Wheel": vals[SRC_WHEEL],
                "Aftertouch": vals[SRC_AFTERTOUCH],
            }

    def modulated_value(self, param_id, note=None):
        """Effective value of a destination (its base value when unmodulated)."""
        with self.lock:
            nv = note_source(self._last_note if note is None else note)
            if param_id == TEMPO_PARAM and self._mod_tempo is not None:
                return self._tempo_bpm(self._mod_values())
            for d, terms, _ in self._mod_dsts:
                if d.param_id == param_id:
                    return self._mod_eff(d, terms, self._mod_values(), nv)
            for pid, d, terms, _ in self._mod_env + self._mod_uni:
                if pid == param_id:
                    return self._mod_eff(d, terms, self._mod_values(), nv)
            for pid, d, terms, _ in self._mod_fx:
                if pid == param_id:
                    base = (self._delay_base_ms() if pid == DELAY_TIME_PARAM
                            else self.fx_base[pid])
                    return self._mod_eff(d, terms, self._mod_values(), nv, base)
            if param_id in self.fx_base:
                return self.fx_base[param_id]
            return self.params[param_id]

    def _mod_eff(self, d, terms, vals, note_val, base=None):
        return effective(
            self.params[d.param_id] if base is None else base,
            [(a, note_val if s == SRC_NOTE else vals[s]) for a, s in terms],
            d.lo, d.hi)

    @staticmethod
    def _mod_apply(view, pid, value):
        view[pid] = value
        if pid == "fm_depth":
            view["mod_index"] = value * FM_INDEX_MAX
        elif pid in ("lpf_cutoff", "lpf_resonance"):
            view["mod_filter"] = True

    def _mod_prepare(self, vals):
        """Evaluate the matrix for one block.

        Returns (shared params view, note-dependent (dest, terms) pairs,
        master-filter overrides).
        """
        params = self.params
        master = params["lpf_mode"] == "master"
        shared = {}
        note_dsts = []
        master_over = {}
        for d, terms, note_dep in self._mod_dsts:
            pid = d.param_id
            if master and pid in ("lpf_cutoff", "lpf_resonance"):
                nv = note_source(self._last_note) if note_dep else 0.0
                master_over[pid] = self._mod_eff(d, terms, vals, nv)
            elif note_dep:
                note_dsts.append((d, terms))
            else:
                shared[pid] = self._mod_eff(d, terms, vals, 0.0)
        view = params
        if shared or note_dsts:
            view = dict(params)
            for pid, value in shared.items():
                self._mod_apply(view, pid, value)
        return view, note_dsts, master_over

    def _mod_plan(self, entries, vals):
        """Split matrix entries into block-wide values and per-note entries."""
        shared, per_note = {}, []
        for pid, d, terms, note_dep in entries:
            if note_dep:
                per_note.append((pid, d, terms))
            else:
                shared[pid] = self._mod_eff(d, terms, vals, 0.0)
        return shared, per_note

    def _mod_voice_eff(self, plan, v, vals):
        eff = dict(plan[0])
        if plan[1]:
            nv = note_source(v.note)
            for pid, d, terms in plan[1]:
                eff[pid] = self._mod_eff(d, terms, vals, nv)
        return eff

    def _mod_voice_state(self, v, vals, env_plan, uni_plan):
        """Apply envelope shapes and unison offsets for one voice."""
        p = self.params
        if env_plan is not None:
            eff = self._mod_voice_eff(env_plan, v, vals)
            v.env.set_shape(eff.get("amp_attack", p["amp_attack"]),
                            eff.get("amp_decay", p["amp_decay"]),
                            eff.get("amp_sustain", p["amp_sustain"]),
                            eff.get("amp_release", p["amp_release"]))
            v.flt_env.set_shape(eff.get("flt_attack", p["flt_attack"]),
                                eff.get("flt_decay", p["flt_decay"]),
                                eff.get("flt_sustain", p["flt_sustain"]),
                                eff.get("flt_release", p["flt_release"]))
        if uni_plan is not None:
            eff = self._mod_voice_eff(uni_plan, v, vals)
            if "unison_detune" in eff:
                v.detune_cents = v.unison_pos * eff["unison_detune"]
            if "unison_spread" in eff:
                v.pan = v.unison_pos * eff["unison_spread"]

    def _mod_voice_view(self, shared, note_dsts, vals, note):
        view = dict(shared)
        nv = note_source(note)
        for d, terms in note_dsts:
            self._mod_apply(view, d.param_id, self._mod_eff(d, terms, vals, nv))
        return view

    def _classic_pool(self):
        """The voices classic allocation may use (the playable ones only)."""
        if len(self.voices) == self.max_voices:
            return self.voices
        return self.voices[:self.max_voices]

    def _allocate_voice(self):
        pool = self._classic_pool()
        for v in pool:
            if not v.active:
                return v
        released = [v for v in pool if not v.gate]
        if released:
            return min(released, key=lambda v: (v.env.level, v.trigger_order))
        return min(pool, key=lambda v: v.trigger_order)

    def _allocate_group(self, count):
        """Pick ``count`` voices: idle ones first, then whole stolen groups."""
        if self.tail_slots > 0:
            return self._allocate_hybrid(count)
        pool = self._classic_pool()
        chosen = [v for v in pool if not v.active][:count]
        if len(chosen) >= count:
            return chosen
        groups = {}
        for i, v in enumerate(pool):
            if v.active:
                key = v.group if v.group is not None else ("single", i)
                groups.setdefault(key, []).append(v)
        victims = sorted(
            groups.values(),
            key=lambda g: _victim_key(g))
        for g in victims:
            chosen.extend(g)
            if len(chosen) >= count:
                break
        return chosen

    def _voice_groups(self, voices, per_voice=False):
        groups = {}
        for i, v in enumerate(voices):
            if per_voice or v.group is None:
                key = ("single", id(v))
            else:
                key = v.group
            groups.setdefault(key, []).append(v)
        return list(groups.values())

    def _force_release_for(self, count):
        """Force-release the oldest held groups until ``count`` more fit."""
        forced = []
        while True:
            held = [v for v in self.voices if v.gate]
            if len(held) + count <= self.max_voices or not held:
                return forced
            oldest = min(self._voice_groups(held),
                         key=lambda g: min(v.trigger_order for v in g))
            for v in oldest:
                v.force_release()
            forced.extend(oldest)
            self.forced_releases += len(oldest)

    def _allocate_hybrid(self, count):
        """Hybrid allocation: free voices first, steal only released tails."""
        forced = self._force_release_for(count)
        voices = self.voices
        active = sum(1 for v in voices if v.active)
        room = max(self.max_voices + self.tail_slots - active, 0)
        chosen = [v for v in voices if not v.active][:min(room, count)]
        if len(chosen) >= count:
            return chosen
        skip = {id(v) for v in forced}
        per_voice = count == 1

        def victims(pred):
            cands = [v for v in voices if v.active and pred(v)]
            return sorted(self._voice_groups(cands, per_voice), key=_victim_key)

        tiers = (
            victims(lambda v: not v.gate and id(v) not in skip),
            victims(lambda v: id(v) in skip),
            victims(lambda v: v.gate),
        )
        for tier in tiers:
            for g in tier:
                chosen.extend(g)
                if len(chosen) >= count:
                    return chosen
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
            stolen = v.active
            self.steal_count += stolen
            v.note_on(note, vel, self._order, glide_from, glide_time,
                      stolen=stolen,
                      unison_pos=float(pos),
                      detune_cents=float(pos * p["unison_detune"]),
                      pan=float(pos * p["unison_spread"]), gain=float(gain),
                      group=self._group_counter, random_phase=True, rng=self._rng,
                      noise_pos=self._noise_start())

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
                if self.tail_slots > 0:
                    voice = self._allocate_hybrid(1)[0]
                else:
                    voice = self._allocate_voice()
            glide_time = self.params["glide_time"]
            glide_from = None
            if (glide_time > 0.0 and self._last_freq is not None
                    and (not self.params["glide_legato"] or held)):
                glide_from = self._last_freq
            self._last_freq = midi_note_to_freq(note)
            self._last_note = note
            if count == 1:
                stolen = voice.active
                self.steal_count += stolen
                voice.note_on(note, vel, self._order, glide_from, glide_time,
                              noise_pos=self._noise_start(), stolen=stolen)
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
            self._reset_aftertouch()
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
                v.flt_env.stage = IDLE
                v.flt_env.level = 0.0
            self._sustained.clear()
            self.sustain = False
            self._mod_wheel = self._wheel_s = 0.0
            self._reset_aftertouch()
            self._reset_limiter()

    def _reset_aftertouch(self):
        self._mod_at = self._at_s = 0.0

    def reset_controllers(self):
        with self.lock:
            self.set_pitch_bend(0.0)
            self.set_sustain(False)
            self._mod_wheel = self._wheel_s = 0.0
            self._reset_aftertouch()

    def active_note_count(self):
        with self.lock:
            return sum(1 for v in self.voices if v.active)

    def gated_count(self):
        """Voices whose key is held (the playable ones in use)."""
        with self.lock:
            return sum(1 for v in self.voices if v.gate)

    def tail_count(self):
        """Released voices still ringing out."""
        with self.lock:
            return sum(1 for v in self.voices if v.active and not v.gate)

    def set_tail_slots(self, n):
        """Set the tail slots in use (clamped to the pool's capacity)."""
        try:
            count = int(n)
            if isinstance(n, float) and n != count:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            raise ValueError("tail slots must be a whole number, got %r" % (n,)) from None
        with self.lock:
            self.tail_slots = min(max(count, 0), self.tail_capacity)
            return self.tail_slots

    def set_effect(self, name, enabled):
        with self.lock:
            self.effects.get(name).enabled = bool(enabled)

    def _set_fx_base(self, pid, value, lo, hi):
        """Record a base value (clamped) and apply it unless it is modulated."""
        value = min(max(float(value), lo), hi)
        with self.lock:
            self.fx_base[pid] = value
            if pid not in self._fx_modulated:
                self._fx_setters[pid](value)
                self._fx_live.pop(pid, None)

    def set_chorus_depth(self, a):
        self._set_fx_base("fx_chorus_depth", a, 0.0, 1.0)

    def set_delay_time(self, ms):
        with self.lock:
            self.fx_base[DELAY_TIME_PARAM] = min(max(float(ms), 1.0), 4000.0)
            if DELAY_TIME_PARAM not in self._fx_modulated:
                self.effects.delay.set_time_ms(self.fx_base[DELAY_TIME_PARAM])
                if self.params["delay_sync"]:
                    self._sync_delay()

    def set_tempo_bpm(self, bpm):
        self._set_unit("tempo_bpm", bpm, TEMPO_MIN, TEMPO_MAX)

    def set_delay_sync(self, on):
        with self.lock:
            on = bool(on)
            was = self.params["delay_sync"]
            self.params["delay_sync"] = on
            if DELAY_TIME_PARAM in self._fx_modulated:
                return   # the per-block evaluation follows the time in force
            if on:
                self._sync_delay()
            elif was:
                self.effects.delay.set_time_ms(self.delay_manual_ms)

    def set_delay_division(self, name):
        if name not in DELAY_DIVISION_BEATS:
            raise ValueError("unknown delay division: %r (choose from %s)"
                             % (name, ", ".join(DELAY_DIVISION_BEATS)))
        with self.lock:
            self.params["delay_division"] = name
            return name

    def _synced_ms(self):
        """Delay time locked to the tempo (external clock wins over manual)."""
        ms = (60000.0 / self.effective_bpm()
              * DELAY_DIVISION_BEATS[self.params["delay_division"]])
        return min(max(ms, 1.0), 4000.0)

    def _sync_delay(self):
        """Jump the delay to the synced time (not while Delay: Time is modulated)."""
        if DELAY_TIME_PARAM in self._fx_modulated:
            return
        ms = self._synced_ms()
        delay = self.effects.delay
        current = delay.time_ms if delay.target_ms is None else delay.target_ms
        if abs(ms - current) > 0.5:
            if self._mod_tempo is not None:
                delay.set_time_target_ms(ms)   # tempo moves every block: glide
            else:
                delay.set_time_ms(ms)

    def _tempo_bpm(self, vals):
        """Tempo in use (external clock or manual) with the matrix applied."""
        base = self.tempo.effective_bpm(self.params["tempo_bpm"])
        t = self._mod_tempo
        if t is None:
            return base
        d, terms, _ = t
        return self._mod_eff(d, terms, vals, note_source(self._last_note), base)

    def effective_bpm(self):
        """Tempo driving the synced delay, including Mod Matrix `Tempo` rows."""
        return self._tempo_bpm(self._mod_values())

    def set_delay_pingpong(self, on):
        with self.lock:
            self.effects.delay.set_pingpong(on)

    def set_reverb_amount(self, v):
        self._set_fx_base("fx_reverb_amount", v, 0.0, 1.0)

    def set_reverb_size(self, v):
        self._set_fx_base("fx_reverb_size", v, 0.5, 0.98)

    def set_reverb_damp(self, v):
        self._set_fx_base("fx_reverb_damp", v, 0.0, 0.9)

    def set_delay_feedback(self, v):
        self._set_fx_base("fx_delay_feedback", v, 0.0, 0.95)

    def set_delay_damp(self, v):
        self._set_fx_base("fx_delay_damp", v, 0.0, 0.9)

    def set_crush_amount(self, a):
        self._set_fx_base("fx_bitcrush_amount", a, 0.0, 1.0)

    def toggle_effect(self, name):
        with self.lock:
            fx = self.effects.get(name)
            fx.enabled = not fx.enabled
            return fx.enabled

    def _run_lfo(self, n):
        """Advance each active LFO one block and publish the combined modulation.

        Pitch ratios multiply, filter octaves and pulse-width offsets add, and
        amp gains multiply. The first LFO to hit a destination assigns its
        value directly so a lone LFO adds no extra arithmetic.
        Returns True when an active LFO targets the filter.
        """
        p = self.params
        seen = set()
        last = self._lfo_last
        cur = [0.0, 0.0]
        stages = ((self.lfo, "lfo", "lfo2-rate"), (self.lfo2, "lfo2", "lfo1-rate"))
        for i, (lfo, pre, cross) in enumerate(stages):
            depth = p[pre + "_depth"]
            routed = depth > 0.0
            if not routed and not self._mod_lfo[i]:
                self.lfo_rate_eff[i] = p[pre + "_rate"]
                continue
            dest = p[pre + "_dest"]
            rate = p[pre + "_rate"]
            o = 1 - i
            opre = stages[o][1]
            if p[opre + "_depth"] > 0.0 and p[opre + "_dest"] == stages[o][2]:
                rate *= 2.0 ** (p[opre + "_depth"] * last[o] * LFO_RATE_MOD_OCTAVES)
                rate = min(max(rate, LFO_RATE_FLOOR), LFO_RATE_CEIL)
            self.lfo_rate_eff[i] = rate
            mid, arr = lfo.next_block(
                n, self.sr, rate, p[pre + "_wave"],
                want_array=routed and dest == "amp")
            cur[i] = mid
            if not routed:
                continue
            first = dest not in seen
            seen.add(dest)
            if dest == "pitch":
                ratio = 2.0 ** (depth * LFO_PITCH_SEMITONES * mid / 12.0)
                p["lfo_pitch_ratio"] = ratio if first else p["lfo_pitch_ratio"] * ratio
            elif dest == "filter":
                octs = depth * LFO_FILTER_OCTAVES * mid
                p["lfo_filter_oct"] = octs if first else p["lfo_filter_oct"] + octs
            elif dest == "pwm":
                off = depth * LFO_PWM_RANGE * mid
                p["lfo_pwm"] = off if first else p["lfo_pwm"] + off
            elif dest == "amp":
                gain = 1.0 - depth * (0.5 - 0.5 * arr)
                p["lfo_amp"] = gain if first else p["lfo_amp"] * gain
            # lfo1-rate / lfo2-rate publish nothing: they only steer the other LFO
        self._lfo_last = cur
        return "filter" in seen

    def _master_lfo_coeffs(self, over=None, lfo_oct=True):
        """Master-bus coefficients with LFO filter octaves and matrix overrides."""
        p = self.params
        over = over or {}
        cutoff = over.get("lpf_cutoff", p["lpf_cutoff"])
        if lfo_oct:
            cutoff *= 2.0 ** p["lfo_filter_oct"]
        cutoff = min(max(cutoff, LPF_MIN_HZ), 0.45 * self.sr)
        if cutoff >= LPF_MAX_HZ / 1.01:
            return None
        return filter_coefficients(
            cutoff, over.get("lpf_resonance", p["lpf_resonance"]), self.sr, p["lpf_slope"])

    def render(self, n=None, apply_effects=True):
        if n is None:
            n = self.block_size
        with self.lock:
            mix = np.zeros(n, dtype=np.float64)
            params = self.params
            lfo_filter = False
            mod = self._mod_dsts
            if (params["lfo_depth"] > 0.0 or params["lfo2_depth"] > 0.0
                    or self._mod_lfo[0] or self._mod_lfo[1]):
                lfo_filter = self._run_lfo(n)
            view, note_dsts, master_over, vals = params, (), None, None
            env_plan = uni_plan = None
            if (mod or self._mod_env or self._mod_uni or self._mod_fx
                    or self._mod_tempo is not None):
                if self._mod_wheel_used:
                    self._wheel_s = smooth(self._wheel_s, self._mod_wheel, MOD_SMOOTH)
                if self._mod_at_used:
                    self._at_s = smooth(self._at_s, self._mod_at, MOD_SMOOTH)
                vals = self._mod_values()
                if mod:
                    view, note_dsts, master_over = self._mod_prepare(vals)
                if self._mod_env:
                    env_plan = self._mod_plan(self._mod_env, vals)
                if self._mod_uni:
                    uni_plan = self._mod_plan(self._mod_uni, vals)
            if params["delay_sync"]:
                self._sync_delay()
            if self._mod_fx:
                self._apply_fx(vals)
            panned = []
            stereo = False
            for v in self.voices:
                if v.active:
                    if env_plan is not None or uni_plan is not None:
                        self._mod_voice_state(v, vals, env_plan, uni_plan)
                    if note_dsts:
                        out_v = v.render(
                            n, self._mod_voice_view(view, note_dsts, vals, v.note))
                    else:
                        out_v = v.render(n, view)
                    if v.pan != 0.0:
                        stereo = True
                    panned.append((v.pan, out_v))
                    if not stereo:
                        mix += out_v
            coeffs = params["lpf_coeffs"]
            if self._master_bypassed and not (
                    params["lpf_mode"] == "master" and (lfo_filter or master_over)):
                # whatever bypassed the filter is gone: resume from clean state
                self.master_lpf.reset()
                self.master_lpf_r.reset()
                self._master_bypassed = False
            if params["lpf_mode"] == "master" and (lfo_filter or master_over):
                coeffs = self._master_lfo_coeffs(master_over, lfo_filter)
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
            driven = out * params["master_gain"]
            if params["auto_limiter"]:
                driven = self._run_limiter(driven)
            out = np.tanh(driven)
            self._meter_post = np.maximum(self._meter_post, np.abs(out).max(axis=1))
            self.last_driven_peak = float(np.abs(driven).max())
            if self.last_driven_peak >= CLIP_THRESHOLD:
                self._meter_clip = True
            return np.ascontiguousarray(out.T).astype(np.float32)

    def peek_meter(self):
        """Return (left, right, clipped) without resetting the meter."""
        with self.lock:
            return (float(self._meter_post[0]), float(self._meter_post[1]),
                    bool(self._meter_clip))

    def take_meter(self):
        """Return linear post-clipper peaks and the clip flag since the last call, then reset."""
        with self.lock:
            result = (float(self._meter_post[0]), float(self._meter_post[1]),
                      bool(self._meter_clip))
            self._meter_post = np.zeros(2)
            self._meter_clip = False
            return result

    @staticmethod
    def _gain_to_db(gain):
        return -20.0 * math.log10(max(gain, 1e-6))

    def limiter_reduction_db(self):
        """Held limiter gain reduction in dB (>= 0); 0.0 when off or idle."""
        with self.lock:
            if not self.params["auto_limiter"]:
                return 0.0
            return self._gain_to_db(1.0 - self._limiter.h)

    def _fx_status(self, pid):
        """Effect dial value for ``status``: the live value when unmodulated
        (the synced delay time while sync is on), the BASE value while a
        matrix row modulates it (for delay time: the time in force)."""
        fx = self.effects
        if pid == DELAY_TIME_PARAM:
            if pid in self._fx_modulated:
                return self._delay_base_ms()
            return fx.delay.time_ms
        if pid in self._fx_modulated:
            return self.fx_base[pid]
        return {
            "fx_chorus_depth": lambda: fx.chorus.amount,
            "fx_delay_feedback": lambda: fx.delay.feedback,
            "fx_delay_damp": lambda: fx.delay.damp,
            "fx_reverb_amount": lambda: fx.reverb.mix,
            "fx_reverb_size": lambda: fx.reverb.room,
            "fx_reverb_damp": lambda: fx.reverb.damp,
            "fx_bitcrush_amount": lambda: fx.bitcrush.amount,
        }[pid]()

    def status(self):
        with self.lock:
            fx = {
                name: getattr(self.effects, name).enabled
                for name in self.effects.order
            }
            return {
                "osc1_level": self.params["osc1_level"],
                "osc1_square": self.params["osc1_square"],
                "osc1_square_level": self.params["osc1_square_level"],
                "osc1_pwm": self.params["osc1_pwm"],
                "osc2_level": self.params["osc2_level"],
                "noise_level": self.params["noise_level"],
                "noise_color": self.params["noise_color"],
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
                "lpf_slope": self.params["lpf_slope"],
                "amp_attack": self.params["amp_attack"],
                "amp_decay": self.params["amp_decay"],
                "amp_sustain": self.params["amp_sustain"],
                "amp_release": self.params["amp_release"],
                "velocity_on": self.params["velocity_on"],
                "auto_limiter": self.params["auto_limiter"],
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
                "lfo2_rate": self.params["lfo2_rate"],
                "lfo2_depth": self.params["lfo2_depth"],
                "lfo2_wave": self.params["lfo2_wave"],
                "lfo2_dest": self.params["lfo2_dest"],
                "glide_time": self.params["glide_time"],
                "glide_legato": self.params["glide_legato"],
                "unison_voices": self.params["unison_voices"],
                "unison_detune": self.params["unison_detune"],
                "unison_spread": self.params["unison_spread"],
                "tempo_bpm": self.params["tempo_bpm"],
                "delay_sync": self.params["delay_sync"],
                "delay_division": self.params["delay_division"],
                "effective_bpm": self.tempo.effective_bpm(self.params["tempo_bpm"]),
                **{"mod%d_%s" % (i + 1, key): value
                   for i, r in enumerate(self.mod_rows)
                   for key, value in zip(("src", "amt", "dst"), r)},
                "chorus_depth": self._fx_status("fx_chorus_depth"),
                "delay_time": self._fx_status("fx_delay_time"),
                "delay_pingpong": self.effects.delay.pingpong,
                "delay_feedback": self._fx_status("fx_delay_feedback"),
                "delay_damp": self._fx_status("fx_delay_damp"),
                "reverb_amount": self._fx_status("fx_reverb_amount"),
                "reverb_size": self._fx_status("fx_reverb_size"),
                "reverb_damp": self._fx_status("fx_reverb_damp"),
                "crush_amount": self._fx_status("fx_bitcrush_amount"),
                "effects": fx,
                "sustain": self.sustain,
                "active_voices": sum(1 for v in self.voices if v.active),
                "steal_count": self.steal_count,
                "tail_slots": self.tail_slots,
                "tails_active": sum(1 for v in self.voices if v.active and not v.gate),
                "gated_voices": sum(1 for v in self.voices if v.gate),
                "forced_releases": self.forced_releases,
            }
