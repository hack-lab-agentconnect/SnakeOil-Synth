import numpy as np
import pytest

from midi_synth.effects import Bitcrusher, Chorus, Delay, EffectChain, Reverb


def test_chorus_default_rate_and_clamp():
    sr = 44100
    c = Chorus(sr)
    assert c.rate == 1.0
    c.set_rate(50)
    assert c.rate == 10.0
    assert c.inc == pytest.approx(2 * np.pi * 10 / sr)
    c.set_rate(0.1)
    assert c.rate == 1.0


def _impulse_echo_index(time_ms, n):
    d = Delay(sr=44100, enabled=True, mix=1.0, feedback=0.0, damp=0.0)
    d.set_time_ms(time_ms)
    assert d.time_ms == time_ms
    x = np.zeros(n)
    x[0] = 1.0
    out = d.process(x) - x
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
        return r.process(x)

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
    out = b.process(x)
    for g in range(0, 64, 4):
        assert len(set(out[g:g + 4])) == 1
    b = Bitcrusher(44100, enabled=True)
    b.set_amount(1.0)
    assert len(set(np.round(b.process(x), 9))) <= 5
    b = Bitcrusher(44100, enabled=True)
    b.set_amount(0.0)
    assert np.max(np.abs(b.process(x) - x)) < 1e-3
    b.set_amount(9)
    assert b.amount == 1.0


def test_chain_crusher_defaults_to_half_amount():
    c = EffectChain(44100).bitcrush
    assert c.amount == 0.5 and c.bits == 8 and c.downsample == 4
