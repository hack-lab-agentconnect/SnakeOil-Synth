"""Stereo behaviour of the effects: right channels and ping-pong against
frozen per-sample references, plus stereo-ness and chunking checks."""
import numpy as np
import pytest

from midi_synth.effects import (
    Bitcrusher, Chorus, Delay, EffectChain, Reverb,
)
from tests.reference_dsp import (
    RefBitcrusher, RefChorus, RefDelay, RefPingPongDelay, RefReverb,
    _RefAllpass, _RefComb,
)

TOL = 1e-9


def stereo_noise(total, seed=3):
    return np.random.default_rng(seed).uniform(-0.5, 0.5, (2, total))


def run_blocks(total, blocks):
    """Yield consecutive stereo blocks cycling through the given sizes."""
    sig = stereo_noise(total)
    pos = 0
    i = 0
    while pos < total:
        b = blocks[i % len(blocks)]
        yield sig[:, pos:pos + b].copy()
        pos += b
        i += 1


# --------------------------------------------------------------- Chorus

@pytest.mark.parametrize("blocks", [[64], [256], [300], [700], [64, 256, 300, 700]])
@pytest.mark.parametrize("depth", [0.3, 1.0])
def test_chorus_right_channel_is_inverted_lfo(blocks, depth):
    sr = 48000
    new = Chorus(sr, enabled=True, amount=depth)
    ref = RefChorus(sr, enabled=True, amount=depth)
    ref.phase = np.pi
    count = 0
    for x in run_blocks(sum(blocks) * 8 + 2000, blocks):
        a = new.process(x.copy())
        b = ref.process(x[1].copy())
        assert np.max(np.abs(a[1] - b)) <= TOL
        count += 1
    assert count >= 8


def test_chorus_left_and_right_differ_for_identical_input():
    c = Chorus(48000, enabled=True, amount=1.0)
    x = np.tile(stereo_noise(4000)[0], (2, 1))
    out = c.process(x)
    assert np.max(np.abs(out[0] - out[1])) > 1e-3


def test_chorus_stereo_block_larger_than_min_delay_is_chunked():
    sr = 48000
    new = Chorus(sr, enabled=True, amount=1.0, feedback=0.6)
    ref_l = RefChorus(sr, enabled=True, amount=1.0, feedback=0.6)
    ref_r = RefChorus(sr, enabled=True, amount=1.0, feedback=0.6)
    ref_r.phase = np.pi
    for x in run_blocks(2000 * 6, [2000]):
        a = new.process(x.copy())
        assert np.max(np.abs(a[0] - ref_l.process(x[0].copy()))) <= TOL
        assert np.max(np.abs(a[1] - ref_r.process(x[1].copy()))) <= TOL


# ---------------------------------------------------------------- Delay

@pytest.mark.parametrize("time_ms", [200.0, 300.0, 1.0])
@pytest.mark.parametrize("blocks", [[64], [256, 300], [700]])
def test_delay_normal_mode_both_channels_match_reference(time_ms, blocks):
    sr = 48000
    new = Delay(sr, enabled=True, feedback=0.6)
    refs = [RefDelay(sr, enabled=True, feedback=0.6) for _ in range(2)]
    new.set_time_ms(time_ms)
    for r in refs:
        r.set_time_ms(time_ms)
    for x in run_blocks(sum(blocks) * 10, blocks):
        a = new.process(x.copy())
        for c in range(2):
            assert np.max(np.abs(a[c] - refs[c].process(x[c].copy()))) <= TOL
    for c in range(2):
        assert new.filter[c] == pytest.approx(refs[c].filter, abs=TOL)


def test_delay_pingpong_defaults_off_and_setter():
    d = Delay(48000)
    assert d.pingpong is False
    d.set_pingpong(True)
    assert d.pingpong is True
    d.set_pingpong(0)
    assert d.pingpong is False


@pytest.mark.parametrize("time_ms", [200.0, 300.0, 4000.0])
@pytest.mark.parametrize("blocks", [[64], [256], [300]])
def test_delay_pingpong_matches_reference(time_ms, blocks):
    sr = 48000
    new = Delay(sr, enabled=True, feedback=0.6, mix=0.5)
    ref = RefPingPongDelay(sr, enabled=True, feedback=0.6, mix=0.5)
    new.set_pingpong(True)
    new.set_time_ms(time_ms)
    ref.set_time_ms(time_ms)
    total = int(sr * time_ms / 1000.0 * 2.5) + 1000
    for x in run_blocks(total, blocks):
        a = new.process(x.copy())
        b = ref.process(x.copy())
        assert np.max(np.abs(a - b)) <= TOL
    assert new.idx == ref.idx
    for c in range(2):
        assert new.filter[c] == pytest.approx(ref.filters[c], abs=TOL)


def test_delay_pingpong_short_time_chunked_matches_reference():
    sr = 48000
    new = Delay(sr, enabled=True, feedback=0.7)
    ref = RefPingPongDelay(sr, enabled=True, feedback=0.7)
    new.set_pingpong(True)
    new.set_time_ms(1.0)
    ref.set_time_ms(1.0)
    for x in run_blocks(700 * 8, [700]):
        assert np.max(np.abs(new.process(x.copy()) - ref.process(x.copy()))) <= TOL


def test_delay_pingpong_echoes_alternate_sides():
    sr = 48000
    d = Delay(sr, enabled=True, mix=1.0, feedback=0.5, damp=0.0)
    d.set_pingpong(True)
    d.set_time_ms(100.0)
    t = int(d.time)
    x = np.zeros((2, 5 * t))
    x[0, 0] = 1.0
    out = d.process(x) - x
    for k in range(1, 4):
        left = out[0, k * t] ** 2
        right = out[1, k * t] ** 2
        if k % 2 == 1:
            assert left > 0.0 and right == pytest.approx(0.0, abs=1e-12)
        else:
            assert right > 0.0 and left == pytest.approx(0.0, abs=1e-12)


# --------------------------------------------------------------- Reverb

def spread_reverb(sr, scale, **kw):
    ref = RefReverb(sr, enabled=True, scale=scale, **kw)
    k = sr / 44100.0 * scale
    ref.combs = [_RefComb((d + 23) * k, ref.room, ref.damp)
                 for d in [1116, 1188, 1277, 1356, 1422, 1491]]
    ref.allpasses = [_RefAllpass((d + 23) * k, 0.5) for d in [556, 441, 341]]
    return ref


@pytest.mark.parametrize("sr", [44100, 48000])
@pytest.mark.parametrize("scale", [1.0, 0.5])
@pytest.mark.parametrize("blocks", [[64], [300], [700, 64]])
def test_reverb_right_bank_is_spread_and_uses_right_input(sr, scale, blocks):
    new = Reverb(sr, enabled=True, scale=scale)
    ref_l = RefReverb(sr, enabled=True, scale=scale)
    ref_r = spread_reverb(sr, scale)
    for x in run_blocks(sum(blocks) * 8, blocks):
        a = new.process(x.copy())
        assert np.max(np.abs(a[0] - ref_l.process(x[0].copy()))) <= TOL
        assert np.max(np.abs(a[1] - ref_r.process(x[1].copy()))) <= TOL


def test_reverb_identical_input_gives_different_tails():
    r = Reverb(44100, enabled=True, mix=1.0)
    x = np.zeros((2, 6000))
    x[:, 0] = 1.0
    out = r.process(x) - x
    assert np.max(np.abs(out[0] - out[1])) > 1e-3


def test_reverb_stereo_chunked_when_block_exceeds_shortest_delay():
    sr = 44100
    new = Reverb(sr, enabled=True, scale=0.05)
    ref_l = RefReverb(sr, enabled=True, scale=0.05)
    ref_r = spread_reverb(sr, 0.05)
    for x in run_blocks(700 * 6, [700]):
        a = new.process(x.copy())
        assert np.max(np.abs(a[0] - ref_l.process(x[0].copy()))) <= TOL
        assert np.max(np.abs(a[1] - ref_r.process(x[1].copy()))) <= TOL


def test_reverb_chunk_limit_uses_shortest_buffer_of_both_banks():
    r = Reverb(44100, enabled=True, scale=0.05)
    r.allpasses_r[-1].buf = np.zeros(3)  # the shortest buffer is in the right bank
    ref_r = spread_reverb(44100, 0.05)
    ref_r.allpasses[-1].buf = np.zeros(3)
    ref_l = RefReverb(44100, enabled=True, scale=0.05)
    x = stereo_noise(500)
    a = r.process(x.copy())
    assert np.max(np.abs(a[1] - ref_r.process(x[1].copy()))) <= TOL
    assert np.max(np.abs(a[0] - ref_l.process(x[0].copy()))) <= TOL


# ----------------------------------------------------------- Bitcrusher

@pytest.mark.parametrize("blocks", [[1], [7, 64, 3], [256]])
@pytest.mark.parametrize("down", [1, 3, 8])
def test_bitcrusher_both_channels_match_reference(blocks, down):
    new = Bitcrusher(48000, enabled=True, bits=6, downsample=down)
    refs = [RefBitcrusher(48000, enabled=True, bits=6, downsample=down)
            for _ in range(2)]
    for x in run_blocks(sum(blocks) * 20, blocks):
        a = new.process(x.copy())
        for c in range(2):
            assert np.max(np.abs(a[c] - refs[c].process(x[c].copy()))) <= TOL
    assert new.counter == refs[0].counter
    for c in range(2):
        assert new.hold[c] == refs[c].hold


# ---------------------------------------------------------------- Chain

def test_chain_all_disabled_returns_input():
    chain = EffectChain(48000)
    x = stereo_noise(256)
    assert chain.process(x) is x


def test_chain_chorus_makes_identical_channels_differ():
    chain = EffectChain(48000)
    chain.chorus.enabled = True
    chain.chorus.set_depth(1.0)
    x = np.tile(stereo_noise(4000)[0], (2, 1))
    out = chain.process(x)
    assert out.shape == (2, 4000)
    assert np.max(np.abs(out[0] - out[1])) > 1e-3


def test_chain_all_effects_stay_finite_and_stereo():
    chain = EffectChain(48000)
    for name in chain.order:
        chain.get(name).enabled = True
    chain.delay.set_pingpong(True)
    for x in run_blocks(256 * 20, [256]):
        out = chain.process(x)
        assert out.shape == (2, 256) and np.all(np.isfinite(out))
