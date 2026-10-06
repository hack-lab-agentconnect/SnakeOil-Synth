"""Audio callback guard, console on/off parsing and ring-buffer edge cases."""
import builtins

import numpy as np
import pytest

from midi_synth.effects import _interp_read
from run import CallbackState, console_loop, parse_on_off, render_into


class BrokenEngine:
    def render(self, frames):
        raise RuntimeError("boom")


class GoodEngine:
    def render(self, frames):
        return np.full((frames, 2), 0.25, dtype=np.float32)


def test_render_into_zeroes_output_and_does_not_raise(capsys):
    out = np.ones((16, 2), dtype=np.float32)
    render_into(out, BrokenEngine(), 16, CallbackState())
    assert not out.any()
    assert "boom" in capsys.readouterr().out


def test_render_into_reports_once(capsys):
    state = CallbackState()
    for _ in range(5):
        out = np.ones((8, 2), dtype=np.float32)
        render_into(out, BrokenEngine(), 8, state)
        assert not out.any()
    assert capsys.readouterr().out.count("boom") == 1


def test_render_into_normal_path(capsys):
    out = np.zeros((8, 2), dtype=np.float32)
    render_into(out, GoodEngine(), 8, CallbackState())
    assert np.all(out == 0.25)
    assert capsys.readouterr().out == ""


def test_interp_read_position_just_below_zero():
    buf = np.arange(8, dtype=np.float64)
    out = _interp_read(buf, 0, 1, 1e-17)
    assert out.shape == (1,)
    assert out[0] == pytest.approx(0.0, abs=1e-9)
    out = _interp_read(buf, 0, 3, np.array([1e-17, 1.0, 2.0]))
    assert np.all(np.isfinite(out))


@pytest.mark.parametrize("text,expected", [
    ("on", True), ("OFF", False), (" On ", True), ("maybe", None), ("", None),
    ("toggle", None),
])
def test_parse_on_off(text, expected):
    assert parse_on_off(text) is expected


def test_parse_on_off_toggle_when_allowed():
    assert parse_on_off("Toggle", allow_toggle=True) == "toggle"


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def rec(*args):
            self.calls.append((name, args))
        return rec


def drive(monkeypatch, capsys, lines):
    feed = iter(list(lines) + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    engine = Recorder()
    console_loop(engine)
    return engine.calls, capsys.readouterr().out


@pytest.mark.parametrize("cmd,method", [
    ("pingpong", "set_delay_pingpong"), ("square", "set_osc1_square"),
    ("oct1", "set_osc1_octave_down"), ("oct2", "set_osc2_octave_up"),
])
def test_console_on_off_commands(monkeypatch, capsys, cmd, method):
    calls, out = drive(monkeypatch, capsys, ["%s ON" % cmd, "%s off" % cmd])
    assert calls == [(method, (True,)), (method, (False,))]
    assert "usage" not in out


@pytest.mark.parametrize("cmd", ["pingpong", "square", "oct1", "oct2"])
@pytest.mark.parametrize("arg", ["", " maybe", " 1", " toggle"])
def test_console_on_off_rejects_other_words(monkeypatch, capsys, cmd, arg):
    calls, out = drive(monkeypatch, capsys, [cmd + arg])
    assert calls == []
    assert "usage: %s <on|off>" % cmd in out


def test_console_fx_parsing(monkeypatch, capsys):
    calls, out = drive(monkeypatch, capsys,
                       ["fx chorus on", "fx delay OFF", "fx reverb toggle",
                        "fx reverb", "fx chorus banana"])
    assert calls == [("set_effect", ("chorus", True)), ("set_effect", ("delay", False)),
                     ("toggle_effect", ("reverb",)), ("toggle_effect", ("reverb",))]
    assert out.count("usage: fx") == 1


def test_console_square_accepts_optional_level(monkeypatch, capsys):
    calls, out = drive(monkeypatch, capsys, ["square on 0.8", "square off 0", "square on"])
    assert calls == [("set_osc1_square", (True,)), ("set_osc1_square_level", (0.8,)),
                     ("set_osc1_square", (False,)), ("set_osc1_square_level", (0.0,)),
                     ("set_osc1_square", (True,))]
    assert "usage" not in out


@pytest.mark.parametrize("line", ["square on abc", "square on 0.5 1", "square on nan", "square maybe 0.5"])
def test_console_square_rejects_bad_level(monkeypatch, capsys, line):
    calls, out = drive(monkeypatch, capsys, [line])
    assert calls == []
    assert "usage: square <on|off> [level]" in out
