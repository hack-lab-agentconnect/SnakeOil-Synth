"""Render benchmark: ms per block and share of the real-time block budget."""
import argparse
import time

from midi_synth.engine import SynthEngine


def fx(*names):
    return lambda e: [e.set_effect(n, True) for n in names]


CASES = [
    ("defaults", lambda e: None),
    ("osc2 audible (level 1, FM)",
     lambda e: (e.set_osc_level(2, 1.0), e.set_mod_mode("fm"))),
    ("LPF off", lambda e: e.set_lpf_cutoff(20000)),
    ("LPF master mode", lambda e: e.set_lpf_mode("master")),
    ("chorus", fx("chorus")),
    ("delay", fx("delay")),
    ("delay ping-pong", lambda e: (e.set_effect("delay", True), e.set_delay_pingpong(True))),
    ("reverb", fx("reverb")),
    ("bitcrush", fx("bitcrush")),
    ("LFO pitch depth 1", lambda e: (e.set_lfo_depth(1.0), e.set_lfo_dest("pitch"))),
    ("LFO filter depth 1", lambda e: (e.set_lfo_depth(1.0), e.set_lfo_dest("filter"))),
    ("LFO filter, master mode",
     lambda e: (e.set_lfo_depth(1.0), e.set_lfo_dest("filter"), e.set_lpf_mode("master"))),
    ("LFO pwm depth 1", lambda e: (e.set_lfo_depth(1.0), e.set_lfo_dest("pwm"))),
    ("LFO amp depth 1", lambda e: (e.set_lfo_depth(1.0), e.set_lfo_dest("amp"))),
    ("LFO 2 pitch depth 1", lambda e: (e.set_lfo2_depth(1.0), e.set_lfo2_dest("pitch"))),
    ("LFO 1 pitch + LFO 2 amp",
     lambda e: (e.set_lfo_depth(1.0), e.set_lfo_dest("pitch"),
                e.set_lfo2_depth(1.0), e.set_lfo2_dest("amp"))),
    ("matrix: wheel -> cutoff",
     lambda e: (e.set_mod_src(1, "Mod Wheel"), e.set_mod_amt(1, 0.8),
                e.set_mod_dst(1, "Filter: Cutoff"), e.set_mod_wheel(0.7))),
    ("matrix: LFO 1 + note rows",
     lambda e: (e.set_mod_src(1, "LFO 1"), e.set_mod_amt(1, 0.5),
                e.set_mod_dst(1, "Filter: Cutoff"),
                e.set_mod_src(2, "Note Number"), e.set_mod_amt(2, 0.6),
                e.set_mod_dst(2, "Filter: Resonance"),
                e.set_osc_level(2, 0.8), e.set_lpf_resonance(0.3),
                e.set_mod_src(3, "Note Number"), e.set_mod_amt(3, -0.5),
                e.set_mod_dst(3, "Osc 2: Level"),
                e.set_mod_src(4, "LFO 1"), e.set_mod_amt(4, 0.4),
                e.set_mod_dst(4, "Osc 1: Level"))),
    ("matrix: unison 12 detune/spread + ADSR by note",
     lambda e: (e.set_unison_voices(12), e.set_mod_wheel(0.8),
                e.set_mod_src(1, "Mod Wheel"), e.set_mod_amt(1, 0.5),
                e.set_mod_dst(1, "Unison: Detune"),
                e.set_mod_src(2, "LFO 1"), e.set_mod_amt(2, 0.5),
                e.set_mod_dst(2, "Unison: Spread"),
                e.set_mod_src(3, "Note Number"), e.set_mod_amt(3, 0.6),
                e.set_mod_dst(3, "Amp Env: Decay"),
                e.set_mod_src(4, "Note Number"), e.set_mod_amt(4, -0.4),
                e.set_mod_dst(4, "Filter Env: Release"))),
    ("matrix: ADSR x8 by note, all four effects",
     lambda e: (fx("chorus", "delay", "reverb", "bitcrush")(e), note_rows(e, ENV_DESTS))),
    ("matrix: effects (delay time/fb, reverb size)",
     lambda e: (fx("chorus", "delay", "reverb", "bitcrush")(e), e.set_mod_wheel(0.7),
                e.set_mod_src(1, "LFO 1"), e.set_mod_amt(1, 0.3),
                e.set_mod_dst(1, "Delay: Time"),
                e.set_mod_src(2, "LFO 1"), e.set_mod_amt(2, 0.5),
                e.set_mod_dst(2, "Delay: Feedback"),
                e.set_mod_src(3, "Mod Wheel"), e.set_mod_amt(3, 0.4),
                e.set_mod_dst(3, "Reverb: Size"),
                e.set_mod_src(4, "Mod Wheel"), e.set_mod_amt(4, 0.5),
                e.set_mod_dst(4, "Chorus: Depth"))),
    ("noise white 0.5",
     lambda e: (e.set_noise_level(0.5), e.set_noise_color("white"))),
    ("noise pink + all effects",
     lambda e: (e.set_noise_level(0.5), e.set_noise_color("pink"),
                fx("chorus", "delay", "reverb", "bitcrush")(e))),
    ("unison 5", lambda e: e.set_unison_voices(5)),
    ("unison 12, all four effects",
     lambda e: (e.set_unison_voices(12), fx("chorus", "delay", "reverb", "bitcrush")(e))),
    ("all four effects", fx("chorus", "delay", "reverb", "bitcrush")),
    ("all four effects + limiter",
     lambda e: (fx("chorus", "delay", "reverb", "bitcrush")(e), e.set_auto_limiter(True))),
    ("all effects + limiter working",
     lambda e: (fx("chorus", "delay", "reverb", "bitcrush")(e), e.set_auto_limiter(True),
                e.set_osc_level(2, 1.0), e.set_master_gain(1.5))),
]


ENV_DESTS = tuple("%s Env: %s" % (env, stage) for env in ("Amp", "Filter")
                  for stage in ("Attack", "Decay", "Sustain", "Release"))


def note_rows(e, dests):
    for slot, dest in enumerate(dests, 1):
        e.set_mod_src(slot, "Note Number")
        e.set_mod_amt(slot, 0.5)
        e.set_mod_dst(slot, dest)


def run(label, setup, sr, block, blocks):
    engine = SynthEngine(sr=sr, block_size=block, max_voices=12)
    setup(engine)
    for note in range(48, 60):
        engine.note_on(note, 100)
    engine.render(block)
    start = time.perf_counter()
    for _ in range(blocks):
        engine.render(block)
    ms = (time.perf_counter() - start) / blocks * 1000
    budget = block / sr * 1000
    print("%-30s %7.2f ms  %4.0f%% of %.1f ms" % (label, ms, 100 * ms / budget, budget))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--block", type=int, default=256)
    ap.add_argument("--blocks", type=int, default=300)
    args = ap.parse_args()
    for label, setup in CASES:
        run(label, setup, args.sr, args.block, args.blocks)


if __name__ == "__main__":
    main()
