# SnakeOil Synth VST3 Plugin — Design

Status: approved by the owner in chat (2026-10-06). The Python app (package `midi_synth`) is feature-complete and is the **reference implementation**; the plugin is a C++ port that must match it.

## Decisions (owner)
- Formats: VST3 first. CLAP later (maybe) via a wrapper from the same code. VST2 is off the table (Steinberg no longer licenses it).
- Platform: Windows first; keep the code portable (macOS/Linux later only if wanted).
- Toolchain: Visual Studio Community 2026 (MSVC 14.51, bundled CMake 4.3.x and Ninja). Hosts for testing: **REAPER** and **Cakewalk Sonar**.
- Location: `plugin/` folder inside this repo (shares golden data and the parameter registry with the Python reference).
- Name: **SnakeOil Synth**. Vendor/company string and VST3 IDs: placeholders until the owner decides (`SnakeOil`).
- The Python app stays the reference; the plugin must reproduce its sound.

## Architecture
- **JUCE** (fetched by CMake FetchContent at a pinned tag, shallow clone) for the plugin shell: AudioProcessor, parameter tree, state save/load, editor. License note: JUCE is AGPL-3.0 or commercial; the JUCE license file in the fetched sources must be read and reported to the owner before any binary is distributed (local development is fine).
- `plugin/dsp/` — **`snakeoil_dsp`**, a static library of pure C++20 DSP with NO JUCE dependency: oscillators (PolyBLEP saw / pulse / top-aligned pulse layer), envelopes, biquad low-pass (12 dB) and Moog-style 4-pole (24 dB) + whistle, noise tables, LFOs, voices, voice allocation (playable voices + tail slots), effects (chorus, delay, ping-pong, reverb, bitcrusher), auto limiter, level meter peaks, mod matrix, tempo helpers. Real-time safe: no allocation, locks, exceptions or I/O on the audio thread. `double` precision while matching the reference; optimise to `float` later only if profiling says so.
- `plugin/src/` — JUCE wrapper: processor, parameter layout generated from the registry, MIDI handling, host tempo (`AudioPlayHead`), editor.
- `plugin/tests/` — unit tests (doctest or Catch2) and the **golden harness**: replays language-neutral scenario files and compares against expected audio exported from the Python engine.
- `tools/` (Python) — exporters: `export_params.py` (registry -> `plugin/params.json`: id, label, group, kind, range, scale, default, choices, formatter hints) and `export_cpp_golden.py` (scenario JSON + expected raw float32 audio rendered by the Python engine through `registry.set`).

## What carries over / what does not
- Carries over: signal flow, algorithms, parameter ids/ranges/defaults/scales, mod-matrix semantics (relative scaling), voice allocation (12 playable + tail slots, forced 10 ms releases), the golden-test approach.
- Replaced by the host: MIDI learn, profiles, QWERTY keys, recording, MIDI clock (use host tempo/transport), console, config files, patches (-> host presets / plugin state).
- Plugin-specific work: parameter automation + smoothing, state save/restore (versioned), sample-rate and block-size changes, denormal protection, bypass, MIDI (note on/off, pitch bend, mod wheel CC1, aftertouch, sustain CC64, all-notes-off), editor.

## Matching the reference
Scenarios are language-neutral JSON: `{"sample_rate", "block_size", "events": [{"block": n, "set": {"param_id": value, ...}, "note_on": [note, velocity], "note_off": [note], ...}], "blocks": N}`; expected output is raw float32 stereo. The Python exporter drives the Python engine only through `registry.set` + engine note methods so the C++ harness can drive the same things by parameter id. Tolerance target: 1e-6 absolute in double (relax per scenario only with a written reason). Stateful pieces with randomness (random unison phases, noise start positions, random LFO) must use the same seeded generators as Python, or be exported as data (noise tables as raw files).

## Phases (one commit/PR-sized task each, always on `main`)
- **P0** Scaffolding and toolchain: `plugin/CMakeLists.txt`, JUCE pinned, build scripts, a do-nothing instrument that builds to VST3 + Standalone, installs to the per-user VST3 folder, DSP library + test harness skeleton, CTest green. Manual check: REAPER and Sonar see the plugin.
- **P1** DSP core + harness: oscillators, envelope, 12 dB filter, voice, minimal engine, master gain + tanh. Scenario "default" matches the Python golden within 1e-6.
- **P2** Plugin v1: generated parameters, MIDI, generic editor, audio in REAPER/Sonar; automation smoothing.
- **P3** Sound-shaping parity: osc2/FM modes, noise, filter envelope/key tracking/velocity, 24 dB ladder + whistle, LFO 1/2 (incl. random-glide, cross-mod), glide, unison, effects (chorus, delay, ping-pong, reverb, bitcrusher), limiter; "busy" scenario matches.
- **P4** Mod matrix, tempo sync (host tempo), hybrid voice allocation with tail slots, meters.
- **P5** Editor (custom JUCE UI), presets/state versioning.
- **P6** Hardening: real-time safety audit, denormals, SR/block-size matrix tests, plugin validation (pluginval, with the owner's permission to download it), performance profiling.
- **P7** Optional: CLAP, macOS, installer.

## Conventions
- Work on `main`, one commit per task, never push without being asked (the owner has been asking explicitly each time).
- C++20, warnings as errors on our code, no exceptions on the audio thread, no `new`/`malloc` in `process`.
- Build output lives in `plugin/build/` (git-ignored). Third-party sources are fetched, never committed.
