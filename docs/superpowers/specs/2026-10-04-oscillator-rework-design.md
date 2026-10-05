# Oscillator Rework: Saw/Square with PWM — Design

## Goal
Replace the four-waveform oscillators with a fixed pair: Osc 1 is a saw with an
optional layered square; Osc 2 is a square only. Both squares have PWM.

## Behaviour
- Waveforms sine and triangle are removed, as are the per-oscillator waveform
  selectors (`osc1_waveform`, `osc2_waveform`), `engine.set_osc*_waveform`, the
  `wave1`/`wave2` console commands, `render_demo` `--wave1/--wave2`, the
  program-change waveform switch, and Default CCs 24/25. `config.WAVEFORMS` is removed.
- **Osc 1** = band-limited saw. Toggle `osc1_square` ("Square layer"): when on,
  output = `LAYER_GAIN * (saw + pulse)` with `LAYER_GAIN = 0.6`, both from the same phase.
- **Osc 2** = band-limited pulse only.
- **PWM**: `osc1_pwm` (square layer) and `osc2_pwm`, 0.0-0.5 duty, default 0.5
  (plain square). Effective duty is clamped to >= `MIN_DUTY = 0.02` (0 would be silent).
  Pulse is PolyBLEP'd at both edges, DC-corrected (`- (2d-1)`) and peak-normalised
  (`/ (2-2d)`), so duty 0.5 is bit-identical to the old square.
- FM / AM / ring / sync modulation keep using Osc 1's full output (including the
  layer) as the modulator; osc2's pulse width applies in every mode.
- Levels, octave switches, coarse/fine, filter, effects unchanged.

## GUI
Oscillator 1: Level, Square layer toggle, PWM, Octave down. Oscillator 2: Level,
Coarse, Fine, PWM, Octave up. Layout grid: row 0 Osc 1 / Osc 2 / Modulation,
row 1 Effects / Filter / Master.

## MIDI
No default CCs for the new params (learnable). Saved profiles referencing the
removed params keep working: unknown param ids are ignored by the router.
