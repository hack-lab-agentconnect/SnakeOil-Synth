# Stereo Output + Performance — Scope

Status: scoping only, nothing implemented. Measured on the dev machine
(48 kHz, 256-sample block, 12 voices held, budget 5.33 ms/block).

## Why performance comes first
Current cost at the new defaults (saw + square layer, per-voice LPF at 2 kHz):

| Case | ms/block | % of budget |
|---|---|---|
| defaults, no effects | 3.57 | 67% |
| LPF master-bus or off | 2.9 | 55% |
| + reverb | 5.28 | 99% |
| + all four effects | 6.89 | **129%** (underruns) |

Profile with all effects on (shares of total): voices incl. LPF 45%
(pulse/PolyBLEP ~20%, LPF ~8%, envelope ~6%), reverb 33%, bitcrush 11%,
chorus 6%, delay 4%. The effects and the filter are per-sample pure-Python
loops. Making the signal stereo as the code stands would roughly double the
effect cost (~+0.8 ms) and push every effects-on case past budget.

## Phase 1 — speed up, sound unchanged (prerequisite)
Add `scipy` (`scipy.signal.lfilter`, C-speed IIR with carried state, ~36 MB wheel).
1. Vectorise with numpy/lfilter, using the fact that every delay line (reverb
   combs 1116+, allpasses 341+, delay >= 200 ms, chorus base 14 ms) is longer
   than one block, so a block never reads what it just wrote:
   reverb, delay, chorus, bitcrusher (all effects), voice LPF biquad.
2. Voices: vectorise the ADSR envelope; skip osc2 entirely while `osc2_level == 0`
   (the default) in modes that don't need it; make PolyBLEP touch only the
   few samples near an edge.
3. Guard with golden tests: render the old implementation vs the new one on
   fixed input and require near-identical output (tolerance ~1e-6) before
   deleting the old code.
Expected: all-effects/12-voice case from ~129% to roughly 50-60% (estimate).
Optional later: batch all voices as 2-D arrays (bigger rewrite, further ~2x).
Stopgap available today with no code: LPF "Master-bus filter" toggle (-0.65 ms).

## Phase 2 — stereo
- Engine renders `(n, 2)`; output callback writes both channels from it;
  `render_demo` writes a stereo WAV; voices stay mono (no per-voice pan).
- Chorus: two modulated delay taps with LFOs 180 degrees apart (L/R) — the
  main fix for the "wobbly" sound. Depth dial unchanged.
- Reverb: Freeverb-style second comb/allpass bank with offset delays for R.
- Delay: stereo (same time both sides; optional ping-pong later).
- Bitcrusher, master gain and tanh run per channel.
- API: `engine.render()` returns stereo; tests that FFT/RMS the mono signal
  take channel 0 or the mean.
- No new GUI controls required.
- Cost after Phase 1: effects ~2x of a small number; negligible.

## Decisions needed
1. OK to add `scipy` as a dependency? (Alternative: numba, much heavier.)
2. Do Phase 1 as its own branch/commit series first, then Phase 2? (Recommended.)
3. Default LPF placement while performance is tight: keep "per voice" or
   default to master-bus until Phase 1 lands?
