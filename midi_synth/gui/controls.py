from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QLabel, QMenu, QPushButton, QVBoxLayout,
)

from ..params import CHOICE, CONTINUOUS, TOGGLE
from .knob import Knob
from .slider import ValueSlider


class ParamControl(QFrame):
    """One GUI control bound to one registry param, with a MIDI-learn badge."""

    learnRequested = Signal(str)
    clearRequested = Signal(str)

    def __init__(self, registry, param, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.param = param
        self._learn_mode = False
        self._learning = False
        self._binding = None
        self.setObjectName("control")
        if param.tooltip:
            self.setToolTip(param.tooltip)

        self.title = QLabel(param.label)
        self.title.setAlignment(Qt.AlignHCenter)
        self.editor = self._make_editor()
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        self.badge.setAlignment(Qt.AlignHCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(self.title)
        layout.addWidget(self.editor, 0, Qt.AlignHCenter)
        layout.addWidget(self.badge)
        self.refresh()

    def _make_editor(self):
        param, registry = self.param, self.registry
        if param.kind == CONTINUOUS:
            cls = ValueSlider if param.widget == "slider" else Knob
            editor = cls(param.minimum, param.maximum, value=param.get(),
                         formatter=param.formatter or param.fmt.format,
                         log=(param.scale == "log"))
            editor.valueChanged.connect(lambda v: registry.set(param.id, v))
            return editor
        if param.kind == CHOICE:
            combo = QComboBox()
            combo.addItems(param.choices)
            combo.textActivated.connect(lambda text: registry.set(param.id, text))
            return combo
        button = QPushButton("Off")
        button.setCheckable(True)
        button.clicked.connect(lambda checked: registry.set(param.id, checked))
        return button

    def refresh(self):
        value = self.param.get()
        if self.param.kind == CONTINUOUS:
            self.editor.setValue(value)
        elif self.param.kind == CHOICE:
            self.editor.setCurrentText(value)
        else:
            self.editor.setChecked(bool(value))
            self.editor.setText("On" if value else "Off")

    def set_binding(self, text):
        self._binding = text
        self._update_badge()

    def set_learning(self, on):
        self._learning = bool(on)
        self.setProperty("learning", self._learning)
        self.style().unpolish(self)
        self.style().polish(self)
        if isinstance(self.editor, (Knob, ValueSlider)):
            self.editor.setLearning(on)
        self._update_badge()

    def set_learn_mode(self, on):
        self._learn_mode = bool(on)
        self.editor.setAttribute(Qt.WA_TransparentForMouseEvents, self._learn_mode)
        self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)

    def _update_badge(self):
        if self._learning:
            self.badge.setText("Move a control…")
        else:
            self.badge.setText(self._binding or "")

    def mousePressEvent(self, event):
        if self._learn_mode and event.button() == Qt.LeftButton:
            self.learnRequested.emit(self.param.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        learn = menu.addAction("MIDI Learn")
        clear = menu.addAction("Clear binding")
        clear.setEnabled(self._binding is not None)
        chosen = menu.exec(event.globalPos())
        if chosen is learn:
            self.learnRequested.emit(self.param.id)
        elif chosen is clear:
            self.clearRequested.emit(self.param.id)
