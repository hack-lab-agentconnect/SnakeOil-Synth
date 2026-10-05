import numpy as np
import pytest

from midi_synth.engine import SynthEngine


def rms_after(engine, note, blocks=30):
    engine.note_on(note, 100)
    for _ in range(blocks):
        out = engine.render(256)[:, 0]
    return float(np.sqrt(np.mean(out.astype(np.float64) ** 2)))


def make():
    return SynthEngine(sr=44100, block_size=256, max_voices=2)


def make_bypassed():
    e = make()
    e.set_lpf_cutoff(20000.0)
    return e


def test_max_cutoff_is_bypassed_and_deterministic():
    a, b = make_bypassed(), make_bypassed()
    assert a.params["lpf_cutoff"] == 20000.0
    assert a.params["lpf_coeffs"] is None
    a.note_on(60, 100)
    b.note_on(60, 100)
    assert np.array_equal(a.render(256), b.render(256))


@pytest.mark.parametrize("mode", ["voice", "master"])
def test_high_note_attenuated_low_note_passes(mode):
    base_low = rms_after(make_bypassed(), 36)
    base_high = rms_after(make_bypassed(), 96)
    e = make()
    e.set_lpf_mode(mode)
    e.set_lpf_cutoff(200.0)
    assert rms_after(e, 96) < 0.1 * base_high
    e2 = make()
    e2.set_lpf_mode(mode)
    e2.set_lpf_cutoff(4000.0)
    assert rms_after(e2, 36) > 0.9 * base_low


def test_cutoff_back_to_maximum_bypasses():
    e = make()
    e.set_lpf_cutoff(1000.0)
    assert e.params["lpf_coeffs"] is not None
    e.set_lpf_cutoff(20000.0)
    assert e.params["lpf_coeffs"] is None


def test_values_are_clamped():
    e = make()
    e.set_lpf_cutoff(1e9)
    assert e.params["lpf_cutoff"] == 20000.0
    e.set_lpf_resonance(9)
    assert e.params["lpf_resonance"] == 1.0


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        make().set_lpf_mode("wobble")


def test_mode_switch_and_note_on_reset_filter_state():
    e = make()
    e.set_lpf_cutoff(1000.0)
    e.note_on(60, 100)
    e.render(256)
    voice = next(v for v in e.voices if v.active)
    assert voice.lpf.z1 != 0.0
    e.set_lpf_mode("master")
    assert voice.lpf.z1 == 0.0 and voice.lpf.z2 == 0.0
    e.render(256)
    assert e.master_lpf.z1 != 0.0
    e.set_lpf_mode("voice")
    assert e.master_lpf.z1 == 0.0


def test_status_reports_filter():
    e = make()
    e.set_lpf_cutoff(500.0)
    s = e.status()
    assert s["lpf_cutoff"] == 500.0 and s["lpf_mode"] == "voice"
