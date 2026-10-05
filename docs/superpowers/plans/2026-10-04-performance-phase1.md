# Performance Phase 1 Implementation Plan (sound unchanged)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Cut per-block CPU so 12 voices plus all four effects fit comfortably in the audio budget, with output numerically unchanged (this is the prerequisite for stereo; see `docs/superpowers/specs/2026-10-04-stereo-and-performance-scope.md`).

**Architecture:** Replace per-sample Python loops with block-wise numpy / `scipy.signal.lfilter`. This is valid because every delay line (reverb combs >= 1116 samples, allpasses >= 341, delay >= 200 ms, chorus >= 6 ms) is longer than a block, so a block never reads what it just wrote; each effect splits oversized blocks into chunks no longer than its shortest delay so any `--blocksize` stays correct. Old implementations are frozen as test-only reference code and every new implementation must match them.

**Tech Stack:** Python 3.12, numpy, scipy (`signal.lfilter`), pytest. Branch: `hpf-filter` (stay on it). Baseline: 169 tests pass; bench `bench.py` is added in Task 1.

**Conventions:** repo root, Git Bash, `.venv/Scripts/python.exe -m pytest ...`. Never delete an old implementation until its golden test passes. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

---

### Task 1: scipy, benchmark script, frozen reference implementations

**Files:** Modify `requirements.txt`; Create `bench.py`, `tests/reference_dsp.py`, `tests/test_reference_dsp.py`.

- [ ] Add `scipy>=1.11` to `requirements.txt`; `pip install -r requirements-dev.txt`; verify `from scipy.signal import lfilter`.
- [ ] Create `bench.py` (repo root): builds `SynthEngine(sr=48000, block_size=256, max_voices=12)`, holds notes 48-59, renders 300 blocks and prints ms/block and % of the block budget for these cases: defaults; osc2 audible (level 1, fm); LPF off (`set_lpf_cutoff(20000)`); LPF master mode; each effect alone; all four effects. Accept `--sr`, `--block`, `--blocks`. (Model it on `/tmp/bench4.py` logic: same case list.) Run it and save the "before" table into the commit message body.
- [ ] Create `tests/reference_dsp.py`: a VERBATIM, test-only snapshot of the current implementations, renamed with a `Ref` prefix so they keep working after the production code changes. Get the exact code with `git show HEAD:midi_synth/effects.py`, `...filters.py`, `...voice.py`, `...oscillators.py`. Contents: `RefChorus`, `RefDelay`, `_RefComb`, `_RefAllpass`, `RefReverb`, `RefBitcrusher` (from effects.py incl. `CHORUS_MAX_DEPTH_MS`, `TWO_PI`); `RefLowPass` (+ import `lpf_coefficients` from production `midi_synth.filters` — coefficient math does not change); `RefEnvelope` (+ stage constants); `ref_poly_blep`, `ref_saw_wave`, `ref_pulse_wave`, `RefOscillator`; `RefVoice` (copy of `Voice` using the Ref components; it needs `midi_note_to_freq`/`semitones_to_ratio` which may be imported from production `midi_synth.voice`). Add a header comment: frozen copy of the pre-optimisation implementation used as the golden reference; do not edit.
- [ ] Create `tests/test_reference_dsp.py` with smoke tests proving the references run (each effect/filter/envelope/voice processes a block and returns finite output of the right length) and that `RefVoice` and the current production `Voice` produce identical output for a few param sets (this proves the snapshot is faithful at this commit).
- [ ] Run full suite; commit `Add scipy, benchmark script and frozen reference DSP for regression tests`.

---

### Task 2: Voice path — LowPass via lfilter, vectorised envelope, cheaper oscillators, skip silent osc2

**Files:** Modify `midi_synth/filters.py`, `midi_synth/voice.py`, `midi_synth/oscillators.py`; Create `tests/test_golden_voice.py`.

Specs (golden tests first, see them pass against the OLD code only where they test the reference-vs-reference harness, then fail/pass as appropriate; the key requirement is that new code matches the reference):

- [ ] **LowPass.process** — keep the class/API (`z1`, `z2`, `reset`, `process(x, coeffs)`); implement with `scipy.signal.lfilter([b0, b1, b2], [1.0, a1, a2], x, zi=[z1, z2])` and store the returned `zf` back into `z1, z2` (scipy's direct-form-II-transposed state equals ours). Return float64 ndarray. Golden: random noise and a sine, several consecutive blocks of sizes 64/128/256/300, coefficient changes between blocks, vs `RefLowPass`; tolerance `1e-9`.
- [ ] **Envelope.process** — vectorise per stage segment instead of per sample. Output must match `RefEnvelope` within `1e-12` for: full ADSR in one block, stages boundary falling inside a block, note_off during attack/decay/sustain, retrigger from a non-zero level, very short attack/decay/release (1 sample), sustain 0 and 1, blocks of 1/7/256/4096. Use `np.cumsum` over a constant-increment array (first element `level + inc`) so the accumulation matches the old repeated `+=` bit for bit; find the first sample crossing the stage threshold with `np.argmax`/`searchsorted`; stage transitions must behave exactly like the old loop (the sample that reaches the threshold already outputs the clamped value and the NEXT sample is in the next stage; sustain outputs `sustain` constant; release ends at 0.0 -> IDLE). Keep `level`, `stage`, `active`, `note_on`, `note_off`, `set_shape` as is.
- [ ] **PolyBLEP** — replace the masked version with the branch-free equivalent `a = np.maximum(1.0 - t / d, 0.0); b = np.maximum(1.0 + (t - 1.0) / d, 0.0); return b*b - a*a` (with `d = max(dt, 1e-9)`); equal to the old function for `dt <= 0.5`. Golden vs `ref_poly_blep` over t in [0,1) and dt in {1e-4, 0.01, 0.1, 0.45}, tol `1e-12`.
- [ ] **Shared edge computation** — `Oscillator._shape` for the saw+square layer must compute `blep(t)` once and reuse it for the saw and the pulse's rising edge (`saw = 2t-1-b0`; pulse uses `b0` and `blep(mod(t - duty, 1))`); `pulse_wave` standalone stays available with identical results. Golden vs `ref_saw_wave`/`ref_pulse_wave` and the layered output `LAYER_GAIN * (saw + pulse)` for duty in {0.0 (clamped), 0.1, 0.25, 0.5}, tol `1e-12`.
- [ ] **Skip silent osc2** in `Voice.render`: when `params["osc2_level"] == 0.0`, do not compute osc2's waveform (`sec`); still advance `self.osc2.phase` by `f2/sr*n` (mod 1) so phase continuity matches the old behaviour exactly; the mix is `osc1_level*mod` (plus `osc2_level*sec` only when level > 0). Output must be identical to `RefVoice` for osc2_level = 0 in all modulation modes (off/fm/am/ring/sync), and after raising the level mid-note the next blocks must still match `RefVoice` (phase continuity).
- [ ] Voice-level golden test (`tests/test_golden_voice.py`): `Voice` vs `RefVoice` for ~40 random-but-seeded parameter sets (all mod modes, octave switches, layer on/off, PWM in [0,0.5], LPF on/off/various cutoffs/resonances, osc levels incl. 0, detune, pitch bend, velocity), rendering 6+ consecutive blocks including a `note_off` in the middle, tol `1e-9`.
- [ ] Run the full suite + `.venv/Scripts/python.exe bench.py`; commit `Vectorise the voice path: lfilter low-pass, envelope, PolyBLEP; skip silent osc2` with the before/after table for the "defaults" and "LPF" cases.

---

### Task 3: Effects — vectorised Delay, Chorus, Bitcrusher, Reverb

**Files:** Modify `midi_synth/effects.py`; Create `tests/test_golden_effects.py`.

Shared rules: each `process(x)` keeps its signature, enabled-bypass, parameter attributes and state attributes (`idx`, `phase`, `filter`, `hold`, `counter`, buffers) so setters and existing tests keep working. Add a helper that splits an oversized block into chunks no longer than the effect's shortest dependency distance (Delay: `int(min delay samples)`; Chorus: `int(base - depth) - 2` (>= 1); Reverb: the shortest comb/allpass buffer length) and processes them sequentially, so any `--blocksize` is correct. Ring-buffer reads/writes use index arrays with wrap: `buf.take(np.arange(idx, idx + n), mode='wrap')` and `np.put(buf, np.arange(idx, idx + n), vals, mode='wrap')`; always READ before WRITE within a chunk.

- [ ] **Delay**: positions `pos = (idx + arange(n) - delay) mod size` (float), `i0 = floor`, `frac`, `i1 = (i0+1) mod size`, `wet = buf[i0]*(1-frac) + buf[i1]*frac`; damping `filt` is the one-pole `y[i] = (1-damp)*wet[i] + damp*y[i-1]` = `lfilter([1-damp], [1, -damp], wet, zi=[damp*filt_prev])` (store `filt = y[-1]`); write `buf[idx..idx+n-1] = x + filt*fb`; `out = x + wet*mix`; advance `idx`. Golden vs `RefDelay`.
- [ ] **Chorus**: `phases = phase + inc*arange(n)`, `delay = base + depth*sin(phases)`, `pos = (idx + arange(n) - delay) mod size`, same interpolation, `wet`, write `x + wet*fb`, `out = x + wet*mix`; `phase` wraps like the old code (`phase` kept in [0, 2pi) via mod after the block). Golden vs `RefChorus` including depth changes between blocks and depth 0/1.
- [ ] **Bitcrusher**: sample-and-hold with persistent `hold`/`counter`: refresh indices `first = counter (0 if counter<=0)`, `first, first+down, ...< n`; held source index via `np.maximum.accumulate` of a marker array (use previous `hold` where no refresh yet); `levels = float(2 ** max(int(bits), 1))`, `np.round(held*levels)/levels` (vectorised round-half-even, same as old); update `hold = held[-1]` source value (the un-quantised held sample) and `counter = counter_end` where, with last refresh index `L`, `counter_end = down - n + L` (no refresh in block: `counter - n`). Golden vs `RefBitcrusher` for downsample 1..8, bits 2..16, block sizes 1/7/64/256, state carry over many blocks.
- [ ] **Reverb**: each comb: `y = ring read of n`, damping one-pole via `lfilter` on `y` with state `filter`, write `x + filt*fb`; output = mean of the 6 comb outputs (`inv`), then the 3 allpasses in series: `y = ring read of n`, write `x_in + y*fb`, `out = y - x_in`; final `xi + s*mix`. Golden vs `RefReverb` (default and non-default room/damp/mix, `scale` != 1.0, sr 44100 and 48000), consecutive blocks, block sizes 64/256/300/700 (700 exercises chunking).
- [ ] Golden tests: noise AND realistic signal (a decaying saw burst) as input, 8+ consecutive blocks, tolerance `1e-9` absolute; plus enabling/disabling an effect between blocks behaves as before.
- [ ] Remove nothing from `tests/reference_dsp.py`. Delete the old per-sample loops from `effects.py` only after the golden tests pass.
- [ ] Run full suite + `bench.py`; commit `Vectorise delay, chorus, bitcrusher and reverb` with the before/after table.

---

### Task 4: Verify and document

- [ ] Run `.venv/Scripts/python.exe bench.py` (record the full table), the full test suite, and an end-to-end sanity check: `render_demo.py` writes a WAV (compare it against the output of the commit before Task 1: check out that commit's `render_demo.py` + package into a temp worktree, render the same demo, and report the max abs sample difference, expected < 1e-6).
- [ ] README: add a short "Performance" note (`bench.py`, scipy dependency).
- [ ] Commit `Document performance work and benchmark`.
