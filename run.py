import argparse
import sys
import time
from pathlib import Path

from midi_synth.config import SAMPLE_RATE, BLOCK_SIZE, MAX_VOICES, WAVEFORMS
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput
from midi_synth.midi_router import MidiRouter
from midi_synth.params import build_registry
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
    p.add_argument("--no-console", action="store_true", help="disable interactive command console")
    p.add_argument("--no-gui", action="store_true", help="run the console only, no window")
    p.add_argument("--profile", default=None, metavar="NAME",
                   help="MIDI binding profile to load (default: last used)")
    p.add_argument("--config-dir", default=None, metavar="PATH",
                   help="where profiles are stored (default: per-user config dir)")
    return p.parse_args(argv)


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
  wave1/wave2 <sine|square|saw|triangle>
  level1/level2 <0-1>        oscillator mix level (osc2 starts at 0)
  mode <off|fm|am|ring|sync> how osc1 modulates osc2
  mod <0-1>                  modulation amount (alias: fm)
  tune2 <-12..12>            osc2 coarse semitones
  cents2 <-0.5..0.5>         osc2 fine cents
  gain <0-1.2>               master volume
  alloff                     release all held notes
  status                     show current settings
  help                       show this help
  quit                       exit (Ctrl+C also works)"""


def console_loop(engine):
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
            elif cmd in ("wave1", "wave2"):
                wf = parts[1].lower()
                if wf not in WAVEFORMS:
                    print("unknown waveform")
                elif cmd == "wave1":
                    engine.set_osc1_waveform(wf)
                else:
                    engine.set_osc2_waveform(wf)
            elif cmd == "fx":
                name = parts[1].lower()
                action = parts[2].lower() if len(parts) > 2 else "toggle"
                if action == "toggle":
                    engine.toggle_effect(name)
                else:
                    engine.set_effect(name, action == "on")
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


def launch_gui(engine, registry, router, store, ports):
    try:
        from midi_synth.gui.app import run_gui
    except ImportError as exc:
        print("GUI unavailable (%s); using the console. Install it with: pip install PySide6" % exc)
        return False
    run_gui(engine, registry, router, store, ports)
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

    store = ProfileStore(Path(args.config_dir) if args.config_dir else default_config_dir())
    profile = store.open_active(args.profile)
    for warning in store.warnings:
        print("Profiles: %s" % warning)
    registry = build_registry(engine)
    router = MidiRouter(registry, profile)
    router.on_profile_changed = store.save
    midi = MidiInput(engine, ports=args.input, channel=args.channel, router=router)
    opened = []
    try:
        opened = midi.start()
        print("MIDI inputs: %s" % ", ".join(opened))
    except Exception as exc:
        print("MIDI unavailable (%s); running without MIDI input" % exc)

    stream = None

    def callback(outdata, frames, time_info, status):
        block = engine.render(frames)
        ch = outdata.shape[1]
        for c in range(ch):
            outdata[:, c] = block

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
        if not args.no_gui and launch_gui(engine, registry, router, store, opened):
            pass
        elif args.no_console:
            while True:
                time.sleep(0.2)
        else:
            console_loop(engine)
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
