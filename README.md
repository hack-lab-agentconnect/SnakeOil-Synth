# midi-synth

Python MIDI synth. Built by Jilly @ Hackers In The Loop

A real-time Python MIDI synthesizer. It listens to **any** MIDI input device, plays
the notes it receives, and runs them through a dual-oscillator voice engine plus a
toggleable effects chain.

## Features

- MIDI input from **all connected input ports** (or a named port / single channel).
- Polyphony up to **12 simultaneous notes**.
- Oscillators (band-limited with PolyBLEP): **osc 1 is a saw** with a **square layer** (on by default, can be switched off); **osc 2 is a square**. Both squares have **PWM** (pulse width 0-0.5, where 0.5 is a plain square). PWM defaults to 0, the narrowest pulse the engine allows (a duty of 0.02).
- **Second oscillator is phase-modulated (FM) by the first oscillator's output.**
- Second oscillator **coarse tuning −12..+12 semitones** plus **fine tuning ±0.5 cents**.
- **Octave switches:** osc 1 can play one octave down, osc 2 one octave up (relative to the played note, on top of its tuning). Osc 2's octave-up switch is on by default.
- Toggleable effects: **Chorus, Delay, Reverb, Bitcrush**. In the GUI each has a
  dial under its button: chorus **Depth** (how far the delay swings; the LFO rate is fixed
  at 0.5 Hz), delay **Time** (200-4000 ms, log scale), reverb **Amount** (wet
  level) and bitcrush **Crush** (bit depth and downsampling together). Each effect owns a
  two-column block in the Effects group: the on/off button spans the top, and its controls
  flow two per row beneath it. The delay block has **Time**, **Ping-pong**, **Feedback**
  (0-0.95, how long the echoes repeat) and **Tone** (0-0.9, higher = darker echoes); the
  reverb block has **Amount**, **Size** (0.5-0.98, how long the tail rings) and **Damping**
  (0-0.9, higher = darker tail). The defaults (Feedback 0.35, Tone 0.25, Size 0.84,
  Damping 0.25) match the sound before these dials existed. The dials have no default MIDI
  CC; use MIDI Learn to bind them, and they are saved in patches.
- **Stereo output.** Voices and the filter are mono; the effect chain is stereo. Chorus
  runs a left and a right delay line with opposite LFO phase, reverb uses a second comb/allpass
  bank offset by 23 samples for the right channel, delay keeps a buffer per channel, and the
  bitcrusher works per channel. The **Ping-pong** button (console: `pingpong on`) bounces the
  echoes between the left and right speakers. With all effects off both channels are identical.
  On a 1-channel device the output is the mean of left and right; channels beyond 2 are silent.
- Resonant 12 dB/oct **low-pass filter** (cutoff + resonance), per voice or on the master bus. The filter is on by default at **2000 Hz**; turning the cutoff fully right (20 kHz) bypasses it.
- Pitch-bend and velocity support; per-voice ADSR envelope.

## Install

```bash
python -m venv .venv && . .venv/bin/activate      # optional
pip install -r requirements.txt       # includes PySide6 for the GUI
pip install -r requirements-dev.txt   # also installs test dependencies
```

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

The *Amp Envelope* group at the bottom of the window has four vertical sliders that shape
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

- **LFO** (*LFO* group): one global low-frequency oscillator shared by all voices.
  *Rate* 0.05-20 Hz, *Depth* 0-1 (default 0 = off, the LFO does no work at all),
  *Wave* sine, triangle, saw, square or random (sample and hold, one new value per cycle),
  *Dest* pitch, filter, pwm or amp. At full depth the destinations move: pitch by up to
  +/-2 semitones, filter cutoff by +/-3 octaves, pulse width of both oscillators by
  +/-0.25 (clamped to 0-0.5), and volume as tremolo from full level down to silence.
  The pitch-bend wheel is unaffected. Console: `lfo <rate> <depth> [wave] [dest]`.
- **Glide** (*Glide* group): *Time* 0-2 s (default 0 = off) slides each new note from the
  previous note's pitch (straight line in semitones). *Legato only* glides only when
  another key is still held when the new note starts. Console: `glide <seconds>`.

LFO and glide values update once per audio block (about 5 ms), which is smooth for
musical rates but steps at extreme settings. With the filter destination the per-voice
filter is recalculated every block; with *Master-bus filter* on, the master filter
coefficients are recalculated every block instead. A filter pushed to 20 kHz or more by
the LFO is bypassed for that block, and the LFO can close an otherwise open (20 kHz)
filter.

## Unison

The *Unison* group stacks several voices on every note: *Voices* 1-12 (default 1 = off,
the sound is bit-identical to before), *Detune* 0-50 cents (default 15) and *Spread* 0-1
(default 0.5). Console: `unison <1-12> [detune_cents] [spread]`.

- The stack is drawn from the same 12-voice pool, so the CPU cost is bounded: polyphony
  is `12 // width` notes (width 4 = 3 notes, width 12 = 1 note).
- When the pool is short, whole groups are stolen: groups that have been released first,
  then the oldest. A note never ends up with only some of its voices.
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

```
fx <chorus|delay|reverb|bitcrush> <on|off|toggle>
chorusdepth <0-1>   # chorus depth (default 0.3; LFO rate fixed at 0.5 Hz)
delaytime <200-4000>  # delay time in ms (default 300)
pingpong <on|off>   # bounce delay echoes between left and right (default off)
reverbamt <0-1>     # reverb wet amount (default 0.3)
rec start [path]    # record the output to a 16-bit stereo WAV (default: recordings/ in the config dir)
rec stop            # stop recording and save the file
crush <0-1>         # bitcrush amount: bit depth and downsampling (default 0.5)
square <on|off>     # oscillator 1 square layer over the saw (default on)
pwm1 <0-0.5>        # oscillator 1 square-layer pulse width (default 0; 0.5 = plain square)
pwm2 <0-0.5>        # oscillator 2 pulse width (default 0; 0.5 = plain square)
level1/level2 <0-1>  # oscillator mix level (osc2 starts at 0)
mode <off|fm|am|ring|sync>  # how osc1 modulates osc2
mod <0-1>           # modulation amount (alias: fm)
tune2 <-12..12>     # oscillator-2 coarse semitones
cents2 <-0.5..0.5>  # oscillator-2 fine cents
oct1 <on|off>       # oscillator 1 one octave down
oct2 <on|off>       # oscillator 2 one octave up (default on)
lpf <20-20000>      # low-pass cutoff in Hz (default 2000; 20000 = off)
lres <0-1>          # low-pass resonance
lpfmode <voice|master>  # filter placement
adsr <a> <d> <s> <r>  # amp envelope: attack and decay in seconds (0.001-5), sustain 0-1, release in seconds (0.001-10)
velocity <on|off>   # off = fixed note velocity (default on)
fltenv <-1..1>      # filter envelope amount (per-voice filter; default 0)
lfo <rate> <depth> [wave] [dest]  # LFO: 0.05-20 Hz, depth 0-1 (0 = off); wave sine|triangle|saw|square|random; dest pitch|filter|pwm|amp
glide <seconds>     # slide between notes, 0-2 s (default 0 = off)
unison <1-12> [detune_cents] [spread]  # stack voices per note (default 1 = off)
tempo <40-240>      # manual tempo in BPM (default 120)
delaysync <on|off> [division]  # lock the delay time to the tempo (default off)
gain <0-1.2>
alloff | status | quit
```

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

This is the seeded `Default` profile; it is now editable via MIDI learn.

| Control | Action |
|---|---|
| CC 1 | modulation amount (0..1) |
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

The square layer and PWM controls have no default CC; assign them with MIDI learn.

Toggle CCs act on press (value ≥ 64) with edge detection. Profiles saved before the
low-pass filter was added do not have CC 71 and CC 74; use the toolbar's Reset to get them.

## Pedal, panic and aftertouch

These work without any binding. A CC you bind yourself (MIDI Learn or a profile) always
wins over the built-in behaviour of the same CC.

| Message | Action |
|---|---|
| CC 64 (sustain pedal) | value >= 64 holds notes; note-offs are deferred until the pedal lifts. Pressing a held key again retriggers it normally. |
| CC 123 (all notes off) | releases every note, including pedal-held ones |
| CC 120 (all sound off) | silences everything immediately (no release tail) and lifts the pedal |
| CC 121 (reset controllers) | pitch bend back to centre and pedal up |
| Channel aftertouch | bindable like a CC (shown as `Aftertouch` or `Aftertouch ch2`); MIDI Learn works for any control, toggles act at value >= 64 |

Polyphonic (per-note) aftertouch is ignored. Console: `sustain on|off` and `panic`.

## Signal flow

```
note ─▶ ADSR ─▶ osc1 ──┬────────────────────────────┐
                       └─(mode: fm/am/ring/sync)─▶ osc2 ─┴▶ low-pass* ─▶ Σ ─▶ low-pass* ─▶ chorus ─▶ delay ─▶ reverb ─▶ bitcrush ─▶ soft clip ─▶ out
```

\* The low-pass filter runs in one of two places: per voice before the sum (the default), or
once on the master bus after the sum and before the effects (`--lpf-mode master`). The other
position is bypassed. The oscillators and filter are mono; the effects are stereo.

Everything up to the sum is mono. The mono mix is copied into left and right channels at the
start of the effect chain; the effects, the volume and the soft clip then run per channel, and
the engine returns an `(n, 2)` float32 block.

`osc2` pitch = note pitch × 2^((semitones + cents/100)/12).

## Performance

The effects, filter and envelope process whole blocks with numpy / SciPy (`scipy.signal.lfilter`)
rather than sample by sample. `python bench.py` prints the time per audio block against the
block budget for 12 voices (defaults, filter placements, each effect, all effects). On the
development machine (48 kHz, 256-sample blocks) all four effects plus 12 voices use about
27% of the budget. The optimised code is checked against frozen copies of the original
implementations in `tests/reference_dsp.py`.

## Offline render (no audio device)

```bash
python render_demo.py --out demo.wav --effects reverb,delay --pwm1 0.3 --mode ring --fm 0.7 --level2 0.6
```

Renders a 12-note chord to a stereo (2-channel, 16-bit, interleaved L/R) WAV file using only
NumPy and the standard library.
