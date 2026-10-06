# SnakeOil Synth VST3 plugin

C++ port of the Python reference synth (`midi_synth/`) as a VST3 instrument (plus a Standalone app) built on JUCE.
Design: `docs/superpowers/specs/2026-10-06-vst3-plugin-design.md`. Status: phase P0 (scaffold; outputs silence).

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

- `dsp/` - `snakeoil_dsp`, pure C++20 static library, no JUCE dependency.
- `src/` - JUCE wrapper: processor and editor.
- `tests/` - doctest unit tests (`snakeoil_tests`) and the golden harness stub (`golden_check`).
- `tools/` - build, test and install scripts.

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
