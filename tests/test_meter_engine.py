import threading
import time

import numpy as np
import pytest

from midi_synth.config import CLIP_THRESHOLD
from midi_synth.engine import SynthEngine

SR = 44100
BLOCK = 256


def make(voices=8):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices)
    return e


def test_clip_threshold_constant():
    assert CLIP_THRESHOLD == 1.0


def test_idle_meter_is_silent():
    e = make()
    e.render(BLOCK)
    assert e.peek_meter() == (0.0, 0.0, False)


def test_post_peak_matches_rendered_block():
    e = make()
    e.note_on(60, 100)
    out = e.render(BLOCK)
    left, right, _ = e.peek_meter()
    assert left == pytest.approx(float(np.abs(out[:, 0]).max()), rel=1e-6)
    assert right == pytest.approx(float(np.abs(out[:, 1]).max()), rel=1e-6)
    assert left > 0.0


def test_peak_is_max_over_several_blocks():
    e = make()
    e.note_on(60, 100)
    peaks = [np.abs(e.render(BLOCK)).max(axis=0) for _ in range(5)]
    left, right, _ = e.peek_meter()
    assert left == pytest.approx(float(max(p[0] for p in peaks)), rel=1e-6)
    assert right == pytest.approx(float(max(p[1] for p in peaks)), rel=1e-6)


def test_take_resets_and_peek_does_not():
    e = make()
    e.note_on(60, 100)
    e.render(BLOCK)
    first = e.peek_meter()
    assert e.peek_meter() == first
    assert e.take_meter() == first
    assert e.take_meter() == (0.0, 0.0, False)
    assert first[0] > 0.0


def test_low_gain_does_not_clip():
    e = make()
    e.set_master_gain(0.1)
    e.note_on(60, 127)
    e.render(BLOCK)
    assert e.peek_meter()[2] is False


def test_high_gain_with_loud_voices_clips():
    e = make()
    e.set_osc_levels(1.0, 1.0)
    e.set_master_gain(1.5)
    for note in (48, 55, 60, 64, 67, 72):
        e.note_on(note, 127)
    for _ in range(4):
        e.render(BLOCK)
    left, right, clipped = e.peek_meter()
    assert clipped is True
    assert max(left, right) < 1.0
    assert e.take_meter()[2] is True
    assert e.take_meter()[2] is False


def test_stereo_spread_gives_different_peaks():
    e = make()
    e.set_unison_voices(3)
    e.set_unison_spread(1.0)
    e.set_unison_detune(0.0)
    e.note_on(60, 100)
    # make the stereo image lopsided: a voice panned hard to one side
    for v in e.voices:
        if v.active:
            v.pan = -1.0
            break
    for _ in range(4):
        e.render(BLOCK)
    left, right, _ = e.peek_meter()
    assert left != right


def test_offline_render_updates_meter():
    e = make()
    e.note_on(60, 100)
    e.render(BLOCK, apply_effects=False)
    assert e.peek_meter()[0] > 0.0


def test_meter_thread_safety_smoke():
    e = make()
    e.note_on(60, 100)
    errors = []
    stop = threading.Event()

    def renderer():
        try:
            while not stop.is_set():
                e.render(BLOCK)
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            while not stop.is_set():
                left, right, clipped = e.take_meter()
                assert 0.0 <= left <= 1.0 and 0.0 <= right <= 1.0
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=renderer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    time.sleep(0.3)
    stop.set()
    for t in threads:
        t.join()
    assert errors == []
