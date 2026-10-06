import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QDoubleSpinBox, QLineEdit, QTextEdit,
)

from midi_synth.gui.qwerty import QwertyKeyboard  # noqa: E402

KEYS = [
    (Qt.Key_A, 0), (Qt.Key_W, 1), (Qt.Key_S, 2), (Qt.Key_E, 3), (Qt.Key_D, 4),
    (Qt.Key_F, 5), (Qt.Key_T, 6), (Qt.Key_G, 7), (Qt.Key_Y, 8), (Qt.Key_H, 9),
    (Qt.Key_U, 10), (Qt.Key_J, 11), (Qt.Key_K, 12), (Qt.Key_O, 13),
    (Qt.Key_L, 14), (Qt.Key_P, 15), (Qt.Key_Semicolon, 16),
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeEngine:
    def __init__(self):
        self.calls = []

    def note_on(self, note, velocity=100):
        self.calls.append(("on", note, velocity))

    def note_off(self, note):
        self.calls.append(("off", note))


@pytest.fixture
def kb(qapp):
    engine = FakeEngine()
    k = QwertyKeyboard(engine)
    k.focus_widget = lambda: None
    return k, engine


def press(k, key, mods=Qt.NoModifier, repeat=False):
    return k.eventFilter(None, QKeyEvent(QEvent.KeyPress, key, mods, "", repeat))


def release(k, key, mods=Qt.NoModifier, repeat=False):
    return k.eventFilter(None, QKeyEvent(QEvent.KeyRelease, key, mods, "", repeat))


@pytest.mark.parametrize("key,offset", KEYS)
def test_key_maps_to_chromatic_note(kb, key, offset):
    k, engine = kb
    assert press(k, key) is True
    assert engine.calls == [("on", 60 + offset, 100)]
    assert release(k, key) is True
    assert engine.calls[-1] == ("off", 60 + offset)


def test_octave_keys_and_clamp(kb):
    k, engine = kb
    assert press(k, Qt.Key_X) is True
    assert k.octave == 1
    for _ in range(10):
        press(k, Qt.Key_X)
    assert k.octave == 3
    for _ in range(10):
        press(k, Qt.Key_Z)
    assert k.octave == -3
    press(k, Qt.Key_A)
    assert engine.calls == [("on", 60 - 36, 100)]


def test_velocity_keys_and_clamp(kb):
    k, engine = kb
    assert k.velocity == 100
    press(k, Qt.Key_C)
    assert k.velocity == 90
    for _ in range(20):
        press(k, Qt.Key_C)
    assert k.velocity == 10
    for _ in range(20):
        press(k, Qt.Key_V)
    assert k.velocity == 127
    press(k, Qt.Key_A)
    assert engine.calls == [("on", 60, 127)]


def test_change_callback(qapp):
    seen = []
    k = QwertyKeyboard(FakeEngine(), on_change=lambda: seen.append(1))
    k.focus_widget = lambda: None
    press(k, Qt.Key_X)
    press(k, Qt.Key_V)
    assert len(seen) == 2
    assert k.status_text() == "Oct +1  Vel 110"


def test_status_text_default(kb):
    assert kb[0].status_text() == "Oct +0  Vel 100"


def test_autorepeat_ignored(kb):
    k, engine = kb
    press(k, Qt.Key_A)
    press(k, Qt.Key_A, repeat=True)
    release(k, Qt.Key_A, repeat=True)
    assert engine.calls == [("on", 60, 100)]
    press(k, Qt.Key_X, repeat=True)
    assert k.octave == 0
    release(k, Qt.Key_A)
    assert engine.calls == [("on", 60, 100), ("off", 60)]


@pytest.mark.parametrize("mod", [Qt.ControlModifier, Qt.AltModifier, Qt.MetaModifier])
def test_modifiers_ignored(kb, mod):
    k, engine = kb
    assert press(k, Qt.Key_A, mod) is False
    assert press(k, Qt.Key_X, mod) is False
    assert release(k, Qt.Key_A, mod) is False
    assert engine.calls == [] and k.octave == 0


@pytest.mark.parametrize("cls", [QLineEdit, QTextEdit, QDoubleSpinBox])
def test_text_widget_focus_ignored(qapp, cls):
    engine = FakeEngine()
    k = QwertyKeyboard(engine)
    w = cls()
    k.focus_widget = lambda: w
    assert press(k, Qt.Key_A) is False
    assert press(k, Qt.Key_X) is False
    assert engine.calls == [] and k.octave == 0


def test_combobox_focus_still_plays(qapp):
    engine = FakeEngine()
    k = QwertyKeyboard(engine)
    combo = QComboBox()
    k.focus_widget = lambda: combo
    assert press(k, Qt.Key_A) is True
    assert engine.calls == [("on", 60, 100)]


def test_unmapped_key_not_consumed(kb):
    k, engine = kb
    assert press(k, Qt.Key_Escape) is False
    assert press(k, Qt.Key_B) is False
    assert release(k, Qt.Key_B) is False
    assert engine.calls == []


def test_release_uses_original_note_after_octave_change(kb):
    k, engine = kb
    press(k, Qt.Key_A)
    press(k, Qt.Key_X)
    release(k, Qt.Key_A)
    assert engine.calls == [("on", 60, 100), ("off", 60)]
    press(k, Qt.Key_A)
    assert engine.calls[-1] == ("on", 72, 100)


def test_release_without_press_does_nothing(kb):
    k, engine = kb
    assert release(k, Qt.Key_A) is False
    assert engine.calls == []


def test_release_all(kb):
    k, engine = kb
    press(k, Qt.Key_A)
    press(k, Qt.Key_D)
    press(k, Qt.Key_X)
    press(k, Qt.Key_G)
    engine.calls.clear()
    k.release_all()
    assert sorted(engine.calls) == [("off", 60), ("off", 64), ("off", 79)]
    engine.calls.clear()
    k.release_all()
    assert engine.calls == []
    release(k, Qt.Key_A)
    assert engine.calls == []


def test_toggle_off_releases_and_ignores(kb):
    k, engine = kb
    press(k, Qt.Key_A)
    engine.calls.clear()
    k.set_enabled(False)
    assert engine.calls == [("off", 60)]
    assert press(k, Qt.Key_A) is False
    assert engine.calls == [("off", 60)]
    k.set_enabled(True)
    assert press(k, Qt.Key_A) is True


def test_non_key_events_pass_through(kb):
    k, _ = kb
    assert k.eventFilter(None, QEvent(QEvent.Enter)) is False


# ---- main window integration ------------------------------------------

def make_window(qapp, tmp_path, **kwargs):
    from midi_synth.engine import SynthEngine
    from midi_synth.gui.bridge import Bridge
    from midi_synth.gui.main_window import MainWindow
    from midi_synth.midi_router import MidiRouter
    from midi_synth.params import build_registry
    from midi_synth.profiles import ProfileStore

    engine = SynthEngine(sr=44100, block_size=64, max_voices=4)
    registry = build_registry(engine)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, store.open_active())
    window = MainWindow(engine, registry, router, store, [], Bridge(registry, router),
                        **kwargs)
    return engine, window


def test_window_has_toggle_and_status_label(qapp, tmp_path):
    engine, window = make_window(qapp, tmp_path)
    assert window.qwerty_btn.text() == "QWERTY keys"
    assert window.qwerty_btn.isCheckable() and window.qwerty_btn.isChecked()
    assert window.qwerty_label.text() == "Oct +0  Vel 100"
    window.qwerty.focus_widget = lambda: None
    press(window.qwerty, Qt.Key_X)
    assert window.qwerty_label.text() == "Oct +1  Vel 100"


def test_window_toggle_off_releases_notes(qapp, tmp_path):
    engine, window = make_window(qapp, tmp_path)
    window.qwerty.focus_widget = lambda: None
    press(window.qwerty, Qt.Key_A)
    assert engine.active_note_count() == 1
    window.qwerty_btn.setChecked(False)
    assert not window.qwerty.enabled
    assert all(not v.gate for v in engine.voices)


def test_window_deactivation_releases_notes(qapp, tmp_path):
    engine, window = make_window(qapp, tmp_path)
    window.qwerty.focus_widget = lambda: None
    press(window.qwerty, Qt.Key_A)
    assert any(v.gate for v in engine.voices)
    window.event(QEvent(QEvent.WindowDeactivate))
    assert all(not v.gate for v in engine.voices)


def test_app_level_filter_is_installed(qapp, tmp_path):
    engine, window = make_window(qapp, tmp_path)
    window.qwerty.focus_widget = lambda: None
    combo = window.profile_box
    qapp.sendEvent(combo, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "a"))
    assert any(v.gate for v in engine.voices)
    qapp.sendEvent(combo, QKeyEvent(QEvent.KeyRelease, Qt.Key_A, Qt.NoModifier, "a"))
    assert all(not v.gate for v in engine.voices)


def test_escape_still_cancels_learn(qapp, tmp_path):
    engine, window = make_window(qapp, tmp_path)
    window._on_learn_requested("osc1_level")
    window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert window.router.armed is None
