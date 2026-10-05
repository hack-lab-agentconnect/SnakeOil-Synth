import numpy as np

from midi_synth.engine import SynthEngine
from midi_synth.params import build_registry

SR = 44100
BLOCK = 256


def make():
    return SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)


def peak_hz(engine, note=69, skip=10, blocks=40):
    engine.note_on(note, 100)
    for _ in range(skip):
        engine.render(BLOCK)
    data = np.concatenate([engine.render(BLOCK)[:, 0] for _ in range(blocks)]).astype(np.float64)
    spectrum = np.abs(np.fft.rfft(data * np.hanning(len(data))))
    return float(np.argmax(spectrum)) * SR / len(data)


def test_osc1_octave_down_halves_pitch():
    e = make()
    e.set_osc_levels(1.0, 0.0)
    assert abs(peak_hz(e) - 440.0) < 6.0
    e = make()
    e.set_osc_levels(1.0, 0.0)
    e.set_osc1_octave_down(True)
    assert abs(peak_hz(e) - 220.0) < 6.0


def test_osc2_octave_up_doubles_pitch():
    e = make()
    e.set_osc_levels(0.0, 1.0)
    e.set_mod_mode("off")
    e.set_osc2_octave_up(False)
    assert abs(peak_hz(e) - 440.0) < 6.0
    e = make()
    e.set_osc_levels(0.0, 1.0)
    e.set_mod_mode("off")
    e.set_osc2_octave_up(True)
    assert abs(peak_hz(e) - 880.0) < 6.0


def test_osc2_stays_relative_to_played_note_with_both_on():
    e = make()
    e.set_osc_levels(0.0, 1.0)
    e.set_mod_mode("off")
    e.set_osc1_octave_down(True)
    e.set_osc2_octave_up(True)
    assert abs(peak_hz(e) - 880.0) < 6.0


def test_both_off_after_toggling_matches_never_toggled():
    a, b = make(), make()
    for e in (a, b):
        e.set_osc1_octave_down(False)
        e.set_osc2_octave_up(False)
    a.set_osc1_octave_down(True)
    a.set_osc2_octave_up(True)
    a.set_osc1_octave_down(False)
    a.set_osc2_octave_up(False)
    assert a.params["osc1_octave_down"] is False
    assert a.params["osc2_octave_up"] is False
    for e in (a, b):
        e.set_osc_levels(0.7, 0.5)
        e.set_detune2(3.0, 0.2)
        e.note_on(60, 100)
    for _ in range(5):
        assert np.array_equal(a.render(BLOCK), b.render(BLOCK))


def test_sync_with_octaves_is_finite():
    e = make()
    e.set_osc_levels(0.7, 0.7)
    e.set_mod_mode("sync")
    e.set_fm_depth(1.0)
    e.set_osc1_octave_down(True)
    e.set_osc2_octave_up(True)
    for note in (0, 60, 127):
        e.note_on(note, 127)
        for _ in range(5):
            assert np.all(np.isfinite(e.render(BLOCK)))


def test_registry_maps_to_engine_and_defaults():
    e = make()
    reg = build_registry(e)
    assert reg.get("osc1_octave") is False
    assert reg.get("osc2_octave") is True
    reg.set("osc1_octave", True)
    reg.set("osc2_octave", False)
    assert e.params["osc1_octave_down"] is True
    assert e.params["osc2_octave_up"] is False
    reg.set("osc2_octave", True)
    assert e.params["osc1_octave_down"] is True
    assert e.params["osc2_octave_up"] is True
    assert reg["osc1_octave"].group == "Oscillator 1"
    assert reg["osc2_octave"].group == "Oscillator 2"


def test_status_reports_octave_switches():
    e = make()
    assert e.status()["osc1_octave_down"] is False
    e.set_osc2_octave_up(1)
    assert e.status()["osc2_octave_up"] is True
