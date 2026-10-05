import numpy as np
import pytest

from midi_synth.engine import SynthEngine


def rms_after(engine, note, blocks=30):
    engine.note_on(note, 100)
    for _ in range(blocks):
        out = engine.render(256)
    return float(np.sqrt(np.mean(out.astype(np.float64) ** 2)))


def make():
    return SynthEngine(sr=44100, block_size=256, max_voices=2)


def test_default_is_bypassed_and_unchanged():
    a, b = make(), make()
    assert a.params["hpf_cutoff"] == 20.0
    assert a.params["hpf_coeffs"] is None
    a.note_on(60, 100)
    b.note_on(60, 100)
    assert np.array_equal(a.render(256), b.render(256))


@pytest.mark.parametrize("mode", ["voice", "master"])
def test_low_note_attenuated_high_note_passes(mode):
    base_low = rms_after(make(), 36)
    base_high = rms_after(make(), 96)
    e = make()
    e.set_hpf_mode(mode)
    e.set_hpf_cutoff(1500.0)
    assert rms_after(e, 36) < 0.1 * base_low
    e2 = make()
    e2.set_hpf_mode(mode)
    e2.set_hpf_cutoff(200.0)
    assert rms_after(e2, 96) > 0.9 * base_high


def test_cutoff_back_to_minimum_bypasses():
    e = make()
    e.set_hpf_cutoff(1000.0)
    assert e.params["hpf_coeffs"] is not None
    e.set_hpf_cutoff(20.0)
    assert e.params["hpf_coeffs"] is None


def test_values_are_clamped():
    e = make()
    e.set_hpf_cutoff(1e9)
    assert e.params["hpf_cutoff"] == 8000.0
    e.set_hpf_resonance(9)
    assert e.params["hpf_resonance"] == 1.0


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        make().set_hpf_mode("wobble")


def test_mode_switch_and_note_on_reset_filter_state():
    e = make()
    e.set_hpf_cutoff(1000.0)
    e.note_on(60, 100)
    e.render(256)
    voice = next(v for v in e.voices if v.active)
    assert voice.hpf.z1 != 0.0
    e.set_hpf_mode("master")
    assert voice.hpf.z1 == 0.0 and voice.hpf.z2 == 0.0
    e.render(256)
    assert e.master_hpf.z1 != 0.0
    e.set_hpf_mode("voice")
    assert e.master_hpf.z1 == 0.0


def test_status_reports_filter():
    e = make()
    e.set_hpf_cutoff(500.0)
    s = e.status()
    assert s["hpf_cutoff"] == 500.0 and s["hpf_mode"] == "voice"
