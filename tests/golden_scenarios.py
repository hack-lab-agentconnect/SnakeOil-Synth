"""Scenario builders for the golden sound lock (shared by the test and tools/regen_golden.py)."""
import numpy as np

from midi_synth.engine import SynthEngine

SR = 44100
BLOCK = 256
MAX_VOICES = 12
NOTES = (48, 52, 55, 59)
NOTE_OFF_BLOCK = 20
BLOCKS = 60

SCENARIOS = {}


def _scenario(fn):
    SCENARIOS[fn.__name__.replace("scenario_", "")] = fn
    return fn


def new_engine():
    return SynthEngine(sr=SR, block_size=BLOCK, max_voices=MAX_VOICES)


def render_chord(engine, blocks=BLOCKS, note_off_block=NOTE_OFF_BLOCK):
    """Play the chord, release it after `note_off_block` blocks, return float32 (n, 2)."""
    for n in NOTES:
        engine.note_on(n, 100)
    out = []
    for i in range(blocks):
        if i == note_off_block:
            for n in NOTES:
                engine.note_off(n)
        out.append(engine.render())
    return np.concatenate(out, axis=0).astype(np.float32)


def configure_busy(engine):
    engine.set_osc_level(2, 0.8)
    engine.set_mod_mode("fm")
    engine.set_fm_depth(0.4)
    engine.set_detune2(7)
    for name in ("chorus", "delay", "reverb", "bitcrush"):
        engine.set_effect(name, True)
    engine.set_delay_pingpong(True)
    engine.set_chorus_depth(0.6)
    engine.set_delay_time(350)
    engine.set_reverb_amount(0.5)
    engine.set_crush_amount(0.4)
    engine.set_lpf_cutoff(3000)
    engine.set_lpf_resonance(0.5)


@_scenario
def scenario_default():
    return render_chord(new_engine())


@_scenario
def scenario_busy():
    engine = new_engine()
    configure_busy(engine)
    return render_chord(engine)
