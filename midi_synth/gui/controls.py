from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox, QFrame, QLabel, QMenu, QPushButton, QVBoxLayout,
)

from ..params import CHOICE, CONTINUOUS, TOGGLE
from .hslider import BipolarSlider
from .knob import Knob
from .slider import ValueSlider


TITLE_WIDTH = 64
# Compact combos size from the longest choice in pixels (a character-count
# size would balloon with wide fonts and widen the whole window).
COMPACT_CHAR_PX = 6.0
COMPACT_COMBO_PAD = 30


def grouped_model(choices):
    """Item model for a choice combo whose names read 'Group: Item'.

    Names sharing the prefix before ':' sit under one disabled header row;
    names without ':' are top-level items. Item text is always the full name.
    """
    model = QStandardItemModel()
    header_font = QFont()
    header_font.setBold(True)
    current = None
    for name in choices:
        group = name.split(":", 1)[0] if ":" in name else None
        if group is not None and group != current:
            header = QStandardItem(group)
            header.setFlags(Qt.NoItemFlags)
            header.setFont(header_font)
            header.setForeground(QColor("#8f98ad"))
            header.setBackground(QColor("#232733"))
            model.appendRow(header)
        current = group
        model.appendRow(QStandardItem(name))
    return model


class ElidedLabel(QLabel):
    """Centered label that elides long text instead of widening its column."""

    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(min(hint.width(), TITLE_WIDTH), hint.height())

    def minimumSizeHint(self):
        return QSize(16, super().minimumSizeHint().height())

    def paintEvent(self, _event):
        painter = QPainter(self)
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        painter.drawText(self.rect(), Qt.AlignHCenter | Qt.AlignVCenter, text)


class ParamControl(QFrame):
    """One GUI control bound to one registry param, with a MIDI-learn badge."""

    learnRequested = Signal(str)
    clearRequested = Signal(str)

    def __init__(self, registry, param, parent=None, compact=False):
        super().__init__(parent)
        self.registry = registry
        self.param = param
        self.compact = bool(compact)
        self._learn_mode = False
        self._learning = False
        self._binding = None
        self.setObjectName("control")
        if param.tooltip:
            self.setToolTip(param.tooltip)

        if self.compact:
            self.title = None
            self.editor = self._make_editor()
            self.badge = QLabel("", self)
            self.badge.setObjectName("badge")
            self.badge.hide()
            layout = QVBoxLayout(self)
            layout.setContentsMargins(2, 1, 2, 1)
            layout.setSpacing(0)
            layout.addWidget(self.editor)
            self._update_badge()
            self.refresh()
            return

        self.title = ElidedLabel(param.label)
        self.title.setAlignment(Qt.AlignHCenter)
        if not param.tooltip:
            self.title.setToolTip(param.label)
        self.editor = self._make_editor()
        self.badge = QLabel("")
        self.badge.setObjectName("badge")
        self.badge.setAlignment(Qt.AlignHCenter)
        self.badge.setFixedHeight(12)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 2)
        layout.setSpacing(1)
        layout.addWidget(self.title)
        layout.addWidget(self.editor, 0, Qt.AlignHCenter)
        layout.addWidget(self.badge)
        self.refresh()

    def _make_editor(self):
        param, registry = self.param, self.registry
        if param.kind == CONTINUOUS and param.widget == "hslider":
            editor = BipolarSlider(value=param.get(),
                                   formatter=param.formatter or param.fmt.format)
            editor.valueChanged.connect(lambda v: registry.set(param.id, v))
            return editor
        if param.kind == CONTINUOUS:
            cls = ValueSlider if param.widget == "slider" else Knob
            editor = cls(param.minimum, param.maximum, value=param.get(),
                         formatter=param.formatter or param.fmt.format,
                         log=(param.scale == "log"))
            editor.valueChanged.connect(lambda v: registry.set(param.id, v))
            return editor
        if param.kind == CHOICE:
            combo = QComboBox()
            if self.compact:
                combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(4)
                longest = max((len(c) for c in param.choices), default=4)
                combo.setMinimumWidth(int(COMPACT_CHAR_PX * longest) + COMPACT_COMBO_PAD)
            if self.compact and any(":" in c for c in param.choices):
                combo.setModel(grouped_model(param.choices))
            else:
                combo.addItems(param.choices)
            if self.compact:
                combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 24)
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
        if isinstance(self.editor, (Knob, ValueSlider, BipolarSlider)):
            self.editor.setLearning(on)
        self._update_badge()

    def set_learn_mode(self, on):
        self._learn_mode = bool(on)
        self.editor.setAttribute(Qt.WA_TransparentForMouseEvents, self._learn_mode)
        self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)

    def _update_badge(self):
        if self.compact:
            lines = [self.param.label]
            if self.param.tooltip:
                lines.append(self.param.tooltip)
            if self._learning:
                lines.append("Move a control...")
            elif self._binding:
                lines.append("MIDI: " + self._binding)
            self.setToolTip("\n".join(lines))
            return
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
