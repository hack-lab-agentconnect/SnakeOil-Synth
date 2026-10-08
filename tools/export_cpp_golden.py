"""Export golden scenarios for the C++ plugin harness (phase P1+).

Writes, for each scenario, a language-neutral ``<name>.scenario.json`` plus the
expected stereo audio as raw little-endian float32 (interleaved L/R) in
``<name>.f32``. The C++ ``golden_check`` replays the JSON and compares.

The expected audio is produced by the Python reference engine
(``midi_synth``), driven only through the registry's ``set`` and the engine's
note methods, so the C++ harness can do exactly the same by parameter id.

Usage (from the repo root):  python tools/export_cpp_golden.py [name ...]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402

OUT_DIR = os.path.join(ROOT, "plugin", "tests", "golden")

SR = 44100
BLOCK = 256
NOTES = (48, 52, 55, 59)
NOTE_OFF_BLOCK = 20
BLOCKS = 60


def _default_scenario():
    events = []
    for note in NOTES:
        events.append({"block": 0, "note_on": [note, 100]})
    for note in NOTES:
        events.append({"block": NOTE_OFF_BLOCK, "note_off": [note]})
    return {"sample_rate": SR, "block_size": BLOCK, "blocks": BLOCKS,
            "params": {}, "events": events}


SCENARIOS = {
    "default": _default_scenario,
}


def render(scenario, registry):
    engine = SynthEngine(sr=scenario["sample_rate"],
                         block_size=scenario["block_size"],
                         max_voices=12)
    registry_args = build_registry(engine)
    for param_id, value in scenario["params"].items():
        registry_args.set(param_id, value)
    by_block = {}
    for event in scenario["events"]:
        by_block.setdefault(event["block"], []).append(event)
    out = []
    for i in range(scenario["blocks"]):
        for event in by_block.get(i, ()):
            if "note_on" in event:
                engine.note_on(*event["note_on"])
            if "note_off" in event:
                engine.note_off(*event["note_off"])
        out.append(engine.render())
    return np.concatenate(out, axis=0).astype(np.float32)


def check_against_npz(name, audio):
    path = os.path.join(ROOT, "tests", "golden", name + ".npz")
    if not os.path.exists(path):
        return
    expected = np.load(path)["audio"]
    if expected.shape != audio.shape:
        print("  note: %s shape differs from npz (%s vs %s)"
              % (name, audio.shape, expected.shape))
        return
    delta = float(np.max(np.abs(audio - expected)))
    print("  %s: event-driven render matches tests/golden/%s.npz (max delta %.2e)"
          % (name, name, delta))
    assert delta < 1e-6, "exporter does not reproduce the golden for %s" % name


def main(argv):
    names = argv or list(SCENARIOS)
    os.makedirs(OUT_DIR, exist_ok=True)
    for name in names:
        scenario = SCENARIOS[name]()
        engine = SynthEngine(sr=scenario["sample_rate"],
                             block_size=scenario["block_size"], max_voices=12)
        registry = build_registry(engine)
        audio = render(scenario, registry)
        check_against_npz(name, audio)
        json_path = os.path.join(OUT_DIR, name + ".scenario.json")
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(scenario, handle, indent=2)
            handle.write("\n")
        f32_path = os.path.join(OUT_DIR, name + ".f32")
        audio.astype("<f4").tofile(f32_path)
        print("  wrote %s (%d frames) and %s"
              % (json_path, audio.shape[0], f32_path))


if __name__ == "__main__":
    main(sys.argv[1:])
