import numpy as np
import pytest

from midi_synth.engine import SynthEngine
from midi_synth.params import build_registry
from run import copy_block_to_output

SR = 44100
BLOCK = 256


def make(voices=2):
    e = SynthEngine(sr=SR, block_size=BLOCK, max_voices=voices)
    e.set_osc_levels(1.0, 0.5)
    return e


def test_render_shape_and_dtype():
    e = make()
    e.note_on(60, 100)
    for n in (BLOCK, 100, 1):
        out = e.render(n)
        assert out.shape == (n, 2)
        assert out.dtype == np.float32
        assert out.flags["C_CONTIGUOUS"]
    assert e.render().shape == (BLOCK, 2)


def test_render_without_effects_has_shape_too():
    e = make()
    e.note_on(60, 100)
    assert e.render(64, apply_effects=False).shape == (64, 2)


def test_channels_identical_with_all_effects_off():
    e = make()
    e.note_on(60, 100)
    e.note_on(64, 100)
    for _ in range(10):
        out = e.render(BLOCK)
        assert np.array_equal(out[:, 0], out[:, 1])
    assert np.any(out[:, 0] != 0.0)


@pytest.mark.parametrize("name", ["chorus", "reverb"])
def test_channels_differ_with_chorus_or_reverb(name):
    e = make()
    e.set_effect(name, True)
    e.note_on(60, 100)
    out = np.concatenate([e.render(BLOCK) for _ in range(20)])
    assert not np.allclose(out[:, 0], out[:, 1])


def test_pingpong_default_off_and_round_trip():
    e = make()
    reg = build_registry(e)
    assert e.effects.delay.pingpong is False
    assert reg.get("fx_delay_pingpong") is False
    assert e.status()["delay_pingpong"] is False
    reg.set("fx_delay_pingpong", True)
    assert e.effects.delay.pingpong is True
    assert e.status()["delay_pingpong"] is True
    e.set_delay_pingpong(False)
    assert reg.get("fx_delay_pingpong") is False


def test_pingpong_registry_entry():
    reg = build_registry(make())
    p = reg["fx_delay_pingpong"]
    assert p.kind == "toggle" and p.group == "Effects"
    assert p.label == "Ping-pong" and p.under == "fx_delay_time"
    assert p.tooltip == "Bounce the echoes between the left and right speakers."
    ids = reg.ids()
    assert ids.index("fx_delay_pingpong") == ids.index("fx_delay_time") + 1


def test_pingpong_makes_channels_differ_through_engine():
    e = make()
    e.set_effect("delay", True)
    e.set_delay_time(200.0)
    e.set_delay_pingpong(True)
    e.note_on(60, 100)
    out = np.concatenate([e.render(BLOCK) for _ in range(120)])
    assert not np.allclose(out[:, 0], out[:, 1])


def block_of(frames, left=0.25, right=-0.5):
    block = np.empty((frames, 2), dtype=np.float32)
    block[:, 0] = left
    block[:, 1] = right
    return block


def test_copy_two_channels():
    block = block_of(8)
    out = np.full((8, 2), 9.0, dtype=np.float32)
    copy_block_to_output(out, block)
    assert np.array_equal(out, block)


def test_copy_one_channel_is_mean():
    block = block_of(8)
    out = np.full((8, 1), 9.0, dtype=np.float32)
    copy_block_to_output(out, block)
    assert np.allclose(out[:, 0], -0.125)


def test_copy_four_channels_zeroes_extras():
    block = block_of(8)
    out = np.full((8, 4), 9.0, dtype=np.float32)
    copy_block_to_output(out, block)
    assert np.array_equal(out[:, 0], block[:, 0])
    assert np.array_equal(out[:, 1], block[:, 1])
    assert np.all(out[:, 2:] == 0.0)


def test_render_demo_writes_interleaved_stereo_wav(tmp_path):
    import wave

    import render_demo

    path = str(tmp_path / "demo.wav")
    args = render_demo.parse_args(["--seconds", "0.5", "--effects", "chorus,reverb"])
    args.effects = ["chorus", "reverb"]
    engine = render_demo.build_engine(args)
    render_demo.render(engine, path, 0.5, [60, 64])
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 2 and w.getsampwidth() == 2
        assert w.getnframes() == int(w.getframerate() * 0.5)
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2)
    assert np.any(data[:, 0] != data[:, 1])
