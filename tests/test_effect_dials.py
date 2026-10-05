import numpy as np
import pytest

from midi_synth.effects import Bitcrusher, Chorus, Delay, EffectChain, Reverb


def test_chorus_depth_clamp_and_default():
    sr = 44100
    c = Chorus(sr)
    assert c.amount == 0.3
    assert c.rate == 0.5
    c.set_depth(5)
    assert c.amount == 1.0
    assert c.depth == pytest.approx(8.0 * sr / 1000)
    c.set_depth(0)
    assert c.depth == 0.0


def test_chorus_depth_changes_output():
    sr = 44100
    t = np.arange(sr // 4) / sr
    x = np.sin(2 * np.pi * 440 * t)
    outs = []
    for amount in (0.0, 1.0):
        c = Chorus(sr, enabled=True)
        c.set_depth(amount)
        outs.append(c.process(np.stack([x, x]))[0])
    assert np.all(np.isfinite(outs[0])) and np.all(np.isfinite(outs[1]))
    assert not np.allclose(outs[0], outs[1])


def test_chorus_buffer_fits_max_depth():
    sr = 44100
    c = Chorus(sr, enabled=True)
    c.set_depth(1.0)
    x = np.random.default_rng(0).uniform(-1, 1, sr)
    out = c.process(np.stack([x, x]))
    assert np.all(np.isfinite(out))


def _impulse_echo_index(time_ms, n):
    d = Delay(sr=44100, enabled=True, mix=1.0, feedback=0.0, damp=0.0)
    d.set_time_ms(time_ms)
    assert d.time_ms == time_ms
    x = np.zeros(n)
    x[0] = 1.0
    out = d.process(np.stack([x, x]))[0] - x
    return int(np.argmax(np.abs(out))), out


def test_delay_time_places_echo():
    idx, out = _impulse_echo_index(200, 20000)
    assert idx == 8820 and abs(out[8820] - 1.0) < 1e-9
    idx, out = _impulse_echo_index(4000, 180000)
    assert idx == 176400 and abs(out[176400] - 1.0) < 1e-9


def test_delay_stores_time_ms():
    assert Delay(44100).time_ms == 300.0


def test_reverb_amount():
    x = np.zeros(2000)
    x[0] = 1.0

    def run(amount):
        r = Reverb(44100, enabled=True)
        r.set_amount(amount)
        return r.process(np.stack([x, x]))[0]

    assert np.array_equal(run(0.0), x)
    e = lambda y: float(np.sum((y - x) ** 2))
    assert e(run(1.0)) > e(run(0.3)) > 0.0
    r = Reverb(44100)
    r.set_amount(5)
    assert r.mix == 1.0
    r.set_amount(-1)
    assert r.mix == 0.0
    assert Reverb(44100).mix == 0.3


def test_bitcrusher_amount():
    b = Bitcrusher(44100, enabled=True)
    b.set_amount(0.5)
    assert (b.bits, b.downsample) == (8, 4)
    x = np.linspace(0.0, 1.0, 64)
    out = b.process(np.stack([x, x]))[0]
    for g in range(0, 64, 4):
        assert len(set(out[g:g + 4])) == 1
    b = Bitcrusher(44100, enabled=True)
    b.set_amount(1.0)
    assert len(set(np.round(b.process(np.stack([x, x]))[0], 9))) <= 5
    b = Bitcrusher(44100, enabled=True)
    b.set_amount(0.0)
    assert np.max(np.abs(b.process(np.stack([x, x]))[0] - x)) < 1e-3
    b.set_amount(9)
    assert b.amount == 1.0


def test_chain_crusher_defaults_to_half_amount():
    c = EffectChain(44100).bitcrush
    assert c.amount == 0.5 and c.bits == 8 and c.downsample == 4
