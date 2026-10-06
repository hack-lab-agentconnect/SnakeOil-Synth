"""Stereo output level meter with falling peak markers and a latched clip light."""

import math
import time

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

FLOOR_DB = -60.0
YELLOW_DB = -12.0
RED_DB = -3.0
RELEASE_DB_S = 24.0
HOLD_SECONDS = 1.0
HOLD_FALL_DB_S = 12.0
CLIP_SECONDS = 2.0

BAR_WIDTH = 11
BAR_GAP = 4
BAR_HEIGHT = 110
CLIP_HEIGHT = 12
MARGIN = 3

GREEN = QColor("#43a047")
YELLOW = QColor("#fdd835")
RED = QColor("#e53935")
TRACK = QColor("#12141a")
CLIP_OFF = QColor("#3a2224")
CLIP_TEXT_OFF = QColor("#6a5658")
MARKER = QColor("#e8ecf5")


def level_to_db(peak):
    """Linear peak to dBFS, floored at FLOOR_DB (silence maps to the floor)."""
    peak = abs(peak)
    if peak <= 0.0:
        return FLOOR_DB
    return max(FLOOR_DB, 20.0 * math.log10(peak))


def db_to_fraction(db):
    """dBFS to a 0..1 bar fraction, linear in dB from FLOOR_DB to 0 dBFS."""
    return min(max((db - FLOOR_DB) / -FLOOR_DB, 0.0), 1.0)


class LevelMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bar_db = [FLOOR_DB, FLOOR_DB]
        self.hold_db = [FLOOR_DB, FLOOR_DB]
        self._hold_since = [0.0, 0.0]
        self._clip_until = None
        self._last = None
        self.clip_lit = False
        self.setToolTip(
            "Output level (dBFS). CLIP lights when the soft clipper is working hard; "
            "click to reset.")
        self.setFixedSize(self.sizeHint())

    def sizeHint(self):
        width = 2 * BAR_WIDTH + BAR_GAP + 2 * MARGIN
        return QSize(width, BAR_HEIGHT + CLIP_HEIGHT + 3 * MARGIN)

    def update_levels(self, peak_l, peak_r, clipped, now=None):
        if now is None:
            now = time.monotonic()
        dt = 0.0 if self._last is None else max(0.0, now - self._last)
        self._last = now
        for ch, peak in enumerate((peak_l, peak_r)):
            db = level_to_db(peak)
            if db >= self.bar_db[ch]:
                self.bar_db[ch] = db
            else:
                self.bar_db[ch] = max(db, self.bar_db[ch] - RELEASE_DB_S * dt)
            if db >= self.hold_db[ch]:
                self.hold_db[ch] = db
                self._hold_since[ch] = now
            else:
                falling = min(dt, now - self._hold_since[ch] - HOLD_SECONDS)
                if falling > 0.0:
                    self.hold_db[ch] = max(
                        self.bar_db[ch], FLOOR_DB, self.hold_db[ch] - HOLD_FALL_DB_S * falling)
        if clipped:
            self._clip_until = now + CLIP_SECONDS
        self.clip_lit = self._clip_until is not None and now < self._clip_until
        self.update()

    def mousePressEvent(self, event):
        self._clip_until = None
        self.clip_lit = False
        self.update()
        event.accept()

    def _bar_rect(self, ch):
        x = MARGIN + ch * (BAR_WIDTH + BAR_GAP)
        y = 2 * MARGIN + CLIP_HEIGHT
        return QRectF(x, y, BAR_WIDTH, BAR_HEIGHT)

    @staticmethod
    def _zone_color(db):
        if db >= RED_DB:
            return RED
        return YELLOW if db >= YELLOW_DB else GREEN

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.transparent)
        clip_rect = QRectF(MARGIN, MARGIN, self.width() - 2 * MARGIN, CLIP_HEIGHT)
        painter.fillRect(clip_rect, RED if self.clip_lit else CLIP_OFF)
        font = painter.font()
        font.setPixelSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(MARKER if self.clip_lit else CLIP_TEXT_OFF)
        painter.drawText(clip_rect, Qt.AlignCenter, "CLIP")
        edges = (FLOOR_DB, YELLOW_DB, RED_DB, 0.0)
        for ch in (0, 1):
            rect = self._bar_rect(ch)
            painter.fillRect(rect, TRACK)
            level = self.bar_db[ch]
            for lo, hi in zip(edges, edges[1:]):
                top = min(level, hi)
                if top <= lo:
                    continue
                y_top = rect.bottom() - db_to_fraction(top) * rect.height()
                y_bot = rect.bottom() - db_to_fraction(lo) * rect.height()
                painter.fillRect(
                    QRectF(rect.left(), y_top, rect.width(), y_bot - y_top),
                    self._zone_color(lo))
            hold = self.hold_db[ch]
            if hold > FLOOR_DB:
                y = rect.bottom() - db_to_fraction(hold) * rect.height()
                painter.fillRect(QRectF(rect.left(), max(y - 1.0, rect.top()),
                                        rect.width(), 2.0), MARKER)
        painter.end()
