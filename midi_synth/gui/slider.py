import math

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QLabel, QSlider, QVBoxLayout, QWidget

_STEPS = 1000
_HEIGHT = 120


class ValueSlider(QWidget):
    """Vertical slider over a real-valued range, with a value label underneath.

    valueChanged is emitted only for user-driven changes (and double-click reset).
    """

    valueChanged = Signal(float)

    def __init__(self, minimum=0.0, maximum=1.0, value=None, formatter=None,
                 log=False, parent=None):
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._log = bool(log)
        self._formatter = formatter or (lambda v: "%.2f" % v)
        self._value = self._clamp(self._min if value is None else value)
        self._default = self._value

        self._slider = QSlider(Qt.Vertical)
        self._slider.setRange(0, _STEPS)
        self._slider.setFixedHeight(_HEIGHT)
        self._slider.installEventFilter(self)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignHCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._slider, 0, Qt.AlignHCenter)
        layout.addWidget(self.label)
        self._show(self._value)
        self._slider.valueChanged.connect(self._on_slider)

    def _clamp(self, v):
        return min(max(float(v), self._min), self._max)

    def _to_step(self, v):
        if self._max == self._min:
            return 0
        if self._log:
            frac = math.log(v / self._min) / math.log(self._max / self._min)
        else:
            frac = (v - self._min) / (self._max - self._min)
        return int(round(min(max(frac, 0.0), 1.0) * _STEPS))

    def _from_step(self, step):
        frac = min(max(step, 0), _STEPS) / float(_STEPS)
        if self._log:
            return self._min * (self._max / self._min) ** frac
        return self._min + frac * (self._max - self._min)

    def _show(self, v):
        self._slider.blockSignals(True)
        self._slider.setValue(self._to_step(v))
        self._slider.blockSignals(False)
        self.label.setText(self._formatter(v))

    def value(self):
        return self._value

    def setValue(self, v):
        self._value = self._clamp(v)
        self._show(self._value)

    def setLearning(self, on):
        self.setProperty("learning", bool(on))
        self._slider.setStyleSheet(
            "QSlider::handle:vertical { background: #ffb74d; }" if on else "")

    def _on_slider(self, step):
        self._value = self._clamp(self._from_step(step))
        self.label.setText(self._formatter(self._value))
        self.valueChanged.emit(self._value)

    def reset(self):
        self._value = self._clamp(self._default)
        self._show(self._value)
        self.valueChanged.emit(self._value)

    def eventFilter(self, obj, event):
        if obj is self._slider and event.type() == QEvent.MouseButtonDblClick:
            self.reset()
            return True
        return super().eventFilter(obj, event)

    def mouseDoubleClickEvent(self, event):
        self.reset()
