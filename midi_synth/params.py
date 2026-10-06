import math
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
    LFO1_DESTS,
    LFO2_DESTS,
    LFO_RATE_MIN,
    LFO_RATE_MAX,
    GLIDE_MAX,
    UNISON_MAX,
    UNISON_DETUNE_MAX,
    TEMPO_MIN,
    TEMPO_MAX,
    DELAY_DIVISION_NAMES,
)
from .filters import LPF_MIN_HZ, LPF_MAX_HZ
from .modmatrix import DEST_NAMES, NUM_SLOTS, SOURCES

CONTINUOUS = "continuous"
TOGGLE = "toggle"
CHOICE = "choice"

EFFECT_NAMES = ("chorus", "delay", "reverb", "bitcrush")
MASTER_GAIN_MAX = 1.2


def format_percent(value):
    """Signed whole percent: '+37%', '-100%'."""
    return "%+d%%" % round(value * 100.0)


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
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("%s must be a finite number, got %r" % (param.id, value))
            return min(max(number, param.minimum), param.maximum)
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
            under="fx_delay", get=lambda: engine.delay_manual_ms,
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
        Param(id="osc1_square_level", label="Sq Level", group="Oscillator 1",
              kind=CONTINUOUS, minimum=0.0, maximum=1.0, fmt="{:.2f}",
              get=lambda: p["osc1_square_level"], set=engine.set_osc1_square_level,
              tooltip="How much square is added on top of the saw."),
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
        Param(id="lfo_rate", label="Rate", group="LFO 1", kind=CONTINUOUS,
              minimum=LFO_RATE_MIN, maximum=LFO_RATE_MAX, scale="log",
              fmt="{:.2f} Hz", get=lambda: p["lfo_rate"], set=engine.set_lfo_rate,
              tooltip="LFO speed."),
        Param(id="lfo_depth", label="Depth", group="LFO 1", kind=CONTINUOUS,
              get=lambda: p["lfo_depth"], set=engine.set_lfo_depth,
              tooltip="LFO amount. 0 = LFO off."),
        Param(id="lfo_wave", label="Wave", group="LFO 1", kind=CHOICE,
              choices=LFO_WAVES, get=lambda: p["lfo_wave"], set=engine.set_lfo_wave,
              tooltip="LFO waveform. Random = sample and hold."),
        Param(id="lfo_dest", label="Dest", group="LFO 1", kind=CHOICE,
              choices=LFO1_DESTS, get=lambda: p["lfo_dest"], set=engine.set_lfo_dest,
              tooltip="What the LFO modulates: pitch, filter cutoff, "
                      "pulse width, volume, or the rate of LFO 2."),
        Param(id="lfo2_rate", label="Rate", group="LFO 2", kind=CONTINUOUS,
              minimum=LFO_RATE_MIN, maximum=LFO_RATE_MAX, scale="log",
              fmt="{:.2f} Hz", get=lambda: p["lfo2_rate"], set=engine.set_lfo2_rate,
              tooltip="LFO 2 speed."),
        Param(id="lfo2_depth", label="Depth", group="LFO 2", kind=CONTINUOUS,
              get=lambda: p["lfo2_depth"], set=engine.set_lfo2_depth,
              tooltip="LFO 2 amount. 0 = LFO 2 off."),
        Param(id="lfo2_wave", label="Wave", group="LFO 2", kind=CHOICE,
              choices=LFO_WAVES, get=lambda: p["lfo2_wave"], set=engine.set_lfo2_wave,
              tooltip="LFO 2 waveform. Random = sample and hold."),
        Param(id="lfo2_dest", label="Dest", group="LFO 2", kind=CHOICE,
              choices=LFO2_DESTS, get=lambda: p["lfo2_dest"], set=engine.set_lfo2_dest,
              tooltip="What LFO 2 modulates: pitch, filter cutoff, "
                      "pulse width, volume, or the rate of LFO 1."),
        Param(id="glide_time", label="Time", group="Glide", kind=CONTINUOUS,
              minimum=0.0, maximum=GLIDE_MAX, fmt="{:.2f} s",
              get=lambda: p["glide_time"], set=engine.set_glide_time,
              tooltip="Time to slide from the previous note. 0 = off."),
        Param(id="glide_legato", label="Legato only", group="Glide", kind=TOGGLE,
              get=lambda: p["glide_legato"], set=engine.set_glide_legato,
              tooltip="Only glide when another key is still held."),
    ]
    params += [
        Param(id="unison_voices", label="Voices", group="Unison", kind=CHOICE,
              choices=tuple(str(i) for i in range(1, UNISON_MAX + 1)),
              get=lambda: str(p["unison_voices"]), set=engine.set_unison_voices,
              tooltip="Voices stacked per note. Polyphony drops to "
                      "12 divided by this. 1 = off."),
        Param(id="unison_detune", label="Detune", group="Unison", kind=CONTINUOUS,
              minimum=0.0, maximum=UNISON_DETUNE_MAX, fmt="{:.0f} ct",
              get=lambda: p["unison_detune"], set=engine.set_unison_detune,
              tooltip="Pitch spread of the outermost unison voices, in cents."),
        Param(id="unison_spread", label="Spread", group="Unison", kind=CONTINUOUS,
              get=lambda: p["unison_spread"], set=engine.set_unison_spread,
              tooltip="Stereo width of the unison voices."),
    ]
    params += [
        Param(id="tempo_bpm", label="BPM", group="Tempo", kind=CONTINUOUS,
              minimum=TEMPO_MIN, maximum=TEMPO_MAX, fmt="{:.0f}",
              get=lambda: p["tempo_bpm"], set=engine.set_tempo_bpm,
              tooltip="Manual tempo, used when no MIDI clock is arriving."),
    ]
    def mod_row(i):
        row = engine.mod_rows[i - 1]
        group = "Mod Matrix"
        return [
            Param(id="mod%d_src" % i, label="Source", group=group, kind=CHOICE,
                  choices=SOURCES, get=lambda: row[0],
                  set=lambda v: engine.set_mod_src(i, v),
                  tooltip="What drives matrix row %d." % i),
            Param(id="mod%d_amt" % i, label="Scale", group=group,
                  kind=CONTINUOUS, minimum=-1.0, maximum=1.0,
                  formatter=format_percent, widget="hslider",
                  get=lambda: row[1], set=lambda v: engine.set_mod_amt(i, v),
                  tooltip="Modulation relative to the destination's current "
                          "value: value x (1 + scale x source). A destination "
                          "at 0 stays at 0."),
            Param(id="mod%d_dst" % i, label="Destination", group=group,
                  kind=CHOICE, choices=DEST_NAMES, get=lambda: row[2],
                  set=lambda v: engine.set_mod_dst(i, v),
                  tooltip="What matrix row %d modulates." % i),
        ]

    for slot in range(1, NUM_SLOTS + 1):
        params += mod_row(slot)
    pingpong = Param(
        id="fx_delay_pingpong", label="Ping-pong", group="Effects", kind=TOGGLE,
        under="fx_delay_time", get=lambda: fx.delay.pingpong,
        set=engine.set_delay_pingpong,
        tooltip="Bounce the echoes between the left and right speakers.")
    extras = {
        "delay": [
            pingpong,
            Param(id="fx_delay_feedback", label="Feedback", group="Effects",
                  kind=CONTINUOUS, minimum=0.0, maximum=0.95, under="fx_delay",
                  get=lambda: fx.delay.feedback, set=engine.set_delay_feedback,
                  tooltip="How much of each echo is fed back. High = "
                          "long trailing repeats."),
            Param(id="fx_delay_damp", label="Tone", group="Effects",
                  kind=CONTINUOUS, minimum=0.0, maximum=0.9, under="fx_delay",
                  get=lambda: fx.delay.damp, set=engine.set_delay_damp,
                  tooltip="Echo brightness: higher = darker echoes."),
            Param(id="fx_delay_sync", label="Sync", group="Effects",
                  kind=TOGGLE, under="fx_delay_time",
                  get=lambda: p["delay_sync"], set=engine.set_delay_sync,
                  tooltip="Lock the delay time to the tempo (MIDI clock "
                          "when present, otherwise the BPM setting)."),
            Param(id="fx_delay_division", label="Division", group="Effects",
                  kind=CHOICE, choices=DELAY_DIVISION_NAMES,
                  under="fx_delay_time", get=lambda: p["delay_division"],
                  set=engine.set_delay_division,
                  tooltip="Note length of one echo when synced. "
                          ". = dotted, T = triplet."),
        ],
        "reverb": [
            Param(id="fx_reverb_size", label="Size", group="Effects",
                  kind=CONTINUOUS, minimum=0.5, maximum=0.98,
                  under="fx_reverb", get=lambda: fx.reverb.room,
                  set=engine.set_reverb_size,
                  tooltip="Room size: how long the reverb tail rings."),
            Param(id="fx_reverb_damp", label="Damping", group="Effects",
                  kind=CONTINUOUS, minimum=0.0, maximum=0.9,
                  under="fx_reverb", get=lambda: fx.reverb.damp,
                  set=engine.set_reverb_damp,
                  tooltip="High-frequency absorption in the reverb tail. "
                          "Higher = darker, softer tail."),
        ],
    }
    for n in EFFECT_NAMES:
        params.append(effect(n))
        params.append(dials[n])
        params.extend(extras.get(n, ()))
    return ParamRegistry(params)
