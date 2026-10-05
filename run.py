import argparse
import sys
import time
from pathlib import Path

from midi_synth.config import (
    SAMPLE_RATE, BLOCK_SIZE, MAX_VOICES, LPF_MODES, DEFAULT_LPF_MODE,
)
from midi_synth.bindings import default_profile
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput
from midi_synth.midi_router import MidiRouter
from midi_synth.params import build_registry
from midi_synth.patches import PatchError, PatchStore, apply as apply_patch, capture
from midi_synth.profiles import ProfileStore, default_config_dir


def parse_args(argv):
    p = argparse.ArgumentParser(
        prog="midi-synth",
        description="Real-time MIDI synth with dual oscillators and effects.",
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


def render_into(outdata, engine, frames, state):
    """Render a block into outdata; on any error output silence and report it once."""
    try:
        copy_block_to_output(outdata, engine.render(frames))
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
  square <on|off>            osc 1 square layer over the saw
  pwm1/pwm2 <0-0.5>          pulse width (osc 1 square layer / osc 2); 0.5 = square
  level1/level2 <0-1>        oscillator mix level (osc2 starts at 0)
  mode <off|fm|am|ring|sync> how osc1 modulates osc2
  mod <0-1>                  modulation amount (alias: fm)
  tune2 <-12..12>            osc2 coarse semitones
  cents2 <-0.5..0.5>         osc2 fine cents
  oct1 <on|off>              osc 1 one octave down
  oct2 <on|off>              osc 2 one octave up
  lpf <20-20000>             low-pass cutoff in Hz (20000 = off)
  lres <0-1>                 low-pass resonance
  lpfmode <voice|master>     filter placement
  adsr <a> <d> <s> <r>       amp envelope: attack, decay (s), sustain (0-1), release (s)
  gain <0-1.2>               master volume
  patch list                 list saved sound patches
  patch save <name>          save the current sound as a patch
  patch load <name>          load a patch
  patch delete <name>        delete a patch (Init cannot be deleted)
  alloff                     release all held notes
  status                     show current settings
  help                       show this help
  quit                       exit (Ctrl+C also works)"""


def load_startup_patch(registry, patch_store, defaults, name=None):
    """Apply `name` (or the last-used patch) and return warning strings.

    Anything unreadable or missing is reported and the factory sound stays.
    """
    warnings = []
    name = name or patch_store.last_used()
    if name:
        try:
            values = patch_store.load(name)
        except PatchError as exc:
            warnings.append("Patch %r not loaded (%s); using factory defaults" % (name, exc))
        else:
            warnings += apply_patch(registry, values, defaults)
            patch_store.set_last_used(name)
    return warnings


def patch_command(parts, registry, patch_store, defaults):
    usage = "usage: patch list | save <name> | load <name> | delete <name>"
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


def console_loop(engine, registry=None, patch_store=None, patch_defaults=None):
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
            elif cmd == "alloff":
                engine.all_notes_off()
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
                if on is None:
                    print("usage: %s <on|off>" % cmd)
                elif cmd == "pingpong":
                    engine.set_delay_pingpong(on)
                elif cmd == "square":
                    engine.set_osc1_square(on)
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
            elif cmd == "adsr":
                attack, decay, sustain, release = (float(x) for x in parts[1:5])
                if len(parts) != 5:
                    raise ValueError("adsr takes four values")
                engine.set_amp_attack(attack)
                engine.set_amp_decay(decay)
                engine.set_amp_sustain(sustain)
                engine.set_amp_release(release)
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
               patch_store=None, patch_defaults=None):
    try:
        from midi_synth.gui.app import run_gui
    except ImportError as exc:
        print("GUI unavailable (%s); using the console. Install it with: pip install PySide6" % exc)
        return False
    run_gui(engine, registry, router, store, ports, on_exit,
            patch_store=patch_store, patch_defaults=patch_defaults)
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

    store = ProfileStore(Path(args.config_dir) if args.config_dir else default_config_dir())
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
        warnings = load_startup_patch(registry, patch_store, patch_defaults, args.patch)
    except OSError as exc:
        print("Patches unavailable (%s); using factory defaults, nothing will be saved" % exc)
        patch_store = None
        warnings = []
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
                patch_store=patch_store, patch_defaults=patch_defaults):
            pass
        elif args.no_console:
            while True:
                time.sleep(0.2)
        else:
            console_loop(engine, registry, patch_store, patch_defaults)
    except KeyboardInterrupt:
        pass
    finally:
        if stream is not None:
            stream.stop()
            stream.close()
        midi.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
