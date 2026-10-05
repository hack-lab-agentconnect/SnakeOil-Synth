import numpy as np
import pytest

from midi_synth.config import DEFAULT_DUTY, LAYER_GAIN, MIN_DUTY
from midi_synth.engine import SynthEngine
from midi_synth.oscillators import Oscillator, pulse_wave, saw_wave

SR = 44100
BLOCK = 256


def phase_ramp(n, inc):
    return np.mod(np.arange(n, dtype=np.float64) * inc, 1.0)


def test_constants():
    assert (MIN_DUTY, DEFAULT_DUTY, LAYER_GAIN) == (0.02, 0.5, 0.6)


def test_unknown_waveform_rejected():
    with pytest.raises(ValueError):
        Oscillator(SR, "sine")
    assert Oscillator(SR, "saw").waveform == "saw"
    assert Oscillator(SR, "square").duty == DEFAULT_DUTY
    assert Oscillator(SR, "saw").layer_square is False


def test_pulse_at_half_duty_is_plain_square():
    inc = 0.01
    t = phase_ramp(10000, inc)
    p = pulse_wave(t, inc, 0.5)
    away = (np.abs(t - 0.0) > 2 * inc) & (np.abs(t - 0.5) > 2 * inc) & (np.abs(t - 1.0) > 2 * inc)
    assert np.allclose(p[away], np.where(t < 0.5, 1.0, -1.0)[away])
    assert np.max(np.abs(p)) <= 1.05


@pytest.mark.parametrize("duty", [0.05, 0.1, 0.25, 0.4])
def test_narrow_pulse_zero_mean_and_bounded(duty):
    inc = 1e-4
    t = phase_ramp(10000, inc)
    p = pulse_wave(t, inc, duty)
    assert abs(np.mean(p)) < 0.02
    assert np.max(np.abs(p)) <= 1.05


def test_duty_below_minimum_behaves_like_minimum():
    inc = 0.01
    t = phase_ramp(500, inc)
    assert np.array_equal(pulse_wave(t, inc, 0.0), pulse_wave(t, inc, MIN_DUTY))
    assert np.array_equal(pulse_wave(t, inc, 0.01), pulse_wave(t, inc, MIN_DUTY))


def test_saw_wave_matches_formula():
    inc = 0.01
    t = phase_ramp(300, inc)
    assert np.allclose(saw_wave(t, inc)[50:60], 2.0 * t[50:60] - 1.0)
    assert np.max(np.abs(saw_wave(t, inc))) <= 1.05


def render_osc1(engine, note=57, blocks=20):
    engine.set_osc_levels(1.0, 0.0)
    engine.note_on(note, 100)
    return np.concatenate([engine.render(BLOCK)[:, 0] for _ in range(blocks)])


def test_layer_off_is_bit_identical_to_saw_only():
    a = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    b = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    a.set_osc1_square(False)
    b.set_osc1_square(True)
    b.set_osc1_square(False)
    b.set_osc1_pwm(0.2)  # PWM must not matter while the layer is off
    assert np.array_equal(render_osc1(a), render_osc1(b))
    a2 = Oscillator(SR, "saw")
    ref = Oscillator(SR, "saw")
    t = ref.advance(440.0, 128)
    assert np.array_equal(a2.generate(440.0, 128), saw_wave(t, 440.0 / SR))


def test_layer_toggle_changes_output_and_is_bounded():
    a = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    b = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    a.set_osc1_square(False)
    b.set_osc1_square(True)
    out_a, out_b = render_osc1(a), render_osc1(b)
    assert not np.allclose(out_a, out_b)
    assert np.all(np.isfinite(out_b))
    osc = Oscillator(SR, "saw")
    osc.layer_square = True
    raw = osc.generate(440.0, 4096)
    assert np.all(np.isfinite(raw))
    assert np.max(np.abs(raw)) < 1.3
    assert np.max(np.abs(raw)) > 0.5  # saw+square peaks near LAYER_GAIN


def bin_mag(signal, freq):
    spec = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
    return spec[int(round(freq * len(signal) / SR))]


def test_osc2_pwm_changes_spectrum():
    f0 = 441.0
    n = 44100

    def spectrum_ratio(duty):
        osc = Oscillator(SR, "square")
        osc.duty = duty
        sig = osc.generate(f0, n)
        return bin_mag(sig, 2 * f0) / bin_mag(sig, f0)

    assert spectrum_ratio(0.5) < 0.02
    assert spectrum_ratio(0.25) > 0.2


def test_engine_pwm_reaches_voice_oscillators():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
    e.set_osc_levels(0.0, 1.0)
    e.set_mod_mode("off")
    e.set_osc2_pwm(0.25)
    e.set_osc1_pwm(0.1)
    e.set_osc1_square(True)
    e.note_on(60, 100)
    e.render(BLOCK)
    v = next(v for v in e.voices if v.active)
    assert v.osc2.duty == 0.25
    assert v.osc1.duty == 0.1
    assert v.osc1.layer_square is True
    assert v.osc1.waveform == "saw" and v.osc2.waveform == "square"


def test_pwm_setters_clamp():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=1)
    e.set_osc1_pwm(-1)
    e.set_osc2_pwm(2)
    assert e.params["osc1_pwm"] == 0.0 and e.params["osc2_pwm"] == 0.5
    e.set_osc1_square(False)
    st = e.status()
    assert st["osc1_pwm"] == 0.0 and st["osc2_pwm"] == 0.5 and st["osc1_square"] is False


def test_engine_has_no_waveform_api():
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=1)
    assert not hasattr(e, "set_osc1_waveform")
    assert not hasattr(e, "set_osc2_waveform")
    assert "osc1_waveform" not in e.params and "osc2_waveform" not in e.status()


def test_extreme_pwm_with_all_modes_is_finite():
    for mode in ("off", "fm", "am", "ring", "sync"):
        e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=2)
        e.set_osc_levels(1.0, 1.0)
        e.set_mod_mode(mode)
        e.set_fm_depth(1.0)
        e.set_osc1_square(True)
        e.set_osc1_pwm(0.0)
        e.set_osc2_pwm(0.0)
        for note in (0, 60, 127):
            e.note_on(note, 127)
            for _ in range(4):
                out = e.render(BLOCK)
                assert np.all(np.isfinite(out))
