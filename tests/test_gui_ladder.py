import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox  # noqa: E402

from tests.test_gui_window import _fit, _make_rig, qapp  # noqa: E402,F401


@pytest.fixture
def rig(qapp, tmp_path):
    return _make_rig(tmp_path, 2)


def test_slope_combo_defaults_to_12_and_reaches_engine(rig):
    engine, _, _, _, window = rig
    editor = window.controls["lpf_slope"].editor
    assert isinstance(editor, QComboBox)
    assert [editor.itemText(i) for i in range(editor.count())] == ["12 dB", "24 dB"]
    assert editor.currentText() == "12 dB"
    editor.setCurrentText("24 dB")
    editor.textActivated.emit("24 dB")
    assert engine.params["lpf_slope"] == "24 dB"


def test_filter_group_layout_is_coherent_and_window_fits(rig):
    *_, window = rig
    hint = window.sizeHint()
    from tests.gui_limits import MAX_HINT_HEIGHT, MAX_HINT_WIDTH
    assert hint.width() <= MAX_HINT_WIDTH and hint.height() <= MAX_HINT_HEIGHT
    _fit(window, 1700, 1000)
    QApplication.processEvents()
    box = next(b for b in window.findChildren(QGroupBox) if b.title() == "Filter")
    ids = ("lpf_cutoff", "lpf_resonance", "lpf_slope", "lpf_master",
           "flt_env_amount", "flt_keytrack", "flt_vel")
    rects = []
    for pid in ids:
        control = window.controls[pid]
        assert box.isAncestorOf(control)
        rect = control.geometry()
        assert control.isVisible() and rect.width() > 0 and rect.height() > 0
        rects.append(rect)
    for i, a in enumerate(rects):
        assert box.rect().contains(a)
        for b in rects[i + 1:]:
            assert not a.intersects(b)
    # the Filter row is no taller than its neighbour in the same grid row
    boxes = {b.title(): b for b in window.findChildren(QGroupBox)}
    assert boxes["Filter"].geometry().height() == boxes["Filter Env"].geometry().height()
