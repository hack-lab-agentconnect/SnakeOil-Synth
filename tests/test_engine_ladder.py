"""Engine and voice behaviour of the 12/24 dB slope switch and the whistle."""
import numpy as np
import pytest

import run
from midi_synth.config import DEFAULT_LPF_SLOPE, LPF_SLOPES
from midi_synth.engine import SynthEngine
from midi_synth.filters import LADDER_OSC_LEVEL, LADDER_OSC_START
from midi_synth.params import CHOICE, build_registry
from midi_synth import patches

SR = 44100
BLOCK = 256


def make(voices=2):
    return SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices)


def silent_source(e):
    """No oscillator and no noise: only the filter itself can make sound."""
    e.set_osc_level(1, 0.0)
    e.set_osc_level(2, 0.0)
    e.set_noise_level(0.0)
    e.set_amp_attack(0.001)
    e.set_amp_sustain(1.0)


def render(e, n_blocks):
    return np.concatenate([e.render(BLOCK)[:, 0] for _ in range(n_blocks)]).astype(np.float64)


def peak_hz(x, pad=8):
    win = np.hanning(len(x))
    spec = np.abs(np.fft.rfft(x * win, n=len(x) * pad))
    return float(spec.argmax()) * SR / (len(x) * pad)


def whistle_engine(res=1.0, cutoff=1000.0, **setup):
    e = make()
    silent_source(e)
    e.set_lpf_slope("24 dB")
    e.set_lpf_cutoff(cutoff)
    e.set_lpf_resonance(res)
    return e


WHISTLE_PEAK = LADDER_OSC_LEVEL * 0.22 * (0.3 + 0.7 * 100 / 127) * 0.8


def settled_peak(e, note=60, blocks=80):
    e.note_on(note, 100)
    render(e, 20)
    return np.abs(render(e, blocks)).max()


# ---- setter, status, registry ---------------------------------------------

def test_default_slope_and_constants():
    assert LPF_SLOPES == ("12 dB", "24 dB")
    assert DEFAULT_LPF_SLOPE == "12 dB"
    e = make()
    assert e.params["lpf_slope"] == "12 dB"
    assert e.status()["lpf_slope"] == "12 dB"
    assert len(e.params["lpf_coeffs"]) == 5


def test_set_slope_validates_and_recomputes_coefficients():
    e = make()
    e.set_lpf_slope("24 dB")
    assert e.params["lpf_slope"] == "24 dB"
    assert len(e.params["lpf_coeffs"]) == 2
    assert e.status()["lpf_slope"] == "24 dB"
    with pytest.raises(ValueError):
        e.set_lpf_slope("36 dB")
    assert e.params["lpf_slope"] == "24 dB"
    e.set_lpf_slope("12 dB")
    assert len(e.params["lpf_coeffs"]) == 5


def test_registry_entry_and_patch_round_trip():
    e = make()
    reg = build_registry(e)
    p = reg["lpf_slope"]
    assert (p.kind, p.label, p.group, p.choices) == (CHOICE, "Slope", "Filter", LPF_SLOPES)
    assert p.tooltip
    ids = reg.ids()
    assert ids.index("lpf_slope") == ids.index("lpf_resonance") + 1
    defaults = patches.capture(reg)
    assert defaults["lpf_slope"] == "12 dB"
    reg.set("lpf_slope", "24 dB")
    snap = patches.capture(reg)
    assert snap["lpf_slope"] == "24 dB"
    e2 = make()
    reg2 = build_registry(e2)
    assert patches.apply(reg2, snap, defaults) == []
    assert e2.params["lpf_slope"] == "24 dB"
    # an old patch without the key loads as 12 dB
    old = {k: v for k, v in snap.items() if k != "lpf_slope"}
    assert patches.apply(reg2, old, defaults) == []
    assert e2.params["lpf_slope"] == "12 dB"
    with pytest.raises(ValueError):
        reg.set("lpf_slope", "6 dB")


def run_console(monkeypatch, capsys, lines, engine):
    import builtins
    feed = iter(lines + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    run.console_loop(engine=engine)
    return capsys.readouterr().out


def test_console_lpfslope(monkeypatch, capsys):
    e = make()
    for text, want in (("24", "24 dB"), ("12", "12 dB"), ("24db", "24 dB"), ("12DB", "12 dB")):
        run_console(monkeypatch, capsys, ["lpfslope " + text], e)
        assert e.params["lpf_slope"] == want
    out = run_console(monkeypatch, capsys, ["lpfslope", "lpfslope 36"], e)
    assert out.count("usage: lpfslope") == 2
    assert e.params["lpf_slope"] == "12 dB"
    assert "lpfslope" in run.HELP_TEXT


# ---- default slope is bit-identical ----------------------------------------

@pytest.mark.parametrize("mode", ["voice", "master"])
@pytest.mark.parametrize("modulated", [False, True])
def test_explicit_12_db_is_bit_identical(mode, modulated):
    outs = []
    for explicit in (False, True):
        e = make()
        e.set_osc_level(2, 0.8)
        e.set_lpf_mode(mode)
        e.set_lpf_cutoff(900.0)
        e.set_lpf_resonance(0.6)
        if modulated:
            e.set_flt_env_amount(0.7)
            e.set_flt_keytrack(0.5)
            e.set_lfo_depth(0.8)
            e.set_lfo_dest("filter")
        if explicit:
            e.set_lpf_slope("12 dB")
        e.note_on(55, 100)
        e.note_on(67, 90)
        outs.append(render(e, 40))
    assert np.array_equal(outs[0], outs[1])


# ---- steeper slope ---------------------------------------------------------

def band_energy(x, lo_hz):
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / SR)
    return float(spec[freqs >= lo_hz].sum())


@pytest.mark.parametrize("mode", ["voice", "master"])
def test_24_db_attenuates_more_above_the_cutoff(mode):
    energy = {}
    for slope in ("12 dB", "24 dB"):
        e = make()
        e.set_lpf_mode(mode)
        e.set_lpf_slope(slope)
        e.set_lpf_cutoff(500.0)
        e.set_lpf_resonance(0.0)
        e.note_on(48, 100)
        render(e, 20)
        energy[slope] = band_energy(render(e, 40), 1000.0)
    ratio_db = 10 * np.log10(energy["12 dB"] / energy["24 dB"])
    assert ratio_db > 10.0


@pytest.mark.parametrize("mode", ["voice", "master"])
def test_bypass_passes_signal_unchanged_in_24_db(mode):
    outs = []
    for slope in ("12 dB", "24 dB"):
        e = make()
        e.set_lpf_mode(mode)
        e.set_lpf_slope(slope)
        e.set_lpf_cutoff(20000.0)
        assert e.params["lpf_coeffs"] is None
        e.note_on(60, 100)
        outs.append(render(e, 10))
    assert np.array_equal(outs[0], outs[1])


@pytest.mark.parametrize("mode", ["voice", "master"])
def test_slope_switch_resets_filter_state(mode):
    e = make()
    e.set_lpf_mode(mode)
    e.set_lpf_slope("24 dB")
    e.set_lpf_cutoff(400.0)
    e.set_lpf_resonance(0.9)
    e.note_on(48, 100)
    render(e, 10)
    states = [e.master_lpf, e.master_lpf_r] + [v.lpf for v in e.voices]
    assert any(s.z1 or s.z2 or s.z3 or s.z4 for s in states)
    e.set_lpf_slope("12 dB")
    for s in states:
        assert (s.z1, s.z2, s.z3, s.z4) == (0.0, 0.0, 0.0, 0.0)
    out = render(e, 5)
    assert np.all(np.isfinite(out))
    e.set_lpf_slope("24 dB")
    for s in states:
        assert (s.z1, s.z2, s.z3, s.z4) == (0.0, 0.0, 0.0, 0.0)


# ---- modulation works with the cascade -------------------------------------

def modulated(name, mode):
    e = make()
    e.set_osc_level(2, 0.6)
    e.set_lpf_slope("24 dB")
    e.set_lpf_mode(mode)
    e.set_lpf_cutoff(1500.0)
    e.set_lpf_resonance(0.4)
    if name == "env":
        e.set_flt_env_amount(0.9)
    elif name == "key":
        e.set_flt_keytrack(1.0)
    elif name == "vel":
        e.set_flt_vel(1.0)
    elif name == "lfo":
        e.set_lfo_depth(1.0)
        e.set_lfo_dest("filter")
        e.set_lfo_rate(3.0)
    elif name == "mx_cut":
        e.set_mod_row(1, "Note Number", 0.9, "Filter: Cutoff")
    elif name == "mx_res":
        e.set_mod_row(1, "Note Number", 0.9, "Filter: Resonance")
    return e


# envelope, key tracking and velocity only exist for the per-voice filter
MODULATIONS = [(n, "voice") for n in ("env", "key", "vel")] + [
    (n, m) for n in ("lfo", "mx_cut", "mx_res") for m in ("voice", "master")]


@pytest.mark.parametrize("name,mode", MODULATIONS)
def test_modulation_with_24_db(name, mode):
    base = modulated("none", mode)
    mod = modulated(name, mode)
    for e in (base, mod):
        e.note_on(36, 70 if name != "vel" else 127)
    a, b = render(base, 60), render(mod, 60)
    assert np.all(np.isfinite(b))
    assert np.abs(a - b).max() > 1e-3 * max(np.abs(a).max(), 1e-9)


@pytest.mark.parametrize("mode", ["voice", "master"])
def test_resonance_one_stays_bounded_while_swept(mode):
    e = make(4)
    e.set_osc_level(2, 0.8)
    e.set_lpf_slope("24 dB")
    e.set_lpf_mode(mode)
    e.set_lpf_cutoff(1000.0)
    e.set_lpf_resonance(1.0)
    e.set_lfo_depth(1.0)
    e.set_lfo_dest("filter")
    e.set_lfo_rate(7.0)
    for n in (36, 48, 60, 67):
        e.note_on(n, 110)
    worst = 0.0
    for _ in range(int(10 * SR / BLOCK)):
        out = e.render(BLOCK)
        assert np.all(np.isfinite(out))
        worst = max(worst, e.last_driven_peak)
    assert np.abs(out).max() <= 1.0
    assert worst < 1000.0


# ---- the self-oscillation whistle --------------------------------------------

def test_whistle_is_a_sine_at_the_cutoff_with_no_input():
    e = whistle_engine()
    e.note_on(60, 100)
    render(e, 20)
    x = render(e, 172)  # about one second
    assert abs(peak_hz(x) - 1000.0) < 3.0
    assert np.abs(x).max() == pytest.approx(WHISTLE_PEAK, rel=0.1)


def test_no_whistle_below_the_start_resonance():
    e = whistle_engine(res=0.85)
    assert settled_peak(e) < 1e-9
    e = whistle_engine(res=LADDER_OSC_START)
    assert settled_peak(e) < 1e-9


def test_whistle_fades_in_smoothly():
    peaks = {r: settled_peak(whistle_engine(res=r)) for r in (0.9, 0.925, 0.95, 0.975, 1.0)}
    assert peaks[0.9] < 1e-9
    values = [peaks[r] for r in (0.9, 0.925, 0.95, 0.975, 1.0)]
    assert all(b > a for a, b in zip(values, values[1:]))
    assert peaks[0.95] == pytest.approx(0.5 * peaks[1.0], rel=0.1)
    assert peaks[0.925] == pytest.approx(0.15625 * peaks[1.0], rel=0.1)


def test_whistle_follows_key_tracking():
    freqs = []
    for note in (60, 72):
        e = whistle_engine()
        e.set_flt_keytrack(1.0)
        e.note_on(note, 100)
        render(e, 20)
        freqs.append(peak_hz(render(e, 172)))
    assert freqs[1] / freqs[0] == pytest.approx(2.0, rel=0.01)


def test_whistle_follows_the_amp_envelope():
    e = whistle_engine()
    e.set_amp_release(0.05)
    e.note_on(60, 100)
    render(e, 30)
    e.note_off(60)
    tail = render(e, 100)
    assert np.abs(tail[-BLOCK:]).max() == 0.0
    assert np.abs(tail[:BLOCK]).max() > 0.0


def test_whistle_scales_with_velocity():
    peaks = []
    for vel in (30, 120):
        e = whistle_engine()
        e.note_on(60, vel)
        render(e, 20)
        peaks.append(np.abs(render(e, 40)).max())
    assert peaks[1] > 1.5 * peaks[0]


def test_whistle_follows_lfo_modulation():
    e = whistle_engine()
    e.set_lfo_depth(1.0)
    e.set_lfo_dest("filter")
    e.set_lfo_rate(2.0)
    e.note_on(60, 100)
    render(e, 10)
    x = render(e, 344)
    chunks = np.array_split(x, 8)
    freqs = [peak_hz(c) for c in chunks]
    assert max(freqs) / min(freqs) > 1.5


def test_whistle_follows_matrix_cutoff():
    freqs = []
    for wheel in (0.0, 1.0):
        e = whistle_engine()
        e.set_mod_row(1, "Mod Wheel", 0.5, "Filter: Cutoff")
        e.set_mod_wheel(wheel)
        e.note_on(60, 100)
        render(e, 20)
        freqs.append(peak_hz(render(e, 172)))
    assert abs(freqs[1] - freqs[0]) > 200.0


def test_matrix_resonance_triggers_the_whistle():
    e = whistle_engine(res=0.5)
    e.set_mod_row(1, "Mod Wheel", 1.0, "Filter: Resonance")
    e.set_mod_wheel(1.0)
    assert settled_peak(e) > 0.01


def test_whistle_absent_in_master_mode_and_at_12_db():
    e = whistle_engine()
    e.set_lpf_mode("master")
    assert settled_peak(e) < 1e-9
    e = whistle_engine()
    e.set_lpf_slope("12 dB")
    assert settled_peak(e) < 1e-9


def test_no_whistle_when_the_filter_is_bypassed():
    e = whistle_engine(cutoff=20000.0)
    assert settled_peak(e) < 1e-9


def test_whistle_is_phase_continuous_across_blocks():
    e = whistle_engine(cutoff=1000.0)
    e.note_on(60, 100)
    render(e, 20)
    x = render(e, 80)
    step = 2 * np.pi * 1000.0 / SR * np.abs(x).max()
    assert np.abs(np.diff(x)).max() <= 1.05 * step


def test_whistle_phase_restarts_at_note_on():
    e = whistle_engine()
    e.note_on(60, 100)
    render(e, 5)
    e.note_off(60)
    render(e, 100)
    assert any(v.osc_phase != 0.0 for v in e.voices)
    e.note_on(60, 100)
    held = [v for v in e.voices if v.gate]
    assert held and all(v.osc_phase == 0.0 for v in held)
