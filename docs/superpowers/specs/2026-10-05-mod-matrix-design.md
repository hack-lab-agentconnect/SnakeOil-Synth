# Mod Matrix + LFO Changes — Design

All work happens directly on `main` (owner's instruction), one commit per task, never pushed unless the owner asks. Rules from `2026-10-05-features-v2-roadmap.md` ("Rules for every task") still apply: TDD, default sound unchanged (golden tests), never block/raise on the audio thread, registry params for everything user-visible, README + console updated, `bench.py` all-effects under 50%.

## Task L — LFO group layout and LFO rate cross-modulation
- The LFO structure does NOT change: each LFO keeps rate, depth, wave (incl. random-glide) and destination, and still drives its destination exactly as today.
- Layout: one GUI group box titled "LFO" containing both LFOs side by side, each as a vertical stack (Rate, Depth, Wave, Dest) under a small header label "LFO 1" / "LFO 2". The registry groups may stay "LFO 1"/"LFO 2" internally (patch compatibility) but the window shows one box. LFO 2's old grid cell (row 1, last column) becomes free for the Mod Matrix group (reserve/keep the cell empty in this task or leave a placeholder constant `GROUP_POSITIONS["Mod Matrix"]` with no widget).
- LFO <-> LFO frequency modulation (NOT part of the matrix): `lfo_dest` gains the choice `lfo2-rate` and `lfo2_dest` gains `lfo1-rate` (append at the end of each choices tuple). When LFO 1's destination is `lfo2-rate`, LFO 1's output scaled by its depth modulates LFO 2's rate: `rate_eff = rate * 2 ** (depth * lfo_value * LFO_RATE_MOD_OCTAVES)` with `LFO_RATE_MOD_OCTAVES = 2.0`, clamped to `[0.01, 40.0]` Hz; symmetric for LFO 2 -> LFO 1. Evaluation order within a block: LFO 1 then LFO 2; each uses the other's value from the previous block when they modulate each other (no same-block feedback), so it is stable. Existing destinations behave exactly as before (bit-identical when the new choices are unused).

## Task M — Mod matrix (framework + sources + voice-level destinations)
Matrix: 8 rows, each `Source | Scale | Destination`; rows can be empty (Source "none" and/or Destination "none"). Parameters (registry, so patches and MIDI learn work): `mod{i}_src` (CHOICE), `mod{i}_amt` (CONTINUOUS -1..1, shown as -100%..+100%, default 0), `mod{i}_dst` (CHOICE), i = 1..8, group "Mod Matrix". Defaults: all "none"/0 — the default sound is unchanged and the factory matrix is EMPTY.

Sources (choice strings exactly): `none`, `Note Number`, `LFO 1`, `LFO 2`, `Mod Wheel`, `Aftertouch`.
- Note Number: `(note - 60) / 60` clipped to [-1, 1] (middle C = 0), evaluated PER VOICE for voice-level destinations; for global destinations the last played note is used.
- LFO 1 / LFO 2: the raw LFO output in [-1, 1] (independent of the LFO's own depth knob), evaluated once per block (block-centre value). An LFO referenced by any matrix row must run even when its depth is 0.
- Mod Wheel: CC 1 value / 127 in [0, 1]; Aftertouch: channel pressure / 127 in [0, 1]. The engine stores them (`set_mod_wheel`, `set_aftertouch`) and `MidiInput` updates them from the raw messages BEFORE the router can consume them (so a user binding of CC 1 or aftertouch still works as before and also feeds the matrix). Both are smoothed per block with a one-pole filter (`MOD_SMOOTH = 0.3`) to avoid zipper noise.
- The factory `Default` profile no longer binds CC 1 (remove it from `_DEFAULT_CCS`; profiles already saved keep their own bindings).

Scale semantics (owner's definition): the modulation is RELATIVE to the destination's CURRENT (base) value: `effective = base * (1 + sum_k(scale_k * source_k))`, then clamped to the destination's own range. So +/-100% means plus or minus the current amount times the percentage. Consequence to document in the UI tooltip and README: a destination whose current value is 0 stays 0 (e.g. Osc 2 Level at 0, PWM at 0, Resonance at 0), so those need a non-zero base value to be modulated. Several rows on the same destination add their percentage terms before multiplying.

Destinations (choice strings exactly, shown grouped in the combo with non-selectable section headers) -> registry param id:
- `Osc 1: Level` osc1_level; `Osc 1: PWM` osc1_pwm; `Osc 1: Sq Level` osc1_square_level
- `Osc 2: Level` osc2_level; `Osc 2: Tune` detune2_semitones; `Osc 2: Fine` detune2_cents; `Osc 2: PWM` osc2_pwm
- `Modulation Amount` fm_depth
- `Tempo` tempo_bpm
- `Filter: Cutoff` lpf_cutoff; `Filter: Resonance` lpf_resonance; `Filter: Env Amount` flt_env_amount; `Filter: Key Trk` flt_keytrack; `Filter: Vel>Cut` flt_vel
- `Filter Env: Attack/Decay/Sustain/Release` flt_attack/flt_decay/flt_sustain/flt_release
- `Amp Env: Attack/Decay/Sustain/Release` amp_attack/amp_decay/amp_sustain/amp_release
- `Chorus: Depth` fx_chorus_depth
- `Delay: Time` fx_delay_time; `Delay: Feedback` fx_delay_feedback; `Delay: Tone` fx_delay_damp
- `Reverb: Amount` fx_reverb_amount; `Reverb: Size` fx_reverb_size; `Reverb: Damping` fx_reverb_damp
- `Bitcrush: Crush` fx_bitcrush_amount
- `Unison: Detune` unison_detune; `Unison: Spread` unison_spread

Architecture rules:
- Modulation never overwrites base values: the user's/patch's base value stays in `engine.params` (or the effect's base store); modulation produces per-block effective values that the voices/effects use. Registry getters, patches and the GUI knobs always show/capture the BASE value.
- A pure `midi_synth/modmatrix.py` holds the destination table (name, param id, kind voice/global, min, max), the source list, and `effective(base, terms, lo, hi)`; the engine owns evaluation per block. Empty matrix (or all rows with scale 0 / none) => zero extra work and bit-identical output.
- Voice-level destinations (per voice, so Note Number can differ per voice): evaluated into a per-voice params view only when a row affects that voice (copy-on-write dict), passed to `Voice.render` as today.
- Global destinations (tempo, effects) are applied once per block to the live effect/tempo values and restored to the base value when no row modulates them any more.
- Matrix rows apply in addition to the LFO's own destination routing (they are independent).

GUI: a "Mod Matrix" group at row 1 (where LFO 2 used to be): 8 compact rows `[Source combo | horizontal bipolar scale slider with a "+37%" readout | Destination combo]`. A horizontal bipolar slider widget (-100%..+100%, centre = 0, double-click resets to 0) is needed. Controls keep MIDI-learn/context-menu support (compact `ParamControl` mode without the big title/badge, tooltip carrying the label). Window size hint <= 1700 x 900 (the body scrolls on smaller screens).

Task split (one commit each): L (above) -> M1 (framework, sources, GUI, the voice-level destinations Osc 1/2, Modulation Amount, Filter group incl. cutoff/resonance in voice AND master-bus mode) -> M2 (Filter Env / Amp Env ADSR per voice, Unison detune/spread live, Tempo) -> M3 (effect destinations incl. Delay Time with intra-block ramp smoothing so there is no zipper noise, base-value store so registry getters stay base) -> final review and README.
