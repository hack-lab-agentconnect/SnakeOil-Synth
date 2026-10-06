"""Mod matrix logic: sources, destination table and relative scaling.

A matrix row is ``source -> scale -> destination``. The modulation is
relative to the destination's base value:
``effective = base * (1 + sum(scale_k * source_k))``, clamped to the
destination's range. A base of 0 therefore stays 0.
"""
from dataclasses import dataclass

from .config import CENTS_MAX, CENTS_MIN, MOD_SMOOTH, SEMITONE_MAX, SEMITONE_MIN
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
    Destination("Modulation Amount", "fm_depth", VOICE, 0.0, 1.0),
    Destination("Filter: Cutoff", "lpf_cutoff", VOICE, LPF_MIN_HZ, LPF_MAX_HZ),
    Destination("Filter: Resonance", "lpf_resonance", VOICE, 0.0, 1.0),
    Destination("Filter: Env Amount", "flt_env_amount", VOICE, -1.0, 1.0),
    Destination("Filter: Key Trk", "flt_keytrack", VOICE, 0.0, 1.0),
    Destination("Filter: Vel>Cut", "flt_vel", VOICE, 0.0, 1.0),
)

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
