import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QGroupBox  # noqa: E402

from midi_synth.gui.meter import (  # noqa: E402
    FLOOR_DB, HOLD_FALL_DB_S, HOLD_SECONDS, CLIP_SECONDS, RELEASE_DB_S,
    LevelMeter, db_to_fraction, level_to_db,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def meter(qapp):
    return LevelMeter()


def test_level_to_db_mapping():
    assert level_to_db(1.0) == pytest.approx(0.0)
    assert level_to_db(0.5) == pytest.approx(-6.0206, abs=1e-3)
    assert level_to_db(0.0) == FLOOR_DB == -60.0
    assert level_to_db(1e-9) == -60.0
    assert level_to_db(-0.5) == pytest.approx(level_to_db(0.5))


def test_db_to_fraction():
    assert db_to_fraction(-60.0) == 0.0
    assert db_to_fraction(0.0) == 1.0
    assert db_to_fraction(-30.0) == pytest.approx(0.5)
    assert db_to_fraction(-90.0) == 0.0
    assert db_to_fraction(6.0) == 1.0


def test_starts_at_floor(meter):
    assert meter.bar_db == [-60.0, -60.0]
    assert meter.hold_db == [-60.0, -60.0]
    assert meter.clip_lit is False


def test_instant_attack(meter):
    meter.update_levels(0.5, 0.1, False, now=0.0)
    assert meter.bar_db[0] == pytest.approx(level_to_db(0.5))
    assert meter.bar_db[1] == pytest.approx(level_to_db(0.1))


def test_release_decay_over_injected_time(meter):
    meter.update_levels(1.0, 1.0, False, now=0.0)
    meter.update_levels(0.0, 0.0, False, now=0.5)
    assert meter.bar_db[0] == pytest.approx(-RELEASE_DB_S * 0.5)
    meter.update_levels(0.0, 0.0, False, now=1.0)
    assert meter.bar_db[0] == pytest.approx(-RELEASE_DB_S * 1.0)
    meter.update_levels(0.0, 0.0, False, now=100.0)
    assert meter.bar_db == [-60.0, -60.0]


def test_bar_is_monotonic_while_released(meter):
    meter.update_levels(1.0, 1.0, False, now=0.0)
    prev = meter.bar_db[0]
    for i in range(1, 40):
        meter.update_levels(0.0, 0.0, False, now=i * 0.033)
        assert meter.bar_db[0] <= prev
        prev = meter.bar_db[0]


def test_bar_rises_instantly_from_partial_decay(meter):
    meter.update_levels(1.0, 1.0, False, now=0.0)
    meter.update_levels(0.0, 0.0, False, now=1.0)
    meter.update_levels(0.5, 0.5, False, now=1.033)
    assert meter.bar_db[0] == pytest.approx(level_to_db(0.5))


def test_hold_marker_holds_then_falls(meter):
    meter.update_levels(1.0, 0.5, False, now=0.0)
    assert meter.hold_db[0] == pytest.approx(0.0)
    meter.update_levels(0.0, 0.0, False, now=HOLD_SECONDS - 0.01)
    assert meter.hold_db[0] == pytest.approx(0.0)
    assert meter.hold_db[1] == pytest.approx(level_to_db(0.5))
    meter.update_levels(0.0, 0.0, False, now=HOLD_SECONDS + 1.0)
    assert meter.hold_db[0] == pytest.approx(-HOLD_FALL_DB_S * 1.0)
    meter.update_levels(0.0, 0.0, False, now=HOLD_SECONDS + 2.0)
    assert meter.hold_db[0] == pytest.approx(-HOLD_FALL_DB_S * 2.0)
    meter.update_levels(0.0, 0.0, False, now=HOLD_SECONDS + 50.0)
    assert meter.hold_db == [-60.0, -60.0]


def test_hold_never_below_bar_and_new_peak_resets_hold(meter):
    meter.update_levels(1.0, 1.0, False, now=0.0)
    for i in range(1, 100):
        meter.update_levels(0.1, 0.1, False, now=i * 0.05)
        assert meter.hold_db[0] >= meter.bar_db[0] - 1e-9
    meter.update_levels(0.3, 0.3, False, now=6.0)
    assert meter.hold_db[0] == pytest.approx(max(level_to_db(0.3), meter.hold_db[0]))
    meter.update_levels(1.0, 1.0, False, now=6.1)
    meter.update_levels(0.0, 0.0, False, now=7.0)
    assert meter.hold_db[0] == pytest.approx(0.0)


def test_clip_latches_for_two_seconds_and_relatches(meter):
    assert CLIP_SECONDS == 2.0
    meter.update_levels(0.5, 0.5, True, now=10.0)
    assert meter.clip_lit
    meter.update_levels(0.5, 0.5, False, now=11.9)
    assert meter.clip_lit
    meter.update_levels(0.5, 0.5, False, now=12.1)
    assert not meter.clip_lit
    meter.update_levels(0.5, 0.5, True, now=13.0)
    meter.update_levels(0.5, 0.5, True, now=14.5)
    meter.update_levels(0.5, 0.5, False, now=16.0)
    assert meter.clip_lit
    meter.update_levels(0.5, 0.5, False, now=16.6)
    assert not meter.clip_lit


def test_click_clears_clip(meter):
    meter.resize(meter.sizeHint())
    meter.update_levels(0.5, 0.5, True, now=1.0)
    assert meter.clip_lit
    QTest.mouseClick(meter, Qt.LeftButton, pos=QPoint(5, 5))
    assert not meter.clip_lit
    meter.update_levels(0.5, 0.5, False, now=1.1)
    assert not meter.clip_lit


def test_now_defaults_to_monotonic_clock(meter):
    meter.update_levels(1.0, 1.0, True)
    assert meter.clip_lit
    assert meter.bar_db[0] == pytest.approx(0.0)


def test_paint_runs_in_all_states(meter):
    meter.resize(meter.sizeHint())
    assert not meter.grab().isNull()
    meter.update_levels(1.0, 0.3, True, now=0.0)
    meter.update_levels(0.5, 0.0, True, now=0.5)
    image = meter.grab().toImage()
    assert image.width() == meter.width() and image.height() == meter.height()
    meter.update_levels(10.0, 0.0, False, now=0.6)
    assert not meter.grab().isNull()


def test_clip_light_paints_red(meter):
    meter.resize(meter.sizeHint())
    before = meter.grab().toImage()
    meter.update_levels(0.0, 0.0, True, now=0.0)
    after = meter.grab().toImage()
    assert before != after
