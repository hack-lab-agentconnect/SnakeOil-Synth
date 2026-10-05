"""Output must not depend on how the stream is split into blocks."""
import numpy as np
import pytest

from midi_synth.effects import EffectChain
from midi_synth.engine import SynthEngine

# (sample rate, total samples, block sizes). Block 1 is slow, so it runs only
# at 44100 over a shorter signal.
CASES = [
    (44100, 8192, [64, 256, 1024, 4096]),
    (96000, 8192, [64, 256, 1024, 4096]),
]
SHORT = (44100, 1024, [1, 64, 256])


def setup_chain(sr):
    chain = EffectChain(sr)
    for name in chain.order:
        getattr(chain, name).enabled = True
    chain.chorus.set_depth(1.0)
    chain.delay.set_time_ms(200.0)
    chain.delay.set_pingpong(True)
    return chain


def render_chain(sr, total, block):
    sig = np.random.default_rng(7).uniform(-0.5, 0.5, (2, total))
    chain = setup_chain(sr)
    out = [chain.process(sig[:, i:i + block].copy()) for i in range(0, total, block)]
    return np.concatenate(out, axis=1)


def setup_engine(sr):
    e = SynthEngine(sr=sr, block_size=256, max_voices=4)
    e.set_osc_levels(1.0, 0.5)
    for name in ("chorus", "delay", "reverb", "bitcrush"):
        e.set_effect(name, True)
    e.set_chorus_depth(1.0)
    e.set_delay_time(200.0)
    e.set_delay_pingpong(True)
    for note in (48, 55, 64):
        e.note_on(note, 100)
    return e


def render_engine(sr, total, block):
    e = setup_engine(sr)
    out = []
    done = 0
    while done < total:
        n = min(block, total - done)
        out.append(e.render(n))
        done += n
    return np.concatenate(out, axis=0)


def cases():
    for sr, total, blocks in CASES + [SHORT]:
        yield sr, total, blocks


@pytest.mark.parametrize("sr,total,blocks", list(cases()))
def test_effect_chain_block_invariant(sr, total, blocks):
    ref = render_chain(sr, total, total)
    for block in blocks:
        assert np.abs(render_chain(sr, total, block) - ref).max() < 1e-9, block


@pytest.mark.parametrize("sr,total,blocks", list(cases()))
def test_engine_block_invariant(sr, total, blocks):
    ref = render_engine(sr, total, total)
    assert np.abs(ref).max() > 0.01
    for block in blocks:
        diff = np.abs(render_engine(sr, total, block) - ref).max()
        assert diff < 1e-5, (block, diff)
