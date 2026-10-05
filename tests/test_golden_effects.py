"""Golden tests: channel 0 of the vectorised stereo effects must match the
frozen per-sample mono reference implementations (tests/reference_dsp.py)
block for block. Channel 1 carries unrelated audio to catch any crosstalk."""
import numpy as np
import pytest

from midi_synth.effects import Bitcrusher, Chorus, Delay, Reverb
from tests.reference_dsp import (
    RefBitcrusher,
    RefChorus,
    RefDelay,
    RefReverb,
)

TOL = 1e-9
BLOCK_SIZES = [64, 128, 256, 300, 700]


def noise(total, seed=1):
    return np.random.default_rng(seed).uniform(-0.5, 0.5, total)


def saw_bursts(total, sr=48000, freq=220.0, period=3000):
    """Repeated decaying saw bursts: a realistic, strongly periodic signal."""
    t = np.arange(total)
    saw = 2.0 * np.mod(t * freq / sr, 1.0) - 1.0
    env = np.exp(-4.0 * (np.mod(t, period) / period))
    return 0.6 * saw * env


SIGNALS = {"noise": noise, "saw_burst": saw_bursts}


def stereo(x):
    """Left = x, right = a different signal derived from x."""
    return np.stack([x, -0.7 * x[::-1]])


def run_blocks(new, ref, signal, block, nblocks=10, between=None):
    """Feed blocks to both effects; assert channel 0 matches the mono ref.

    `between(i, new, ref)` is called before block i to change parameters.
    """
    for i in range(nblocks):
        if between is not None:
            between(i, new, ref)
        x = signal[i * block:(i + 1) * block]
        a = new.process(stereo(x))
        b = ref.process(x.copy())
        assert a.shape == (2, len(x))
        assert np.max(np.abs(a[0] - b)) <= TOL, "block %d differs" % i


def apply_both(new, ref, **attrs):
    for k, v in attrs.items():
        setattr(new, k, v)
        setattr(ref, k, v)


def make_signal(kind, total, sr):
    if kind == "saw_burst":
        return saw_bursts(total, sr)
    return noise(total)


# ---------------------------------------------------------------- Delay

@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
@pytest.mark.parametrize("block", BLOCK_SIZES + [1, 7])
@pytest.mark.parametrize("time_ms", [200.0, 300.0])
def test_delay_matches_reference(kind, block, time_ms):
    sr = 48000
    new, ref = Delay(sr, enabled=True), RefDelay(sr, enabled=True)
    new.set_time_ms(time_ms)
    ref.set_time_ms(time_ms)
    nblocks = 10 if block > 7 else 400
    sig = make_signal(kind, block * nblocks, sr)
    run_blocks(new, ref, sig, block, nblocks)
    assert new.idx == ref.idx
    assert new.filter[0] == pytest.approx(ref.filter, abs=TOL)


@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
@pytest.mark.parametrize("damp", [0.0, 0.25, 0.9])
def test_delay_damping_and_feedback(kind, damp):
    sr = 48000
    new, ref = Delay(sr, enabled=True), RefDelay(sr, enabled=True)
    apply_both(new, ref, damp=damp, feedback=0.8, mix=0.6)
    new.set_time_ms(5.0)
    ref.set_time_ms(5.0)
    run_blocks(new, ref, make_signal(kind, 256 * 40, sr), 256, 40)
    assert new.filter[0] == pytest.approx(ref.filter, abs=TOL)


@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
@pytest.mark.parametrize("block", [256, 300])
def test_delay_4s_wraps_ring_buffer(kind, block):
    sr = 48000
    new, ref = Delay(sr, enabled=True), RefDelay(sr, enabled=True)
    new.set_time_ms(4000.0)
    ref.set_time_ms(4000.0)
    nblocks = (len(new.buf) * 2) // block + 2  # > 2 full trips round the ring
    sig = make_signal(kind, block * nblocks, sr)
    apply_both(new, ref, feedback=0.6)
    run_blocks(new, ref, sig, block, nblocks)
    assert new.idx == ref.idx
    assert np.max(np.abs(new.buf[0] - ref.buf)) <= TOL


def test_delay_time_changes_between_blocks():
    sr = 48000
    new, ref = Delay(sr, enabled=True), RefDelay(sr, enabled=True)
    times = [200.0, 333.3, 50.0, 4000.0, 1.0, 120.7, 300.0, 77.7]

    def between(i, n, r):
        n.set_time_ms(times[i % len(times)])
        r.set_time_ms(times[i % len(times)])

    run_blocks(new, ref, noise(256 * 16), 256, 16, between)


def test_delay_enable_disable_between_blocks():
    sr = 48000
    new, ref = Delay(sr, enabled=True), RefDelay(sr, enabled=True)

    def between(i, n, r):
        n.enabled = r.enabled = (i % 3 != 1)

    run_blocks(new, ref, saw_bursts(256 * 12), 256, 12, between)
    assert new.idx == ref.idx


def test_delay_disabled_returns_input_untouched():
    d = Delay(48000, enabled=False)
    x = stereo(noise(64))
    assert d.process(x) is x


def test_delay_shortest_delay_with_block_larger_than_delay():
    """1 ms = 48 samples: a 700-sample block must be chunked, not read
    from not-yet-written data."""
    sr = 48000
    new, ref = Delay(sr, enabled=True), RefDelay(sr, enabled=True)
    new.set_time_ms(1.0)
    ref.set_time_ms(1.0)
    apply_both(new, ref, feedback=0.7)
    run_blocks(new, ref, noise(700 * 8), 700, 8)
    assert new.filter[0] == pytest.approx(ref.filter, abs=TOL)


# --------------------------------------------------------------- Chorus

@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
@pytest.mark.parametrize("block", BLOCK_SIZES + [1, 7])
@pytest.mark.parametrize("depth", [0.0, 0.3, 1.0])
def test_chorus_matches_reference(kind, block, depth):
    sr = 48000
    new = Chorus(sr, enabled=True, amount=depth)
    ref = RefChorus(sr, enabled=True, amount=depth)
    nblocks = 10 if block > 7 else 300
    run_blocks(new, ref, make_signal(kind, block * nblocks, sr), block, nblocks)
    assert new.idx == ref.idx
    assert new.phase == pytest.approx(ref.phase, abs=1e-6)
    assert 0.0 <= new.phase < 2 * np.pi


@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
def test_chorus_depth_changes_between_blocks(kind):
    sr = 48000
    new, ref = Chorus(sr, enabled=True), RefChorus(sr, enabled=True)
    depths = [0.0, 1.0, 0.3, 0.7, 1.0, 0.0, 0.5, 1.0, 0.1, 0.9]

    def between(i, n, r):
        n.set_depth(depths[i])
        r.set_depth(depths[i])

    run_blocks(new, ref, make_signal(kind, 300 * 10, sr), 300, 10, between)


def test_chorus_fast_rate_phase_wraps():
    sr = 48000
    new = Chorus(sr, enabled=True, rate=5.0, amount=1.0, mix=0.8, feedback=0.5)
    ref = RefChorus(sr, enabled=True, rate=5.0, amount=1.0, mix=0.8, feedback=0.5)
    run_blocks(new, ref, noise(700 * 12), 700, 12)
    assert new.phase == pytest.approx(ref.phase, abs=1e-6)


def test_chorus_enable_disable_between_blocks():
    sr = 48000
    new, ref = Chorus(sr, enabled=True), RefChorus(sr, enabled=True)

    def between(i, n, r):
        n.enabled = r.enabled = (i % 3 != 1)

    run_blocks(new, ref, saw_bursts(256 * 12), 256, 12, between)
    assert new.idx == ref.idx


def test_chorus_block_larger_than_min_delay_is_chunked():
    """At depth 1 the shortest delay is 6 ms = 288 samples; a 2000-sample
    block (and feedback) must still match the sample-by-sample reference."""
    sr = 48000
    new = Chorus(sr, enabled=True, amount=1.0, feedback=0.6)
    ref = RefChorus(sr, enabled=True, amount=1.0, feedback=0.6)
    run_blocks(new, ref, noise(2000 * 6), 2000, 6)


# --------------------------------------------------------- Bitcrusher

@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
@pytest.mark.parametrize("block", [1, 7, 64, 256])
@pytest.mark.parametrize("down", [1, 2, 3, 4, 5, 6, 7, 8])
def test_bitcrusher_downsample(kind, block, down):
    new = Bitcrusher(48000, enabled=True, bits=6, downsample=down)
    ref = RefBitcrusher(48000, enabled=True, bits=6, downsample=down)
    nblocks = 400 if block == 1 else 40
    run_blocks(new, ref, make_signal(kind, block * nblocks, 48000), block, nblocks)
    assert new.counter == ref.counter
    assert new.hold[0] == ref.hold


@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
@pytest.mark.parametrize("block", [1, 7, 64, 256])
@pytest.mark.parametrize("bits", list(range(2, 17)))
def test_bitcrusher_bits(kind, block, bits):
    new = Bitcrusher(48000, enabled=True, bits=bits, downsample=3)
    ref = RefBitcrusher(48000, enabled=True, bits=bits, downsample=3)
    nblocks = 200 if block == 1 else 12
    run_blocks(new, ref, make_signal(kind, block * nblocks, 48000), block, nblocks)
    assert new.counter == ref.counter
    assert new.hold[0] == ref.hold


@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
def test_bitcrusher_params_change_between_blocks(kind):
    new, ref = Bitcrusher(48000, enabled=True), RefBitcrusher(48000, enabled=True)
    amounts = [0.0, 0.5, 1.0, 0.25, 0.9, 0.1, 0.6, 0.0, 1.0, 0.33]
    blocks = [7, 64, 256, 1, 64, 7, 256, 3, 64, 11]
    for i, (a, b) in enumerate(zip(amounts, blocks)):
        new.set_amount(a)
        ref.set_amount(a)
        x = make_signal(kind, 300, 48000)[:b]
        assert np.max(np.abs(new.process(stereo(x))[0] - ref.process(x.copy()))) <= TOL
        assert new.counter == ref.counter and new.hold[0] == ref.hold


def test_bitcrusher_counter_longer_than_block():
    """downsample 8 with 1/7 sample blocks: no refresh inside the block."""
    new = Bitcrusher(48000, enabled=True, downsample=8)
    ref = RefBitcrusher(48000, enabled=True, downsample=8)
    sig = noise(500)
    pos = 0
    for b in [1, 1, 7, 3, 1, 5, 2, 7, 7, 1, 20, 4]:
        x = sig[pos:pos + b]
        pos += b
        assert np.max(np.abs(new.process(stereo(x))[0] - ref.process(x.copy()))) <= TOL
        assert new.counter == ref.counter and new.hold[0] == ref.hold


def test_bitcrusher_enable_disable_between_blocks():
    new, ref = Bitcrusher(48000, enabled=True), RefBitcrusher(48000, enabled=True)

    def between(i, n, r):
        n.enabled = r.enabled = (i % 3 != 1)

    run_blocks(new, ref, noise(64 * 12), 64, 12, between)


# -------------------------------------------------------------- Reverb

@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
@pytest.mark.parametrize("sr", [44100, 48000])
@pytest.mark.parametrize("block", BLOCK_SIZES)
def test_reverb_default(kind, sr, block):
    new, ref = Reverb(sr, enabled=True), RefReverb(sr, enabled=True)
    run_blocks(new, ref, make_signal(kind, block * 10, sr), block, 10)
    for cn, cr in zip(new.combs, ref.combs):
        assert cn.idx == cr.idx
        assert cn.filter == pytest.approx(cr.filter, abs=TOL)
    for an, ar in zip(new.allpasses, ref.allpasses):
        assert an.idx == ar.idx


@pytest.mark.parametrize("kind", ["noise", "saw_burst"])
@pytest.mark.parametrize("sr", [44100, 48000])
@pytest.mark.parametrize("block", [64, 256, 300, 700])
@pytest.mark.parametrize("room,damp,mix,scale", [
    (0.5, 0.0, 1.0, 1.0),
    (0.95, 0.7, 0.5, 1.0),
    (0.84, 0.25, 0.3, 0.5),
    (0.9, 0.4, 0.8, 1.7),
])
def test_reverb_non_default(kind, sr, block, room, damp, mix, scale):
    new = Reverb(sr, enabled=True, mix=mix, room=room, damp=damp, scale=scale)
    ref = RefReverb(sr, enabled=True, mix=mix, room=room, damp=damp, scale=scale)
    run_blocks(new, ref, make_signal(kind, block * 10, sr), block, 10)


def test_reverb_per_comb_settings_changed_between_blocks():
    sr = 48000
    new, ref = Reverb(sr, enabled=True), RefReverb(sr, enabled=True)

    def between(i, n, r):
        for rv in (n, r):
            for c in rv.combs:
                c.fb = 0.5 + 0.04 * i
                c.damp = 0.05 * i
            rv.set_amount(0.1 * (i % 10))

    run_blocks(new, ref, noise(256 * 10), 256, 10, between)


def test_reverb_enable_disable_between_blocks():
    sr = 48000
    new, ref = Reverb(sr, enabled=True), RefReverb(sr, enabled=True)

    def between(i, n, r):
        n.enabled = r.enabled = (i % 3 != 1)

    run_blocks(new, ref, saw_bursts(256 * 12), 256, 12, between)


def test_reverb_tail_after_input_stops():
    """Wrap the shortest ring several times with the input gone silent."""
    sr = 48000
    new, ref = Reverb(sr, enabled=True), RefReverb(sr, enabled=True)
    sig = np.concatenate([saw_bursts(256 * 2), np.zeros(256 * 40)])
    run_blocks(new, ref, sig, 256, 42)


def test_reverb_block_larger_than_shortest_delay_is_chunked():
    """Shortest allpass is 341 samples; 2000-sample blocks must be chunked."""
    sr = 44100
    new, ref = Reverb(sr, enabled=True), RefReverb(sr, enabled=True)
    run_blocks(new, ref, noise(2000 * 6), 2000, 6)


def test_reverb_tiny_scale_short_buffers_with_large_block():
    sr = 44100
    new = Reverb(sr, enabled=True, scale=0.05)
    ref = RefReverb(sr, enabled=True, scale=0.05)
    run_blocks(new, ref, noise(700 * 6), 700, 6)
