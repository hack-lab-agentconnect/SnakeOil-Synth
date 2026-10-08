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


def _chord_events(note_off_block):
    events = [{"block": 0, "note_on": [note, 100]} for note in NOTES]
    events += [{"block": note_off_block, "note_off": [note]} for note in NOTES]
    return events


def _scenario(params=None, blocks=BLOCKS, note_off_block=NOTE_OFF_BLOCK):
    return {"sample_rate": SR, "block_size": BLOCK, "blocks": blocks,
            "params": dict(params or {}), "events": _chord_events(note_off_block)}


SCENARIOS = {
    "default": lambda: _scenario(),
    "filter_env": lambda: _scenario(
        {"flt_env_amount": 0.8, "lpf_cutoff": 500.0, "lpf_resonance": 0.5}),
    "ladder": lambda: _scenario(
        {"lpf_slope": "24 dB", "lpf_cutoff": 800.0, "lpf_resonance": 0.5}),
    "keytrack_vel": lambda: _scenario(
        {"flt_keytrack": 0.5, "flt_vel": 0.5, "lpf_cutoff": 1000.0}),
    "amp_env": lambda: _scenario(
        {"amp_attack": 0.2, "amp_decay": 0.3, "amp_sustain": 0.2, "amp_release": 0.5}),
    "limiter": lambda: _scenario(
        {"auto_limiter": True, "master_gain": 1.2}),
    "ladder_osc": lambda: _scenario(
        {"lpf_slope": "24 dB", "lpf_cutoff": 400.0, "lpf_resonance": 0.95}),
    "glide": lambda: {
        "sample_rate": SR, "block_size": BLOCK, "blocks": BLOCKS,
        "params": {"glide_time": 0.2},
        "events": [
            {"block": 0, "note_on": [48, 100]},
            {"block": 10, "note_on": [60, 100]},
            {"block": 40, "note_off": [48]},
            {"block": 40, "note_off": [60]},
        ],
    },
    "lfo_pitch": lambda: _scenario(
        {"lfo_depth": 1.0, "lfo_dest": "pitch", "lfo_wave": "sine", "lfo_rate": 2.0}),
    "lfo_filter": lambda: _scenario(
        {"lfo2_depth": 1.0, "lfo2_dest": "filter", "lfo2_wave": "triangle",
         "lfo2_rate": 1.0, "lpf_cutoff": 1000.0}),
    "lfo_pwm": lambda: _scenario(
        {"lfo_depth": 0.8, "lfo_dest": "pwm", "lfo_wave": "saw", "lfo_rate": 3.0,
         "osc1_pwm": 0.2}),
    "lfo_amp": lambda: _scenario(
        {"lfo_depth": 1.0, "lfo_dest": "amp", "lfo_wave": "square", "lfo_rate": 4.0}),
    "chorus": lambda: _scenario({"fx_chorus": True, "fx_chorus_depth": 0.6}),
    "delay": lambda: _scenario(
        {"fx_delay": True, "fx_delay_time": 350.0, "fx_delay_feedback": 0.4,
         "fx_delay_damp": 0.3}),
    "delay_pp": lambda: _scenario(
        {"fx_delay": True, "fx_delay_time": 350.0, "fx_delay_pingpong": True}),
    "reverb": lambda: _scenario(
        {"fx_reverb": True, "fx_reverb_amount": 0.5, "fx_reverb_size": 0.9,
         "fx_reverb_damp": 0.3}),
    "bitcrush": lambda: _scenario({"fx_bitcrush": True, "fx_bitcrush_amount": 0.6}),
    "busy": lambda: _scenario({
        "osc2_level": 0.8, "mod_mode": "fm", "fm_depth": 0.4, "detune2_semitones": 7.0,
        "fx_chorus": True, "fx_delay": True, "fx_reverb": True, "fx_bitcrush": True,
        "fx_delay_pingpong": True, "fx_chorus_depth": 0.6, "fx_delay_time": 350.0,
        "fx_reverb_amount": 0.5, "fx_bitcrush_amount": 0.4,
        "lpf_cutoff": 3000.0, "lpf_resonance": 0.5}),
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
