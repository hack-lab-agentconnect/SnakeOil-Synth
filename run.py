import argparse
import math
import sys
import time
from pathlib import Path

from midi_synth.config import (
    SAMPLE_RATE, BLOCK_SIZE, MAX_VOICES, LPF_MODES, DEFAULT_LPF_MODE,
)
from midi_synth.bindings import default_profile
from midi_synth.engine import SynthEngine
from midi_synth.config import DELAY_DIVISION_BEATS
from midi_synth.midi_input import MidiInput
from midi_synth.modmatrix import NUM_SLOTS, parse_mod_args
from midi_synth.midi_router import MidiRouter
from midi_synth.params import build_registry
from midi_synth.patches import INIT_NAME, PatchError, PatchStore, apply as apply_patch, capture
from midi_synth.profiles import (
    ProfileStore, default_config_dir, migrate_legacy_config,
)
from midi_synth.recorder import Recorder, recording_path


def resolve_config_dir(config_dir_arg):
    """Return (config dir, migration message). Migrates only for the default dir."""
    if config_dir_arg:
        return Path(config_dir_arg), None
    config_dir = default_config_dir()
    return config_dir, migrate_legacy_config(config_dir)


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="snakeoil-synth",
        description="SnakeOil Synth: a real-time synthesizer with dual oscillators and effects.",
    )
    p.add_argument("--list", action="store_true", help="list MIDI and audio devices and exit")
    p.add_argument("--input", action="append", metavar="NAME",
                   help="MIDI input port name (repeatable). Default: all ports")
    p.add_argument("--channel", type=int, default=None,
                   help="Only accept this MIDI channel (1-16). Default: all")
    p.add_argument("--samplerate", type=int, default=None,
                   help="output sample rate (default: the selected device's rate)")
    p.add_argument("--blocksize", type=int, default=BLOCK_SIZE)
    p.add_argument("--voices", type=int, default=MAX_VOICES, help="max simultaneous notes (1-12+)")
    p.add_argument("--audio-device", default=None, help="output device index or name")
    p.add_argument("--hostapi", default=None,
                   help="force a host API: asio, wasapi, wdm-ks, mme, ... (default: auto)")
    p.add_argument("--latency", default="low", help="'low', 'high', or seconds (default: low)")
    p.add_argument("--shared", action="store_true",
                   help="do not request WASAPI exclusive mode")
    p.add_argument("--no-asio", action="store_true",
                   help="do not opt in to the bundled ASIO-enabled PortAudio DLL")
    p.add_argument("--channels", type=int, default=2, help="output channels")
    p.add_argument("--lpf-mode", choices=LPF_MODES, default=DEFAULT_LPF_MODE,
                   help="low-pass filter placement: per voice, or one on the master bus (fallback if per-voice is too heavy)")
    p.add_argument("--no-console", action="store_true", help="disable interactive command console")
    p.add_argument("--no-gui", action="store_true", help="run the console only, no window")
    p.add_argument("--profile", default=None, metavar="NAME",
                   help="MIDI binding profile to load (default: last used)")
    p.add_argument("--patch", default=None, metavar="NAME",
                   help="sound patch to load at startup (default: last used)")
    p.add_argument("--config-dir", default=None, metavar="PATH",
                   help="where profiles are stored (default: per-user config dir)")
    return p.parse_args(argv)


def copy_block_to_output(outdata, block):
    """Write a stereo (frames, 2) block into outdata of any channel count.

    Two or more channels get left and right in the first two and silence in
    the rest; a single channel gets the mean of left and right.
    """
    channels = outdata.shape[1]
    if channels >= 2:
        outdata[:, :2] = block
        outdata[:, 2:] = 0.0
    else:
        outdata[:, 0] = block.mean(axis=1)


class CallbackState:
    """Remembers whether the audio callback has already reported an error."""

    def __init__(self):
        self.reported = False
        self.recorder = None


def render_into(outdata, engine, frames, state):
    """Render a block into outdata; on any error output silence and report it once."""
    try:
        block = engine.render(frames)
        copy_block_to_output(outdata, block)
        recorder = state.recorder
        if recorder is not None and recorder.active:
            recorder.push(block)
    except Exception as exc:
        outdata.fill(0)
        if not state.reported:
            state.reported = True
            print("Audio render error (output muted while it persists): %r" % (exc,))


def parse_on_off(text, allow_toggle=False):
    """Return True/False for on/off (case-insensitive), 'toggle' if allowed, else None."""
    word = text.strip().lower() if isinstance(text, str) else ""
    if word == "on":
        return True
    if word == "off":
        return False
    if allow_toggle and word == "toggle":
        return "toggle"
    return None


def list_devices():
    print("MIDI inputs:")
    try:
        names = MidiInput.available_ports()
    except Exception as exc:
        names = []
        print("  (could not query MIDI: %s)" % exc)
    if names:
        for n in names:
            print("  - %s" % n)
    else:
        print("  (none found)")
    print()
    from midi_synth import audio_backend

    audio_backend.prepare_asio()
    try:
        import sounddevice as sd

        print(audio_backend.format_device_listing(sd))
    except Exception as exc:
        print("Audio outputs: (could not query audio: %s)" % exc)


HELP_TEXT = """commands:
  fx <chorus|delay|reverb|bitcrush> <on|off|toggle>
  chorusdepth <0-1>          chorus depth (default 0.3)
  delaytime <200-4000>       delay time in ms
  pingpong <on|off>          bounce delay echoes between left and right
  reverbamt <0-1>            reverb wet amount
  crush <0-1>                bitcrush amount (bit depth and downsampling)
  square <on|off> [level]    osc 1 square layer added to the saw; level 0-1 (default 0.5)
  pwm1/pwm2 <0-0.5>          pulse width (osc 1 square layer / osc 2); 0.5 = square
  level1/level2 <0-1>        oscillator mix level (osc2 starts at 0)
  mode <off|fm|am|ring|sync> how osc1 modulates osc2
  mod <0-1>                  modulation amount (alias: fm)
  mod <slot 1-8> <source> <scale -100..100> <destination>  mod matrix row, e.g.
                             mod 1 lfo1 40 filter:cutoff
                             sources none note lfo1 lfo2 wheel aftertouch;
                             destinations: lowercase name, spaces removed
                             (osc1:level osc2:tune modulationamount filter:cutoff
                             filter:resonance filter:envamount filter:keytrk
                             filter:vel>cut tempo filterenv:attack|decay|sustain|release
                             ampenv:attack|decay|sustain|release (also amp:attack ...)
                             chorus:depth delay:time|feedback|tone
                             reverb:amount|size|damping bitcrush:crush
                             unison:detune unison:spread ...) or none
  mod clear [slot]           empty one matrix row, or all of them
  tune2 <-12..12>            osc2 coarse semitones
  cents2 <-0.5..0.5>         osc2 fine cents
  oct1 <on|off>              osc 1 one octave down
  oct2 <on|off>              osc 2 one octave up
  lpf <20-20000>             low-pass cutoff in Hz (20000 = off)
  lres <0-1>                 low-pass resonance
  lpfmode <voice|master>     filter placement
  lpfslope <12|24>           low-pass slope in dB/octave (24 = Moog-style, whistles at
                             maximum resonance in the per-voice filter)
  adsr <a> <d> <s> <r>       amp envelope: attack, decay (s), sustain (0-1), release (s)
  velocity <on|off>          off = every note plays at one fixed velocity
  limiter <on|off>           auto limiter: turns the volume down when the signal would clip
                             and holds it there until silence or a patch change
  limiter reset              drop the limiter's held gain reduction
  fltenv <-1..1>            filter envelope amount (per-voice filter)
  lfo <rate> <depth> [wave] [dest]  LFO: 0.05-20 Hz, depth 0-1 (0 = off),
                             wave sine|triangle|saw|square|random|random-glide,
                             dest pitch|filter|pwm|amp|lfo2-rate (LFO 1 speeds/slows LFO 2)
  lfo2 <rate> <depth> [wave] [dest]  second LFO, same arguments (default dest filter;
                             dest also lfo1-rate)
  glide <seconds>            slide between notes, 0-2 s (0 = off)
  noise <0-1> [white|pink|brown]  noise level mixed in per voice (0 = off) and color
  unison <1-12> [detune_cents] [spread]  stack voices per note (polyphony = 12 // width);
                             detune 0-50 cents, spread 0-1
  tempo <40-240>             manual tempo in BPM (used when no MIDI clock arrives)
  delaysync <on|off> [division]  lock the delay time to the tempo; division
                             1/1 1/2 1/2. 1/4 1/4. 1/4T 1/8 1/8. 1/8T 1/16 1/16.
                             (. = dotted, T = triplet)
  gain <0-1.2>               master volume
  patch list                 list saved sound patches
  patch save <name>          save the current sound as a patch
  patch load <name>          load a patch
  patch delete <name>        delete a patch (Init cannot be deleted)
  patch reset                restore the Init patch to the factory sound
  rec start [path]           record the output to a 16-bit stereo WAV file
                             (default: recordings/ in the config dir)
  rec stop                   stop recording and save the file
  sustain <on|off>           hold the sustain pedal down / up
  panic                      silence all voices immediately (delay/reverb tails still ring out)
  alloff                     release all held notes
  status                     show current settings
  help                       show this help
  quit                       exit (Ctrl+C also works)"""


def load_startup_patch(registry, patch_store, defaults, name=None):
    """Apply `name` (or the last-used patch); return (warnings, applied name).

    Anything unreadable or missing is reported, the factory sound stays and
    the applied name is None; the last-used patch then becomes Init so the
    GUI does not show a patch that never loaded.
    """
    warnings = []
    name = name or patch_store.last_used()
    if not name:
        return warnings, None
    try:
        values = patch_store.load(name)
        warnings += apply_patch(registry, values, defaults)
        patch_store.set_last_used(name)
        stored = {n.lower(): n for n in patch_store.names()}
        return warnings, stored.get(name.lower(), name)
    except Exception as exc:
        warnings.append("Patch %r not loaded (%s); using factory defaults" % (name, exc))
    try:
        patch_store.set_last_used(INIT_NAME)
    except OSError:
        pass
    return warnings, None


def patch_command(parts, registry, patch_store, defaults):
    usage = "usage: patch list | save <name> | load <name> | delete <name> | reset"
    if registry is None or patch_store is None:
        print("patches unavailable")
        return
    sub = parts[1].lower() if len(parts) > 1 else ""
    name = " ".join(parts[2:])
    try:
        if sub == "list":
            for n in patch_store.names():
                print("  %s" % n)
            for w in patch_store.warnings:
                print("  (%s)" % w)
        elif sub == "reset" and not name:
            patch_store.reset_init(defaults)
            print("Init patch reset to the factory sound")
        elif sub in ("save", "load", "delete") and name:
            if sub == "save":
                patch_store.save(name, capture(registry))
                patch_store.set_last_used(name)
                print("saved patch %s" % name)
            elif sub == "load":
                for w in apply_patch(registry, patch_store.load(name), defaults):
                    print("warning: %s" % w)
                patch_store.set_last_used(name)
                print("loaded patch %s" % name)
            else:
                patch_store.delete(name)
                print("deleted patch %s" % name)
        else:
            print(usage)
    except (PatchError, OSError) as exc:
        print(exc)


MOD_USAGE = ("usage: mod <slot 1-8> <none|note|lfo1|lfo2|wheel|aftertouch> "
             "<scale -100..100> <destination|none>  |  mod clear [slot]")


def mod_command(parts, engine):
    """``mod <slot> <source> <scale> <destination>`` and ``mod clear [slot]``."""
    if parts[1].lower() == "clear":
        try:
            slots = range(1, NUM_SLOTS + 1) if len(parts) == 2 else [int(parts[2])]
            if len(parts) > 3 or any(not 1 <= s <= NUM_SLOTS for s in slots):
                raise ValueError
        except ValueError:
            print(MOD_USAGE)
            return
        for slot in slots:
            engine.set_mod_row(slot, "none", 0.0, "none")
        return
    try:
        slot, source, scale, dest = parse_mod_args(parts[1:])
    except ValueError:
        print(MOD_USAGE)
        return
    try:
        engine.set_mod_row(slot, source, scale, dest)
    except ValueError:
        print(MOD_USAGE)


def rec_command(parts, engine, recorder, config_dir):
    usage = "usage: rec start [path] | rec stop"
    if recorder is None:
        print("recording unavailable")
        return
    sub = parts[1].lower() if len(parts) > 1 else ""
    try:
        if sub == "start":
            if len(parts) > 2:
                path = Path(" ".join(parts[2:]))
                if path.exists():
                    print("%s already exists; choose a new file name" % path)
                    return
                path.parent.mkdir(parents=True, exist_ok=True)
            else:
                path = recording_path(config_dir or default_config_dir())
            recorder.start(path, engine.sr)
            print("recording to %s" % path)
        elif sub == "stop" and len(parts) == 2:
            if recorder.active:
                recorder.stop()
                problems = recorder.problem_summary()
                print("saved %s (%.1f s)%s"
                      % (recorder.path, recorder.elapsed,
                         " - warning: " + problems if problems else ""))
            else:
                print("not recording")
        else:
            print(usage)
    except (OSError, RuntimeError) as exc:
        print(exc)


def console_loop(engine, registry=None, patch_store=None, patch_defaults=None,
                 recorder=None, config_dir=None):
    help_text = HELP_TEXT
    print(help_text)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        try:
            if cmd in ("quit", "exit", "q"):
                return
            elif cmd == "help":
                print(help_text)
            elif cmd == "status":
                for k, v in engine.status().items():
                    print("  %s: %s" % (k, v))
            elif cmd == "patch":
                patch_command(parts, registry, patch_store, patch_defaults)
            elif cmd == "rec":
                rec_command(parts, engine, recorder, config_dir)
            elif cmd == "sustain":
                on = parse_on_off(parts[1]) if len(parts) > 1 else None
                if on is None:
                    print("usage: sustain <on|off>")
                else:
                    engine.set_sustain(on)
            elif cmd == "panic":
                engine.panic()
            elif cmd == "alloff":
                engine.all_notes_off()
            elif cmd == "mod" and (len(parts) > 2 or parts[1:] == ["clear"]):
                mod_command(parts, engine)
            elif cmd in ("fm", "mod"):
                engine.set_fm_depth(float(parts[1]))
            elif cmd == "mode":
                engine.set_mod_mode(parts[1].lower())
            elif cmd in ("level1", "level2"):
                osc = 1 if cmd == "level1" else 2
                engine.set_osc_level(osc, float(parts[1]))
            elif cmd == "tune2":
                engine.set_detune2(float(parts[1]))
            elif cmd == "cents2":
                engine.set_detune2(engine.params["detune2_semitones"], float(parts[1]))
            elif cmd == "gain":
                engine.set_master_gain(float(parts[1]))
            elif cmd == "chorusdepth":
                engine.set_chorus_depth(float(parts[1]))
            elif cmd == "delaytime":
                engine.set_delay_time(min(max(float(parts[1]), 200.0), 4000.0))
            elif cmd in ("pingpong", "square", "oct1", "oct2"):
                on = parse_on_off(parts[1]) if len(parts) > 1 else None
                level = None
                if cmd == "square" and on is not None and len(parts) > 2:
                    try:
                        level = float(parts[2])
                    except ValueError:
                        on = None
                    if len(parts) > 3 or (level is not None and not math.isfinite(level)):
                        on = None
                if on is None:
                    print("usage: square <on|off> [level]" if cmd == "square"
                          else "usage: %s <on|off>" % cmd)
                elif cmd == "pingpong":
                    engine.set_delay_pingpong(on)
                elif cmd == "square":
                    engine.set_osc1_square(on)
                    if level is not None:
                        engine.set_osc1_square_level(level)
                elif cmd == "oct1":
                    engine.set_osc1_octave_down(on)
                else:
                    engine.set_osc2_octave_up(on)
            elif cmd == "reverbamt":
                engine.set_reverb_amount(float(parts[1]))
            elif cmd == "crush":
                engine.set_crush_amount(float(parts[1]))
            elif cmd == "pwm1":
                engine.set_osc1_pwm(float(parts[1]))
            elif cmd == "pwm2":
                engine.set_osc2_pwm(float(parts[1]))
            elif cmd == "lpf":
                engine.set_lpf_cutoff(float(parts[1]))
            elif cmd == "lres":
                engine.set_lpf_resonance(float(parts[1]))
            elif cmd == "lpfmode":
                engine.set_lpf_mode(parts[1].lower())
            elif cmd == "lpfslope":
                slope = {"12": "12 dB", "12db": "12 dB", "24": "24 dB", "24db": "24 dB"}.get(
                    parts[1].lower() if len(parts) > 1 else "")
                if slope is None:
                    print("usage: lpfslope <12|24>")
                else:
                    engine.set_lpf_slope(slope)
            elif cmd == "adsr":
                attack, decay, sustain, release = (float(x) for x in parts[1:5])
                if len(parts) != 5:
                    raise ValueError("adsr takes four values")
                engine.set_amp_attack(attack)
                engine.set_amp_decay(decay)
                engine.set_amp_sustain(sustain)
                engine.set_amp_release(release)
            elif cmd == "velocity":
                on = parse_on_off(parts[1]) if len(parts) > 1 else None
                if on is None:
                    print("usage: velocity <on|off>")
                else:
                    engine.set_velocity_on(on)
            elif cmd == "limiter":
                arg = parts[1].lower() if len(parts) > 1 else ""
                on = parse_on_off(arg) if arg and arg != "reset" else None
                if arg == "reset":
                    engine.reset_limiter()
                elif on is None:
                    print("usage: limiter <on|off|reset>")
                else:
                    engine.set_auto_limiter(on)
            elif cmd == "fltenv":
                engine.set_flt_env_amount(float(parts[1]))
            elif cmd == "lfo":
                if len(parts) < 3 or len(parts) > 5:
                    raise ValueError("lfo takes rate depth [wave] [dest]")
                rate, depth = float(parts[1]), float(parts[2])
                if len(parts) > 3:
                    engine.set_lfo_wave(parts[3].lower())
                if len(parts) > 4:
                    engine.set_lfo_dest(parts[4].lower())
                engine.set_lfo_rate(rate)
                engine.set_lfo_depth(depth)
            elif cmd == "lfo2":
                if len(parts) < 3 or len(parts) > 5:
                    raise ValueError("lfo2 takes rate depth [wave] [dest]")
                rate, depth = float(parts[1]), float(parts[2])
                if len(parts) > 3:
                    engine.set_lfo2_wave(parts[3].lower())
                if len(parts) > 4:
                    engine.set_lfo2_dest(parts[4].lower())
                engine.set_lfo2_rate(rate)
                engine.set_lfo2_depth(depth)
            elif cmd == "glide":
                engine.set_glide_time(float(parts[1]))
            elif cmd == "noise":
                colors = ("white", "pink", "brown")
                try:
                    if not 2 <= len(parts) <= 3:
                        raise ValueError
                    level = float(parts[1])
                    if len(parts) == 3 and parts[2].lower() not in colors:
                        raise ValueError
                except ValueError:
                    print("usage: noise <0-1> [white|pink|brown]")
                else:
                    engine.set_noise_level(level)
                    if len(parts) == 3:
                        engine.set_noise_color(parts[2].lower())
            elif cmd == "unison":
                if len(parts) < 2 or len(parts) > 4:
                    raise ValueError("unison takes <1-12> [detune_cents] [spread]")
                engine.set_unison_voices(parts[1])
                if len(parts) > 2:
                    engine.set_unison_detune(float(parts[2]))
                if len(parts) > 3:
                    engine.set_unison_spread(float(parts[3]))
            elif cmd == "tempo":
                if len(parts) != 2:
                    print("usage: tempo <40-240>")
                else:
                    engine.set_tempo_bpm(float(parts[1]))
            elif cmd == "delaysync":
                on = parse_on_off(parts[1]) if len(parts) > 1 else None
                division = parts[2] if len(parts) > 2 else None
                names = {n.lower(): n for n in DELAY_DIVISION_BEATS}
                if division is not None:
                    division = names.get(division.lower())
                if (on is None or len(parts) > 3
                        or (len(parts) > 2 and division is None)):
                    print("usage: delaysync <on|off> [%s]" % "|".join(DELAY_DIVISION_BEATS))
                else:
                    if division is not None:
                        engine.set_delay_division(division)
                    engine.set_delay_sync(on)
            elif cmd == "fx":
                name = parts[1].lower()
                action = parse_on_off(parts[2], allow_toggle=True) if len(parts) > 2 else "toggle"
                if action is None:
                    print("usage: fx <chorus|delay|reverb|bitcrush> <on|off|toggle>")
                elif action == "toggle":
                    engine.toggle_effect(name)
                else:
                    engine.set_effect(name, action)
            else:
                print("unknown command")
        except (IndexError, ValueError):
            print("bad arguments")
        except KeyError:
            print("unknown effect")


def open_output_stream(sd, choice, args, samplerate, callback):
    def attempt(extra):
        kwargs = dict(
            samplerate=samplerate,
            blocksize=args.blocksize,
            channels=args.channels,
            device=choice["device"],
            dtype="float32",
            latency=args.latency,
            callback=callback,
        )
        if extra is not None:
            kwargs["extra_settings"] = extra
        return sd.OutputStream(**kwargs)

    try:
        return attempt(choice["extra_settings"]), choice
    except Exception as exc:
        if choice["extra_settings"] is not None:
            print("  (%s mode failed: %s; retrying shared)" % (choice["hostapi"], exc))
            fallback = dict(choice)
            fallback["extra_settings"] = None
            fallback["exclusive"] = False
            return attempt(None), fallback
        raise


def launch_gui(engine, registry, router, store, ports, on_exit=None,
               patch_store=None, patch_defaults=None, recorder=None,
               initial_patch=None):
    try:
        from midi_synth.gui.app import run_gui
    except ImportError as exc:
        print("GUI unavailable (%s); using the console. Install it with: pip install PySide6" % exc)
        return False
    run_gui(engine, registry, router, store, ports, on_exit,
            patch_store=patch_store, patch_defaults=patch_defaults,
            recorder=recorder, initial_patch=initial_patch)
    return True


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    from midi_synth import audio_backend

    if not args.no_asio:
        audio_backend.prepare_asio()

    if args.list:
        list_devices()
        return 0

    try:
        import sounddevice as sd
    except Exception as exc:
        print("Audio backend unavailable: %s" % exc)
        print("Install PortAudio (linux: sudo apt install libportaudio2) and sounddevice.")
        return 1

    try:
        choice = audio_backend.resolve_output(
            sd, hostapi=args.hostapi, device=args.audio_device,
            prefer_exclusive=not args.shared,
        )
    except Exception as exc:
        print("Could not select audio output: %s" % exc)
        return 1

    samplerate = args.samplerate or audio_backend.default_samplerate(
        sd, choice["device"], SAMPLE_RATE
    )
    engine = SynthEngine(sr=samplerate, block_size=args.blocksize,
                         max_voices=args.voices)
    engine.set_lpf_mode(args.lpf_mode)

    config_dir, migration_message = resolve_config_dir(args.config_dir)
    if migration_message:
        print(migration_message)
    store = ProfileStore(config_dir)
    try:
        profile = store.open_active(args.profile)
        saving = True
    except OSError as exc:
        print("Profiles unavailable (%s); using in-memory defaults, nothing will be saved" % exc)
        profile = default_profile()
        saving = False
    for warning in store.warnings:
        print("Profiles: %s" % warning)
    registry = build_registry(engine)
    patch_defaults = capture(registry)
    patch_store = PatchStore(store.directory)
    try:
        patch_store.ensure_init(patch_defaults)
        warnings, applied_patch = load_startup_patch(
            registry, patch_store, patch_defaults, args.patch)
    except OSError as exc:
        print("Patches unavailable (%s); using factory defaults, nothing will be saved" % exc)
        patch_store = None
        warnings = []
        applied_patch = None
    if patch_store is not None:
        warnings += patch_store.warnings
    for warning in warnings:
        print("Patches: %s" % warning)
    router = MidiRouter(registry, profile)
    router.on_profile_changed = store.save if saving else None
    midi = MidiInput(engine, ports=args.input, channel=args.channel, router=router)
    opened = []
    try:
        opened = midi.start()
        print("MIDI inputs: %s" % ", ".join(opened))
    except Exception as exc:
        print("MIDI unavailable (%s); running without MIDI input" % exc)

    stream = None
    cb_state = CallbackState()
    recorder = Recorder()
    cb_state.recorder = recorder

    def callback(outdata, frames, time_info, status):
        render_into(outdata, engine, frames, cb_state)

    try:
        stream, choice = open_output_stream(sd, choice, args, samplerate, callback)
        stream.start()
    except Exception as exc:
        print("Could not open audio output: %s" % exc)
        print("Try --list to see devices, or --hostapi / --audio-device / --samplerate.")
        midi.stop()
        return 1

    mode = "exclusive" if choice.get("exclusive") else "shared"
    print("Output: %s via %s (%s)" % (choice["device_name"], choice["hostapi"], mode))
    try:
        lat = stream.latency[1]
        if lat:
            print("Latency: %.1f ms output @ %d Hz, block %d"
                  % (lat * 1000.0, samplerate, args.blocksize))
    except Exception:
        pass
    print("Playing. Press Ctrl+C to stop.")
    try:
        if not args.no_gui and launch_gui(
                engine, registry, router, store, opened, midi.stop,
                patch_store=patch_store, patch_defaults=patch_defaults,
                recorder=recorder, initial_patch=applied_patch or INIT_NAME):
            pass
        elif args.no_console:
            while True:
                time.sleep(0.2)
        else:
            console_loop(engine, registry, patch_store, patch_defaults,
                         recorder=recorder, config_dir=store.directory)
    except KeyboardInterrupt:
        pass
    finally:
        recorder.stop()
        if stream is not None:
            stream.stop()
            stream.close()
        midi.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
