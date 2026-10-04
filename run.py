import argparse
import sys
import time

from midi_synth.config import SAMPLE_RATE, BLOCK_SIZE, MAX_VOICES, WAVEFORMS
from midi_synth.engine import SynthEngine
from midi_synth.midi_input import MidiInput


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
    p.add_argument("--samplerate", type=int, default=SAMPLE_RATE)
    p.add_argument("--blocksize", type=int, default=BLOCK_SIZE)
    p.add_argument("--voices", type=int, default=MAX_VOICES, help="max simultaneous notes (1-12+)")
    p.add_argument("--audio-device", default=None, help="output device index or name")
    p.add_argument("--channels", type=int, default=2, help="output channels")
    p.add_argument("--no-console", action="store_true", help="disable interactive command console")
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
    print("Audio outputs:")
    try:
        import sounddevice as sd

        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_output_channels", 0) > 0:
                print("  [%d] %s (%d out)" % (idx, dev["name"], dev["max_output_channels"]))
    except Exception as exc:
        print("  (could not query audio: %s)" % exc)


def console_loop(engine):
    help_text = (
        "commands: fx <chorus|delay|reverb|bitcrush> <on|off|toggle>, "
        "wave1/wave2 <sine|square|saw|triangle>, fm <0-1>, "
        "tune2 <-12..12>, cents2 <-0.5..0.5>, gain <0-1.2>, alloff, status, quit"
    )
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
            elif cmd == "fm":
                engine.set_fm_depth(float(parts[1]))
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


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.list:
        list_devices()
        return 0

    engine = SynthEngine(sr=args.samplerate, block_size=args.blocksize,
                         max_voices=args.voices)

    try:
        import sounddevice as sd
    except Exception as exc:
        print("Audio backend unavailable: %s" % exc)
        print("Install PortAudio (linux: sudo apt install libportaudio2) and sounddevice.")
        return 1

    midi = MidiInput(engine, ports=args.input, channel=args.channel)
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
        if status:
            pass

    try:
        stream = sd.OutputStream(
            samplerate=args.samplerate,
            blocksize=args.blocksize,
            channels=args.channels,
            device=args.audio_device,
            dtype="float32",
            callback=callback,
        )
        stream.start()
    except Exception as exc:
        print("Could not open audio output: %s" % exc)
        midi.stop()
        return 1

    print("Playing. Press Ctrl+C to stop.")
    try:
        if args.no_console:
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
