import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.controls import ParamControl  # noqa: E402
from midi_synth.gui.slider import ValueSlider  # noqa: E402
from midi_synth.params import build_registry, format_seconds  # noqa: E402

IDS = ["amp_attack", "amp_decay", "amp_sustain", "amp_release"]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def engine_registry(qapp):
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    return engine, build_registry(engine)


def test_linear_endpoints_and_fixed_height(qapp):
    s = ValueSlider(0.0, 1.0, value=0.5)
    assert s._slider.minimumHeight() == s._slider.maximumHeight() == 120
    s._slider.setValue(0)
    assert s.value() == pytest.approx(0.0)
    s._slider.setValue(1000)
    assert s.value() == pytest.approx(1.0)
    s._slider.setValue(500)
    assert s.value() == pytest.approx(0.5)


def test_log_endpoints_and_midpoint(qapp):
    s = ValueSlider(0.001, 5.0, value=0.1, log=True)
    s._slider.setValue(0)
    assert s.value() == pytest.approx(0.001)
    s._slider.setValue(1000)
    assert s.value() == pytest.approx(5.0)
    s._slider.setValue(500)
    assert s.value() == pytest.approx((0.001 * 5.0) ** 0.5, rel=0.01)


def test_set_value_does_not_emit_and_clamps(qapp):
    s = ValueSlider(0.001, 5.0, value=0.1, log=True)
    seen = []
    s.valueChanged.connect(seen.append)
    s.setValue(1.0)
    assert seen == []
    assert s.value() == pytest.approx(1.0, rel=0.01)
    s.setValue(99.0)
    assert s.value() == pytest.approx(5.0)
    assert seen == []


def test_user_change_emits_real_value(qapp):
    s = ValueSlider(0.0, 10.0, value=2.0)
    seen = []
    s.valueChanged.connect(seen.append)
    s._slider.setValue(500)  # same path a drag takes
    assert seen == [pytest.approx(5.0)]


def test_double_click_resets_to_initial(qapp):
    s = ValueSlider(0.0, 10.0, value=2.0)
    s.setValue(8.0)
    seen = []
    s.valueChanged.connect(seen.append)
    pos = QPointF(5, 5)
    s.mouseDoubleClickEvent(QMouseEvent(
        QEvent.MouseButtonDblClick, pos, pos, Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))
    assert s.value() == pytest.approx(2.0, abs=0.01)
    assert seen and seen[-1] == pytest.approx(2.0, abs=0.01)


def test_value_label_follows_both_kinds_of_change(qapp):
    s = ValueSlider(0.001, 5.0, value=0.12, log=True, formatter=format_seconds)
    assert s.label.text() == "120 ms"
    s.setValue(1.5)
    assert s.label.text() == "1.50 s"
    s._slider.setValue(0)
    assert s.label.text() == "1 ms"


def test_control_builds_slider_and_round_trips(engine_registry):
    engine, reg = engine_registry
    ctl = ParamControl(reg, reg["amp_release"])
    assert isinstance(ctl.editor, ValueSlider)
    assert ctl.editor.value() == pytest.approx(0.18, rel=0.01)
    ctl.editor.valueChanged.emit(2.0)
    assert reg.get("amp_release") == 2.0
    assert engine.voices[0].env.release == 2.0
    reg.set("amp_release", 0.5)
    ctl.refresh()
    assert ctl.editor.value() == pytest.approx(0.5, rel=0.01)
    assert ctl.editor.label.text() == "500 ms"


def test_user_drag_reaches_engine(engine_registry):
    engine, reg = engine_registry
    ctl = ParamControl(reg, reg["amp_sustain"])
    ctl.editor._slider.setValue(250)
    assert engine.params["amp_sustain"] == pytest.approx(0.25)
    assert engine.voices[1].env.sustain == pytest.approx(0.25)


def test_learn_mode_click_on_slider_control(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["amp_attack"])
    asked = []
    ctl.learnRequested.connect(asked.append)
    ctl.set_learn_mode(True)
    assert ctl.editor.testAttribute(Qt.WA_TransparentForMouseEvents)
    pos = QPointF(5, 5)
    ctl.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))
    assert asked == ["amp_attack"]
    ctl.set_learn_mode(False)
    assert not ctl.editor.testAttribute(Qt.WA_TransparentForMouseEvents)


def test_learning_highlight_on_slider(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["amp_decay"])
    ctl.set_binding("CC 5")
    assert ctl.badge.text() == "CC 5"
    ctl.set_learning(True)
    assert ctl.property("learning") is True
    assert "Move" in ctl.badge.text()
    ctl.set_learning(False)
    assert ctl.badge.text() == "CC 5"


def test_window_envelope_group(qapp, tmp_path):
    from midi_synth.gui.bridge import Bridge
    from midi_synth.gui.main_window import GROUP_POSITIONS, MainWindow
    from midi_synth.midi_router import MidiRouter
    from midi_synth.profiles import ProfileStore
    from PySide6.QtWidgets import QGroupBox

    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    reg = build_registry(engine)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(reg, store.open_active())
    window = MainWindow(engine, reg, router, store, [], Bridge(reg, router))
    assert GROUP_POSITIONS["Amp Envelope"] == (2, 0, 1, 1)
    assert GROUP_POSITIONS["Filter Env"] == (2, 1, 1, 1)
    assert set(window.controls) == set(reg.ids())
    box = next(b for b in window.findChildren(QGroupBox) if b.title() == "Amp Envelope")
    layout = box.layout()
    widgets = [layout.itemAtPosition(0, c).widget() for c in range(4)]
    assert [w.param.id for w in widgets] == IDS
    assert all(isinstance(w.editor, ValueSlider) for w in widgets)
    window.close()
