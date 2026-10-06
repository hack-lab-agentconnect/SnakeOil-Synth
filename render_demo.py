import argparse
import sys
import wave

from midi_synth.config import SAMPLE_RATE, BLOCK_SIZE, MODES, DEFAULT_PWM, DEFAULT_SQUARE_LEVEL
from midi_synth.engine import SynthEngine


def build_engine(args):
    engine = SynthEngine(sr=args.samplerate, block_size=args.blocksize,
                         max_voices=args.voices)
    engine.set_osc1_square(not args.no_square_layer)
    engine.set_osc1_square_level(args.square_level)
    engine.set_osc1_pwm(args.pwm1)
    engine.set_osc2_pwm(args.pwm2)
    engine.set_osc_levels(args.level1, args.level2)
    engine.set_mod_mode(args.mode)
    engine.set_fm_depth(args.fm)
    engine.set_detune2(args.tune2, args.cents2)
    engine.set_master_gain(args.gain)
    for name in ("chorus", "delay", "reverb", "bitcrush"):
        engine.set_effect(name, name in args.effects)
    return engine


def render(engine, path, seconds, notes, release_tail=0.4):
    sr = engine.sr
    total = int(sr * seconds)
    gate_off_at = max(int(sr * (seconds - release_tail)), 1)
    for note in notes:
        engine.note_on(note, 100)
    frames = bytearray()  # interleaved L/R, 16-bit
    pos = 0
    released = False
    while pos < total:
        n = min(engine.block_size, total - pos)
        block = engine.render(n)
        frames.extend((block * 32767.0).astype("<i2").tobytes())
        pos += n
        if not released and pos >= gate_off_at:
            for note in notes:
                engine.note_off(note)
            released = True
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))
    return path


def parse_args(argv):
    p = argparse.ArgumentParser(description="Offline render of the MIDI synth to a WAV file")
    p.add_argument("--out", default="demo.wav")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--samplerate", type=int, default=SAMPLE_RATE)
    p.add_argument("--blocksize", type=int, default=BLOCK_SIZE)
    p.add_argument("--voices", type=int, default=12)
    p.add_argument("--notes", default="48,52,55,59,60,64,67,71,72,76,79,83",
                   help="comma-separated MIDI note numbers (up to 12)")
    p.add_argument("--no-square-layer", action="store_true", help="turn off the square layer over osc 1's saw")
    p.add_argument("--square-level", type=float, default=DEFAULT_SQUARE_LEVEL,
                   help="how much square is added over osc 1's saw (0-1)")
    p.add_argument("--pwm1", type=float, default=DEFAULT_PWM, help="osc 1 square-layer duty (0-0.5)")
    p.add_argument("--pwm2", type=float, default=DEFAULT_PWM, help="osc 2 square duty (0-0.5)")
    p.add_argument("--level1", type=float, default=1.0)
    p.add_argument("--level2", type=float, default=0.0)
    p.add_argument("--mode", choices=MODES, default="fm")
    p.add_argument("--fm", type=float, default=0.0)
    p.add_argument("--tune2", type=float, default=0.0)
    p.add_argument("--cents2", type=float, default=0.0)
    p.add_argument("--gain", type=float, default=0.8)
    p.add_argument("--effects", default="", help="comma-separated subset of chorus,delay,reverb,bitcrush")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    notes = [int(x) for x in args.notes.split(",") if x.strip()][:args.voices]
    args.effects = [e.strip() for e in args.effects.split(",") if e.strip()]
    engine = build_engine(args)
    path = render(engine, args.out, args.seconds, notes)
    print("wrote %s (%d notes, %.1fs)" % (path, len(notes), args.seconds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
