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
    DEFAULT_LPF_MODE,
)
from .filters import LowPass, LPF_MIN_HZ, LPF_MAX_HZ, lpf_coefficients
from .voice import Voice
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
        self.params = {
            "osc1_waveform": "sine",
            "osc2_waveform": "sine",
            "osc1_level": 1.0,
            "osc2_level": 0.0,
            "mod_mode": DEFAULT_MODE,
            "fm_depth": 0.0,
            "mod_index": 0.0,
            "detune2_semitones": 0.0,
            "detune2_cents": 0.0,
            "osc1_octave_down": False,
            "osc2_octave_up": False,
            "pitch_bend": 0.0,
            "pitch_ratio": 1.0,
            "master_gain": 0.8,
            "lpf_cutoff": LPF_MAX_HZ,
            "lpf_resonance": 0.0,
            "lpf_mode": DEFAULT_LPF_MODE,
            "lpf_coeffs": None,
        }
        self._order = 0
        self._refresh_oscillators()

    def _refresh_oscillators(self):
        for v in self.voices:
            v.osc1.set_waveform(self.params["osc1_waveform"])
            v.osc2.set_waveform(self.params["osc2_waveform"])

    def _refresh_derived(self):
        self.params["mod_index"] = self.params["fm_depth"] * FM_INDEX_MAX
        self.params["pitch_ratio"] = 2.0 ** (self.params["pitch_bend"] / 12.0)

    def set_osc1_waveform(self, waveform):
        with self.lock:
            self.params["osc1_waveform"] = waveform
            for v in self.voices:
                v.osc1.set_waveform(waveform)

    def set_osc2_waveform(self, waveform):
        with self.lock:
            self.params["osc2_waveform"] = waveform
            for v in self.voices:
                v.osc2.set_waveform(waveform)

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

    def note_on(self, note, velocity=100):
        with self.lock:
            for v in self.voices:
                if v.active and v.note == note and v.gate:
                    v.gate = False
                    v.env.note_off()
            self._order += 1
            voice = self._allocate_voice()
            voice.note_on(note, velocity / 127.0, self._order)

    def note_off(self, note):
        with self.lock:
            for v in self.voices:
                if v.note == note and v.gate:
                    v.note_off()

    def all_notes_off(self):
        with self.lock:
            for v in self.voices:
                if v.active:
                    v.note_off()

    def active_note_count(self):
        with self.lock:
            return sum(1 for v in self.voices if v.active)

    def set_effect(self, name, enabled):
        with self.lock:
            self.effects.get(name).enabled = bool(enabled)

    def toggle_effect(self, name):
        with self.lock:
            fx = self.effects.get(name)
            fx.enabled = not fx.enabled
            return fx.enabled

    def render(self, n=None, apply_effects=True):
        if n is None:
            n = self.block_size
        with self.lock:
            mix = np.zeros(n, dtype=np.float64)
            params = self.params
            for v in self.voices:
                if v.active:
                    mix += v.render(n, params)
            coeffs = params["lpf_coeffs"]
            if coeffs is not None and params["lpf_mode"] == "master":
                mix = self.master_lpf.process(mix, coeffs)
            if apply_effects:
                mix = self.effects.process(mix)
            mix *= params["master_gain"]
            return np.tanh(mix).astype(np.float32)

    def status(self):
        with self.lock:
            fx = {
                name: getattr(self.effects, name).enabled
                for name in self.effects.order
            }
            return {
                "osc1_waveform": self.params["osc1_waveform"],
                "osc2_waveform": self.params["osc2_waveform"],
                "osc1_level": self.params["osc1_level"],
                "osc2_level": self.params["osc2_level"],
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
                "effects": fx,
                "active_voices": sum(1 for v in self.voices if v.active),
            }
