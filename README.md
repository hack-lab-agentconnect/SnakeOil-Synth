# midi-synth

Python MIDI synth. Built by Jilly @ Hackers In The Loop

A real-time Python MIDI synthesizer. It listens to **any** MIDI input device, plays
the notes it receives, and runs them through a dual-oscillator voice engine plus a
toggleable effects chain.

## Features

- MIDI input from **all connected input ports** (or a named port / single channel).
- Polyphony up to **12 simultaneous notes**.
- Waveforms: **sine, square, saw, triangle** (square/saw are band-limited with PolyBLEP).
- **Second oscillator is phase-modulated (FM) by the first oscillator's output.**
- Second oscillator **coarse tuning −12..+12 semitones** plus **fine tuning ±0.5 cents**.
- Toggleable effects: **Chorus, Delay, Reverb, Bitcrush**.
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
```

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
wave1/wave2 <sine|square|saw|triangle>
level1/level2 <0-1>  # oscillator mix level (osc2 starts at 0)
mode <off|fm|am|ring|sync>  # how osc1 modulates osc2
mod <0-1>           # modulation amount (alias: fm)
tune2 <-12..12>     # oscillator-2 coarse semitones
cents2 <-0.5..0.5>  # oscillator-2 fine cents
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
| CC 24 | osc 1 waveform (0-31 sine, 32-63 square, 64-95 saw, 96-127 triangle) |
| CC 25 | osc 2 waveform (same zones) |
| CC 26 | osc 2 coarse tune (−12..+12 semitones) |
| CC 27 | osc 2 fine tune (−0.5..+0.5 cents) |
| CC 28 | osc 2 level (0..1) |
| CC 29 | osc 1 level (0..1) |
| CC 30 | modulation mode (zones: off / fm / am / ring / sync) |
| Pitch wheel | pitch bend (±2 semitones) |

Toggle CCs act on press (value ≥ 64) with edge detection.

## Signal flow

```
note ─▶ ADSR ─▶ osc1 ──┬────────────────────────────▶ Σ ─▶ chorus ─▶ delay ─▶ reverb ─▶ bitcrush ─▶ soft clip ─▶ out
                       └─(mode: fm/am/ring/sync)─▶ osc2 ─┘
```

`osc2` pitch = note pitch × 2^((semitones + cents/100)/12).

## Offline render (no audio device)

```bash
python render_demo.py --out demo.wav --effects reverb,delay --wave1 saw --mode ring --fm 0.7 --level2 0.6
```

Renders a 12-note chord to a WAV file using only NumPy and the standard library.
