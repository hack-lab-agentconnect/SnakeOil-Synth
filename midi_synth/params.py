from dataclasses import dataclass
from typing import Any, Callable, Tuple

from .config import (
    MODES,
    SEMITONE_MIN,
    SEMITONE_MAX,
    CENTS_MIN,
    CENTS_MAX,
)
from .filters import LPF_MIN_HZ, LPF_MAX_HZ

CONTINUOUS = "continuous"
TOGGLE = "toggle"
CHOICE = "choice"

EFFECT_NAMES = ("chorus", "delay", "reverb", "bitcrush")
MASTER_GAIN_MAX = 1.2


@dataclass(frozen=True, kw_only=True)
class Param:
    id: str
    label: str
    group: str
    kind: str
    get: Callable[[], Any]
    set: Callable[[Any], None]
    minimum: float = 0.0
    maximum: float = 1.0
    choices: Tuple[str, ...] = ()
    fmt: str = "{:.2f}"
    affects: Tuple[str, ...] = ()
    scale: str = "linear"
    tooltip: str = ""
    under: str = ""


class ParamRegistry:
    def __init__(self, params):
        self._params = {p.id: p for p in params}
        self._listeners = []
        self._pressed = {}

    def __iter__(self):
        return iter(self._params.values())

    def __contains__(self, param_id):
        return param_id in self._params

    def __getitem__(self, param_id):
        return self._params[param_id]

    def ids(self):
        return list(self._params)

    def add_listener(self, fn):
        self._listeners.append(fn)

    def get(self, param_id):
        return self._params[param_id].get()

    def _coerce(self, param, value):
        if param.kind == CONTINUOUS:
            return min(max(float(value), param.minimum), param.maximum)
        if param.kind == TOGGLE:
            return bool(value)
        if value not in param.choices:
            raise ValueError(
                "unknown value %r for %s (choose from %s)"
                % (value, param.id, ", ".join(param.choices))
            )
        return value

    def set(self, param_id, value):
        param = self._params[param_id]
        param.set(self._coerce(param, value))
        for pid in (param_id,) + param.affects:
            for fn in list(self._listeners):
                fn(pid)

    def from_midi(self, param_id, value):
        param = self._params[param_id]
        value = int(value)
        if param.kind == CONTINUOUS:
            frac = min(max(value, 0), 127) / 127.0
            if param.scale == "log":
                return param.minimum * (param.maximum / param.minimum) ** frac
            return param.minimum + (param.maximum - param.minimum) * frac
        if param.kind == TOGGLE:
            return value >= 64
        idx = min(max(value, 0) * len(param.choices) // 128, len(param.choices) - 1)
        return param.choices[idx]

    def reset_pressed(self):
        self._pressed.clear()

    def apply_midi(self, param_id, value):
        param = self._params[param_id]
        if param.kind == TOGGLE:
            pressed = int(value) >= 64
            was = self._pressed.get(param_id, False)
            self._pressed[param_id] = pressed
            if not (pressed and not was):
                return param.get()
            new = not param.get()
        else:
            new = self.from_midi(param_id, value)
        self.set(param_id, new)
        return new


def build_registry(engine):
    p = engine.params

    def effect(name):
        return Param(
            id="fx_" + name,
            label=name.capitalize(),
            group="Effects",
            kind=TOGGLE,
            get=lambda: engine.effects.get(name).enabled,
            set=lambda v: engine.set_effect(name, v),
        )

    fx = engine.effects
    dials = {
        "chorus": Param(
            id="fx_chorus_rate", label="Rate", group="Effects", kind=CONTINUOUS,
            minimum=1.0, maximum=10.0, fmt="{:.1f} Hz", under="fx_chorus",
            get=lambda: fx.chorus.rate, set=engine.set_chorus_rate,
            tooltip="Chorus LFO speed."),
        "delay": Param(
            id="fx_delay_time", label="Time", group="Effects", kind=CONTINUOUS,
            minimum=200.0, maximum=4000.0, scale="log", fmt="{:.0f} ms",
            under="fx_delay", get=lambda: fx.delay.time_ms,
            set=engine.set_delay_time, tooltip="Delay time between echoes."),
        "reverb": Param(
            id="fx_reverb_amount", label="Amount", group="Effects",
            kind=CONTINUOUS, under="fx_reverb", get=lambda: fx.reverb.mix,
            set=engine.set_reverb_amount, tooltip="Reverb wet level."),
        "bitcrush": Param(
            id="fx_bitcrush_amount", label="Crush", group="Effects",
            kind=CONTINUOUS, under="fx_bitcrush",
            get=lambda: fx.bitcrush.amount, set=engine.set_crush_amount,
            tooltip="Bit depth and sample-rate reduction."),
    }

    params = [
        Param(id="osc1_level", label="Level", group="Oscillator 1", kind=CONTINUOUS,
              get=lambda: p["osc1_level"], set=lambda v: engine.set_osc_level(1, v)),
        Param(id="osc1_square", label="Square layer", group="Oscillator 1", kind=TOGGLE,
              get=lambda: p["osc1_square"], set=engine.set_osc1_square,
              tooltip="Layer a square wave over the saw."),
        Param(id="osc1_pwm", label="PWM", group="Oscillator 1", kind=CONTINUOUS,
              minimum=0.0, maximum=0.5, fmt="{:.2f}",
              get=lambda: p["osc1_pwm"], set=engine.set_osc1_pwm,
              tooltip="Pulse width of the square layer. 0.50 = plain square."),
        Param(id="osc1_octave", label="Octave down", group="Oscillator 1", kind=TOGGLE,
              get=lambda: p["osc1_octave_down"], set=engine.set_osc1_octave_down,
              tooltip="Play Oscillator 1 one octave below the note."),
        Param(id="osc2_level", label="Level", group="Oscillator 2", kind=CONTINUOUS,
              get=lambda: p["osc2_level"], set=lambda v: engine.set_osc_level(2, v)),
        Param(id="detune2_semitones", label="Coarse", group="Oscillator 2",
              kind=CONTINUOUS, minimum=SEMITONE_MIN, maximum=SEMITONE_MAX,
              fmt="{:+.1f} st", get=lambda: p["detune2_semitones"],
              set=lambda v: engine.set_detune2(v)),
        Param(id="detune2_cents", label="Fine", group="Oscillator 2",
              kind=CONTINUOUS, minimum=CENTS_MIN, maximum=CENTS_MAX,
              fmt="{:+.2f} ct", get=lambda: p["detune2_cents"],
              set=lambda v: engine.set_detune2(p["detune2_semitones"], v)),
        Param(id="osc2_pwm", label="PWM", group="Oscillator 2", kind=CONTINUOUS,
              minimum=0.0, maximum=0.5, fmt="{:.2f}",
              get=lambda: p["osc2_pwm"], set=engine.set_osc2_pwm,
              tooltip="Pulse width of the square. 0.50 = plain square."),
        Param(id="osc2_octave", label="Octave up", group="Oscillator 2", kind=TOGGLE,
              get=lambda: p["osc2_octave_up"], set=engine.set_osc2_octave_up,
              tooltip="Play Oscillator 2 one octave above the note."),
        Param(id="mod_mode", label="Mode", group="Modulation", kind=CHOICE,
              choices=MODES, get=lambda: p["mod_mode"], set=engine.set_mod_mode,
              affects=("fm_depth",)),
        Param(id="fm_depth", label="Amount", group="Modulation", kind=CONTINUOUS,
              get=lambda: p["fm_depth"], set=engine.set_fm_depth),
        Param(id="lpf_cutoff", label="Cutoff", group="Filter", kind=CONTINUOUS,
              minimum=LPF_MIN_HZ, maximum=LPF_MAX_HZ, scale="log", fmt="{:.0f} Hz",
              get=lambda: p["lpf_cutoff"], set=engine.set_lpf_cutoff,
              tooltip="Low-pass cutoff. Fully right = filter off."),
        Param(id="lpf_resonance", label="Resonance", group="Filter", kind=CONTINUOUS,
              get=lambda: p["lpf_resonance"], set=engine.set_lpf_resonance),
        Param(id="lpf_master", label="Master-bus filter", group="Filter", kind=TOGGLE,
              get=lambda: p["lpf_mode"] == "master",
              set=lambda v: engine.set_lpf_mode("master" if v else "voice"),
              tooltip="Off: one filter per voice. On: a single filter on the whole mix "
                      "(lighter on the CPU; use it if audio glitches)."),
        Param(id="master_gain", label="Volume", group="Master", kind=CONTINUOUS,
              maximum=MASTER_GAIN_MAX, get=lambda: p["master_gain"],
              set=engine.set_master_gain),
    ]
    for n in EFFECT_NAMES:
        params.append(effect(n))
        params.append(dials[n])
    return ParamRegistry(params)
