from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit,
)

BASE_NOTE = 60
OCTAVE_MIN, OCTAVE_MAX = -3, 3
VELOCITY_MIN, VELOCITY_MAX, VELOCITY_STEP = 10, 127, 10
DEFAULT_VELOCITY = 100

NOTE_KEYS = {
    Qt.Key_A: 0, Qt.Key_W: 1, Qt.Key_S: 2, Qt.Key_E: 3, Qt.Key_D: 4,
    Qt.Key_F: 5, Qt.Key_T: 6, Qt.Key_G: 7, Qt.Key_Y: 8, Qt.Key_H: 9,
    Qt.Key_U: 10, Qt.Key_J: 11, Qt.Key_K: 12, Qt.Key_O: 13, Qt.Key_L: 14,
    Qt.Key_P: 15, Qt.Key_Semicolon: 16,
}
CONTROL_KEYS = (Qt.Key_Z, Qt.Key_X, Qt.Key_C, Qt.Key_V)
BLOCKING_MODIFIERS = (
    Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
TEXT_WIDGETS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


class QwertyKeyboard(QObject):
    """Turns computer-keyboard events into engine notes.

    Install it as an application-level event filter. It consumes only the
    events it acts on, and remembers which note each held key started so a
    release always ends the right note even if the octave changed meanwhile.
    """

    def __init__(self, engine, parent=None, on_change=None):
        super().__init__(parent)
        self.engine = engine
        self.on_change = on_change
        self.enabled = True
        self.octave = 0
        self.velocity = DEFAULT_VELOCITY
        self.held = {}
        self.focus_widget = QApplication.focusWidget

    def status_text(self):
        return "Oct %+d  Vel %d" % (self.octave, self.velocity)

    def set_enabled(self, on):
        self.enabled = bool(on)
        if not self.enabled:
            self.release_all()

    def release_all(self):
        held, self.held = self.held, {}
        for note in held.values():
            self.engine.note_off(note)

    def _changed(self):
        if self.on_change is not None:
            self.on_change()

    def _blocked(self, event):
        if event.modifiers() & BLOCKING_MODIFIERS:
            return True
        return isinstance(self.focus_widget(), TEXT_WIDGETS)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind not in (QEvent.KeyPress, QEvent.KeyRelease) or not self.enabled:
            return False
        key = event.key()
        if key not in NOTE_KEYS and key not in CONTROL_KEYS:
            return False
        if kind == QEvent.KeyRelease:
            return self._release(key, event)
        if self._blocked(event):
            return False
        if event.isAutoRepeat():
            return True
        if key in NOTE_KEYS:
            self._press_note(key)
        else:
            self._press_control(key)
        return True

    def _press_note(self, key):
        previous = self.held.pop(key, None)
        if previous is not None:
            self.engine.note_off(previous)
        note = BASE_NOTE + 12 * self.octave + NOTE_KEYS[key]
        self.held[key] = note
        self.engine.note_on(note, self.velocity)

    def _press_control(self, key):
        if key == Qt.Key_Z:
            self.octave = max(self.octave - 1, OCTAVE_MIN)
        elif key == Qt.Key_X:
            self.octave = min(self.octave + 1, OCTAVE_MAX)
        elif key == Qt.Key_C:
            self.velocity = max(self.velocity - VELOCITY_STEP, VELOCITY_MIN)
        else:
            self.velocity = min(self.velocity + VELOCITY_STEP, VELOCITY_MAX)
        self._changed()

    def _release(self, key, event):
        if key in self.held:
            if event.isAutoRepeat():
                return True
            self.engine.note_off(self.held.pop(key))
            return True
        return False
