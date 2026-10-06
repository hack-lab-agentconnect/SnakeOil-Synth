"""Mod matrix logic: sources, destination table and relative scaling.

A matrix row is ``source -> scale -> destination``. The modulation is
relative to the destination's base value:
``effective = base * (1 + sum(scale_k * source_k))``, clamped to the
destination's range. A base of 0 therefore stays 0.
"""
from dataclasses import dataclass

from .config import (
    AMP_ATTACK_MAX,
    AMP_DECAY_MAX,
    AMP_RELEASE_MAX,
    AMP_TIME_MIN,
    CENTS_MAX,
    CENTS_MIN,
    MOD_SMOOTH,
    SEMITONE_MAX,
    SEMITONE_MIN,
    TEMPO_MAX,
    TEMPO_MIN,
    UNISON_DETUNE_MAX,
)
from .filters import LPF_MAX_HZ, LPF_MIN_HZ

SOURCES = ("none", "Note Number", "LFO 1", "LFO 2", "Mod Wheel", "Aftertouch")
NUM_SLOTS = 8

SRC_NONE, SRC_NOTE, SRC_LFO1, SRC_LFO2, SRC_WHEEL, SRC_AFTERTOUCH = range(len(SOURCES))

VOICE = "voice"
GLOBAL = "global"


@dataclass(frozen=True)
class Destination:
    name: str
    param_id: str
    kind: str
    lo: float
    hi: float


DESTINATIONS = (
    Destination("Osc 1: Level", "osc1_level", VOICE, 0.0, 1.0),
    Destination("Osc 1: PWM", "osc1_pwm", VOICE, 0.0, 0.5),
    Destination("Osc 1: Sq Level", "osc1_square_level", VOICE, 0.0, 1.0),
    Destination("Osc 2: Level", "osc2_level", VOICE, 0.0, 1.0),
    Destination("Osc 2: Tune", "detune2_semitones", VOICE, SEMITONE_MIN, SEMITONE_MAX),
    Destination("Osc 2: Fine", "detune2_cents", VOICE, CENTS_MIN, CENTS_MAX),
    Destination("Osc 2: PWM", "osc2_pwm", VOICE, 0.0, 0.5),
    Destination("Noise: Level", "noise_level", VOICE, 0.0, 1.0),
    Destination("Modulation Amount", "fm_depth", VOICE, 0.0, 1.0),
    Destination("Tempo", "tempo_bpm", GLOBAL, TEMPO_MIN, TEMPO_MAX),
    Destination("Filter: Cutoff", "lpf_cutoff", VOICE, LPF_MIN_HZ, LPF_MAX_HZ),
    Destination("Filter: Resonance", "lpf_resonance", VOICE, 0.0, 1.0),
    Destination("Filter: Env Amount", "flt_env_amount", VOICE, -1.0, 1.0),
    Destination("Filter: Key Trk", "flt_keytrack", VOICE, 0.0, 1.0),
    Destination("Filter: Vel>Cut", "flt_vel", VOICE, 0.0, 1.0),
    Destination("Filter Env: Attack", "flt_attack", VOICE, AMP_TIME_MIN, AMP_ATTACK_MAX),
    Destination("Filter Env: Decay", "flt_decay", VOICE, AMP_TIME_MIN, AMP_DECAY_MAX),
    Destination("Filter Env: Sustain", "flt_sustain", VOICE, 0.0, 1.0),
    Destination("Filter Env: Release", "flt_release", VOICE, AMP_TIME_MIN, AMP_RELEASE_MAX),
    Destination("Amp Env: Attack", "amp_attack", VOICE, AMP_TIME_MIN, AMP_ATTACK_MAX),
    Destination("Amp Env: Decay", "amp_decay", VOICE, AMP_TIME_MIN, AMP_DECAY_MAX),
    Destination("Amp Env: Sustain", "amp_sustain", VOICE, 0.0, 1.0),
    Destination("Amp Env: Release", "amp_release", VOICE, AMP_TIME_MIN, AMP_RELEASE_MAX),
    Destination("Chorus: Depth", "fx_chorus_depth", GLOBAL, 0.0, 1.0),
    # delay time: engine limits, not the 200 ms knob minimum (synced times are shorter)
    Destination("Delay: Time", "fx_delay_time", GLOBAL, 1.0, 4000.0),
    Destination("Delay: Feedback", "fx_delay_feedback", GLOBAL, 0.0, 0.95),
    Destination("Delay: Tone", "fx_delay_damp", GLOBAL, 0.0, 0.9),
    Destination("Reverb: Amount", "fx_reverb_amount", GLOBAL, 0.0, 1.0),
    Destination("Reverb: Size", "fx_reverb_size", GLOBAL, 0.5, 0.98),
    Destination("Reverb: Damping", "fx_reverb_damp", GLOBAL, 0.0, 0.9),
    Destination("Bitcrush: Crush", "fx_bitcrush_amount", GLOBAL, 0.0, 1.0),
    Destination("Unison: Detune", "unison_detune", VOICE, 0.0, UNISON_DETUNE_MAX),
    Destination("Unison: Spread", "unison_spread", VOICE, 0.0, 1.0),
)

ENVELOPE_PARAMS = ("amp_attack", "amp_decay", "amp_sustain", "amp_release",
                   "flt_attack", "flt_decay", "flt_sustain", "flt_release")
UNISON_PARAMS = ("unison_detune", "unison_spread")
TEMPO_PARAM = "tempo_bpm"
DELAY_TIME_PARAM = "fx_delay_time"
FX_PARAMS = ("fx_chorus_depth", "fx_delay_time", "fx_delay_feedback", "fx_delay_damp",
             "fx_reverb_amount", "fx_reverb_size", "fx_reverb_damp", "fx_bitcrush_amount")

DEST_NAMES = ("none",) + tuple(d.name for d in DESTINATIONS)
_BY_NAME = {d.name: d for d in DESTINATIONS}


def destination(name):
    """The Destination called ``name`` (KeyError for 'none' or unknown)."""
    return _BY_NAME[name]


def effective(base, terms, lo, hi):
    """``base * (1 + sum(scale * source))`` clamped to ``[lo, hi]``."""
    total = 0.0
    for scale, value in terms:
        total += scale * value
    return min(max(base * (1.0 + total), lo), hi)


def note_source(note):
    """Note number as a bipolar source: middle C = 0, clipped to [-1, 1]."""
    if note is None:
        return 0.0
    return min(max((note - 60) / 60.0, -1.0), 1.0)


def smooth(current, target, coeff=MOD_SMOOTH):
    """One one-pole smoothing step towards ``target``."""
    return current + coeff * (target - current)


_SOURCE_ALIASES = {
    "none": "none",
    "note": "Note Number", "notenumber": "Note Number",
    "lfo1": "LFO 1", "lfo2": "LFO 2",
    "wheel": "Mod Wheel", "modwheel": "Mod Wheel",
    "aftertouch": "Aftertouch",
}


def _squash(text):
    return "".join(text.split()).strip("\"'").lower()


def parse_mod_args(tokens):
    """Parse ``<slot> <source> <scale -100..100> <destination>`` console words.

    Names may be split over several words ("lfo 1", "Osc 1: Level") and are
    matched case-insensitively with spaces ignored. Returns
    ``(slot, source, scale, destination)`` with scale in -1..1; raises
    ValueError on bad input.
    """
    tokens = list(tokens)
    if len(tokens) < 4:
        raise ValueError("too few arguments")
    slot = int(tokens[0])
    if not 1 <= slot <= NUM_SLOTS:
        raise ValueError("slot out of range")
    dest_aliases = {_squash(n): n for n in DEST_NAMES}
    for n in DEST_NAMES:
        if n.startswith("Amp Env:"):
            dest_aliases.setdefault(_squash("Amp" + n[len("Amp Env"):]), n)
    for k in (1, 2):
        source = _SOURCE_ALIASES.get(_squash("".join(tokens[1:1 + k])))
        if source is None or len(tokens) < k + 3:
            continue
        try:
            percent = float(tokens[1 + k])
        except ValueError:
            continue
        dest = dest_aliases.get(_squash("".join(tokens[2 + k:])))
        if dest is None or not -100.0 <= percent <= 100.0:
            raise ValueError("bad scale or destination")
        return slot, source, percent / 100.0, dest
    raise ValueError("bad source")
