from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

_STEPS = 1000
_MIN_WIDTH = 110
_HEIGHT = 22
_MARGIN = 6.0
_KEY_STEP = 10

_GROOVE = QColor("#2c3242")
_BORDER = QColor("#3d445a")
_POSITIVE = QColor("#1e88e5")
_NEGATIVE = QColor("#8e6bd8")
_HANDLE = QColor("#dfe3ec")
_LEARNING = QColor("#ffb74d")
_TEXT = QColor("#ffffff")


class BipolarSlider(QWidget):
    """Horizontal slider over [-1, 1] (centre = 0) with the readout drawn on it.

    valueChanged is emitted only for user-driven changes (drag, click, arrow
    keys and the double-click reset to 0); setValue never emits.
    """

    valueChanged = Signal(float)

    def __init__(self, value=0.0, formatter=None, parent=None):
        super().__init__(parent)
        self._formatter = formatter or (lambda v: "%+d%%" % round(v * 100.0))
        self._value = self._clamp(value)
        self._learning = False
        self.setMinimumSize(_MIN_WIDTH, _HEIGHT)
        self.setFixedHeight(_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)

    @staticmethod
    def _clamp(v):
        return min(max(float(v), -1.0), 1.0)

    def sizeHint(self):
        return QSize(_MIN_WIDTH, _HEIGHT)

    def value(self):
        return self._value

    def text(self):
        return self._formatter(self._value)

    def setValue(self, v):
        self._value = self._clamp(v)
        self.update()

    def setLearning(self, on):
        self._learning = bool(on)
        self.setProperty("learning", self._learning)
        self.update()

    def reset(self):
        self._value = 0.0
        self.update()
        self.valueChanged.emit(0.0)

    # ---- interaction --------------------------------------------------

    def _value_at(self, x):
        span = max(self.width() - 2 * _MARGIN, 1.0)
        frac = min(max((x - _MARGIN) / span, 0.0), 1.0)
        return round((frac * 2.0 - 1.0) * _STEPS) / _STEPS

    def _user_set(self, v):
        v = self._clamp(v)
        if v != self._value:
            self._value = v
            self.update()
            self.valueChanged.emit(v)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._user_set(self._value_at(event.position().x()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._user_set(self._value_at(event.position().x()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.reset()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_Down):
            self._user_set(self._value - _KEY_STEP / _STEPS)
        elif key in (Qt.Key_Right, Qt.Key_Up):
            self._user_set(self._value + _KEY_STEP / _STEPS)
        else:
            super().keyPressEvent(event)

    # ---- painting -----------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width, height = float(self.width()), float(self.height())
        groove = QRectF(1.5, 2.5, width - 3.0, height - 5.0)
        painter.setPen(QPen(_BORDER, 1))
        painter.setBrush(_GROOVE)
        painter.drawRoundedRect(groove, 4, 4)

        span = width - 2 * _MARGIN
        centre_x = _MARGIN + span / 2.0
        handle_x = _MARGIN + (self._value + 1.0) / 2.0 * span
        fill = QRectF(min(centre_x, handle_x), groove.top() + 1.5,
                      abs(handle_x - centre_x), groove.height() - 3.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_POSITIVE if self._value >= 0 else _NEGATIVE)
        painter.drawRect(fill)

        painter.setPen(QPen(_BORDER.lighter(160), 1))
        painter.drawLine(int(centre_x), int(groove.top()) + 1,
                         int(centre_x), int(groove.top()) + 4)
        painter.drawLine(int(centre_x), int(groove.bottom()) - 3,
                         int(centre_x), int(groove.bottom()))

        painter.setPen(QPen(_LEARNING if self._learning else _HANDLE, 2))
        painter.drawLine(int(handle_x), int(groove.top()),
                         int(handle_x), int(groove.bottom()))

        painter.setPen(_TEXT)
        painter.drawText(groove, Qt.AlignCenter, self.text())
        if self.hasFocus():
            painter.setPen(QPen(_LEARNING.darker(150), 1, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(groove, 4, 4)
