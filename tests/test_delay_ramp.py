"""Delay time ramp: per-sample linear delay glide inside a block."""
import numpy as np
import pytest

from midi_synth.effects import Delay

SR = 48000
TOL = 1e-9


class NaiveRampDelay:
    """Plain per-sample stereo delay with a linearly ramped fractional delay."""

    def __init__(self, sr, feedback, damp, mix=0.35, time_ms=300.0, pingpong=False):
        self.sr = sr
        self.fb, self.damp, self.mix = feedback, damp, mix
        self.time = time_ms * sr / 1000.0
        self.size = int(sr * 4.0) + 4
        self.bufs = np.zeros((2, self.size))
        self.idx = 0
        self.filt = [0.0, 0.0]
        self.pingpong = pingpong

    def _read(self, c, delay):
        read = self.idx - delay
        while read < 0.0:
            read += self.size
        i0 = int(read)
        frac = read - i0
        i1 = i0 + 1
        if i1 >= self.size:
            i1 = 0
        return self.bufs[c, i0] * (1.0 - frac) + self.bufs[c, i1] * frac

    def process(self, x, target_ms=None):
        n = x.shape[1]
        d0 = self.time
        d1 = d0 if target_ms is None else target_ms * self.sr / 1000.0
        out = np.empty((2, n))
        for i in range(n):
            delay = d0 + (d1 - d0) * (i + 1) / n
            wet = [self._read(c, delay) for c in range(2)]
            for c in range(2):
                self.filt[c] = wet[c] * (1.0 - self.damp) + self.filt[c] * self.damp
            if self.pingpong:
                self.bufs[0, self.idx] = 0.5 * (x[0, i] + x[1, i]) + self.filt[1] * self.fb
                self.bufs[1, self.idx] = self.filt[0] * self.fb
            else:
                for c in range(2):
                    self.bufs[c, self.idx] = x[c, i] + self.filt[c] * self.fb
            for c in range(2):
                out[c, i] = x[c, i] + wet[c] * self.mix
            self.idx = (self.idx + 1) % self.size
        self.time = d1
        return out


def signal(n, seed):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((2, n)) * 0.3


@pytest.mark.parametrize("pingpong", [False, True])
@pytest.mark.parametrize("block", [64, 256, 300, 700])
@pytest.mark.parametrize("start,targets", [
    (200.0, [400.0, 1000.0, 4000.0, 3000.0, 250.0, 200.0]),
    (4000.0, [3500.0, 2000.0, 300.0, 1.0 + 5.0, 700.0]),
    (500.0, [500.0, 520.0, 520.0, 480.0]),
])
def test_ramp_matches_naive_reference(pingpong, block, start, targets):
    d = Delay(SR, enabled=True, feedback=0.6, damp=0.3)
    d.set_pingpong(pingpong)
    d.set_time_ms(start)
    ref = NaiveRampDelay(SR, 0.6, 0.3, time_ms=start, pingpong=pingpong)
    if block > 300:
        targets = targets[:3]
    for k, target in enumerate(targets):
        x = signal(block, k)
        d.set_time_target_ms(target)
        got = d.process(x.copy())
        want = ref.process(x.copy(), target)
        assert np.max(np.abs(got - want)) <= TOL
        assert d.time_ms == pytest.approx(target)
        assert d.time == pytest.approx(target * SR / 1000.0)


def test_target_equal_to_current_is_a_plain_block():
    a = Delay(SR, enabled=True, feedback=0.5)
    b = Delay(SR, enabled=True, feedback=0.5)
    x = signal(256, 1)
    b.set_time_target_ms(b.time_ms)
    for _ in range(4):
        assert np.array_equal(a.process(x.copy()), b.process(x.copy()))


def test_no_ramp_path_unchanged_by_the_feature():
    # a delay that never receives a target equals one that jumps with set_time_ms
    a = Delay(SR, enabled=True, feedback=0.5)
    b = Delay(SR, enabled=True, feedback=0.5)
    a.set_time_ms(700.0)
    b.set_time_ms(700.0)
    x = signal(300, 2)
    assert np.array_equal(a.process(x.copy()), b.process(x.copy()))


def test_set_time_ms_clears_a_pending_target():
    d = Delay(SR, enabled=True)
    d.set_time_target_ms(900.0)
    d.set_time_ms(250.0)
    d.process(signal(128, 3))
    assert d.time_ms == 250.0


def test_target_is_clamped_to_engine_limits():
    d = Delay(SR, enabled=True)
    d.set_time_target_ms(99999.0)
    d.process(signal(128, 3))
    assert d.time_ms == 4000.0
    d.set_time_target_ms(-5.0)
    d.process(signal(128, 3))
    assert d.time_ms == 1.0


def test_disabled_delay_keeps_the_target_pending():
    d = Delay(SR, enabled=False)
    d.set_time_target_ms(900.0)
    d.process(signal(64, 1))
    assert d.time_ms == 300.0
    d.enabled = True
    d.process(signal(64, 1))
    assert d.time_ms == pytest.approx(900.0)


def _wet_jumps(ramped):
    sr = SR
    d = Delay(sr, enabled=True, mix=1.0, feedback=0.0, damp=0.0)
    d.set_time_ms(500.0)
    block, nblocks = 256, 600
    t = np.arange(block * nblocks) / sr
    sine = np.sin(2 * np.pi * 220.0 * t)
    x = np.vstack([sine, sine])
    outs = []
    for k in range(nblocks):
        centre = (k * block + block / 2) / sr
        ms = 500.0 * (1.0 + 0.2 * np.sin(2 * np.pi * 1.0 * centre))
        if ramped:
            d.set_time_target_ms(ms)
        else:
            d.set_time_ms(ms)
        seg = x[:, k * block:(k + 1) * block]
        outs.append(d.process(seg.copy()) - seg)
    wet = np.concatenate(outs, axis=1)[0]
    wet = wet[sr:]
    return np.max(np.abs(np.diff(wet)))


def test_ramp_is_smoother_than_stepped_delay_time():
    ramped, stepped = _wet_jumps(True), _wet_jumps(False)
    # 220 Hz sine: the natural max sample step is 2*pi*220/sr ~ 0.029
    assert ramped < 0.05
    assert stepped > 2 * ramped


def test_chunked_ramp_with_short_times_stays_finite_and_matches():
    d = Delay(SR, enabled=True, feedback=0.5, damp=0.2)
    d.set_time_ms(5.0)
    ref = NaiveRampDelay(SR, 0.5, 0.2, time_ms=5.0)
    for k, target in enumerate([5.0, 3.0, 8.0, 2.0]):
        x = signal(700, k)
        d.set_time_target_ms(target)
        assert np.max(np.abs(d.process(x.copy()) - ref.process(x.copy(), target))) <= TOL
