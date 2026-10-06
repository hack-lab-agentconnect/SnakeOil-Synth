# midi-synth

Python MIDI synth. Built by Jilly @ Hackers In The Loop

A real-time Python MIDI synthesizer. It listens to **any** MIDI input device, plays
the notes it receives, and runs them through a dual-oscillator voice engine plus a
toggleable effects chain.

## Features

- **MIDI input** from all connected ports (or a named port / single channel), up to
  **12 simultaneous notes**, pitch bend, velocity (can be switched off), sustain pedal,
  channel aftertouch and MIDI clock.
- **Two oscillators** (band-limited with PolyBLEP): osc 1 is a saw with an optional square
  layer (on by default); osc 2 is a square. Both squares have **PWM** (0-0.5, 0.5 = plain
  square; default 0 = narrowest pulse). Osc 1's square layer is Juno-style: the pulse is
  derived from the same ramp as the saw, high at the top of the rising ramp, and added on
  top of the untouched saw at the **Sq Level** (0-1, default 0.5). It adds loudness, more as
  PWM widens (PWM 0 is a thin spike that adds little level). Osc 2 has **coarse** (-12..+12 semitones) and
  **fine** (+/-0.5 cents) tuning. **Octave switches:** osc 1 one octave down, osc 2 one
  octave up (on by default).
- **Modulation modes** (osc 1 -> osc 2): off, FM (phase modulation), AM, ring and hard sync,
  with one amount control. See [Modulation modes](#modulation-modes-osc1---osc2).
- **Resonant 12 dB/oct low-pass filter** (cutoff + resonance, 2000 Hz by default, 20 kHz =
  bypass), per voice or on the master bus, with a **filter envelope** (ADSR + amount),
  **key tracking** and **velocity-to-cutoff**.
- **Amp envelope** (ADSR) per voice.
- Two **LFOs** (sine, triangle, saw, square, random, random-glide) to pitch, filter, pulse width or volume,
  and **glide** (portamento, optionally legato only).
- **Unison:** up to 12 stacked voices per note with detune and stereo spread.
- **Stereo effects chain:** chorus, delay (with **ping-pong**, feedback, tone and
  **tempo sync** to MIDI clock or a manual BPM), reverb (size, damping) and bitcrush.
- **Patches** (saved sounds), **MIDI-learn profiles**, a **QWERTY keyboard** for playing
  without a MIDI device, and **WAV recording** of the output.
- A Qt GUI and an interactive console that expose the same parameters.

## GUI overview

The window is one scrollable body (so it also fits small screens) between two fixed toolbar
rows and a status bar. The toolbars hold the profile box with New / Duplicate / Rename /
Delete / Reset, *MIDI Learn*, *QWERTY keys* and *Rec* on the first row, and the patch box
with Save / Save As / Rename / Delete on the second. The status bar shows the MIDI ports, the
last MIDI message, active voices, the QWERTY octave and velocity, and the recording time.

The groups sit on a grid:

| | Col 1 | Col 2 | Col 3 | Col 4 | Col 5 |
|---|---|---|---|---|---|
| Row 1 | Oscillator 1 | Oscillator 2 | Modulation | Master (volume, velocity, level meter) | Tempo |
| Row 2 | Filter (incl. env amount, key track, velocity) | Filter Env | Amp Envelope | LFO (LFO 1 and LFO 2 side by side) | Mod Matrix |
| Row 3 | Effects (spans columns 1-3) | | | Unison | Glide |

The *LFO* box holds two vertical stacks side by side, *LFO 1* and *LFO 2*, each with Rate, Depth, Wave
and Dest from top to bottom under its header. The *Mod Matrix* box (row 2, column 5) is described
under [Mod Matrix](#mod-matrix).

In *Effects* every toggle (Chorus, Delay, Reverb, Bitcrush) heads a block with its dials in
a row beneath it: Chorus has Depth; Delay has Time, Ping-pong, Feedback, Tone, Sync and
Division; Reverb has Amount, Size and Damping; Bitcrush has Crush. Long control names are
shortened in the window and shown in full as a tooltip.

Feedback (0.35), Tone (0.25), Size (0.84) and Damping (0.25) default to the values the
effects had before these dials existed. The effect dials have no default MIDI CC; use MIDI
Learn to bind them. They are saved in patches.

## Install

```bash
python -m venv .venv && . .venv/bin/activate      # optional
pip install -r requirements.txt       # includes PySide6 for the GUI
pip install -r requirements-dev.txt   # also installs test dependencies
```

Or install it as a package (`requirements.txt` / `requirements-dev.txt` remain
the pinned-minimum dependency lists and keep working):

```bash
pip install .            # installs the package and its dependencies
pip install -e .[dev]    # editable install plus pytest, for development
```

This provides two console scripts, `midi-synth` (same as `python run.py`) and
`midi-synth-render` (same as `python render_demo.py`).

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs the test suite on
Windows and Ubuntu with Python 3.12 for pushes to `main` and for pull requests.
It could not be run locally, so it is unverified until it has run on GitHub.

On Linux the PortAudio system library is also required:

```bash
sudo apt install libportaudio2
```

(macOS/Windows wheels bundle PortAudio.)

## Run

```bash
python run.py --list            # list MIDI inputs, host APIs and audio outputs
python run.py                   # listen on all MIDI ports, auto-pick the lowest-latency output
python run.py --input "Launchkey" --channel 1
python run.py --lpf-mode master # one low-pass filter on the whole mix instead of one per voice
```

`--lpf-mode voice|master` picks where the low-pass filter sits. `voice` (default)
filters each note separately; `master` is lighter on the CPU if audio glitches.

`--channel` takes 1-16 (the channel filter is one-based).

## GUI and MIDI learn

The window opens by default; use `--no-gui` for the console only.

- **Learn a binding:** right-click a control and choose *MIDI Learn*, or toggle the
  *MIDI Learn* toolbar button and click controls. Then move a knob or press a button
  on your controller. Press `Esc` to cancel. Toggles can also be learned from a note.
  Right-click -> *Clear binding* removes it.
- **Profiles:** the toolbar has New, Duplicate, Rename, Delete and Reset. Bindings
  autosave to the active profile.
- **Files:** profiles are `*.json` files in `%APPDATA%\midi-synth\profiles\` on Windows
  (`~/.config/midi-synth/profiles/` elsewhere). Copy the files to share them.
- `--profile NAME` starts with a given profile; `--config-dir PATH` uses another
  config directory.

## QWERTY keyboard

The **QWERTY keys** toolbar button (on by default) plays notes from the computer keyboard,
with no MIDI device needed. The status bar shows the current octave and velocity
(`Oct +0  Vel 100`).

| Keys | Action |
| --- | --- |
| `A W S E D F T G Y H U J K O L P ;` | Chromatic notes from C of the current octave (C4 = MIDI 60 at octave +0): C, C#, D, D#, E, F, F#, G, G#, A, A#, B, C, C#, D, D#, E |
| `Z` / `X` | Octave down / up (range -3 to +3) |
| `C` / `V` | Velocity -10 / +10 (default 100, range 10-127) |

Held keys keep sounding until released, and a key always releases the note it started even
if you changed octave meanwhile. Auto-repeat, keys pressed with Ctrl, Alt or Meta, and keys
typed into a text box or number field are ignored. All keyboard notes are released when the
window loses focus or the button is switched off.

## Recording

The **Rec** toolbar button records the synth output to a 16-bit stereo WAV file (at the
engine's sample rate) in `recordings/synth-YYYYmmdd-HHMMSS.wav` inside the config directory
(next to `profiles/` and `patches/`). The status bar shows the file path and the elapsed
time while recording, and "Saved <path>" when you stop. Recording runs on a background
thread; if the disk cannot keep up, blocks are dropped rather than glitching the audio.

Console: `rec start [path]` starts recording (to `path`, or to a timestamped file in the
recordings folder), and `rec stop` finishes the file.

## Patches

A patch is a saved sound: every knob, slider and switch except master volume.

- **GUI:** the second toolbar row has a *Patch* box (choosing one loads it at once) and
  Save, Save As..., Rename and Delete. A `*` after the name means you changed something
  since loading or saving. `Init` is the factory sound: it is read-only (Save is
  disabled, and it cannot be renamed or deleted); use Save As... to keep a variation.
- **Console:** `patch list`, `patch save <name>`, `patch load <name>`,
  `patch delete <name>`.
- **Startup:** `--patch NAME` loads a patch before the window opens; otherwise the last
  used patch is loaded. An unreadable patch prints a warning and the factory sound is used.
- **Files:** `patches/<name>.json` in the config directory (next to `profiles/`), plus
  `patch_settings.json` for the last used patch. Each file holds `{"version", "name",
  "params"}`. Parameters missing from a file load at their factory value, so older patches
  keep working when new controls are added; files from a newer version are refused.

## Amp envelope (ADSR)

The *Amp Envelope* group (row 2 of the window) has four vertical sliders that shape
the volume of every note:

| Slider | Range | Scale | Default |
|---|---|---|---|
| Attack | 1 ms - 5 s | log | 6 ms |
| Decay | 1 ms - 5 s | log | 120 ms |
| Sustain | 0 - 1 | linear | 0.75 |
| Release | 1 ms - 10 s | log | 180 ms |

Changes apply to notes that are already sounding as well as to new notes. Double-click
a slider to restore its default. The console command `adsr <attack_s> <decay_s> <sustain>
<release_s>` sets all four at once (out-of-range values are clamped). The sliders have no
default MIDI CC; assign them with MIDI learn.

## Level meter

The *Master* group has a stereo output meter beside the Volume knob. It shows the left and
right peak level after the soft clipper on a dBFS scale from -60 dB (bottom) to 0 dB (top):
green below -12 dB, yellow from -12 to -3 dB, red above -3 dB. The bars rise at once and
fall at about 24 dB per second. A thin marker on each bar holds the highest recent peak for
one second and then falls at about 12 dB per second until it meets the bar.

The **CLIP** light above the bars comes on when the signal entering the soft clipper
(after master volume) reaches full scale, so the clipper is compressing hard and the sound
is being distorted. It stays lit for two seconds after the last clip; click the meter to
clear it at once. If it lights often, turn the master volume down, or play fewer voices or
lower the oscillator and effect levels. The meter only watches the audio; it does not change
the sound.

## Velocity, filter envelope and key tracking

- **Velocity** (Master group): when switched off, every note plays at one fixed velocity
  (100), whatever the keyboard sends. Console: `velocity on|off`.
- **Filter envelope:** the *Filter Env* group (next to *Amp Envelope*) has Attack, Decay,
  Sustain and Release sliders with the same ranges as the amp envelope (defaults 5 ms,
  300 ms, 0.30, 300 ms). *Env Amt* in the *Filter* group (-1 to +1, default 0 = off) sets
  how far the envelope moves the cutoff, up to 6 octaves at full amount; negative values
  close the filter instead. Console: `fltenv <-1..1>`.
- **Key Trk** (0-1): the cutoff follows the note. At 1.00 the cutoff doubles for each
  octave above middle C (note 60) and halves for each octave below.
- **Vel>Cut** (0-1): harder key presses raise the cutoff, up to 3 octaves up or down at
  full amount (velocity 127 vs 0).

All of these default to off, so the default sound is unchanged. They apply to the
per-voice filter only; with *Master-bus filter* on they are ignored. A cutoff pushed to
20 kHz or more bypasses the filter for that note.

## LFO and glide

- **LFO 1 and LFO 2** (the *LFO* box, with an *LFO 1* and an *LFO 2* stack): two global low-frequency oscillators
  shared by all voices, with identical controls. Each has its own
  *Rate* 0.05-20 Hz, *Depth* 0-1 (default 0 = off, the LFO does no work at all),
  *Wave* sine, triangle, saw, square, random (sample and hold, one new value per cycle) or random-glide
  (one new random target per cycle, reached with a smooth cosine glide),
  *Dest* pitch, filter, pwm, amp, or the rate of the other LFO (`lfo2-rate` for LFO 1, `lfo1-rate`
  for LFO 2). At full depth the destinations move: pitch by up to
  +/-2 semitones, filter cutoff by +/-3 octaves, pulse width of both oscillators by
  +/-0.25 (clamped to 0-0.5), and volume as tremolo from full level down to silence.
  LFO 2 defaults to depth 0 (off) and destination filter; its random wave differs from
  LFO 1's. When both LFOs target the same destination they combine: pitch (semitones),
  filter (octaves) and pulse-width offsets add, and volume gains multiply. An LFO at
  depth 0 does no work, and with both off nothing is modulated.
  **Rate cross-modulation:** with Dest `lfo2-rate` (LFO 1) or `lfo1-rate` (LFO 2), the LFO
  steers the other LFO's speed instead of the sound: `rate = base_rate * 2 ** (depth * lfo_value * 2)`,
  i.e. up to +/-2 octaves at full depth, clamped to 0.01-40 Hz. LFO 1 runs before LFO 2 in each
  block, and each one reads the other's value from the previous block, so mutual modulation is
  stable. The other LFO still drives its own destination as usual.
  The pitch-bend wheel is unaffected. Console: `lfo <rate> <depth> [wave] [dest]` and
  `lfo2 <rate> <depth> [wave] [dest]`.
- **Glide** (*Glide* group): *Time* 0-2 s (default 0 = off) slides each new note from the
  previous note's pitch (straight line in semitones). *Legato only* glides only when
  another key is still held when the new note starts. Console: `glide <seconds>`.

LFO and glide values update once per audio block (about 5 ms), which is smooth for
musical rates but steps at extreme settings. With the filter destination the per-voice
filter is recalculated every block; with *Master-bus filter* on, the master filter
coefficients are recalculated every block instead. A filter pushed to 20 kHz or more by
the LFO is bypassed for that block, and the LFO can close an otherwise open (20 kHz)
filter.

## Mod Matrix

Eight rows, each `Source | Scale | Destination`, all registry params
(`mod1_src` .. `mod8_dst`, group "Mod Matrix") so patches and MIDI learn cover
them. The factory matrix is empty and an empty matrix (or rows with source or
destination `none`, or scale 0) costs nothing and leaves the sound untouched.
In the window the *Mod Matrix* box is a small table: a header (*Source*, *Scale*,
*Destination*) and eight rows `[source | scale slider | destination]`. The source is a
plain drop-down. *Scale* is a horizontal bipolar slider (-100% .. +100%, centre = 0, the
filled bar grows from the centre toward the handle, the value such as `+37%` is drawn on
it); double-click it to reset to 0. The destination drop-down groups its entries under
non-selectable headers (*Osc 1*, *Osc 2*, *Filter*); entries without a group such as
*Modulation Amount* sit at the top level, and `none` comes first. Every control in the box
supports MIDI learn like the rest of the window (in learn mode click a scale slider, then
move a controller; or right-click for *MIDI Learn* / *Clear binding*); the binding is shown
in the control's tooltip and an armed control gets the orange highlight. Hover the box
for the scale rule below. The console `mod` command still works too.

Sources:

| Source | Range |
|---|---|
| `Note Number` | `(note - 60) / 60`, clipped to -1..+1 (middle C = 0); per voice, so two notes held at once are modulated differently |
| `LFO 1`, `LFO 2` | the raw LFO output, -1..+1, independent of the LFO's own depth knob; an LFO used by a row runs even with depth 0 (and then does not drive its own destination) |
| `Mod Wheel` | CC 1 / 127, 0..1 |
| `Aftertouch` | channel pressure / 127, 0..1 |

Wheel and aftertouch are fed from the raw MIDI messages before MIDI learn
bindings are applied, so a binding on CC 1 or aftertouch keeps working and the
matrix still sees the controller. Both are smoothed per block (one-pole,
`MOD_SMOOTH = 0.3`) to avoid zipper noise.

Scale is -100%..+100% and is **relative to the destination's current value**:
`effective = value x (1 + sum(scale x source))`, clamped to the destination's
own range; several rows on one destination add their percentages first. The
knob/slider/patch always keeps the base value. Consequence: a destination whose
current value is 0 stays 0 (Osc 2 Level at 0, PWM at 0, Resonance at 0, Env
Amount at 0 ...), so give it a non-zero value first. Example: Filter Cutoff at
1000 Hz with `Mod Wheel +50%` gives 1000 Hz with the wheel down and 1500 Hz fully up.

Destinations so far: `Osc 1: Level`, `Osc 1: PWM`, `Osc 1: Sq Level`,
`Osc 2: Level`, `Osc 2: Tune`, `Osc 2: Fine`, `Osc 2: PWM`, `Modulation Amount`,
`Tempo`, `Filter: Cutoff`, `Filter: Resonance` (per voice or on the master bus, where
Note Number means the last played note), `Filter: Env Amount`,
`Filter: Key Trk`, `Filter: Vel>Cut`, `Filter Env: Attack/Decay/Sustain/Release`,
`Amp Env: Attack/Decay/Sustain/Release`, `Unison: Detune` and `Unison: Spread`.
Effects follow.

- **Envelopes** are modulated per voice (so Note Number can give two held notes
  different decay times). The effective stage times are clamped to the knob ranges
  and sustain to 0..1; the other stages of that envelope keep their knob values.
  Clearing the last envelope row restores the knob shapes exactly. A change reaches
  a note that is already sounding at the next block.
- **Unison Detune / Spread** are live: every unison voice keeps its position in the
  stack (-1..+1) and its detune and pan follow `position x effective value` each
  block. A Spread or Detune of 0 stays 0 (relative rule).
- **Tempo** is applied on top of whichever tempo is in use (the MIDI clock when one
  is arriving, else the manual BPM): `bpm = clamp(tempo x (1 + sum), 40, 240)`. It
  drives the tempo-synced delay. Note Number means the last played note. The
  tempo label in the window keeps showing the BASE tempo (manual or MIDI clock).
- Console aliases: lowercase name without spaces, e.g. `mod 3 wheel -50 ampenv:attack`
  (also `amp:attack`), `mod 4 note 30 unison:detune`, `mod 5 lfo2 20 tempo`,
  `filterenv:release`.

Matrix rows apply in addition to the LFOs' own destinations.

Console: `mod <slot 1-8> <source|none> <scale -100..100> <destination|none>`,
e.g. `mod 1 lfo1 40 filter:cutoff` or `mod 2 note -25 osc1:level`. Sources are
`note lfo1 lfo2 wheel aftertouch` and destinations are the lowercase name with
spaces removed (`filter:vel>cut`, `modulationamount`), case-insensitive.
`mod clear [slot]` empties one row or all of them. (`mod <0-1>` with a single
number still sets the modulation amount.)

## Unison

The *Unison* group stacks several voices on every note: *Voices* 1-12 (default 1 = off,
the sound is bit-identical to before), *Detune* 0-50 cents (default 15) and *Spread* 0-1
(default 0.5). Console: `unison <1-12> [detune_cents] [spread]`.

- The stack is drawn from the same 12-voice pool, so the CPU cost is bounded: polyphony
  is `12 // width` notes (width 4 = 3 notes, width 12 = 1 note).
- When the pool is short, whole groups are stolen: groups that have been released first,
  then the oldest. A note never ends up with only some of its voices, except when the width is reduced to 1 while grouped notes are sounding.
- Voice `i` of `N` is detuned by `linspace(-1, 1, N)[i] * Detune` cents and panned by
  `linspace(-1, 1, N)[i] * Spread` (balance law, centre voices untouched). Each voice is
  scaled by `1/sqrt(N)` so loudness stays about the same as the width grows.
- Each voice starts its oscillators at a random phase from a fixed-seed generator, so a
  stack does not cancel or beat identically every note, yet renders repeat exactly.
- With any panned voice the mix is stereo; with the master-bus filter on, the left and
  right channels use two filters with the same settings. Note off, sustain pedal, all
  notes off and panic act on the whole stack.

## Tempo, MIDI clock and synced delay

The *Tempo* group has a manual **BPM** (40-240, default 120) and a live readout:
`120.0 BPM (MIDI clock)` when a clock is arriving, `120 BPM (manual)` otherwise.
The delay block of the Effects group has a **Sync** toggle (default off) and a **Division**
choice (default 1/8). Console: `tempo <bpm>` and `delaysync <on|off> [division]`.

- MIDI clock is 24 pulses per quarter note. The synth reads `clock` from every connected
  input (not filtered by channel), averages the last 48 pulses and shows the tempo to 0.1 BPM.
  `start`, `stop` and `continue` are recognised (they set a running flag only; there is no
  sequencer to start).
- If no clock pulse arrives for 1 second, or fewer than 24 pulses have been seen, the manual
  BPM is used instead and the clock is picked up again as soon as it resumes.
- With Sync on, the delay time is `60000 / BPM * beats` ms, using the external tempo when
  present and the manual BPM otherwise. The result is clamped to the delay's 1-4000 ms
  range (so 1/1 below 60 BPM stops at 4000 ms). The Time knob keeps its own value and is
  used again when Sync is switched off.

| Division | Beats | Division | Beats |
|---|---|---|---|
| 1/1 | 4 | 1/4T | 2/3 |
| 1/2 | 2 | 1/8 | 1/2 |
| 1/2. | 3 | 1/8. | 3/4 |
| 1/4 | 1 | 1/8T | 1/3 |
| 1/4. | 3/2 | 1/16 | 1/4 |
| | | 1/16. | 3/8 |

`.` = dotted (x1.5), `T` = triplet (x2/3). The new controls are saved in patches and have
no default MIDI CC.

## Low latency on Windows (ASIO / WASAPI)

By default PortAudio picks the **MME** host API, which can add ~100–200 ms of
note-to-sound delay. `run.py` now auto-selects the fastest available output, in
this order: **ASIO → WASAPI (exclusive) → WDM-KS → system default**, and prints
the chosen backend plus the actual latency at startup:

```
Output: Focusrite USB ASIO via ASIO (exclusive)
Latency: 5.3 ms output @ 48000 Hz, block 256
```

- `--list` shows every host API and device, so you can see whether ASIO exists.
- **ASIO** is opt-in at the PortAudio level. The pip `sounddevice` wheel bundles
  an ASIO-enabled DLL, but it stays off until `SD_ENABLE_ASIO` is set *before*
  `sounddevice` is imported. `run.py` does this for you on Windows. (Use
  `--no-asio` to disable; this opt-in does not work with the conda package.)
- **WASAPI exclusive** mode is requested automatically and falls back to shared
  mode if the device refuses it.
- Force things explicitly:

```bash
python run.py --hostapi asio
python run.py --audio-device "Focusrite USB ASIO"
python run.py --hostapi wasapi          # WASAPI shared
python run.py --latency low
```

If ASIO is not listed, install your interface's vendor ASIO driver first
(or ASIO4ALL). If audio crackles, raise `--blocksize` (e.g. 512).

An interactive console starts alongside the audio. Type `help`. Commands:

| Command | Action |
|---|---|
| `fx <chorus\|delay\|reverb\|bitcrush> <on\|off\|toggle>` | switch an effect |
| `chorusdepth <0-1>` | chorus depth (default 0.3; LFO rate fixed at 0.5 Hz) |
| `delaytime <200-4000>` | delay time in ms |
| `pingpong <on\|off>` | bounce delay echoes between left and right |
| `reverbamt <0-1>` | reverb wet amount |
| `crush <0-1>` | bitcrush amount (bit depth and downsampling) |
| `square <on\|off> [level]` | osc 1 square layer added to the saw; optional level 0-1 (default 0.5) |
| `pwm1` / `pwm2 <0-0.5>` | pulse width (osc 1 square layer / osc 2); 0.5 = plain square |
| `level1` / `level2 <0-1>` | oscillator mix level (osc 2 starts at 0) |
| `mode <off\|fm\|am\|ring\|sync>` | how osc 1 modulates osc 2 |
| `mod <0-1>` | modulation amount (alias `fm`) |
| `tune2 <-12..12>` | osc 2 coarse semitones |
| `cents2 <-0.5..0.5>` | osc 2 fine cents |
| `oct1 <on\|off>` | osc 1 one octave down |
| `oct2 <on\|off>` | osc 2 one octave up (default on) |
| `lpf <20-20000>` | low-pass cutoff in Hz (20000 = off, default 2000) |
| `lres <0-1>` | low-pass resonance |
| `lpfmode <voice\|master>` | filter placement |
| `adsr <a> <d> <s> <r>` | amp envelope: attack, decay in s (0.001-5), sustain 0-1, release in s (0.001-10) |
| `velocity <on\|off>` | off = every note plays at one fixed velocity |
| `fltenv <-1..1>` | filter envelope amount (per-voice filter; default 0) |
| `lfo <rate> <depth> [wave] [dest]` | LFO 1: 0.05-20 Hz, depth 0-1 (0 = off); wave sine\|triangle\|saw\|square\|random\|random-glide; dest pitch\|filter\|pwm\|amp\|lfo2-rate |
| `lfo2 <rate> <depth> [wave] [dest]` | LFO 2, same arguments (default dest filter; dest also lfo1-rate) |
| `glide <seconds>` | slide between notes, 0-2 s (0 = off) |
| `unison <1-12> [detune_cents] [spread]` | stack voices per note (polyphony = 12 // width); detune 0-50 cents, spread 0-1 |
| `tempo <40-240>` | manual tempo in BPM (used when no MIDI clock arrives) |
| `delaysync <on\|off> [division]` | lock the delay time to the tempo; divisions 1/1 1/2 1/2. 1/4 1/4. 1/4T 1/8 1/8. 1/8T 1/16 1/16. |
| `gain <0-1.2>` | master volume |
| `patch list` / `save <name>` / `load <name>` / `delete <name>` / `reset` | manage sound patches (Init is read-only and cannot be deleted; `patch reset` restores it to the factory sound) |
| `rec start [path]` / `rec stop` | record the output to a 16-bit stereo WAV (default: `recordings/` in the config dir) |
| `sustain <on\|off>` | hold the sustain pedal down / up |
| `panic` | silence all voices immediately; effect tails (delay/reverb) still ring out |
| `alloff` | release all held notes |
| `status` | show current settings |
| `help` | show the command list |
| `quit` | exit (Ctrl+C also works) |

> To hear the second oscillator, raise its level: `level2 0.5` (it defaults to 0
> so you get a pure osc-1 tone until you turn it up).

### Modulation modes (osc1 -> osc2)

`mode` selects how osc1's output drives osc2. `mod` is the amount.

| Mode | Behavior |
|---|---|
| `off` | osc2 runs free, unaffected by osc1 |
| `fm` | osc1 phase-modulates osc2 -> sidebands; osc2 carrier is always on |
| `am` | osc1 amplitude-modulates osc2; carrier stays present (never fully silent) |
| `ring` | ring/balanced modulation, carrier suppressed: osc2 is **silent whenever osc1 is silent** |
| `sync` | hard sync: osc1's cycle resets osc2's phase; `mod` blends free <-> synced |

`ring` is the "osc2 doesn't play while osc1 is silent" behavior. Selecting any
mode other than `off` while `mod` is 0 auto-raises it to 0.7.

## Default profile CC map

This is the seeded `Default` profile; it is now editable via MIDI learn. CC 1 (mod wheel) is no longer bound: it feeds the Mod Matrix instead (profiles you saved earlier keep their own bindings).

| Control | Action |
|---|---|
| CC 7 | master volume |
| CC 20 | toggle Chorus |
| CC 21 | toggle Delay |
| CC 22 | toggle Reverb |
| CC 23 | toggle Bitcrush |
| CC 26 | osc 2 coarse tune (−12..+12 semitones) |
| CC 27 | osc 2 fine tune (−0.5..+0.5 cents) |
| CC 28 | osc 2 level (0..1) |
| CC 29 | osc 1 level (0..1) |
| CC 30 | modulation mode (zones: off / fm / am / ring / sync) |
| CC 71 | low-pass resonance |
| CC 74 | low-pass cutoff (log scale) |
| Pitch wheel | pitch bend (±2 semitones) |

The square layer, Sq Level and PWM controls have no default CC; assign them with MIDI learn.

Toggle CCs act on press (value ≥ 64) with edge detection. Profiles saved before the
low-pass filter was added do not have CC 71 and CC 74; use the toolbar's Reset to get them.

## Pedal, panic and aftertouch

These work without any binding. A CC you bind yourself (MIDI Learn or a profile) always
wins over the built-in behaviour of the same CC.

| Message | Action |
|---|---|
| CC 64 (sustain pedal) | value >= 64 holds notes; note-offs are deferred until the pedal lifts. Pressing a held key again retriggers it normally. |
| CC 123 (all notes off) | releases every note, including pedal-held ones |
| CC 120 (all sound off) | silences all voices immediately (no release tail; delay/reverb tails still ring out) and lifts the pedal |
| CC 121 (reset controllers) | pitch bend back to centre and pedal up |
| Channel aftertouch | bindable like a CC (shown as `Aftertouch` or `Aftertouch ch2`); MIDI Learn works for any control, toggles act at value >= 64 |

Polyphonic (per-note) aftertouch is ignored. Console: `sustain on|off` and `panic`.

## Signal flow

```
per voice (up to 12, shared with unison):
  osc1 (saw + square layer) ─────────────────────────────┐
  osc2 (square) ◀── mode: fm/am/ring/sync ── osc1        ├─▶ mix ─▶ low-pass* ─▶ amp envelope ─▶ pan
                                                         ┘            ▲
                                         filter envelope, key tracking, velocity, LFO

all voices ─▶ sum (left/right) ─▶ low-pass* ─▶ chorus ─▶ delay ─▶ reverb ─▶ bitcrush
           ─▶ master gain ─▶ soft clip (tanh) ─▶ out  (level meter reads here)
```

\* The low-pass filter runs in one of two places: per voice before the amp envelope (the
default; the only place the filter envelope, key tracking and velocity act), or once on the
master bus after the sum and before the effects (`--lpf-mode master`).

Modulation sources: the **filter envelope**, **key tracking** and **velocity** move the
per-voice cutoff; the global **LFO** moves pitch, cutoff, pulse width or volume; **velocity**
also scales the note level (unless switched off); **glide** shapes pitch between notes. The
oscillators and per-voice filter are mono. Voices are panned by unison spread; with every
voice centred the mix is identical in both channels. The effects, master gain and soft clip
run per channel and the engine returns an `(n, 2)` float32 block. On a 1-channel device the
output is the mean of left and right; channels beyond 2 are silent.

`osc2` pitch = note pitch x 2^((semitones + cents/100)/12).

## Performance

The effects, filter and envelope process whole blocks with numpy / SciPy (`scipy.signal.lfilter`)
rather than sample by sample. `python bench.py` prints the time per audio block against the
block budget for 12 voices (defaults, filter placements, each effect, all effects). On the
development machine (48 kHz, 256-sample blocks) all four effects plus 12 voices use about
33% of the budget; the numbers vary by machine, so run `bench.py` to measure your own. The optimised code is checked against frozen copies of the original
implementations in `tests/reference_dsp.py`.

## Offline render (no audio device)

```bash
python render_demo.py --out demo.wav --effects reverb,delay --pwm1 0.3 --mode ring --fm 0.7 --level2 0.6
```

Renders a 12-note chord to a stereo (2-channel, 16-bit, interleaved L/R) WAV file using only
NumPy and the standard library.
