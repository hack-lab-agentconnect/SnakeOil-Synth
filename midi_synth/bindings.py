from dataclasses import dataclass
from typing import Optional

CC = "cc"
NOTE = "note"
DEFAULT_NAME = "Default"
PROFILE_VERSION = 1


@dataclass(frozen=True)
class Source:
    kind: str
    number: int
    channel: Optional[int] = None  # 1-16, None = any channel

    def key(self):
        chan = "*" if self.channel is None else str(self.channel)
        return "%s:%s:%d" % (self.kind, chan, self.number)

    @classmethod
    def from_key(cls, key):
        kind, chan, num = key.split(":")
        if kind not in (CC, NOTE):
            raise ValueError("bad source kind: %r" % kind)
        number = int(num)
        if not 0 <= number <= 127:
            raise ValueError("bad source number: %d" % number)
        channel = None
        if chan != "*":
            channel = int(chan)
            if not 1 <= channel <= 16:
                raise ValueError("bad channel: %d" % channel)
        return cls(kind, number, channel)

    def label(self):
        base = ("CC %d" if self.kind == CC else "Note %d") % self.number
        return base if self.channel is None else "%s ch%d" % (base, self.channel)

    def overlaps(self, other):
        return (
            self.kind == other.kind
            and self.number == other.number
            and (self.channel is None or other.channel is None
                 or self.channel == other.channel)
        )


class Profile:
    def __init__(self, name, bindings=()):
        self.name = name
        self._by_source = {}
        self._by_param = {}
        for source, param_id in bindings:
            self.bind(source, param_id)

    def bind(self, source, param_id):
        for other in [s for s in self._by_source if s.overlaps(source)]:
            self._by_param.pop(self._by_source.pop(other), None)
        old = self._by_param.pop(param_id, None)
        if old is not None:
            self._by_source.pop(old, None)
        self._by_source[source] = param_id
        self._by_param[param_id] = source

    def clear(self, param_id):
        source = self._by_param.pop(param_id, None)
        if source is None:
            return False
        self._by_source.pop(source, None)
        return True

    def param_for(self, kind, channel, number):
        pid = self._by_source.get(Source(kind, number, channel))
        if pid is None:
            pid = self._by_source.get(Source(kind, number, None))
        return pid

    def source_for(self, param_id):
        return self._by_param.get(param_id)

    def items(self):
        return list(self._by_source.items())

    def copy(self, name):
        return Profile(name, self.items())

    def to_dict(self):
        return {
            "version": PROFILE_VERSION,
            "name": self.name,
            "bindings": [
                {"source": s.key(), "param": pid} for s, pid in self.items()
            ],
        }

    @classmethod
    def from_dict(cls, name, data):
        if not isinstance(data, dict) or not isinstance(data.get("bindings", []), list):
            raise ValueError("not a profile file")
        profile = cls(name)
        for entry in data.get("bindings", []):
            try:
                profile.bind(Source.from_key(entry["source"]), str(entry["param"]))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        return profile


_DEFAULT_CCS = (
    (1, "fm_depth"),
    (7, "master_gain"),
    (20, "fx_chorus"),
    (21, "fx_delay"),
    (22, "fx_reverb"),
    (23, "fx_bitcrush"),
    (26, "detune2_semitones"),
    (27, "detune2_cents"),
    (28, "osc2_level"),
    (29, "osc1_level"),
    (30, "mod_mode"),
    (71, "lpf_resonance"),
    (74, "lpf_cutoff"),
)


def default_profile(name=DEFAULT_NAME):
    return Profile(name, [(Source(CC, cc, None), pid) for cc, pid in _DEFAULT_CCS])
