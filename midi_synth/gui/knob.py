import math

from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

_START_DEG = 225.0
_SWEEP_DEG = 270.0
_DRAG_PIXELS = 200.0


class Knob(QWidget):
    """Rotary knob. valueChanged is emitted only for user-driven changes."""

    valueChanged = Signal(float)

    def __init__(self, minimum=0.0, maximum=1.0, value=None, formatter=None, log=False, parent=None):
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._log = bool(log)
        self._value = self._clamp(self._min if value is None else value)
        self._default = self._value
        self._formatter = formatter or (lambda v: "%.2f" % v)
        self._drag_y = None
        self._drag_frac = 0.0
        self._learning = False
        self.setMinimumSize(72, 88)
        self.setCursor(Qt.SizeVerCursor)
        self.setFocusPolicy(Qt.WheelFocus)

    def _clamp(self, v):
        return min(max(float(v), self._min), self._max)

    def value(self):
        return self._value

    def fraction(self):
        if self._max == self._min:
            return 0.0
        if self._log:
            return math.log(self._value / self._min) / math.log(self._max / self._min)
        return (self._value - self._min) / (self._max - self._min)

    def _from_fraction(self, f):
        f = min(max(f, 0.0), 1.0)
        if self._log:
            return self._min * (self._max / self._min) ** f
        return self._min + f * (self._max - self._min)

    def setValue(self, v):
        self._value = self._clamp(v)
        self.update()

    def setLearning(self, on):
        self._learning = bool(on)
        self.update()

    def _emit(self, v):
        v = self._clamp(v)
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)

    def nudge(self, fraction_delta):
        """Move by a fraction of the full range (user-driven)."""
        self._emit(self._from_fraction(self.fraction() + fraction_delta))

    def reset(self):
        self._value = self._clamp(self._default)
        self.update()
        self.valueChanged.emit(self._value)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_y = event.position().y()
            self._drag_frac = self.fraction()

    def mouseMoveEvent(self, event):
        if self._drag_y is not None:
            delta = (self._drag_y - event.position().y()) / _DRAG_PIXELS
            self._emit(self._from_fraction(self._drag_frac + delta))

    def mouseReleaseEvent(self, event):
        self._drag_y = None

    def mouseDoubleClickEvent(self, event):
        self.reset()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        self.nudge(steps / 50.0)
        event.accept()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height() - 18) - 10
        rect = QRectF((self.width() - side) / 2.0, 5.0, side, side)
        pen = QPen(QColor("#3a3f4b"), 5.0, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(_START_DEG * 16), int(-_SWEEP_DEG * 16))
        frac = self.fraction()
        pen.setColor(QColor("#ffb74d") if self._learning else QColor("#4fc3f7"))
        p.setPen(pen)
        if frac > 0:
            p.drawArc(rect, int(_START_DEG * 16), int(-_SWEEP_DEG * 16 * frac))
        angle = math.radians(_START_DEG - _SWEEP_DEG * frac)
        c = rect.center()
        r = side / 2.0 - 9
        tip = QPointF(c.x() + r * math.cos(angle), c.y() - r * math.sin(angle))
        inner = QPointF(c.x() + 0.4 * (tip.x() - c.x()), c.y() + 0.4 * (tip.y() - c.y()))
        p.setPen(QPen(QColor("#e8eaf0"), 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(inner, tip)
        p.setPen(QColor("#c8ccd6"))
        p.drawText(QRectF(0, side + 6, self.width(), 16), Qt.AlignHCenter | Qt.AlignVCenter,
                   self._formatter(self._value))
