# Low-Pass Filter with Resonance — Design

## Goal
Add a classic resonant low-pass filter (12 dB/oct) with cutoff and resonance
dials, controllable from the GUI, MIDI learn and profiles like every other
parameter.

## Behaviour
- **Cutoff**: log-scaled 20 Hz - 20 kHz, default 20 kHz = bypass (no CPU, output
  identical to today).
- **Resonance**: 0-1 mapped exponentially to Q 0.707 - 12.
- **Filter**: RBJ biquad low-pass, direct form II transposed, coefficients
  recomputed once per render block from the current params.
- **Placement** (runtime toggle "Master-bus filter" in the GUI, param
  `lpf_master`; CLI `--lpf-mode voice|master` sets the initial value):
  - `voice` (default): one filter per voice, after the oscillator mix and before
    the amplitude envelope. State resets on each note-on.
  - `master`: one filter on the summed voices, before the effect chain. This is
    the fallback if per-voice filtering costs too much CPU (bench: 12 pure-Python
    filters ~0.7 ms/block on a ~5.8 ms budget; engine alone ~1 ms).
  - Switching mode or bypass state resets filter state to avoid clicks.
- **MIDI**: Default profile gains CC 74 -> cutoff, CC 71 -> resonance (standard
  assignments). Existing saved Default profiles pick these up via Reset.
- **GUI**: new "Filter" group (Cutoff knob, Resonance knob, Master-bus filter
  toggle). Knob supports log scaling. Master moves to the top row.

## Non-goals
Other filter types, filter envelope, key tracking, cutoff smoothing between
blocks.
