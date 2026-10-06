"""CPU load, peak and underflow bookkeeping in the audio callback."""
import numpy as np
import pytest

from run import CallbackState, render_into

SR = 44100
FRAMES = 256
BLOCK_S = FRAMES / SR


class GoodEngine:
    sr = SR

    def render(self, frames):
        return np.zeros((frames, 2), dtype=np.float32)


class BrokenEngine:
    sr = SR

    def render(self, frames):
        raise RuntimeError("boom")


class FakeClock:
    def __init__(self, busy):
        self.busy = busy
        self.t = 0.0
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls % 2 == 1:
            return self.t
        self.t += 10.0
        return self.t - 10.0 + self.busy


def run(state, busy, frames=FRAMES, status=None, engine=None):
    out = np.zeros((frames, 2), dtype=np.float32)
    render_into(out, engine or GoodEngine(), frames, state, status=status,
                clock=FakeClock(busy))


def test_initial_state():
    s = CallbackState()
    assert (s.load, s.peak, s.underflows, s.callbacks) == (0.0, 0.0, 0, 0)


def test_load_is_busy_over_block_time_ema():
    s = CallbackState()
    run(s, BLOCK_S * 0.5)
    assert s.callbacks == 1
    # first callback seeds the average so the readout is meaningful at once
    assert s.load == pytest.approx(0.5)
    run(s, BLOCK_S * 1.0)
    assert s.load == pytest.approx(0.5 * 0.9 + 1.0 * 0.1)


def test_busy_2_9_ms_of_5_8_ms_block_is_half():
    s = CallbackState()
    run(s, 0.0029025, frames=256)
    assert s.load == pytest.approx(0.5, abs=0.01)


def test_peak_jumps_up_and_decays():
    s = CallbackState()
    run(s, BLOCK_S * 0.9)
    assert s.peak == pytest.approx(0.9)
    run(s, BLOCK_S * 0.1)
    assert s.peak == pytest.approx(0.9 * 0.97)
    for _ in range(300):
        run(s, BLOCK_S * 0.1)
    assert s.peak == pytest.approx(0.1, abs=0.01)


def test_peak_tracks_instant_load_not_average():
    s = CallbackState()
    for _ in range(20):
        run(s, BLOCK_S * 0.2)
    run(s, BLOCK_S * 1.1)
    assert s.peak == pytest.approx(1.1)
    assert s.load < 0.4


class Flags:
    output_underflow = True


class NoFlag:
    pass


class Clean:
    output_underflow = False


@pytest.mark.parametrize("status,expected", [
    (None, 0), (NoFlag(), 0), (Clean(), 0), (Flags(), 1)])
def test_underflows(status, expected):
    s = CallbackState()
    run(s, 0.001, status=status)
    assert s.underflows == expected
    assert s.callbacks == 1


def test_underflows_accumulate():
    s = CallbackState()
    for _ in range(3):
        run(s, 0.001, status=Flags())
    assert s.underflows == 3


def test_errors_never_propagate_and_still_count(capsys):
    s = CallbackState()
    out = np.ones((FRAMES, 2), dtype=np.float32)
    render_into(out, BrokenEngine(), FRAMES, s, status=Flags(),
                clock=FakeClock(0.001))
    assert not out.any()
    assert s.underflows == 1
    assert "boom" in capsys.readouterr().out


def test_defaults_work_without_new_arguments():
    s = CallbackState()
    out = np.zeros((8, 2), dtype=np.float32)
    render_into(out, GoodEngine(), 8, s)
    assert s.callbacks == 1 and s.load >= 0.0


def test_recorder_still_receives_block():
    class Rec:
        active = True

        def __init__(self):
            self.pushed = []

        def push(self, block):
            self.pushed.append(block)

    s = CallbackState()
    s.recorder = Rec()
    run(s, 0.001)
    assert len(s.recorder.pushed) == 1
