import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.bridge import Bridge  # noqa: E402
from midi_synth.gui.main_window import MainWindow  # noqa: E402
from midi_synth.midi_router import MidiRouter  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402
from midi_synth.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _window(tmp_path, **engine_kw):
    engine = SynthEngine(sr=44100, block_size=64, **engine_kw)
    registry = build_registry(engine)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, store.open_active())
    bridge = Bridge(registry, router)
    return engine, MainWindow(engine, registry, router, store, ["P"], bridge)


def _click(label):
    QTest.mouseClick(label, Qt.LeftButton, Qt.NoModifier, QPoint(2, 2))


def hybrid(tmp_path, tails=6, voices=4):
    return _window(tmp_path, max_voices=voices, tail_slots=tails, tail_capacity=12)


def test_tail_label_text_and_tooltip(qapp, tmp_path):
    engine, w = hybrid(tmp_path)
    for n in (60, 62, 64):
        engine.note_on(n, 100)
    engine.note_off(60)
    w._tick()
    assert w.tail_label.text() == "Tails 1/6"
    tip = w.tail_label.toolTip()
    assert "Released notes still ringing / tail slots" in tip
    assert "Click to switch between 6 and 12 tail slots." in tip
    assert "shared" in tip


def test_voices_label_hybrid_and_classic(qapp, tmp_path):
    engine, w = hybrid(tmp_path)
    engine.note_on(60, 100)
    engine.note_on(62, 100)
    engine.note_off(60)
    w._tick()
    assert w.voice_label.text() == "Voices 1/4"
    assert w.voice_label.toolTip() == "0 voices stolen, 0 forced releases so far"
    for n in (64, 66, 68, 70):
        engine.note_on(n, 100)
    w._tick()
    assert w.voice_label.text() == "Voices 4/4"
    assert "1 forced releases" in w.voice_label.toolTip()
    cengine, cw = _window(tmp_path / "c", max_voices=2)
    cengine.note_on(60, 100)
    cw._tick()
    assert cw.voice_label.text() == "Voices: 1/2"
    assert cw.voice_label.toolTip() == "0 voices stolen so far"


def test_click_cycles_6_12_6(qapp, tmp_path):
    engine, w = hybrid(tmp_path)
    _click(w.tail_label)
    assert engine.tail_slots == 12 and w.tail_label.text() == "Tails 0/12"
    _click(w.tail_label)
    assert engine.tail_slots == 6 and w.tail_label.text() == "Tails 0/6"


def test_click_from_three_goes_to_twelve_and_zero_goes_to_six(qapp, tmp_path):
    engine, w = hybrid(tmp_path, tails=3)
    _click(w.tail_label)
    assert engine.tail_slots == 12
    engine.set_tail_slots(0)
    w._tick()
    assert w.tail_label.text() == "Tails off"
    _click(w.tail_label)
    assert engine.tail_slots == 6 and w.tail_label.text() == "Tails 0/6"


def test_engine_without_tails_shows_off_and_click_enables_six(qapp, tmp_path):
    engine, w = _window(tmp_path, max_voices=4)
    w._tick()
    assert w.tail_label.text() == "Tails off"
    assert w.voice_label.text() == "Voices: 0/4"
    _click(w.tail_label)
    assert engine.tail_slots == 0 and w.tail_label.text() == "Tails off"


def test_engine_with_capacity_but_zero_slots_click_enables_six(qapp, tmp_path):
    engine, w = hybrid(tmp_path, tails=0)
    w._tick()
    assert w.tail_label.text() == "Tails off"
    _click(w.tail_label)
    assert engine.tail_slots == 6
    assert w.voice_label.text().startswith("Voices ")


def test_tail_label_warns_when_full(qapp, tmp_path):
    engine, w = hybrid(tmp_path, tails=1, voices=3)
    engine.set_amp_release(5.0)
    for n in (60, 62):
        engine.note_on(n, 100)
    w._tick()
    assert w.tail_label.property("level") == "ok"
    engine.note_off(60)
    w._tick()
    assert w.tail_label.text() == "Tails 1/1"
    assert w.tail_label.property("level") == "warn"
    engine.set_tail_slots(6)
    w._tick()
    assert w.tail_label.property("level") == "ok"


def test_size_hint_still_fits(qapp, tmp_path):
    _, w = hybrid(tmp_path)
    hint = w.centralWidget().sizeHint()
    from tests.gui_limits import MAX_HINT_HEIGHT, MAX_HINT_WIDTH
    assert hint.width() <= MAX_HINT_WIDTH and hint.height() <= MAX_HINT_HEIGHT
