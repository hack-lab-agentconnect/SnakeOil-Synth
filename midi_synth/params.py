from dataclasses import dataclass
from typing import Any, Callable, Tuple

from .config import (
    MODES,
    SEMITONE_MIN,
    SEMITONE_MAX,
    CENTS_MIN,
    CENTS_MAX,
    AMP_TIME_MIN,
    AMP_ATTACK_MAX,
    AMP_DECAY_MAX,
    AMP_RELEASE_MAX,
    LFO_WAVES,
    LFO_DESTS,
    LFO_RATE_MIN,
    LFO_RATE_MAX,
    GLIDE_MAX,
)
from .filters import LPF_MIN_HZ, LPF_MAX_HZ

CONTINUOUS = "continuous"
TOGGLE = "toggle"
CHOICE = "choice"

EFFECT_NAMES = ("chorus", "delay", "reverb", "bitcrush")
MASTER_GAIN_MAX = 1.2


def format_seconds(value):
    """Milliseconds below one second, seconds otherwise: '6 ms', '1.50 s'."""
    ms = round(value * 1000.0)
    if ms < 1000:
        return "%d ms" % ms
    return "%.2f s" % value


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
    formatter: Callable | None = None
    widget: str = "knob"


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
            id="fx_chorus_depth", label="Depth", group="Effects", kind=CONTINUOUS,
            minimum=0.0, maximum=1.0, fmt="{:.2f}", under="fx_chorus",
            get=lambda: fx.chorus.amount, set=engine.set_chorus_depth,
            tooltip="How far the chorus delay swings. Low = subtle "
                    "thickening, high = obvious wobble."),
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

    def envelope(pid, label, maximum, tooltip, time=True, group="Amp Envelope"):
        return Param(
            id=pid, label=label, group=group, kind=CONTINUOUS,
            minimum=AMP_TIME_MIN if time else 0.0, maximum=maximum,
            scale="log" if time else "linear",
            formatter=format_seconds if time else None, widget="slider",
            get=lambda: p[pid], set=getattr(engine, "set_" + pid),
            tooltip=tooltip)

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
        Param(id="flt_env_amount", label="Env Amt", group="Filter", kind=CONTINUOUS,
              minimum=-1.0, maximum=1.0, fmt="{:+.2f}",
              get=lambda: p["flt_env_amount"], set=engine.set_flt_env_amount,
              tooltip="How far the filter envelope moves the cutoff "
                      "(up to 6 octaves). Negative closes the filter."),
        Param(id="flt_keytrack", label="Key Trk", group="Filter", kind=CONTINUOUS,
              get=lambda: p["flt_keytrack"], set=engine.set_flt_keytrack,
              tooltip="Cutoff follows the note pitch. 1.00 = one octave "
                      "of cutoff per octave of pitch."),
        Param(id="flt_vel", label="Vel>Cut", group="Filter", kind=CONTINUOUS,
              get=lambda: p["flt_vel"], set=engine.set_flt_vel,
              tooltip="Harder key presses open the filter further."),
        Param(id="master_gain", label="Volume", group="Master", kind=CONTINUOUS,
              maximum=MASTER_GAIN_MAX, get=lambda: p["master_gain"],
              set=engine.set_master_gain),
        Param(id="velocity_on", label="Velocity", group="Master", kind=TOGGLE,
              get=lambda: p["velocity_on"], set=engine.set_velocity_on,
              tooltip="When off, every note plays at one fixed velocity."),
    ]
    params += [
        envelope("amp_attack", "Attack", AMP_ATTACK_MAX,
                 "Time for a note to rise to full volume."),
        envelope("amp_decay", "Decay", AMP_DECAY_MAX,
                 "Time to fall from full volume to the sustain level."),
        envelope("amp_sustain", "Sustain", 1.0,
                 "Volume held while the key is down.", time=False),
        envelope("amp_release", "Release", AMP_RELEASE_MAX,
                 "Time for a note to fade out after the key is released."),
    ]
    params += [
        envelope("flt_attack", "Attack", AMP_ATTACK_MAX,
                 "Time for the filter to open after a note starts.",
                 group="Filter Env"),
        envelope("flt_decay", "Decay", AMP_DECAY_MAX,
                 "Time for the filter to fall to the sustain level.",
                 group="Filter Env"),
        envelope("flt_sustain", "Sustain", 1.0,
                 "Filter envelope level held while the key is down.",
                 time=False, group="Filter Env"),
        envelope("flt_release", "Release", AMP_RELEASE_MAX,
                 "Time for the filter envelope to fall after key release.",
                 group="Filter Env"),
    ]
    params += [
        Param(id="lfo_rate", label="Rate", group="LFO", kind=CONTINUOUS,
              minimum=LFO_RATE_MIN, maximum=LFO_RATE_MAX, scale="log",
              fmt="{:.2f} Hz", get=lambda: p["lfo_rate"], set=engine.set_lfo_rate,
              tooltip="LFO speed."),
        Param(id="lfo_depth", label="Depth", group="LFO", kind=CONTINUOUS,
              get=lambda: p["lfo_depth"], set=engine.set_lfo_depth,
              tooltip="LFO amount. 0 = LFO off."),
        Param(id="lfo_wave", label="Wave", group="LFO", kind=CHOICE,
              choices=LFO_WAVES, get=lambda: p["lfo_wave"], set=engine.set_lfo_wave,
              tooltip="LFO waveform. Random = sample and hold."),
        Param(id="lfo_dest", label="Dest", group="LFO", kind=CHOICE,
              choices=LFO_DESTS, get=lambda: p["lfo_dest"], set=engine.set_lfo_dest,
              tooltip="What the LFO modulates: pitch, filter cutoff, "
                      "pulse width or volume."),
        Param(id="glide_time", label="Time", group="Glide", kind=CONTINUOUS,
              minimum=0.0, maximum=GLIDE_MAX, fmt="{:.2f} s",
              get=lambda: p["glide_time"], set=engine.set_glide_time,
              tooltip="Time to slide from the previous note. 0 = off."),
        Param(id="glide_legato", label="Legato only", group="Glide", kind=TOGGLE,
              get=lambda: p["glide_legato"], set=engine.set_glide_legato,
              tooltip="Only glide when another key is still held."),
    ]
    pingpong = Param(
        id="fx_delay_pingpong", label="Ping-pong", group="Effects", kind=TOGGLE,
        under="fx_delay_time", get=lambda: fx.delay.pingpong,
        set=engine.set_delay_pingpong,
        tooltip="Bounce the echoes between the left and right speakers.")
    for n in EFFECT_NAMES:
        params.append(effect(n))
        params.append(dials[n])
        if n == "delay":
            params.append(pingpong)
    return ParamRegistry(params)
