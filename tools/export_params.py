"""Export the parameter registry to plugin/params.json for the C++ plugin.

The registry in ``midi_synth/params.py`` is the single source of truth for the
parameter ids, ranges, defaults and MIDI value mapping. The C++ side reads this
file to generate its parameter layout (phase P2), so this script only reads the
registry and writes JSON; it never changes engine state other than by
constructing a default engine.

Usage (from the repo root):  python tools/export_params.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402

OUT = os.path.join(ROOT, "plugin", "params.json")


def param_to_dict(param, registry):
    return {
        "id": param.id,
        "label": param.label,
        "group": param.group,
        "kind": param.kind,
        "minimum": param.minimum,
        "maximum": param.maximum,
        "scale": param.scale,
        "choices": list(param.choices),
        "format": param.fmt,
        "affects": list(param.affects),
        "under": param.under,
        "tooltip": param.tooltip,
        "default": registry.get(param.id),
    }


def main():
    engine = SynthEngine()
    registry = build_registry(engine)
    params = [param_to_dict(p, registry) for p in registry]
    payload = {"version": 1, "params": params}
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print("wrote %s (%d params)" % (OUT, len(params)))


if __name__ == "__main__":
    main()
