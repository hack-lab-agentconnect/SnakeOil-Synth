# Stereo Output (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the signal path stereo from the effect chain onward (left/right chorus, stereo reverb, stereo delay with an optional ping-pong mode, per-channel bitcrusher), with a ping-pong toggle button under the Delay dial. Spec: `docs/superpowers/specs/2026-10-04-stereo-and-performance-scope.md` (Phase 2) plus the ping-pong request.

**Architecture:** Voices and the master-bus low-pass stay mono. The mono mix is duplicated into a `(2, n)` array at the start of the effect chain; every effect processes `(2, n)` blocks. **Key design rule: the LEFT channel must reproduce today's mono result exactly** (chorus left LFO phase = current; reverb left bank = current delays; delay and bitcrusher per channel), and the RIGHT channel differs (chorus LFO inverted, reverb right bank with +23-sample spread, ping-pong off by default). This lets us regression-test the left channel against the frozen mono references in `tests/reference_dsp.py`. `engine.render(n)` returns `(n, 2)` float32.

**Tech Stack:** Python 3.12, numpy, scipy, PySide6, pytest. Stay on branch `hpf-filter`. Baseline: 698 tests pass; `bench.py` shows all-effects at ~27% of budget.

**Conventions:** repo root, Git Bash, `.venv/Scripts/python.exe -m pytest ...`. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Do not edit `tests/reference_dsp.py` except where a task says so (adding new `Ref...` classes is allowed; never change existing ones).

---

### Task 1: Stereo effects in `midi_synth/effects.py`

**Files:** Modify `midi_synth/effects.py`; update `tests/test_golden_effects.py`, `tests/test_effect_dials.py` and any other effect tests; add new tests in `tests/test_stereo_effects.py`; may add `RefPingPongDelay` to `tests/reference_dsp.py`.

All effects: `process(x)` takes and returns a float64 array of shape `(2, n)` (row 0 = left, row 1 = right); disabled effects return the input unchanged. Keep every public setter/attribute that other code uses (`enabled`, `mix`, `set_depth`, `amount`, `depth`, `set_time_ms`, `time_ms`, `set_amount`, bits/downsample, etc.). Per-channel state becomes arrays (e.g. `buf` shape `(2, size)`, `filter` shape `(2,)`); the shared ring index `idx` and chorus `phase` stay scalars. Keep the chunking guard (blocks longer than the shortest dependency distance are split) and read-before-write ordering.

- [ ] **Chorus**: two delay lines. Left channel is exactly today's algorithm on `x[0]`; right channel is the same on `x[1]` with the LFO inverted (`delay_R = base - depth*sin(phase)`, i.e. a 180 degree offset). Same `phase`, `inc`, `depth`, `mix`, `feedback`.
- [ ] **Delay**: two ring buffers, shared delay time, per-channel one-pole damping state. Add `self.pingpong = False` and `set_pingpong(on)`. Normal mode: each channel is today's algorithm on its own input. Ping-pong mode (reference semantics, per sample, with `m = 0.5*(xL + xR)`): read `wetL` from the left buffer and `wetR` from the right buffer at the delay time; `filtL = damp-filter(wetL)`, `filtR = damp-filter(wetR)`; write `bufL[idx] = m + filtR*fb`, `bufR[idx] = filtL*fb`; output `outL = xL + wetL*mix`, `outR = xR + wetR*mix`. So the first echo lands left, the second right, the third left, and so on. Vectorise like the existing delay (delay time >> block, lfilter one-pole per channel). Add `RefPingPongDelay` to `tests/reference_dsp.py` as a plain per-sample loop of exactly these semantics for the golden test.
- [ ] **Reverb**: two banks. Bank L = today's delays (`1116, 1188, 1277, 1356, 1422, 1491` combs; `556, 441, 341` allpasses); bank R = every delay plus `23` samples (Freeverb stereo spread), all scaled by `sr/44100 * scale` like today. Left bank processes `x[0]`, right bank `x[1]` (per-channel input, no summing). `mix`, `room`, `damp`, `set_amount` shared. Chunk limit = shortest buffer across both banks.
- [ ] **Bitcrusher**: sample-and-hold with per-channel `hold` (array of 2) and one shared `counter`; same bits/downsample for both channels; keep `set_amount`.
- [ ] **EffectChain**: `process(x)` takes `(2, n)`; chain order and `enabled` handling unchanged; `get(name)` unchanged.
- [ ] Tests (write first): update the existing golden tests so each runs the new effect on a stereo input and compares **channel 0 against the existing `Ref*` class** processing `x[0]` (state attribute checks use channel 0 of the arrays; keep all tolerances 1e-9). Add `tests/test_stereo_effects.py` with: chorus right channel equals `RefChorus` processing `x[1]` with its LFO phase started at pi (set `ref.phase = pi` before processing; compare 8+ blocks, block sizes 64/256/300/700); delay normal mode both channels vs `RefDelay` per channel; ping-pong vs `RefPingPongDelay` (blocks 64/256/300; delay times 200/300/4000 ms), plus a behavioural test (impulse in the left channel at fb 0.5, mix 1: first echo energy is in the left output, second echo in the right, third in the left); reverb right channel vs a `RefReverb` whose combs/allpasses are rebuilt with delays + 23 (build it inside the test from `_RefComb`/`_RefAllpass`), sr 44100 and 48000, scales 1.0 and 0.5; bitcrusher both channels vs `RefBitcrusher` per channel; **stereo-ness**: with chorus enabled and identical L/R input the output channels differ; with all effects disabled the output equals the input; reverb with identical L/R input produces different L/R tails. Include the chunking-guard tests (blocks larger than the shortest delay) for the stereo versions.
- [ ] Run the full suite + `.venv/Scripts/python.exe bench.py` (the bench still drives `SynthEngine.render`, which Task 2 changes — if the engine isn't stereo yet, the bench must keep working: Task 1 may temporarily adapt `SynthEngine.render` minimally to wrap the mono mix as `(2, n)` into the chain and return channel 0 as before, so the engine API is unchanged until Task 2). Commit `Make the effect chain stereo (left/right chorus, stereo reverb, ping-pong delay)`.

---

### Task 2: Engine output, audio callback, render_demo, ping-pong control, GUI layout, docs

**Files:** Modify `midi_synth/engine.py`, `midi_synth/params.py`, `midi_synth/gui/main_window.py`, `run.py`, `render_demo.py`, `README.md`, `bench.py` (if needed); update tests that use `engine.render`.

- [ ] **Engine**: `render(n=None, apply_effects=True)` returns float32 shape `(n, 2)`: sum voices (mono), master-bus LPF (mono, as today), duplicate to `(2, n)`, effect chain if requested, `master_gain` and `np.tanh` per channel, then `np.ascontiguousarray(out.T).astype(np.float32)`. Add `set_delay_pingpong(on)` (locked, forwards to `effects.delay.set_pingpong`) and a `delay_pingpong` entry in `status()`. Remove the Task 1 temporary shim.
- [ ] **Registry**: add TOGGLE `fx_delay_pingpong` (label "Ping-pong", group "Effects", `under="fx_delay_time"`, tooltip "Bounce the echoes between the left and right speakers."), `get=lambda: engine.effects.delay.pingpong`, `set=engine.set_delay_pingpong`, registered right after the delay time dial.
- [ ] **GUI** (`main_window.py` `_build_body`): a param with `under=X` is placed in the same column as X at row `row(X) + 1` (generalising today's fixed row 1) so the Ping-pong button sits below the Delay dial (row 2). Nothing else about the layout changes. Update the GUI grid test to also assert ping-pong row > time row > toggle row in the same column.
- [ ] **Audio callback** (`run.py`): write the stereo block into the output: `outdata[:, :2] = block[:, :channels]` for 2+ channels; for 1 channel use the mean of L and R; extra channels beyond 2 are zeroed. Console: add `pingpong <on|off>` + help line. Anything else in `run.py` that assumes a mono block must be updated (grep for `render(`).
- [ ] **render_demo.py**: write a 2-channel 16-bit WAV (interleaved L/R); update its header/params and any helper that assumed mono.
- [ ] **Tests**: update every test that calls `engine.render(...)` and treats the result as 1-D: use channel 0 (`[:, 0]`) or the mean where mono is wanted (pitch/FFT tests, RMS tests, bit-identity tests). Add: render shape/dtype `(n, 2)` float32; with all effects off the two channels are identical; with chorus or reverb on they differ; ping-pong registry/engine round trip and default off; `status()` has `delay_pingpong`; callback behaviour for 1/2/4 channels if the callback is testable without audio (factor the block-copy into a small helper function in `run.py`, e.g. `copy_block_to_output(outdata, block)`, and unit-test it).
- [ ] README: document stereo output (chorus L/R, reverb spread, delay stereo + ping-pong button/console command), update the signal-flow diagram text if needed, the render_demo note (stereo WAV).
- [ ] Run full suite + `bench.py`; commit `Stereo output: (n, 2) engine render, ping-pong control and stereo render_demo`.

---

### Task 3: Verify

- [ ] End-to-end regression: render the same demo (`--seconds 3 --level2 0.8 --mode fm --fm 0.4 --tune2 7 --effects chorus,delay,reverb,bitcrush`) with the commit `7c9d40d` (mono, pre-stereo; use a temporary `git worktree`, remove it afterwards) and with the new code; the NEW left channel must equal the OLD mono samples (report max abs difference; expected 0 or <= 1 LSB), and report left-vs-right difference to prove the right channel is different.
- [ ] Run `bench.py`; report the table. The all-effects 12-voice case must stay under 50% of the budget; if it does not, report where the time goes (profile) instead of guessing.
- [ ] Full test suite. Report counts.
