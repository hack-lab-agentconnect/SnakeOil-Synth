"""Golden tests: the optimised voice path must match the frozen reference DSP."""
import numpy as np
import pytest

from midi_synth.filters import LowPass, lpf_coefficients
from midi_synth.oscillators import Oscillator, _poly_blep, pulse_wave, saw_wave
from midi_synth.voice import Envelope, Voice
from tests.reference_dsp import (
    RefEnvelope, RefLowPass, RefOscillator, RefVoice, ref_poly_blep,
    ref_pulse_wave, ref_saw_wave,
)
from midi_synth.config import LAYER_GAIN

SR = 48000


# ---------------------------------------------------------------- low-pass

@pytest.mark.parametrize("kind", ["noise", "sine"])
def test_lowpass_matches_reference(kind):
    rng = np.random.default_rng(1)
    new, ref = LowPass(SR), RefLowPass(SR)
    sizes = [64, 128, 256, 300, 256, 64, 300, 128]
    pos = 0
    for k, n in enumerate(sizes):
        if kind == "noise":
            x = rng.uniform(-1, 1, n)
        else:
            x = np.sin(2 * np.pi * 440.0 * (pos + np.arange(n)) / SR)
            pos += n
        coeffs = lpf_coefficients(500.0 + 1500.0 * k, 0.1 * k, SR)
        a = ref.process(x, coeffs)
        b = new.process(x, coeffs)
        assert isinstance(b, np.ndarray) and b.dtype == np.float64
        assert np.max(np.abs(a - b)) < 1e-9
        assert abs(ref.z1 - new.z1) < 1e-9 and abs(ref.z2 - new.z2) < 1e-9
    new.reset()
    assert new.z1 == 0.0 and new.z2 == 0.0


# ---------------------------------------------------------------- envelope

def _pair(**shape):
    new, ref = Envelope(SR), RefEnvelope(SR)
    if shape:
        new.set_shape(**shape)
        ref.set_shape(**shape)
    return new, ref


def _step(new, ref, n):
    a = ref.process(n)
    b = new.process(n)
    assert len(b) == n
    assert np.max(np.abs(a - b)) < 1e-12 if n else True
    assert new.stage == ref.stage
    assert abs(new.level - ref.level) < 1e-12
    assert new.active == ref.active


SHAPES = [
    dict(attack=0.006, decay=0.120, sustain=0.75, release=0.180),
    dict(attack=1.0 / SR, decay=1.0 / SR, sustain=0.5, release=1.0 / SR),
    dict(attack=0.002, decay=0.003, sustain=0.0, release=0.004),
    dict(attack=0.002, decay=0.003, sustain=1.0, release=0.004),
    dict(attack=0.01, decay=0.02, sustain=0.3, release=0.05),
]


@pytest.mark.parametrize("shape", SHAPES)
def test_envelope_full_adsr_one_block(shape):
    new, ref = _pair(**shape)
    new.note_on(); ref.note_on()
    _step(new, ref, 4096)
    new.note_off(); ref.note_off()
    _step(new, ref, 16384)
    assert not new.active


@pytest.mark.parametrize("block", [1, 7, 256, 4096])
@pytest.mark.parametrize("shape", SHAPES)
def test_envelope_block_sizes(shape, block):
    new, ref = _pair(**shape)
    new.note_on(); ref.note_on()
    total = 0
    off_at = 1500
    done_off = False
    while total < 12000:
        if not done_off and total >= off_at:
            new.note_off(); ref.note_off()
            done_off = True
        _step(new, ref, block)
        total += block


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("off_after", [0, 1, 5, 40, 90, 200, 400, 1500, 3000])
def test_envelope_note_off_in_every_stage(shape, off_after):
    for block in (1, 7, 256):
        new, ref = _pair(**shape)
        new.note_on(); ref.note_on()
        done = 0
        while done < off_after:
            n = min(block, off_after - done)
            _step(new, ref, n)
            done += n
        new.note_off(); ref.note_off()
        for _ in range(6000 // block + 2):
            _step(new, ref, block)


@pytest.mark.parametrize("shape", SHAPES)
def test_envelope_retrigger_from_nonzero_level(shape):
    new, ref = _pair(**shape)
    new.note_on(); ref.note_on()
    _step(new, ref, 100)
    new.note_off(); ref.note_off()
    _step(new, ref, 50)
    new.note_on(); ref.note_on()          # retrigger mid-release
    for _ in range(20):
        _step(new, ref, 256)
    # retrigger from a full level
    new.note_on(); ref.note_on()
    for _ in range(5):
        _step(new, ref, 256)


def test_envelope_idle_and_note_off_when_idle():
    new, ref = _pair()
    _step(new, ref, 64)
    new.note_off(); ref.note_off()
    _step(new, ref, 64)
    assert not new.active


def test_envelope_random_blocks_and_changing_shape():
    rng = np.random.default_rng(7)
    new, ref = _pair()
    new.note_on(); ref.note_on()
    for i in range(300):
        r = rng.random()
        if r < 0.05:
            new.note_off(); ref.note_off()
        elif r < 0.10:
            new.note_on(); ref.note_on()
        elif r < 0.15:
            s = dict(attack=float(rng.uniform(0, 0.02)),
                     decay=float(rng.uniform(0, 0.02)),
                     sustain=float(rng.uniform(0, 1)),
                     release=float(rng.uniform(0, 0.02)))
            new.set_shape(**s); ref.set_shape(**s)
        _step(new, ref, int(rng.integers(1, 400)))


# ---------------------------------------------------------------- PolyBLEP

@pytest.mark.parametrize("dt", [1e-4, 0.01, 0.1, 0.45])
def test_poly_blep_matches_reference(dt):
    t = np.concatenate([np.linspace(0.0, 1.0, 20001)[:-1],
                        [0.0, dt, 1.0 - dt, np.nextafter(1.0, 0.0)]])
    assert np.max(np.abs(_poly_blep(t, dt) - ref_poly_blep(t, dt))) < 1e-12


def test_poly_blep_zero_dt():
    t = np.linspace(0.0, 1.0, 1001)[:-1]
    assert np.max(np.abs(_poly_blep(t, 0.0) - ref_poly_blep(t, 0.0))) < 1e-12


# ------------------------------------------------------- oscillator shapes

@pytest.mark.parametrize("duty", [0.0, 0.1, 0.25, 0.5])
@pytest.mark.parametrize("inc", [0.0005, 0.01, 0.1, 0.45])
def test_wave_shapes_match_reference(duty, inc):
    t = np.mod(0.123 + inc * np.arange(2048), 1.0)
    assert np.max(np.abs(saw_wave(t, inc) - ref_saw_wave(t, inc))) < 1e-12
    assert np.max(np.abs(pulse_wave(t, inc, duty)
                         - ref_pulse_wave(t, inc, duty))) < 1e-12
    layered = LAYER_GAIN * (ref_saw_wave(t, inc) + ref_pulse_wave(t, inc, duty))
    osc = Oscillator(SR, "saw")
    osc.layer_square = True
    osc.duty = duty
    assert np.max(np.abs(osc._shape(t, inc) - layered)) < 1e-12
    osc.layer_square = False
    assert np.max(np.abs(osc._shape(t, inc) - ref_saw_wave(t, inc))) < 1e-12
    sq = Oscillator(SR, "square")
    sq.duty = duty
    assert np.max(np.abs(sq._shape(t, inc) - ref_pulse_wave(t, inc, duty))) < 1e-12


@pytest.mark.parametrize("layer", [False, True])
def test_oscillator_generate_matches_reference(layer):
    new, ref = Oscillator(SR, "saw"), RefOscillator(SR, "saw")
    new.layer_square = ref.layer_square = layer
    new.duty = ref.duty = 0.2
    pm = np.sin(np.arange(256) * 0.05)
    for _ in range(5):
        for phase_mod in (None, pm):
            a = ref.generate(523.25, 256, phase_mod=phase_mod)
            b = new.generate(523.25, 256, phase_mod=phase_mod)
            assert np.max(np.abs(a - b)) < 1e-12
            assert abs(new.phase - ref.phase) < 1e-12


# --------------------------------------------------------- voice-level

def _base_params():
    return {
        "osc1_level": 1.0, "osc2_level": 0.0, "osc1_square": True,
        "osc1_pwm": 0.0, "osc2_pwm": 0.0, "mod_mode": "off", "fm_depth": 0.0,
        "mod_index": 0.0, "detune2_semitones": 0.0, "detune2_cents": 0.0,
        "osc1_octave_down": False, "osc2_octave_up": True, "pitch_ratio": 1.0,
        "lpf_mode": "voice",
        "lpf_coeffs": lpf_coefficients(2000.0, 0.2, SR),
    }


MODES = ["off", "fm", "am", "ring", "sync"]


@pytest.mark.parametrize("mode", MODES)
def test_silent_osc2_matches_reference_all_modes(mode):
    p = _base_params()
    p.update(mod_mode=mode, fm_depth=0.7, mod_index=4.0, osc2_level=0.0,
             detune2_cents=7.0)
    ref, new = RefVoice(SR), Voice(SR)
    ref.note_on(60, 0.9, 1); new.note_on(60, 0.9, 1)
    for _ in range(4):
        a, b = ref.render(256, p), new.render(256, p)
        assert np.max(np.abs(a - b)) < 1e-9
        assert abs(new.osc2.phase - ref.osc2.phase) < 1e-12


@pytest.mark.parametrize("mode", MODES)
def test_osc2_level_raised_mid_note_keeps_phase_continuity(mode):
    p = _base_params()
    p.update(mod_mode=mode, fm_depth=0.6, mod_index=3.0, osc2_level=0.0,
             detune2_cents=11.0, osc2_pwm=0.3)
    ref, new = RefVoice(SR), Voice(SR)
    ref.note_on(55, 0.7, 1); new.note_on(55, 0.7, 1)
    for block in range(8):
        if block == 3:
            p = dict(p, osc2_level=0.8)
        if block == 6:
            p = dict(p, osc2_level=0.0)
        a, b = ref.render(300, p), new.render(300, p)
        assert np.max(np.abs(a - b)) < 1e-9


def _random_params(rng):
    p = _base_params()
    cutoff_on = rng.random() < 0.75
    p.update(
        osc1_level=float(rng.choice([0.0, 0.5, 1.0, rng.uniform(0, 1)])),
        osc2_level=float(rng.choice([0.0, 0.0, 1.0, rng.uniform(0, 1)])),
        osc1_square=bool(rng.random() < 0.5),
        osc1_pwm=float(rng.uniform(0.0, 0.5)),
        osc2_pwm=float(rng.uniform(0.0, 0.5)),
        mod_mode=str(rng.choice(MODES)),
        fm_depth=float(rng.uniform(0, 1)),
        mod_index=float(rng.uniform(0, 8)),
        detune2_semitones=float(rng.choice([0, 0, 7, -5, 12])),
        detune2_cents=float(rng.uniform(-50, 50)),
        osc1_octave_down=bool(rng.random() < 0.5),
        osc2_octave_up=bool(rng.random() < 0.5),
        pitch_ratio=float(2.0 ** (rng.uniform(-2, 2) / 12.0)),
        lpf_mode=str(rng.choice(["voice", "voice", "master"])),
        lpf_coeffs=(lpf_coefficients(float(rng.uniform(100, 20000)),
                                     float(rng.uniform(0, 1)), SR)
                    if cutoff_on else None),
    )
    return p


@pytest.mark.parametrize("seed", range(40))
def test_voice_matches_reference_random_params(seed):
    rng = np.random.default_rng(1000 + seed)
    p = _random_params(rng)
    note = int(rng.integers(24, 100))
    vel = float(rng.uniform(0.1, 1.0))
    ref, new = RefVoice(SR), Voice(SR)
    ref.note_on(note, vel, 1); new.note_on(note, vel, 1)
    block = int(rng.choice([64, 128, 256, 300]))
    for b in range(8):
        if b == 4:
            ref.note_off(); new.note_off()
        if b == 2 and rng.random() < 0.5:
            p = dict(p, osc2_level=float(rng.uniform(0, 1)))
        a, c = ref.render(block, p), new.render(block, p)
        assert len(c) == block and c.dtype == np.float64
        assert np.max(np.abs(a - c)) < 1e-9
        assert new.active == ref.active
