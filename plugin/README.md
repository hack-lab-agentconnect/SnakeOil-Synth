# SnakeOil Synth VST3 plugin

C++ port of the Python reference synth (`midi_synth/`) as a VST3 instrument (plus a Standalone app) built on JUCE.
Design: `docs/superpowers/specs/2026-10-06-vst3-plugin-design.md`. Status: phases P1-P5 complete and P6 partly -
the JUCE shell runs a DSP core that matches the Python reference bit-for-bit across 42 golden scenarios: oscillators
(saw + square layer, PWM, fm/am/ring/sync), envelopes, filter env/key-tracking/velocity, 12/24 dB filters + whistle,
glide, LFOs, unison, noise, limiter, stereo effects (chorus, ping-pong delay, reverb, bitcrush), the mod matrix,
hybrid voice allocation with tail slots, and host-tempo-synced delay. A custom editor drives every parameter with
output meters. Remaining: the P6 real-time-safety pass (the engine still looks parameters up by string each block),
and P7 (CLAP/macOS/installer). The JUCE plugin build is not compiled in the development sandbox (no
CMake/JUCE/system headers); only the no-JUCE DSP, golden harness and self-test are built there.

## Build, test, install (Windows, no admin)

Requires Visual Studio 2026 Community (MSVC). The scripts load the MSVC environment and use the CMake and Ninja
bundled with Visual Studio. Run from the repo root in `cmd` or Git Bash:

    plugin\tools\build.bat            # configure + build Release into plugin\build\Release
    plugin\tools\build.bat debug      # Debug build into plugin\build\Debug
    plugin\tools\test.bat             # run CTest
    plugin\tools\install_vst3.bat     # copy the bundle to %LOCALAPPDATA%\Programs\Common\VST3

The first configure fetches JUCE and doctest from GitHub (needs network; sources land in `plugin\build`).

Outputs: `plugin\build\Release\SnakeOilSynth_artefacts\Release\VST3\SnakeOil Synth.vst3` and
`...\Standalone\SnakeOil Synth.exe`.

## Layout

- `dsp/` - `snakeoil_dsp`, pure C++20 DSP with no JUCE dependency (header-only):
  `oscillator.hpp`, `envelope.hpp`, `biquad.hpp`, `voice.hpp`, `engine.hpp`.
- `src/` - JUCE wrapper: processor and editor.
- `tests/` - doctest unit tests (`snakeoil_tests`) and the golden harness (`golden_check`).
- `tools/` - build, test and install scripts.

## Golden sound lock

`golden_check <scenario.json> <expected.f32>` replays a scenario and compares the
rendered audio with the Python reference within 1e-6 absolute. `ctest` runs the
`default` scenario. Regenerate the scenario and expected audio after an
intentional sound change:

    python tools/export_cpp_golden.py default

`tools/export_params.py` writes `plugin/params.json` (the parameter registry) for
the generated parameter layout in P2.

## Host setup

- REAPER: Options > Preferences > Plug-ins > VST. Add `%LOCALAPPDATA%\Programs\Common\VST3` to the VST plug-in
  paths if it is not scanned, then Re-scan.
- Cakewalk Sonar: Preferences > Audio > Plug-in Manager. Add the same path to the scan paths and rescan.

## Phases

P0 scaffolding and toolchain; P1 DSP core and golden harness; P2 plugin v1 (parameters, MIDI, generic editor);
P3 sound-shaping parity; P4 mod matrix, tempo sync, voice allocation, meters; P5 custom editor and presets;
P6 hardening and validation; P7 optional CLAP, macOS, installer.

## Licensing

JUCE is AGPL-3.0 or commercial. Read its license before distributing any binary.
