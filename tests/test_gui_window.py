import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midi_synth.bindings import CC, Source  # noqa: E402
from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.bridge import Bridge  # noqa: E402
from midi_synth.gui.main_window import MainWindow  # noqa: E402
from midi_synth.midi_router import MidiRouter  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402
from midi_synth.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def rig(qapp, tmp_path):
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, store.open_active())
    router.on_profile_changed = store.save
    bridge = Bridge(registry, router)
    window = MainWindow(engine, registry, router, store, ["Test Port"], bridge)
    return engine, registry, router, store, window


def test_every_param_has_a_control(rig):
    _, registry, _, _, window = rig
    assert set(window.controls) == set(registry.ids())


def test_default_bindings_show_as_badges(rig):
    *_, window = rig
    assert window.controls["fm_depth"].badge.text() == "CC 1"


def test_gui_edit_reaches_engine(rig):
    engine, *_, window = rig
    window.controls["osc1_level"].editor.valueChanged.emit(0.4)
    assert engine.params["osc1_level"] == 0.4


def test_midi_change_moves_gui_control(rig):
    _, _, router, _, window = rig
    router.handle_cc(0, 7, 127)
    assert window.controls["master_gain"].editor.value() == pytest.approx(1.2)


def test_learn_flow_binds_saves_and_updates_badge(rig):
    _, _, router, store, window = rig
    window._on_learn_requested("osc1_level")
    assert router.armed == "osc1_level"
    assert "Move" in window.controls["osc1_level"].badge.text()
    router.handle_cc(2, 74, 10)
    assert window.controls["osc1_level"].badge.text() == "CC 74 ch3"
    assert window.controls["osc1_level"]._learning is False
    assert store.load("Default").source_for("osc1_level") == Source(CC, 74, 3)


def test_escape_cancels_learn(rig):
    _, _, router, _, window = rig
    window._on_learn_requested("osc1_level")
    window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert router.armed is None
    assert window.controls["osc1_level"]._learning is False


def test_clear_binding(rig):
    _, _, router, store, window = rig
    window._on_clear_requested("fm_depth")
    assert window.controls["fm_depth"].badge.text() == ""
    assert store.load("Default").source_for("fm_depth") is None


def test_profile_switch_swaps_bindings(rig):
    _, _, router, store, window = rig
    store.create("Blank")
    window._reload_profiles("Blank")
    window._switch("Blank")
    assert router.profile.name == "Blank"
    assert window.controls["fm_depth"].badge.text() == ""
    assert store.active_name() == "Blank"
    window._switch("Default")
    assert window.controls["fm_depth"].badge.text() == "CC 1"


def test_delete_and_default_protection(rig):
    _, _, _, store, window = rig
    assert window.btn["delete"].isEnabled() is False
    assert window.btn["reset"].isEnabled() is True
    store.create("X")
    window._reload_profiles("X")
    window._switch("X")
    assert window.btn["delete"].isEnabled() is True
    assert window.btn["reset"].isEnabled() is False


def test_last_message_shown_in_footer(rig):
    _, _, router, _, window = rig
    router.handle_cc(0, 99, 5)
    assert "CC 99 ch1 = 5" in window.msg_label.text()


def test_oscillator_groups_hold_their_controls(rig):
    *_, window = rig
    from PySide6.QtWidgets import QGroupBox
    from midi_synth.gui.controls import ParamControl

    def ids(title):
        box = next(b for b in window.findChildren(QGroupBox) if b.title() == title)
        return [c.param.id for c in box.findChildren(ParamControl)]

    assert ids("Oscillator 2") == [
        "osc2_level", "detune2_semitones", "detune2_cents", "osc2_pwm", "osc2_octave",
    ]
    assert ids("Oscillator 1") == [
        "osc1_level", "osc1_square", "osc1_pwm", "osc1_octave",
    ]
