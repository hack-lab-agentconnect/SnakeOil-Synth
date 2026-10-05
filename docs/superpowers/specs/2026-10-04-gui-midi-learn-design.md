# GUI + MIDI Learn + Binding Profiles — Design

## Goal
Add a PySide6 GUI that controls every synth parameter, and a MIDI-learn system
so a hardware controller can drive the GUI. Bindings are stored in named,
switchable profiles saved as files.

## Non-goals
Recording MIDI to .mid/JSON, per-port bindings, MIDI-mapped note playing
changes, plugin/VST hosting.

## Architecture (all new code in `midi_synth/`, engine setters unchanged)

### `params.py` (no Qt)
Registry of controllable parameters. Each entry: `id`, `kind`
(`continuous` | `toggle` | `choice`), range/choices, `get()`, `set(value)`.
`set` calls the existing `SynthEngine` setters. Includes a
`from_midi(value_0_127)` mapping per entry (continuous -> range, toggle ->
>=64 edge-triggered, choice -> bucketed, same as today's `_waveform_from_cc` /
`_mode_from_cc`). Used by the GUI, the MIDI router and the console.

### `bindings.py` (no Qt)
- `Source`: `(channel, msg_type, number)` where msg_type is `cc` or `note`.
  Port-agnostic.
- `Profile`: name + `{Source -> param_id}`. `bind(source, param_id)` removes any
  existing binding of that source or that param (rebinding steals).
  `clear(param_id)`. `to_dict` / `from_dict`.
- `ProfileStore`: directory of `<name>.json` files plus `settings.json`
  holding the active profile name. Operations: `list`, `load`, `save`,
  `create` (blank), `duplicate`, `rename`, `delete`, `set_active`.
  Autosaves on every bind/clear. Corrupt files are skipped with a warning,
  never crash startup.
- Location: `%APPDATA%\midi-synth\` on Windows, `~/.config/midi-synth/`
  elsewhere; override with `--config-dir`. Profile files are plain JSON
  (users can copy/share them to import/export).
- First run seeds a `Default` profile with the current hard-coded map
  (CC1 mod, 7 volume, 20-23 effects, 24/25 waves, 26/27 tuning, 28/29 levels,
  30 mode). `Default` can be reset to factory but not deleted; the last
  remaining profile cannot be deleted.

### `midi_router.py`
`MidiInput` keeps note / pitch-bend / program-change handling. Control
changes (and notes, when a note-bound toggle exists or learn is armed) go to
the router:
- **Learn armed** for a param -> bind the message's source to it, disarm,
  emit `learned`.
- Otherwise -> look up the active profile, convert the value via the
  param's `from_midi`, call `set`, emit `param_changed`.
Notes bound to a param are consumed instead of played. Router emits a
`last_message` signal for the footer readout. Runs on the rtmidi thread;
GUI updates go through Qt signals (queued to the GUI thread).

### `gui/`
- `knob.py`: custom rotary knob widget (drag/scroll, double-click reset).
- `main_window.py`: sections Osc 1, Osc 2 (waveform, level, coarse, fine),
  Modulation (mode, amount), Effects (4 toggles), Master (gain).
  Toolbar: profile dropdown + New / Duplicate / Rename / Delete, and a
  **MIDI Learn** toggle. Footer: MIDI port(s), active voices, last message.
- Each control is a thin wrapper over a registry entry; updates from MIDI
  block widget signals to avoid echo loops.

### Learn flow
Right-click a control -> **Learn** (or enable MIDI Learn mode and click
controls). Control pulses "Move a control...". Next CC (or note, for toggles)
is bound and the control shows its binding (e.g. `CC 74 ch1`). Esc cancels.
Right-click -> **Clear** removes it. Switching profile swaps the map live;
binding badges refresh.

## Launch
`python run.py` opens the GUI by default. `--no-gui` keeps the console.
Existing audio/MIDI flags unchanged. Add `--profile NAME` and
`--config-dir PATH`. `PySide6` added to `requirements.txt`.

## Error handling
Missing/invalid profile JSON -> skipped, warning in status bar. Unknown
param ids in a profile -> ignored on load, preserved on save. MIDI
unavailable -> GUI still opens, footer says so.

## Testing
- Unit: `Profile` bind/steal/clear, `ProfileStore` create/duplicate/rename/
  delete/active/corrupt-file handling (temp dirs), `from_midi` mappings.
- Router: fake messages -> engine params; learn arm/bind/cancel.
- GUI: offscreen smoke test (`QT_QPA_PLATFORM=offscreen`), plus a manual
  run with screenshot to check layout.
