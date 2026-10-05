import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QPushButton  # noqa: E402

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.controls import ParamControl  # noqa: E402
from midi_synth.gui.knob import Knob  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def registry(qapp):
    return build_registry(SynthEngine(sr=44100, block_size=64, max_voices=2))


def test_knob_set_value_clamps_and_does_not_emit(qapp):
    knob = Knob(0.0, 1.0)
    seen = []
    knob.valueChanged.connect(seen.append)
    knob.setValue(5.0)
    assert knob.value() == 1.0
    assert seen == []


def test_knob_user_change_emits_and_double_click_resets(qapp):
    knob = Knob(0.0, 10.0, value=2.0)
    seen = []
    knob.valueChanged.connect(seen.append)
    knob.nudge(0.5)
    assert knob.value() == pytest.approx(7.0)
    knob.reset()
    assert knob.value() == 2.0
    assert seen == [pytest.approx(7.0), 2.0]


def test_continuous_control_writes_registry(registry):
    ctl = ParamControl(registry, registry["osc1_level"])
    assert isinstance(ctl.editor, Knob)
    ctl.editor.valueChanged.emit(0.25)
    assert registry.get("osc1_level") == 0.25


def test_choice_control_writes_and_refreshes(registry):
    ctl = ParamControl(registry, registry["osc1_waveform"])
    assert isinstance(ctl.editor, QComboBox)
    registry.set("osc1_waveform", "saw")
    ctl.refresh()
    assert ctl.editor.currentText() == "saw"
    ctl.editor.textActivated.emit("square")
    assert registry.get("osc1_waveform") == "square"


def test_toggle_control(registry):
    ctl = ParamControl(registry, registry["fx_delay"])
    assert isinstance(ctl.editor, QPushButton)
    ctl.editor.click()
    assert registry.get("fx_delay") is True
    registry.set("fx_delay", False)
    ctl.refresh()
    assert ctl.editor.isChecked() is False


def test_badge_and_learning_state(registry):
    ctl = ParamControl(registry, registry["fm_depth"])
    ctl.set_binding("CC 1")
    assert ctl.badge.text() == "CC 1"
    ctl.set_learning(True)
    assert "Move" in ctl.badge.text()
    ctl.set_learning(False)
    assert ctl.badge.text() == "CC 1"
    ctl.set_binding(None)
    assert ctl.badge.text() == ""


def test_learn_mode_click_requests_learn(registry):
    from PySide6.QtCore import Qt, QPointF, QEvent
    from PySide6.QtGui import QMouseEvent

    ctl = ParamControl(registry, registry["fm_depth"])
    asked = []
    ctl.learnRequested.connect(asked.append)
    ctl.set_learn_mode(True)
    pos = QPointF(5, 5)
    ctl.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert asked == ["fm_depth"]
    ctl.set_learn_mode(False)
    ctl.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert asked == ["fm_depth"]
