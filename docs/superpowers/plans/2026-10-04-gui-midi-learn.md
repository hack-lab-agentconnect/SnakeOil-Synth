# GUI + MIDI Learn + Binding Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PySide6 GUI that controls every synth parameter, plus MIDI learn with named, file-backed binding profiles.

**Architecture:** A Qt-free core (`params.py` registry, `bindings.py` profile model, `profiles.py` file store, `midi_router.py` routing/learn) sits between `MidiInput` and `SynthEngine`. The GUI is a thin layer: each control wraps one registry entry, and a `Bridge` QObject turns registry/router callbacks (fired on the rtmidi thread) into queued Qt signals. The existing hard-coded CC map becomes the seeded `Default` profile.

**Tech Stack:** Python 3.12, PySide6, mido/python-rtmidi, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-10-04-gui-midi-learn-design.md` (two refinements are made in Task 9: bindings may use "any channel", and `Default` is never deletable, which also covers "last profile can't be deleted").

**Conventions:** Run everything from the repo root. Python is `.venv/Scripts/python.exe` (Git Bash path style). Tests: `.venv/Scripts/python.exe -m pytest ...`.

## File structure

| File | Responsibility |
|---|---|
| `pytest.ini`, `requirements-dev.txt`, `requirements.txt` | test config, deps |
| `midi_synth/params.py` | `Param` + `ParamRegistry` + `build_registry(engine)`: the one list of controllable params, value mapping, MIDI->value, change listeners |
| `midi_synth/bindings.py` | `Source`, `Profile`, `DEFAULT_NAME`, `default_profile()` |
| `midi_synth/profiles.py` | `ProfileStore` (files, active profile), `default_config_dir()`, `ProfileError` |
| `midi_synth/midi_router.py` | `MidiRouter`: lookup bound params, learn arm/bind, callbacks |
| `midi_synth/midi_input.py` | (modify) notes/pitch/program + delegate CC/notes to router; fix `--channel` off-by-one |
| `midi_synth/gui/__init__.py` | package marker |
| `midi_synth/gui/knob.py` | rotary knob widget |
| `midi_synth/gui/controls.py` | `ParamControl` (knob / combo / toggle + learn badge + context menu) |
| `midi_synth/gui/bridge.py` | `Bridge` QObject: thread-safe signals |
| `midi_synth/gui/style.py` | dark stylesheet string |
| `midi_synth/gui/main_window.py` | `MainWindow`: layout, profile toolbar, learn mode, footer |
| `midi_synth/gui/app.py` | `run_gui(...)` |
| `run.py` | (modify) store/registry/router wiring, `--no-gui`, `--profile`, `--config-dir` |
| `tests/test_*.py` | unit + offscreen GUI smoke tests |

---

### Task 0: Branch, dependencies, test scaffolding

**Files:**
- Create: `pytest.ini`, `requirements-dev.txt`
- Modify: `requirements.txt`

- [ ] **Step 1: Create a feature branch**

```bash
git checkout -b gui-midi-learn
```

- [ ] **Step 2: Add dependencies and pytest config**

Append to `requirements.txt`:

```
PySide6>=6.6
```

Create `requirements-dev.txt`:

```
-r requirements.txt
pytest>=8
```

Create `pytest.ini`:

```ini
[pytest]
testpaths = tests
pythonpath = .
```

- [ ] **Step 3: Install**

Run: `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`
Expected: ends with `Successfully installed ... PySide6 ... pytest ...`

- [ ] **Step 4: Verify tooling**

Run: `.venv/Scripts/python.exe -c "import PySide6, pytest; print(PySide6.__version__, pytest.__version__)"`
Expected: two version strings, no error.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini
git commit -m "Add PySide6 and pytest dependencies

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Parameter registry (`params.py`)

**Files:**
- Create: `midi_synth/params.py`
- Test: `tests/test_params.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_params.py`:

```python
import pytest

from midi_synth.engine import SynthEngine
from midi_synth.params import build_registry


@pytest.fixture
def rig():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    return engine, build_registry(engine)


def test_continuous_set_clamps_and_writes_engine(rig):
    engine, reg = rig
    reg.set("osc2_level", 5.0)
    assert engine.params["osc2_level"] == 1.0
    assert reg.get("osc2_level") == 1.0


def test_from_midi_continuous_endpoints(rig):
    _, reg = rig
    assert reg.from_midi("detune2_semitones", 0) == -12.0
    assert reg.from_midi("detune2_semitones", 127) == 12.0
    assert reg.from_midi("master_gain", 127) == pytest.approx(1.2)
    assert reg.from_midi("osc1_level", 0) == 0.0


def test_from_midi_choice_buckets(rig):
    _, reg = rig
    assert [reg.from_midi("osc1_waveform", v) for v in (0, 31, 32, 64, 96, 127)] == [
        "sine", "sine", "square", "saw", "triangle", "triangle",
    ]
    assert reg.from_midi("mod_mode", 0) == "off"
    assert reg.from_midi("mod_mode", 127) == "sync"
    assert reg.from_midi("osc1_waveform", 254) == "triangle"  # program-change style overflow


def test_toggle_fires_once_per_press(rig):
    engine, reg = rig
    assert reg.get("fx_chorus") is False
    reg.apply_midi("fx_chorus", 127)
    assert reg.get("fx_chorus") is True
    reg.apply_midi("fx_chorus", 127)  # held, no retrigger
    assert reg.get("fx_chorus") is True
    reg.apply_midi("fx_chorus", 0)
    reg.apply_midi("fx_chorus", 127)
    assert reg.get("fx_chorus") is False
    assert engine.effects.chorus.enabled is False


def test_set_choice_rejects_unknown_value(rig):
    _, reg = rig
    with pytest.raises(ValueError):
        reg.set("osc1_waveform", "wobble")


def test_mod_mode_change_also_notifies_fm_depth(rig):
    _, reg = rig
    seen = []
    reg.add_listener(seen.append)
    reg.set("mod_mode", "am")
    assert seen == ["mod_mode", "fm_depth"]
    assert reg.get("fm_depth") == pytest.approx(0.7)


def test_cents_setter_preserves_semitones(rig):
    engine, reg = rig
    reg.set("detune2_semitones", 3.0)
    reg.set("detune2_cents", 0.25)
    assert engine.params["detune2_semitones"] == 3.0
    assert engine.params["detune2_cents"] == 0.25


def test_ids_cover_every_group(rig):
    _, reg = rig
    assert set(reg.ids()) >= {
        "osc1_waveform", "osc1_level", "osc2_waveform", "osc2_level",
        "detune2_semitones", "detune2_cents", "mod_mode", "fm_depth",
        "master_gain", "fx_chorus", "fx_delay", "fx_reverb", "fx_bitcrush",
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_params.py -v`
Expected: collection ERROR `ModuleNotFoundError: No module named 'midi_synth.params'`

- [ ] **Step 3: Implement `midi_synth/params.py`**

```python
from dataclasses import dataclass
from typing import Any, Callable, Tuple

from .config import (
    WAVEFORMS,
    MODES,
    SEMITONE_MIN,
    SEMITONE_MAX,
    CENTS_MIN,
    CENTS_MAX,
)

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
            return param.minimum + (param.maximum - param.minimum) * min(max(value, 0), 127) / 127.0
        if param.kind == TOGGLE:
            return value >= 64
        idx = min(max(value, 0) * len(param.choices) // 128, len(param.choices) - 1)
        return param.choices[idx]

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

    params = [
        Param(id="osc1_waveform", label="Waveform", group="Oscillator 1", kind=CHOICE,
              choices=WAVEFORMS, get=lambda: p["osc1_waveform"],
              set=engine.set_osc1_waveform),
        Param(id="osc1_level", label="Level", group="Oscillator 1", kind=CONTINUOUS,
              get=lambda: p["osc1_level"], set=lambda v: engine.set_osc_level(1, v)),
        Param(id="osc2_waveform", label="Waveform", group="Oscillator 2", kind=CHOICE,
              choices=WAVEFORMS, get=lambda: p["osc2_waveform"],
              set=engine.set_osc2_waveform),
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
        Param(id="mod_mode", label="Mode", group="Modulation", kind=CHOICE,
              choices=MODES, get=lambda: p["mod_mode"], set=engine.set_mod_mode,
              affects=("fm_depth",)),
        Param(id="fm_depth", label="Amount", group="Modulation", kind=CONTINUOUS,
              get=lambda: p["fm_depth"], set=engine.set_fm_depth),
        Param(id="master_gain", label="Volume", group="Master", kind=CONTINUOUS,
              maximum=MASTER_GAIN_MAX, get=lambda: p["master_gain"],
              set=engine.set_master_gain),
    ] + [effect(n) for n in EFFECT_NAMES]
    return ParamRegistry(params)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_params.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add midi_synth/params.py tests/test_params.py
git commit -m "Add parameter registry with MIDI value mapping

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Bindings model (`bindings.py`)

**Files:**
- Create: `midi_synth/bindings.py`
- Test: `tests/test_bindings.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bindings.py`:

```python
import pytest

from midi_synth.bindings import (
    CC, NOTE, Source, Profile, default_profile, DEFAULT_NAME,
)


def test_source_key_roundtrip_and_label():
    s = Source(CC, 74, 3)
    assert s.key() == "cc:3:74"
    assert Source.from_key("cc:3:74") == s
    assert s.label() == "CC 74 ch3"
    any_ch = Source(NOTE, 60, None)
    assert any_ch.key() == "note:*:60"
    assert Source.from_key("note:*:60") == any_ch
    assert any_ch.label() == "Note 60"


@pytest.mark.parametrize("bad", ["cc:3", "foo:1:2", "cc:17:2", "cc:1:200", "cc:x:2"])
def test_source_from_key_rejects_garbage(bad):
    with pytest.raises(ValueError):
        Source.from_key(bad)


def test_bind_and_lookup_exact_channel():
    p = Profile("t")
    p.bind(Source(CC, 74, 1), "osc1_level")
    assert p.param_for(CC, 1, 74) == "osc1_level"
    assert p.param_for(CC, 2, 74) is None
    assert p.source_for("osc1_level") == Source(CC, 74, 1)


def test_any_channel_binding_matches_all_channels():
    p = Profile("t")
    p.bind(Source(CC, 1, None), "fm_depth")
    assert p.param_for(CC, 1, 1) == "fm_depth"
    assert p.param_for(CC, 16, 1) == "fm_depth"


def test_rebinding_param_moves_it():
    p = Profile("t")
    p.bind(Source(CC, 10, 1), "osc1_level")
    p.bind(Source(CC, 11, 1), "osc1_level")
    assert p.param_for(CC, 1, 10) is None
    assert p.param_for(CC, 1, 11) == "osc1_level"


def test_binding_taken_source_steals_it():
    p = Profile("t")
    p.bind(Source(CC, 10, 1), "osc1_level")
    p.bind(Source(CC, 10, 1), "osc2_level")
    assert p.source_for("osc1_level") is None
    assert p.param_for(CC, 1, 10) == "osc2_level"


def test_exact_binding_steals_overlapping_any_channel_binding():
    p = Profile("t")
    p.bind(Source(CC, 1, None), "fm_depth")
    p.bind(Source(CC, 1, 5), "master_gain")
    assert p.source_for("fm_depth") is None
    assert p.param_for(CC, 5, 1) == "master_gain"


def test_clear():
    p = Profile("t")
    p.bind(Source(CC, 10, 1), "osc1_level")
    assert p.clear("osc1_level") is True
    assert p.clear("osc1_level") is False
    assert p.param_for(CC, 1, 10) is None


def test_dict_roundtrip_and_malformed_entries_skipped():
    p = Profile("t")
    p.bind(Source(CC, 74, 2), "osc1_level")
    p.bind(Source(NOTE, 36, None), "fx_delay")
    data = p.to_dict()
    assert data["version"] == 1
    again = Profile.from_dict("t", data)
    assert sorted(again.items(), key=lambda x: x[1]) == sorted(p.items(), key=lambda x: x[1])

    data["bindings"].append({"source": "nonsense", "param": "x"})
    data["bindings"].append({"nope": 1})
    assert len(Profile.from_dict("t", data).items()) == 2


def test_from_dict_rejects_non_object():
    with pytest.raises(ValueError):
        Profile.from_dict("t", [1, 2, 3])


def test_copy_is_independent():
    p = Profile("a")
    p.bind(Source(CC, 5, 1), "osc1_level")
    q = p.copy("b")
    q.clear("osc1_level")
    assert q.name == "b"
    assert p.source_for("osc1_level") is not None


def test_default_profile_matches_legacy_cc_map():
    p = default_profile()
    assert p.name == DEFAULT_NAME
    expected = {
        1: "fm_depth", 7: "master_gain",
        20: "fx_chorus", 21: "fx_delay", 22: "fx_reverb", 23: "fx_bitcrush",
        24: "osc1_waveform", 25: "osc2_waveform",
        26: "detune2_semitones", 27: "detune2_cents",
        28: "osc2_level", 29: "osc1_level", 30: "mod_mode",
    }
    for cc, pid in expected.items():
        assert p.param_for(CC, 9, cc) == pid
    assert len(p.items()) == len(expected)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bindings.py -v`
Expected: collection ERROR `No module named 'midi_synth.bindings'`

- [ ] **Step 3: Implement `midi_synth/bindings.py`**

```python
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
    (24, "osc1_waveform"),
    (25, "osc2_waveform"),
    (26, "detune2_semitones"),
    (27, "detune2_cents"),
    (28, "osc2_level"),
    (29, "osc1_level"),
    (30, "mod_mode"),
)


def default_profile(name=DEFAULT_NAME):
    return Profile(name, [(Source(CC, cc, None), pid) for cc, pid in _DEFAULT_CCS])
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bindings.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add midi_synth/bindings.py tests/test_bindings.py
git commit -m "Add MIDI binding model with default legacy CC profile

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Profile store (`profiles.py`)

**Files:**
- Create: `midi_synth/profiles.py`
- Test: `tests/test_profiles.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profiles.py`:

```python
import json

import pytest

from midi_synth.bindings import CC, Source, default_profile, DEFAULT_NAME
from midi_synth.profiles import ProfileStore, ProfileError


@pytest.fixture
def store(tmp_path):
    s = ProfileStore(tmp_path / "cfg")
    s.ensure_default()
    return s


def test_first_run_seeds_default(store):
    assert store.names() == ["Default"]
    assert store.load("Default").param_for(CC, 1, 1) == "fm_depth"


def test_names_default_first_then_sorted(store):
    store.create("zeta")
    store.create("Alpha")
    assert store.names() == ["Default", "Alpha", "zeta"]


def test_save_load_roundtrip(store):
    p = default_profile()
    p.bind(Source(CC, 74, 3), "osc1_level")
    store.save(p)
    loaded = store.load("Default")
    assert loaded.source_for("osc1_level") == Source(CC, 74, 3)
    assert loaded.param_for(CC, 1, 1) == "fm_depth"


def test_unknown_params_survive_roundtrip(store):
    path = store.profiles_dir / "future.json"
    path.write_text(json.dumps({
        "version": 1,
        "bindings": [{"source": "cc:*:5", "param": "future_param"}],
    }))
    store.save(store.load("future"))
    assert "future_param" in path.read_text()


def test_duplicate_copies_bindings(store):
    p = store.load("Default")
    p.bind(Source(CC, 74, 1), "osc1_level")
    store.save(p)
    copy = store.duplicate("Default", "Mine")
    assert copy.name == "Mine"
    assert store.load("Mine").source_for("osc1_level") == Source(CC, 74, 1)


def test_create_is_blank(store):
    assert store.create("Blank").items() == []


def test_names_are_case_insensitive_unique(store):
    store.create("Live")
    with pytest.raises(ProfileError):
        store.create("live")


@pytest.mark.parametrize("bad", ["", "   ", "a/b", "a:b", "CON", "nul.x", "x.", "..", "a?b"])
def test_invalid_names_rejected(store, bad):
    with pytest.raises(ProfileError):
        store.create(bad)


def test_rename_updates_active(store):
    store.create("a")
    store.set_active("a")
    store.rename("a", "b")
    assert store.names() == ["Default", "b"]
    assert store.active_name() == "b"


def test_rename_default_or_onto_existing_refused(store):
    store.create("a")
    with pytest.raises(ProfileError):
        store.rename("Default", "x")
    with pytest.raises(ProfileError):
        store.rename("a", "default")


def test_rename_case_only_allowed(store):
    store.create("live")
    store.rename("live", "Live")
    assert "Live" in store.names()


def test_delete_active_falls_back_to_default(store):
    store.create("x")
    store.set_active("x")
    store.delete("x")
    assert store.names() == ["Default"]
    assert store.active_name() == DEFAULT_NAME


def test_delete_default_refused(store):
    with pytest.raises(ProfileError):
        store.delete("Default")


def test_reset_default_restores_factory(store):
    p = store.load("Default")
    p.clear("fm_depth")
    store.save(p)
    store.reset_default()
    assert store.load("Default").source_for("fm_depth") is not None


def test_corrupt_file_skipped_with_warning(store):
    (store.profiles_dir / "bad.json").write_text("{not json")
    assert store.names() == ["Default"]
    assert any("bad.json" in w for w in store.warnings)
    with pytest.raises(ProfileError):
        store.load("bad")


def test_load_missing_raises(store):
    with pytest.raises(ProfileError):
        store.load("nope")


def test_open_active_prefers_arg_then_stored_then_default(store):
    store.create("x")
    store.set_active("x")
    assert store.open_active().name == "x"
    assert store.open_active("nope").name == "x"
    assert store.open_active("Default").name == "Default"
    assert store.active_name() == "Default"


def test_open_active_recovers_corrupt_default(store):
    (store.profiles_dir / "Default.json").write_text("garbage")
    store.set_active("Default")
    p = store.open_active()
    assert p.param_for(CC, 1, 1) == "fm_depth"
    assert any("Default" in w for w in store.warnings)


def test_settings_file_corruption_ignored(store):
    store.settings_path.write_text("{{{")
    assert store.active_name() == DEFAULT_NAME
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profiles.py -v`
Expected: collection ERROR `No module named 'midi_synth.profiles'`

- [ ] **Step 3: Implement `midi_synth/profiles.py`**

```python
import json
import os
import re
import sys
from pathlib import Path

from .bindings import Profile, default_profile, DEFAULT_NAME


class ProfileError(Exception):
    pass


_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {
    "LPT%d" % i for i in range(1, 10)
}


def default_config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "midi-synth"


def validate_name(name):
    name = (name or "").strip()
    if (
        not name
        or name in (".", "..")
        or name.endswith(".")
        or _INVALID_CHARS.search(name)
        or name.split(".")[0].upper() in _RESERVED
    ):
        raise ProfileError("invalid profile name: %r" % name)
    return name


def _atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


class ProfileStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.profiles_dir = self.directory / "profiles"
        self.settings_path = self.directory / "settings.json"
        self.warnings = []

    def _warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def _find(self, name):
        if not self.profiles_dir.is_dir():
            return None
        wanted = name.lower()
        for path in self.profiles_dir.glob("*.json"):
            if path.stem.lower() == wanted:
                return path
        return None

    def _read(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Profile.from_dict(path.stem, data)
        except (OSError, ValueError) as exc:
            raise ProfileError("%s: %s" % (path.name, exc))

    def names(self):
        found = []
        if self.profiles_dir.is_dir():
            for path in self.profiles_dir.glob("*.json"):
                try:
                    self._read(path)
                except ProfileError as exc:
                    self._warn("Skipped unreadable profile %s" % exc)
                    continue
                found.append(path.stem)
        found.sort(key=lambda n: (n.lower() != DEFAULT_NAME.lower(), n.lower()))
        return found

    def load(self, name):
        path = self._find(name)
        if path is None:
            raise ProfileError("no such profile: %s" % name)
        return self._read(path)

    def save(self, profile):
        name = validate_name(profile.name)
        path = self._find(name) or (self.profiles_dir / (name + ".json"))
        _atomic_write_json(path, profile.to_dict())

    def create(self, name):
        name = validate_name(name)
        if self._find(name) is not None:
            raise ProfileError("profile already exists: %s" % name)
        profile = Profile(name)
        self.save(profile)
        return profile

    def duplicate(self, source_name, new_name):
        new_name = validate_name(new_name)
        if self._find(new_name) is not None:
            raise ProfileError("profile already exists: %s" % new_name)
        copy = self.load(source_name).copy(new_name)
        self.save(copy)
        return copy

    def rename(self, old, new):
        if old.lower() == DEFAULT_NAME.lower():
            raise ProfileError("the Default profile cannot be renamed")
        new = validate_name(new)
        src = self._find(old)
        if src is None:
            raise ProfileError("no such profile: %s" % old)
        clash = self._find(new)
        if clash is not None and clash != src:
            raise ProfileError("profile already exists: %s" % new)
        os.replace(src, self.profiles_dir / (new + ".json"))
        if self.active_name().lower() == old.lower():
            self.set_active(new)

    def delete(self, name):
        if name.lower() == DEFAULT_NAME.lower():
            raise ProfileError("the Default profile cannot be deleted")
        path = self._find(name)
        if path is None:
            raise ProfileError("no such profile: %s" % name)
        path.unlink()
        if self.active_name().lower() == name.lower():
            self.set_active(DEFAULT_NAME)

    def ensure_default(self):
        if self._find(DEFAULT_NAME) is None:
            self.save(default_profile())

    def reset_default(self):
        self.save(default_profile())

    def active_name(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return str(data.get("active") or DEFAULT_NAME)
        except (OSError, ValueError, AttributeError):
            return DEFAULT_NAME

    def set_active(self, name):
        _atomic_write_json(self.settings_path, {"active": name})

    def open_active(self, preferred=None):
        self.ensure_default()
        for name in (preferred, self.active_name(), DEFAULT_NAME):
            if not name:
                continue
            try:
                profile = self.load(name)
            except ProfileError as exc:
                if name.lower() == DEFAULT_NAME.lower():
                    self._warn("Default profile was unreadable (%s); restored defaults" % exc)
                continue
            self.set_active(profile.name)
            return profile
        self.reset_default()
        profile = self.load(DEFAULT_NAME)
        self.set_active(profile.name)
        return profile
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profiles.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add midi_synth/profiles.py tests/test_profiles.py
git commit -m "Add file-backed profile store

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: MIDI router (`midi_router.py`)

**Files:**
- Create: `midi_synth/midi_router.py`
- Test: `tests/test_midi_router.py`

Channels: mido channels are 0-15, profile `Source` channels are 1-16. The router takes mido's 0-15 and converts.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_midi_router.py`:

```python
import pytest

from midi_synth.bindings import CC, NOTE, Profile, Source, default_profile
from midi_synth.engine import SynthEngine
from midi_synth.midi_router import MidiRouter
from midi_synth.params import build_registry


@pytest.fixture
def rig():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    router = MidiRouter(registry, default_profile())
    return engine, registry, router


def test_bound_cc_sets_param(rig):
    engine, _, router = rig
    assert router.handle_cc(0, 1, 127) is True
    assert engine.params["fm_depth"] == 1.0


def test_unbound_cc_returns_false(rig):
    _, _, router = rig
    assert router.handle_cc(0, 99, 10) is False


def test_channel_specific_binding_ignores_other_channels(rig):
    engine, registry, _ = rig
    profile = Profile("t", [(Source(CC, 74, 2), "osc1_level")])
    router = MidiRouter(registry, profile)
    assert router.handle_cc(0, 74, 0) is False   # channel 1
    assert router.handle_cc(1, 74, 0) is True    # channel 2
    assert engine.params["osc1_level"] == 0.0


def test_learn_cc_binds_and_applies_afterwards(rig):
    engine, _, router = rig
    learned, changed = [], []
    router.on_learned = lambda pid, src: learned.append((pid, src))
    router.on_profile_changed = changed.append
    router.arm("osc1_level")
    assert router.armed == "osc1_level"
    assert router.handle_cc(2, 74, 64) is True
    assert router.armed is None
    assert learned == [("osc1_level", Source(CC, 74, 3))]
    assert changed == [router.profile]
    router.handle_cc(2, 74, 0)
    assert engine.params["osc1_level"] == 0.0


def test_learn_steals_param_from_old_source(rig):
    _, _, router = rig
    router.arm("osc1_level")           # default has CC 29 -> osc1_level
    router.handle_cc(0, 74, 10)
    assert router.profile.param_for(CC, 1, 29) is None
    assert router.profile.param_for(CC, 1, 74) == "osc1_level"


def test_learn_toggle_from_note(rig):
    _, registry, router = rig
    router.arm("fx_reverb")
    assert router.handle_note(0, 60, 100, True) is True
    assert router.profile.source_for("fx_reverb") == Source(NOTE, 60, 1)
    assert router.handle_note(0, 60, 0, False) is True       # release consumed
    assert registry.get("fx_reverb") is False                # binding press did not toggle
    router.handle_note(0, 60, 40, True)                      # soft press still toggles
    assert registry.get("fx_reverb") is True
    router.handle_note(0, 60, 0, False)


def test_notes_ignored_while_learning_continuous_param(rig):
    _, _, router = rig
    router.arm("osc1_level")
    assert router.handle_note(0, 60, 100, True) is False
    assert router.armed == "osc1_level"


def test_unbound_note_returns_false(rig):
    _, _, router = rig
    assert router.handle_note(0, 60, 100, True) is False
    assert router.handle_note(0, 60, 0, False) is False


def test_clear_binding_notifies_and_unbinds(rig):
    _, _, router = rig
    changed = []
    router.on_profile_changed = changed.append
    router.clear_binding("fm_depth")
    assert router.profile.source_for("fm_depth") is None
    assert len(changed) == 1
    router.clear_binding("fm_depth")        # already clear: no second notification
    assert len(changed) == 1


def test_message_callback_reports_cc(rig):
    _, _, router = rig
    seen = []
    router.on_message = seen.append
    router.handle_cc(0, 1, 127)
    assert seen == ["CC 1 ch1 = 127"]


def test_set_profile_disarms_and_swaps(rig):
    engine, _, router = rig
    router.arm("osc1_level")
    router.set_profile(Profile("empty"))
    assert router.armed is None
    assert router.handle_cc(0, 1, 127) is False


def test_arm_unknown_param_raises(rig):
    _, _, router = rig
    with pytest.raises(KeyError):
        router.arm("nope")


def test_save_failure_reported_not_raised(rig):
    _, _, router = rig
    seen = []
    router.on_message = seen.append

    def boom(profile):
        raise OSError("disk full")

    router.on_profile_changed = boom
    router.arm("osc1_level")
    router.handle_cc(0, 74, 1)
    assert any("disk full" in m for m in seen)
    assert router.profile.param_for(CC, 1, 74) == "osc1_level"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_midi_router.py -v`
Expected: collection ERROR `No module named 'midi_synth.midi_router'`

- [ ] **Step 3: Implement `midi_synth/midi_router.py`**

```python
import threading

from .bindings import CC, NOTE, Source
from .params import TOGGLE


class MidiRouter:
    """Maps incoming CC/note messages to registry params via the active profile.

    Callbacks (all optional) run on the calling MIDI thread:
      on_learned(param_id, source), on_message(text), on_profile_changed(profile)
    """

    def __init__(self, registry, profile):
        self.registry = registry
        self._profile = profile
        self._armed = None
        self._lock = threading.RLock()
        self.on_learned = None
        self.on_message = None
        self.on_profile_changed = None

    @property
    def profile(self):
        return self._profile

    @property
    def armed(self):
        return self._armed

    def set_profile(self, profile):
        with self._lock:
            self._profile = profile
            self._armed = None

    def arm(self, param_id):
        if param_id not in self.registry:
            raise KeyError(param_id)
        with self._lock:
            self._armed = param_id

    def disarm(self):
        with self._lock:
            self._armed = None

    def clear_binding(self, param_id):
        with self._lock:
            if self._profile.clear(param_id):
                self._changed()

    def handle_cc(self, channel, control, value):
        """channel is mido-style 0-15. Returns True if the message was consumed."""
        ch = channel + 1
        self._message("CC %d ch%d = %d" % (control, ch, value))
        with self._lock:
            if self._armed is not None:
                self._learn(Source(CC, control, ch))
                return True
            pid = self._profile.param_for(CC, ch, control)
            if pid is None or pid not in self.registry:
                return False
            self.registry.apply_midi(pid, value)
            return True

    def handle_note(self, channel, note, velocity, on):
        """channel is mido-style 0-15. Returns True if the note was consumed."""
        ch = channel + 1
        if on:
            self._message("Note %d ch%d" % (note, ch))
        with self._lock:
            if self._armed is not None and on:
                if self.registry[self._armed].kind == TOGGLE:
                    self._learn(Source(NOTE, note, ch))
                    return True
                return False
            pid = self._profile.param_for(NOTE, ch, note)
            if pid is None or pid not in self.registry:
                return False
            self.registry.apply_midi(pid, 127 if on else 0)
            return True

    def _learn(self, source):
        pid, self._armed = self._armed, None
        self._profile.bind(source, pid)
        self._changed()
        if self.on_learned:
            self.on_learned(pid, source)

    def _changed(self):
        if self.on_profile_changed:
            try:
                self.on_profile_changed(self._profile)
            except OSError as exc:
                self._message("Could not save profile: %s" % exc)

    def _message(self, text):
        if self.on_message:
            self.on_message(text)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_midi_router.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add midi_synth/midi_router.py tests/test_midi_router.py
git commit -m "Add MIDI router with learn mode

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Route `MidiInput` through the router

**Files:**
- Modify: `midi_synth/midi_input.py` (full rewrite below)
- Test: `tests/test_midi_input.py`

Also fixes an existing bug: `--channel N` is documented as 1-16 but was compared against mido's 0-15.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_midi_input.py`:

```python
import mido
import pytest

from midi_synth.bindings import NOTE, Source
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput


@pytest.fixture
def rig():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=4)
    return engine, MidiInput(engine)


def test_note_on_and_off_play_the_engine(rig):
    engine, midi = rig
    midi._on_message(mido.Message("note_on", note=60, velocity=100))
    assert engine.active_note_count() == 1
    assert any(v.gate for v in engine.voices)
    midi._on_message(mido.Message("note_off", note=60))
    assert not any(v.gate for v in engine.voices)


def test_note_on_velocity_zero_is_note_off(rig):
    engine, midi = rig
    midi._on_message(mido.Message("note_on", note=60, velocity=100))
    midi._on_message(mido.Message("note_on", note=60, velocity=0))
    assert not any(v.gate for v in engine.voices)


def test_default_profile_cc_controls_engine(rig):
    engine, midi = rig
    midi._on_message(mido.Message("control_change", control=29, value=0))
    assert engine.params["osc1_level"] == 0.0
    midi._on_message(mido.Message("control_change", control=21, value=127))
    assert engine.effects.delay.enabled is True


def test_note_bound_to_toggle_is_consumed_not_played(rig):
    engine, midi = rig
    midi.router.profile.bind(Source(NOTE, 36, None), "fx_delay")
    midi._on_message(mido.Message("note_on", note=36, velocity=100))
    assert engine.active_note_count() == 0
    assert engine.effects.delay.enabled is True


def test_learn_through_midi_input(rig):
    engine, midi = rig
    midi.router.arm("master_gain")
    midi._on_message(mido.Message("control_change", channel=4, control=50, value=0))
    midi._on_message(mido.Message("control_change", channel=4, control=50, value=127))
    assert engine.params["master_gain"] == pytest.approx(1.2)


def test_channel_filter_is_one_based():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    midi = MidiInput(engine, channel=2)
    midi._on_message(mido.Message("note_on", channel=0, note=60, velocity=100))
    assert engine.active_note_count() == 0
    midi._on_message(mido.Message("note_on", channel=1, note=60, velocity=100))
    assert engine.active_note_count() == 1


def test_pitchwheel_and_program_change(rig):
    engine, midi = rig
    midi._on_message(mido.Message("pitchwheel", pitch=8191))
    assert engine.params["pitch_bend"] > 1.9
    midi._on_message(mido.Message("program_change", program=64))
    assert engine.params["osc1_waveform"] == "triangle"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_midi_input.py -v`
Expected: FAILs (`AttributeError: 'MidiInput' object has no attribute 'router'`, and the channel test fails).

- [ ] **Step 3: Rewrite `midi_synth/midi_input.py`**

```python
import sys
import traceback

import mido

from .bindings import default_profile
from .midi_router import MidiRouter
from .params import build_registry


class MidiInput:
    def __init__(self, engine, ports=None, channel=None, router=None):
        self.engine = engine
        self.port_names = list(ports) if ports else None
        self.channel = channel  # 1-16, None = all
        self.ports = []
        if router is None:
            router = MidiRouter(build_registry(engine), default_profile())
        self.router = router
        self.registry = router.registry

    @staticmethod
    def available_ports():
        return mido.get_input_names()

    def start(self):
        names = self.port_names
        if not names:
            names = mido.get_input_names()
        if not names:
            raise RuntimeError("no MIDI input devices found")
        for name in names:
            self.ports.append(mido.open_input(name, callback=self._on_message))
        return [p.name for p in self.ports]

    def stop(self):
        for p in self.ports:
            try:
                p.close()
            except Exception:
                pass
        self.ports = []

    def _accepts(self, msg):
        if self.channel is None:
            return True
        channel = getattr(msg, "channel", None)
        return channel is not None and channel + 1 == self.channel

    def _on_message(self, msg):
        if not self._accepts(msg):
            return
        try:
            if msg.type == "note_on" and msg.velocity > 0:
                if not self.router.handle_note(msg.channel, msg.note, msg.velocity, True):
                    self.engine.note_on(msg.note, msg.velocity)
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                if not self.router.handle_note(msg.channel, msg.note, 0, False):
                    self.engine.note_off(msg.note)
            elif msg.type == "control_change":
                self.router.handle_cc(msg.channel, msg.control, msg.value)
            elif msg.type == "pitchwheel":
                self.engine.set_pitch_bend(msg.pitch / 8192.0)
            elif msg.type == "program_change":
                self.registry.apply_midi("osc1_waveform", msg.program * 2)
        except Exception:
            traceback.print_exc(file=sys.stderr)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: all tests pass (params, bindings, profiles, router, midi_input).

- [ ] **Step 5: Commit**

```bash
git add midi_synth/midi_input.py tests/test_midi_input.py
git commit -m "Route MIDI input through the profile router; fix channel filter off-by-one

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: GUI widgets (knob, control, bridge, style)

**Files:**
- Create: `midi_synth/gui/__init__.py` (empty), `knob.py`, `controls.py`, `bridge.py`, `style.py`
- Test: `tests/test_gui_widgets.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gui_widgets.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QPushButton  # noqa: E402

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.controls import ParamControl  # noqa: E402
from midi_synth.gui.knob import Knob  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def registry(qapp):
    return build_registry(SynthEngine(sr=44100, block_size=64, max_voices=2))


def test_knob_set_value_clamps_and_does_not_emit(qapp):
    knob = Knob(0.0, 1.0)
    seen = []
    knob.valueChanged.connect(seen.append)
    knob.setValue(5.0)
    assert knob.value() == 1.0
    assert seen == []


def test_knob_user_change_emits_and_double_click_resets(qapp):
    knob = Knob(0.0, 10.0, value=2.0)
    seen = []
    knob.valueChanged.connect(seen.append)
    knob.nudge(0.5)
    assert knob.value() == pytest.approx(7.0)
    knob.reset()
    assert knob.value() == 2.0
    assert seen == [pytest.approx(7.0), 2.0]


def test_continuous_control_writes_registry(registry):
    ctl = ParamControl(registry, registry["osc1_level"])
    assert isinstance(ctl.editor, Knob)
    ctl.editor.valueChanged.emit(0.25)
    assert registry.get("osc1_level") == 0.25


def test_choice_control_writes_and_refreshes(registry):
    ctl = ParamControl(registry, registry["osc1_waveform"])
    assert isinstance(ctl.editor, QComboBox)
    registry.set("osc1_waveform", "saw")
    ctl.refresh()
    assert ctl.editor.currentText() == "saw"
    ctl.editor.textActivated.emit("square")
    assert registry.get("osc1_waveform") == "square"


def test_toggle_control(registry):
    ctl = ParamControl(registry, registry["fx_delay"])
    assert isinstance(ctl.editor, QPushButton)
    ctl.editor.click()
    assert registry.get("fx_delay") is True
    registry.set("fx_delay", False)
    ctl.refresh()
    assert ctl.editor.isChecked() is False


def test_badge_and_learning_state(registry):
    ctl = ParamControl(registry, registry["fm_depth"])
    ctl.set_binding("CC 1")
    assert ctl.badge.text() == "CC 1"
    ctl.set_learning(True)
    assert "Move" in ctl.badge.text()
    ctl.set_learning(False)
    assert ctl.badge.text() == "CC 1"
    ctl.set_binding(None)
    assert ctl.badge.text() == ""


def test_learn_mode_click_requests_learn(registry):
    from PySide6.QtCore import Qt, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent

    ctl = ParamControl(registry, registry["fm_depth"])
    asked = []
    ctl.learnRequested.connect(asked.append)
    ctl.set_learn_mode(True)
    pos = QPointF(5, 5)
    ctl.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert asked == ["fm_depth"]
    ctl.set_learn_mode(False)
    ctl.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert asked == ["fm_depth"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_widgets.py -v`
Expected: collection ERROR `No module named 'midi_synth.gui'`

- [ ] **Step 3: Create `midi_synth/gui/__init__.py` (empty file) and `knob.py`**

`midi_synth/gui/knob.py`:

```python
import math

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

_START_DEG = 225.0
_SWEEP_DEG = 270.0
_DRAG_PIXELS = 200.0


class Knob(QWidget):
    """Rotary knob. valueChanged is emitted only for user-driven changes."""

    valueChanged = Signal(float)

    def __init__(self, minimum=0.0, maximum=1.0, value=None, formatter=None, parent=None):
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._value = self._clamp(self._min if value is None else value)
        self._default = self._value
        self._formatter = formatter or (lambda v: "%.2f" % v)
        self._drag_y = None
        self._drag_start = 0.0
        self._learning = False
        self.setMinimumSize(72, 88)
        self.setCursor(Qt.SizeVerCursor)
        self.setFocusPolicy(Qt.WheelFocus)

    def _clamp(self, v):
        return min(max(float(v), self._min), self._max)

    def value(self):
        return self._value

    def fraction(self):
        span = self._max - self._min
        return 0.0 if span == 0 else (self._value - self._min) / span

    def setValue(self, v):
        self._value = self._clamp(v)
        self.update()

    def setLearning(self, on):
        self._learning = bool(on)
        self.update()

    def _emit(self, v):
        v = self._clamp(v)
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)

    def nudge(self, fraction_delta):
        """Move by a fraction of the full range (user-driven)."""
        self._emit(self._value + fraction_delta * (self._max - self._min))

    def reset(self):
        self._value = self._clamp(self._default)
        self.update()
        self.valueChanged.emit(self._value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_y = event.position().y()
            self._drag_start = self._value

    def mouseMoveEvent(self, event):
        if self._drag_y is not None:
            delta = (self._drag_y - event.position().y()) / _DRAG_PIXELS
            self._emit(self._drag_start + delta * (self._max - self._min))

    def mouseReleaseEvent(self, event):
        self._drag_y = None

    def mouseDoubleClickEvent(self, event):
        self.reset()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        self.nudge(steps / 50.0)
        event.accept()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height() - 18) - 10
        rect = QRectF((self.width() - side) / 2.0, 5.0, side, side)
        pen = QPen(QColor("#3a3f4b"), 5.0, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(_START_DEG * 16), int(-_SWEEP_DEG * 16))
        frac = self.fraction()
        pen.setColor(QColor("#ffb74d") if self._learning else QColor("#4fc3f7"))
        p.setPen(pen)
        if frac > 0:
            p.drawArc(rect, int(_START_DEG * 16), int(-_SWEEP_DEG * 16 * frac))
        angle = math.radians(_START_DEG - _SWEEP_DEG * frac)
        c = rect.center()
        r = side / 2.0 - 9
        tip = QPointF(c.x() + r * math.cos(angle), c.y() - r * math.sin(angle))
        inner = QPointF(c.x() + 0.4 * (tip.x() - c.x()), c.y() + 0.4 * (tip.y() - c.y()))
        p.setPen(QPen(QColor("#e8eaf0"), 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(inner, tip)
        p.setPen(QColor("#c8ccd6"))
        p.drawText(QRectF(0, side + 6, self.width(), 16), Qt.AlignHCenter | Qt.AlignVCenter,
                   self._formatter(self._value))
```

- [ ] **Step 4: Create `midi_synth/gui/controls.py`**

```python
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QLabel, QMenu, QPushButton, QVBoxLayout,
)

from ..params import CHOICE, CONTINUOUS, TOGGLE
from .knob import Knob


class ParamControl(QFrame):
    """One GUI control bound to one registry param, with a MIDI-learn badge."""

    learnRequested = Signal(str)
    clearRequested = Signal(str)

    def __init__(self, registry, param, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.param = param
        self._learn_mode = False
        self._learning = False
        self._binding = None
        self.setObjectName("control")

        self.title = QLabel(param.label)
        self.title.setAlignment(Qt.AlignHCenter)
        self.editor = self._make_editor()
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        self.badge.setAlignment(Qt.AlignHCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(self.title)
        layout.addWidget(self.editor, 0, Qt.AlignHCenter)
        layout.addWidget(self.badge)
        self.refresh()

    def _make_editor(self):
        param, registry = self.param, self.registry
        if param.kind == CONTINUOUS:
            knob = Knob(param.minimum, param.maximum, value=param.get(),
                        formatter=param.fmt.format)
            knob.valueChanged.connect(lambda v: registry.set(param.id, v))
            return knob
        if param.kind == CHOICE:
            combo = QComboBox()
            combo.addItems(param.choices)
            combo.textActivated.connect(lambda text: registry.set(param.id, text))
            return combo
        button = QPushButton("Off")
        button.setCheckable(True)
        button.clicked.connect(lambda checked: registry.set(param.id, checked))
        return button

    def refresh(self):
        value = self.param.get()
        if self.param.kind == CONTINUOUS:
            self.editor.setValue(value)
        elif self.param.kind == CHOICE:
            self.editor.setCurrentText(value)
        else:
            self.editor.setChecked(bool(value))
            self.editor.setText("On" if value else "Off")

    def set_binding(self, text):
        self._binding = text
        self._update_badge()

    def set_learning(self, on):
        self._learning = bool(on)
        self.setProperty("learning", self._learning)
        self.style().unpolish(self)
        self.style().polish(self)
        if isinstance(self.editor, Knob):
            self.editor.setLearning(on)
        self._update_badge()

    def set_learn_mode(self, on):
        self._learn_mode = bool(on)
        self.editor.setAttribute(Qt.WA_TransparentForMouseEvents, self._learn_mode)
        self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)

    def _update_badge(self):
        if self._learning:
            self.badge.setText("Move a control…")
        else:
            self.badge.setText(self._binding or "")

    def mousePressEvent(self, event):
        if self._learn_mode and event.button() == Qt.LeftButton:
            self.learnRequested.emit(self.param.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        learn = menu.addAction("MIDI Learn")
        clear = menu.addAction("Clear binding")
        clear.setEnabled(self._binding is not None)
        chosen = menu.exec(event.globalPos())
        if chosen is learn:
            self.learnRequested.emit(self.param.id)
        elif chosen is clear:
            self.clearRequested.emit(self.param.id)
```

- [ ] **Step 5: Create `midi_synth/gui/bridge.py` and `style.py`**

`midi_synth/gui/bridge.py`:

```python
from PySide6.QtCore import QObject, Signal


class Bridge(QObject):
    """Turns registry/router callbacks (fired on the MIDI thread) into Qt signals.

    Qt queues a signal emitted from a non-GUI thread onto the receiver's thread.
    """

    param_changed = Signal(str)
    learned = Signal(str, str)
    message = Signal(str)

    def __init__(self, registry, router):
        super().__init__()
        registry.add_listener(self.param_changed.emit)
        router.on_learned = lambda pid, source: self.learned.emit(pid, source.label())
        router.on_message = self.message.emit
```

`midi_synth/gui/style.py`:

```python
STYLE = """
QWidget { background: #1b1e25; color: #dfe3ec; font-size: 13px; }
QMainWindow, QStatusBar { background: #1b1e25; }
QToolBar { background: #232733; border: 0; padding: 4px; spacing: 6px; }
QGroupBox { border: 1px solid #343a4a; border-radius: 6px; margin-top: 14px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #8f98ad; }
QFrame#control { border: 1px solid transparent; border-radius: 6px; }
QFrame#control[learning="true"] { border: 1px solid #ffb74d; background: #2a2620; }
QLabel#badge { color: #ffb74d; font-size: 11px; min-height: 14px; }
QPushButton, QComboBox { background: #2c3242; border: 1px solid #3d445a; border-radius: 4px; padding: 4px 10px; }
QPushButton:hover, QComboBox:hover { background: #343b50; }
QPushButton:checked { background: #1e88e5; border-color: #42a5f5; }
QPushButton:disabled { color: #666c7c; }
QComboBox QAbstractItemView { background: #2c3242; selection-background-color: #1e88e5; }
"""
```

- [ ] **Step 6: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_widgets.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add midi_synth/gui tests/test_gui_widgets.py
git commit -m "Add knob, param control and bridge widgets

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Main window and GUI entry point

**Files:**
- Create: `midi_synth/gui/main_window.py`, `midi_synth/gui/app.py`
- Test: `tests/test_gui_window.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gui_window.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midi_synth.bindings import CC, Source  # noqa: E402
from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.bridge import Bridge  # noqa: E402
from midi_synth.gui.main_window import MainWindow  # noqa: E402
from midi_synth.midi_router import MidiRouter  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402
from midi_synth.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def rig(qapp, tmp_path):
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, store.open_active())
    router.on_profile_changed = store.save
    bridge = Bridge(registry, router)
    window = MainWindow(engine, registry, router, store, ["Test Port"], bridge)
    return engine, registry, router, store, window


def test_every_param_has_a_control(rig):
    _, registry, _, _, window = rig
    assert set(window.controls) == set(registry.ids())


def test_default_bindings_show_as_badges(rig):
    *_, window = rig
    assert window.controls["fm_depth"].badge.text() == "CC 1"


def test_gui_edit_reaches_engine(rig):
    engine, *_, window = rig
    window.controls["osc1_level"].editor.valueChanged.emit(0.4)
    assert engine.params["osc1_level"] == 0.4


def test_midi_change_moves_gui_control(rig):
    _, _, router, _, window = rig
    router.handle_cc(0, 7, 127)
    assert window.controls["master_gain"].editor.value() == pytest.approx(1.2)


def test_learn_flow_binds_saves_and_updates_badge(rig):
    _, _, router, store, window = rig
    window._on_learn_requested("osc1_level")
    assert router.armed == "osc1_level"
    assert "Move" in window.controls["osc1_level"].badge.text()
    router.handle_cc(2, 74, 10)
    assert window.controls["osc1_level"].badge.text() == "CC 74 ch3"
    assert window.controls["osc1_level"]._learning is False
    assert store.load("Default").source_for("osc1_level") == Source(CC, 74, 3)


def test_escape_cancels_learn(rig):
    _, _, router, _, window = rig
    window._on_learn_requested("osc1_level")
    window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert router.armed is None
    assert window.controls["osc1_level"]._learning is False


def test_clear_binding(rig):
    _, _, router, store, window = rig
    window._on_clear_requested("fm_depth")
    assert window.controls["fm_depth"].badge.text() == ""
    assert store.load("Default").source_for("fm_depth") is None


def test_profile_switch_swaps_bindings(rig):
    _, _, router, store, window = rig
    store.create("Blank")
    window._reload_profiles("Blank")
    window._switch("Blank")
    assert router.profile.name == "Blank"
    assert window.controls["fm_depth"].badge.text() == ""
    assert store.active_name() == "Blank"
    window._switch("Default")
    assert window.controls["fm_depth"].badge.text() == "CC 1"


def test_delete_and_default_protection(rig):
    _, _, _, store, window = rig
    assert window.btn["delete"].isEnabled() is False
    assert window.btn["reset"].isEnabled() is True
    store.create("X")
    window._reload_profiles("X")
    window._switch("X")
    assert window.btn["delete"].isEnabled() is True
    assert window.btn["reset"].isEnabled() is False


def test_last_message_shown_in_footer(rig):
    _, _, router, _, window = rig
    router.handle_cc(0, 99, 5)
    assert "CC 99 ch1 = 5" in window.msg_label.text()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gui_window.py -v`
Expected: collection ERROR `No module named 'midi_synth.gui.main_window'`

- [ ] **Step 3: Implement `midi_synth/gui/main_window.py`**

```python
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QMainWindow, QMessageBox, QPushButton, QToolBar, QWidget,
)

from ..bindings import DEFAULT_NAME
from ..profiles import ProfileError
from .controls import ParamControl

GROUP_POSITIONS = {
    "Oscillator 1": (0, 0, 1, 1),
    "Oscillator 2": (0, 1, 1, 1),
    "Modulation": (0, 2, 1, 1),
    "Effects": (1, 0, 1, 2),
    "Master": (1, 2, 1, 1),
}


class MainWindow(QMainWindow):
    def __init__(self, engine, registry, router, store, midi_ports, bridge):
        super().__init__()
        self.setWindowTitle("MIDI Synth")
        self.engine = engine
        self.registry = registry
        self.router = router
        self.store = store
        self.controls = {}
        self.btn = {}

        self._build_toolbar()
        self._build_body()
        self._build_footer(midi_ports)

        bridge.param_changed.connect(self._on_param_changed)
        bridge.learned.connect(self._on_learned)
        bridge.message.connect(self._on_message)

        self._reload_profiles(router.profile.name)
        self._refresh_badges()
        for warning in store.warnings:
            self.statusBar().showMessage(warning, 8000)

    # ---- construction -------------------------------------------------

    def _build_toolbar(self):
        bar = QToolBar("Profiles")
        bar.setMovable(False)
        self.addToolBar(bar)
        bar.addWidget(QLabel("Profile: "))
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(160)
        self.profile_box.textActivated.connect(self._switch)
        bar.addWidget(self.profile_box)
        for key, text, slot in (
            ("new", "New", self._new_profile),
            ("duplicate", "Duplicate", self._duplicate_profile),
            ("rename", "Rename", self._rename_profile),
            ("delete", "Delete", self._delete_profile),
            ("reset", "Reset", self._reset_default),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, s=slot: s())
            bar.addWidget(button)
            self.btn[key] = button
        bar.addSeparator()
        self.learn_btn = QPushButton("MIDI Learn")
        self.learn_btn.setCheckable(True)
        self.learn_btn.toggled.connect(self._on_learn_mode)
        bar.addWidget(self.learn_btn)

    def _build_body(self):
        groups = {}
        for param in self.registry:
            box = groups.get(param.group)
            if box is None:
                box = QGroupBox(param.group)
                box.setLayout(QHBoxLayout())
                groups[param.group] = box
            control = ParamControl(self.registry, param)
            control.learnRequested.connect(self._on_learn_requested)
            control.clearRequested.connect(self._on_clear_requested)
            box.layout().addWidget(control)
            self.controls[param.id] = control
        grid = QGridLayout()
        for index, (name, box) in enumerate(groups.items()):
            grid.addWidget(box, *GROUP_POSITIONS.get(name, (2, index, 1, 1)))
        body = QWidget()
        body.setLayout(grid)
        self.setCentralWidget(body)

    def _build_footer(self, midi_ports):
        bar = self.statusBar()
        self.port_label = QLabel("MIDI: " + (", ".join(midi_ports) or "none"))
        self.msg_label = QLabel("Last MIDI: –")
        self.voice_label = QLabel("Voices: 0")
        for label in (self.port_label, self.msg_label, self.voice_label):
            bar.addPermanentWidget(label)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(250)

    # ---- profiles -----------------------------------------------------

    def _reload_profiles(self, select):
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        self.profile_box.addItems(self.store.names())
        self.profile_box.setCurrentText(select)
        self.profile_box.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self):
        is_default = self.profile_box.currentText().lower() == DEFAULT_NAME.lower()
        self.btn["rename"].setEnabled(not is_default)
        self.btn["delete"].setEnabled(not is_default)
        self.btn["reset"].setEnabled(is_default)

    def _switch(self, name):
        try:
            profile = self.store.load(name)
        except ProfileError as exc:
            self.statusBar().showMessage(str(exc), 6000)
            self._reload_profiles(self.router.profile.name)
            return
        self.router.set_profile(profile)
        self.store.set_active(profile.name)
        self._clear_learning_state()
        self._reload_profiles(profile.name)
        self._refresh_badges()

    def _ask_name(self, title, default=""):
        text, ok = QInputDialog.getText(self, title, "Profile name:", text=default)
        return text.strip() if ok else None

    def _run_store_action(self, action):
        try:
            return action()
        except ProfileError as exc:
            QMessageBox.warning(self, "Profile", str(exc))
            return None

    def _new_profile(self):
        name = self._ask_name("New profile")
        if name and self._run_store_action(lambda: self.store.create(name)):
            self._switch(name)

    def _duplicate_profile(self):
        current = self.profile_box.currentText()
        name = self._ask_name("Duplicate profile", current + " copy")
        if name and self._run_store_action(lambda: self.store.duplicate(current, name)):
            self._switch(name)

    def _rename_profile(self):
        current = self.profile_box.currentText()
        name = self._ask_name("Rename profile", current)
        if name and self._run_store_action(lambda: self.store.rename(current, name) or True):
            self._switch(name)

    def _delete_profile(self):
        current = self.profile_box.currentText()
        answer = QMessageBox.question(self, "Delete profile", "Delete profile '%s'?" % current)
        if answer == QMessageBox.Yes and self._run_store_action(
                lambda: self.store.delete(current) or True):
            self._switch(DEFAULT_NAME)

    def _reset_default(self):
        answer = QMessageBox.question(
            self, "Reset Default", "Restore the Default profile to factory bindings?")
        if answer == QMessageBox.Yes:
            self.store.reset_default()
            self._switch(DEFAULT_NAME)

    # ---- learn --------------------------------------------------------

    def _on_learn_mode(self, checked):
        for control in self.controls.values():
            control.set_learn_mode(checked)
        if checked:
            self.statusBar().showMessage("MIDI Learn: click a control, then move a MIDI control", 6000)
        else:
            self._cancel_learn()

    def _on_learn_requested(self, param_id):
        self.router.arm(param_id)
        for pid, control in self.controls.items():
            control.set_learning(pid == param_id)
        self.statusBar().showMessage("Move a control on your MIDI device… (Esc cancels)")

    def _on_clear_requested(self, param_id):
        self.router.clear_binding(param_id)
        self._refresh_badges()

    def _on_learned(self, param_id, label):
        self._clear_learning_state()
        self._refresh_badges()
        self.statusBar().showMessage(
            "Bound %s to %s" % (label, self.registry[param_id].label), 5000)

    def _clear_learning_state(self):
        for control in self.controls.values():
            control.set_learning(False)

    def _cancel_learn(self):
        self.router.disarm()
        self._clear_learning_state()
        self.statusBar().showMessage("Learn cancelled", 3000)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.router.armed is not None:
            self._cancel_learn()
            return
        super().keyPressEvent(event)

    # ---- sync ---------------------------------------------------------

    def _refresh_badges(self):
        profile = self.router.profile
        for pid, control in self.controls.items():
            source = profile.source_for(pid)
            control.set_binding(source.label() if source else None)

    def _on_param_changed(self, param_id):
        control = self.controls.get(param_id)
        if control is not None:
            control.refresh()

    def _on_message(self, text):
        self.msg_label.setText("Last MIDI: " + text)

    def _tick(self):
        self.voice_label.setText("Voices: %d" % self.engine.active_note_count())
```

- [ ] **Step 4: Implement `midi_synth/gui/app.py`**

```python
import sys

from PySide6.QtWidgets import QApplication

from .bridge import Bridge
from .main_window import MainWindow
from .style import STYLE


def run_gui(engine, registry, router, store, midi_ports):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyleSheet(STYLE)
    bridge = Bridge(registry, router)
    window = MainWindow(engine, registry, router, store, midi_ports, bridge)
    window.show()
    return app.exec()
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add midi_synth/gui tests/test_gui_window.py
git commit -m "Add main window with profile toolbar and MIDI learn

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Wire into `run.py`

**Files:**
- Modify: `run.py` (imports, `parse_args`, `main`)

- [ ] **Step 1: Add imports** (top of `run.py`, after the existing `from midi_synth.midi_input import MidiInput`)

```python
from pathlib import Path

from midi_synth.midi_router import MidiRouter
from midi_synth.params import build_registry
from midi_synth.profiles import ProfileStore, default_config_dir
```

- [ ] **Step 2: Add arguments** (in `parse_args`, directly before `return p.parse_args(argv)`)

```python
    p.add_argument("--no-gui", action="store_true", help="run the console only, no window")
    p.add_argument("--profile", default=None, metavar="NAME",
                   help="MIDI binding profile to load (default: last used)")
    p.add_argument("--config-dir", default=None, metavar="PATH",
                   help="where profiles are stored (default: per-user config dir)")
```

- [ ] **Step 3: Add GUI launcher helper** (above `main`)

```python
def launch_gui(engine, registry, router, store, ports):
    try:
        from midi_synth.gui.app import run_gui
    except ImportError as exc:
        print("GUI unavailable (%s); using the console. Install it with: pip install PySide6" % exc)
        return False
    run_gui(engine, registry, router, store, ports)
    return True
```

- [ ] **Step 4: Replace MIDI construction in `main`**

Replace:

```python
    midi = MidiInput(engine, ports=args.input, channel=args.channel)
    try:
        opened = midi.start()
```

with:

```python
    store = ProfileStore(Path(args.config_dir) if args.config_dir else default_config_dir())
    profile = store.open_active(args.profile)
    for warning in store.warnings:
        print("Profiles: %s" % warning)
    registry = build_registry(engine)
    router = MidiRouter(registry, profile)
    router.on_profile_changed = store.save
    midi = MidiInput(engine, ports=args.input, channel=args.channel, router=router)
    opened = []
    try:
        opened = midi.start()
```

- [ ] **Step 5: Replace the run loop in `main`**

Replace:

```python
        if args.no_console:
            while True:
                time.sleep(0.2)
        else:
            console_loop(engine)
```

with:

```python
        if not args.no_gui and launch_gui(engine, registry, router, store, opened):
            pass
        elif args.no_console:
            while True:
                time.sleep(0.2)
        else:
            console_loop(engine)
```

- [ ] **Step 6: Verify tests still pass and the CLI parses**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

Run: `.venv/Scripts/python.exe run.py --help`
Expected: help text includes `--no-gui`, `--profile`, `--config-dir`.

- [ ] **Step 7: Commit**

```bash
git add run.py
git commit -m "Launch GUI by default; add --no-gui, --profile, --config-dir

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Docs, spec refinements, manual verification

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-04-gui-midi-learn-design.md`

- [ ] **Step 1: Refine the spec**

In the spec under `### bindings.py`, change the `Source` bullet to: `Source`: `(msg_type, number, channel)` where msg_type is `cc` or `note` and channel is 1-16 or `None` (any channel; used by the Default profile so existing controllers on any channel keep working). Port-agnostic. An exact-channel binding replaces an overlapping any-channel binding.

Under `ProfileStore`, replace "`Default` can be reset to factory but not deleted; the last remaining profile cannot be deleted." with "`Default` can be reset to factory but not renamed or deleted (so at least one profile always exists)."

- [ ] **Step 2: Update README**

Add after the "Run" section's code block a "GUI and MIDI learn" section covering: the window opens by default (`--no-gui` for console); right-click a control -> MIDI Learn or toggle the MIDI Learn button and click controls, then move a knob / press a button; Esc cancels; toggles can also be learned from a note; profiles toolbar (New/Duplicate/Rename/Delete/Reset), profile files live in `%APPDATA%\midi-synth\profiles\*.json` (or `~/.config/midi-synth/profiles/`), copy files to share them; `--profile NAME` and `--config-dir PATH`. Change the heading "Default MIDI CC map" to "Default profile CC map" with a one-line note that it's the seeded `Default` profile and now editable. Also update the Install section to mention PySide6 and `requirements-dev.txt` for tests.

- [ ] **Step 3: Manual verification in the real app**

Run: `.venv/Scripts/python.exe run.py --config-dir C:/Users/joelt/AppData/Local/Temp/midi-synth-manual`
Verify and report on each:
1. Window opens; footer shows the MIDI port(s) or `none`; audio output line printed in the terminal.
2. Dragging the Osc 1 Level knob, changing a waveform, toggling Reverb all change the sound (play a note on the controller).
3. Right-click Master Volume -> MIDI Learn, move a knob on the controller: badge shows the new CC, the on-screen knob follows the controller afterwards.
4. Learn an effect toggle from a pad/key.
5. New profile -> badges clear; switch back to Default -> badges return; restart the app and confirm the last profile and bindings persisted.
6. Take a screenshot of the window and check layout/readability at the default size.

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add README.md docs
git commit -m "Document GUI, MIDI learn and profiles

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage:** GUI controlling all params (Tasks 1, 6, 7); MIDI learn (4, 6, 7); profiles incl. file storage, new/duplicate/rename/delete/reset/active (3, 7); two-way sync via registry listeners + Bridge (6, 7); default-launch + flags (8); error handling for corrupt profiles/save failure/no MIDI (3, 4, 7, 8); testing (every task + manual in 9).
- **Spec deviations** (made explicit in Task 9): any-channel bindings and Default-undeletable.
- **Bug fixed in passing:** `--channel` off-by-one (Task 5).
- **Type consistency:** `Source(kind, number, channel)` argument order used identically in `bindings.py`, router, and all tests; `router.handle_cc/handle_note` take mido 0-15 channels; param ids (`fx_*`, `detune2_*`, etc.) match between `params.py`, `bindings._DEFAULT_CCS` and tests.
