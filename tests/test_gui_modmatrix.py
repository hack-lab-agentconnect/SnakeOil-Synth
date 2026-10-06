import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QGroupBox  # noqa: E402

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.bridge import Bridge  # noqa: E402
from midi_synth.gui.controls import ParamControl  # noqa: E402
from midi_synth.gui.hslider import BipolarSlider  # noqa: E402
from midi_synth.gui.main_window import GROUP_POSITIONS, MOD_MATRIX_CELL, MainWindow  # noqa: E402
from midi_synth.midi_router import MidiRouter  # noqa: E402
from midi_synth.modmatrix import DEST_NAMES, NUM_SLOTS, SOURCES  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402
from midi_synth.patches import PatchStore, capture  # noqa: E402
from midi_synth.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def engine_registry(qapp):
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    return engine, build_registry(engine)


@pytest.fixture
def rig(qapp, tmp_path):
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    defaults = capture(registry)
    profiles = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, profiles.open_active())
    router.on_profile_changed = profiles.save
    bridge = Bridge(registry, router)
    patches = PatchStore(tmp_path / "cfg")
    patches.ensure_init(defaults)
    window = MainWindow(engine, registry, router, profiles, ["Port"], bridge,
                        patch_store=patches, patch_defaults=defaults)
    yield engine, registry, router, patches, window
    window.close()


# ---- BipolarSlider ----------------------------------------------------

def _click(slider, x):
    QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(int(x), 10))


def test_slider_starts_centred_with_compact_size(qapp):
    s = BipolarSlider()
    assert s.value() == 0.0
    assert 100 <= s.minimumWidth() <= 120
    assert 20 <= s.height() <= 24
    assert s.text() == "+0%"


def test_slider_mapping_endpoints_and_centre(qapp):
    s = BipolarSlider()
    s.resize(200, 22)
    seen = []
    s.valueChanged.connect(seen.append)
    _click(s, 0)
    assert seen[-1] == -1.0
    _click(s, 199)
    assert seen[-1] == 1.0
    _click(s, 100)
    assert abs(seen[-1]) <= 0.05
    assert all(isinstance(v, float) for v in seen)


def test_slider_set_value_does_not_emit_and_clamps(qapp):
    s = BipolarSlider()
    seen = []
    s.valueChanged.connect(seen.append)
    s.setValue(0.37)
    assert s.value() == pytest.approx(0.37)
    s.setValue(5)
    assert s.value() == 1.0
    s.setValue(-5)
    assert s.value() == -1.0
    assert seen == []


def test_slider_drag_emits_float(qapp):
    s = BipolarSlider()
    s.resize(200, 22)
    seen = []
    s.valueChanged.connect(seen.append)
    QTest.mousePress(s, Qt.LeftButton, pos=QPoint(100, 10))
    ev = QMouseEvent(QEvent.MouseMove, QPointF(170, 10), QPointF(170, 10),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    s.mouseMoveEvent(ev)
    QTest.mouseRelease(s, Qt.LeftButton, pos=QPoint(170, 10))
    assert seen[-1] > 0.3


def test_slider_double_click_resets_to_zero(qapp):
    s = BipolarSlider()
    s.resize(200, 22)
    s.setValue(0.8)
    seen = []
    s.valueChanged.connect(seen.append)
    QTest.mouseDClick(s, Qt.LeftButton, pos=QPoint(180, 10))
    assert s.value() == 0.0
    assert seen[-1] == 0.0


def test_slider_readout_uses_formatter(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["mod1_amt"], compact=True)
    ctl.editor.setValue(0.37)
    assert ctl.editor.text() == "+37%"
    ctl.editor.setValue(-1.0)
    assert ctl.editor.text() == "-100%"


def test_slider_learning_and_paint(qapp):
    s = BipolarSlider()
    s.resize(160, 22)
    s.setLearning(True)
    assert s.property("learning") is True
    for v in (-1.0, -0.4, 0.0, 0.6, 1.0):
        s.setValue(v)
        assert not s.grab().isNull()
    s.setLearning(False)
    assert s.property("learning") is False


# ---- compact ParamControl ---------------------------------------------

def test_compact_control_has_no_title_or_badge_row(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["mod1_src"], compact=True)
    assert ctl.layout().count() == 1
    assert ctl.layout().itemAt(0).widget() is ctl.editor
    assert isinstance(ctl.editor, QComboBox)


def test_compact_tooltip_carries_label_and_binding(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["mod1_amt"], compact=True)
    assert "Scale" in ctl.toolTip()
    assert "CC 74" not in ctl.toolTip()
    ctl.set_binding("CC 74")
    assert "CC 74" in ctl.toolTip()
    ctl.set_binding(None)
    assert "CC 74" not in ctl.toolTip()


def test_compact_learning_highlight_and_click(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["mod1_amt"], compact=True)
    asked = []
    ctl.learnRequested.connect(asked.append)
    ctl.set_learn_mode(True)
    pos = QPointF(1, 1)
    ctl.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))
    assert asked == ["mod1_amt"]
    ctl.set_learning(True)
    assert ctl.property("learning") is True
    assert ctl.editor.property("learning") is True
    ctl.set_learning(False)
    assert ctl.property("learning") is False


def test_non_compact_controls_unchanged(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["osc1_level"])
    assert ctl.layout().count() == 3


# ---- combos -----------------------------------------------------------

def _items(combo):
    model = combo.model()
    out = []
    for row in range(model.rowCount()):
        item = model.item(row)
        out.append((item.text(), bool(item.flags() & Qt.ItemIsEnabled)))
    return out


def test_source_combo_lists_sources(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["mod1_src"], compact=True)
    assert [ctl.editor.itemText(i) for i in range(ctl.editor.count())] == list(SOURCES)


def test_destination_combo_has_disabled_headers(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["mod1_dst"], compact=True)
    combo = ctl.editor
    items = _items(combo)
    assert items[0] == ("none", True)
    headers = [t for t, enabled in items if not enabled]
    assert headers == ["Osc 1", "Osc 2", "Filter", "Filter Env", "Amp Env", "Unison"]
    selectable = [t for t, enabled in items if enabled]
    assert sorted(selectable) == sorted(DEST_NAMES)
    assert len(selectable) == len(set(selectable))
    assert "Modulation Amount" in selectable
    # a header sits directly before the first entry of its group
    texts = [t for t, _ in items]
    assert texts[texts.index("Osc 1") + 1].startswith("Osc 1:")


def test_destination_selection_reaches_engine(engine_registry):
    engine, reg = engine_registry
    ctl = ParamControl(reg, reg["mod1_dst"], compact=True)
    combo = ctl.editor
    index = combo.findText("Filter: Cutoff")
    combo.setCurrentIndex(index)
    combo.textActivated.emit("Filter: Cutoff")
    assert engine.mod_rows[0][2] == "Filter: Cutoff"
    assert combo.currentText() == "Filter: Cutoff"


def test_destination_refresh_selects_the_entry(engine_registry):
    _, reg = engine_registry
    ctl = ParamControl(reg, reg["mod2_dst"], compact=True)
    for name in ("Osc 2: Tune", "Modulation Amount", "none", "Filter: Key Trk"):
        reg.set("mod2_dst", name)
        ctl.refresh()
        assert ctl.editor.currentText() == name
        assert ctl.editor.model().item(ctl.editor.currentIndex()).flags() & Qt.ItemIsEnabled


def test_combos_are_compact(engine_registry):
    _, reg = engine_registry
    for pid in ("mod1_src", "mod1_dst"):
        ctl = ParamControl(reg, reg[pid], compact=True)
        combo = ctl.editor
        assert (combo.sizeAdjustPolicy()
                == QComboBox.AdjustToMinimumContentsLengthWithIcon)


# ---- window -----------------------------------------------------------

def _box(window):
    return next(b for b in window.findChildren(QGroupBox) if b.title() == "Mod Matrix")


def test_matrix_lives_in_its_cell(rig):
    *_, window = rig
    assert GROUP_POSITIONS["Mod Matrix"] == MOD_MATRIX_CELL == (1, 4, 1, 1)


def test_every_matrix_param_has_a_control(rig):
    _, registry, *_, window = rig
    ids = {p.id for p in registry if p.group == "Mod Matrix"}
    assert len(ids) == 3 * NUM_SLOTS
    assert ids <= set(window.controls)
    assert set(window.controls) == set(registry.ids())
    assert isinstance(window.controls["mod1_amt"].editor, BipolarSlider)


def test_matrix_box_is_8_rows_of_3_aligned_controls(rig):
    *_, window = rig
    window.resize(1700, 1000)
    window.show()
    QApplication.processEvents()
    box = _box(window)
    cols = ("src", "amt", "dst")
    pos = {}
    for i in range(1, NUM_SLOTS + 1):
        for c in cols:
            ctl = window.controls["mod%d_%s" % (i, c)]
            assert box.isAncestorOf(ctl)
            pos[(i, c)] = ctl.mapTo(box, QPoint(0, 0))
            assert box.rect().contains(QRect(pos[(i, c)], ctl.size()))
    assert len(box.findChildren(ParamControl)) == 3 * NUM_SLOTS
    for c in cols:
        assert len({pos[(i, c)].x() for i in range(1, NUM_SLOTS + 1)}) == 1
    for i in range(1, NUM_SLOTS + 1):
        assert len({pos[(i, c)].y() for c in cols}) == 1
        assert pos[(i, "src")].x() < pos[(i, "amt")].x() < pos[(i, "dst")].x()
    ys = [pos[(i, "src")].y() for i in range(1, NUM_SLOTS + 1)]
    assert ys == sorted(set(ys))
    assert "relative" in box.toolTip().lower()
    assert "stays 0" in box.toolTip()


def test_matrix_box_neighbours_not_stretched(rig):
    *_, window = rig
    window.resize(window.sizeHint())
    window.show()
    QApplication.processEvents()
    boxes = {b.title(): b for b in window.findChildren(QGroupBox)}
    assert boxes["Mod Matrix"].geometry().top() == boxes["Filter"].geometry().top()
    assert boxes["Mod Matrix"].height() <= 380


def test_window_slider_and_combos_reach_engine(rig):
    engine, _, _, _, window = rig
    window.controls["mod1_amt"].editor.valueChanged.emit(0.5)
    assert engine.mod_rows[0][1] == pytest.approx(0.5)
    src = window.controls["mod1_src"].editor
    src.setCurrentText("LFO 2")
    src.textActivated.emit("LFO 2")
    assert engine.mod_rows[0][0] == "LFO 2"
    dst = window.controls["mod1_dst"].editor
    dst.setCurrentText("Osc 2: Level")
    dst.textActivated.emit("Osc 2: Level")
    assert engine.mod_rows[0][2] == "Osc 2: Level"


def test_registry_change_refreshes_widgets(rig):
    _, registry, _, _, window = rig
    registry.set("mod3_amt", -0.25)
    registry.set("mod3_src", "Aftertouch")
    registry.set("mod3_dst", "Filter: Resonance")
    assert window.controls["mod3_amt"].editor.value() == pytest.approx(-0.25)
    assert window.controls["mod3_src"].editor.currentText() == "Aftertouch"
    assert window.controls["mod3_dst"].editor.currentText() == "Filter: Resonance"


def test_learn_click_on_matrix_slider_binds_cc_and_drives_it(rig):
    engine, _, router, _, window = rig
    window.learn_btn.setChecked(True)
    ctl = window.controls["mod4_amt"]
    pos = QPointF(1, 1)
    ctl.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))
    assert router.armed == "mod4_amt"
    assert ctl.property("learning") is True
    router.handle_cc(0, 75, 127)
    assert "CC 75" in ctl.toolTip()
    router.handle_cc(0, 75, 0)
    assert ctl.editor.value() == pytest.approx(-1.0)
    assert engine.mod_rows[3][1] == pytest.approx(-1.0)
    window.learn_btn.setChecked(False)


def test_patch_apply_refreshes_matrix(rig):
    _, registry, _, patches, window = rig
    values = capture(registry)
    values.update({"mod1_src": "Note Number", "mod1_amt": 0.6,
                   "mod1_dst": "Osc 1: PWM", "mod8_src": "LFO 1",
                   "mod8_amt": -0.9, "mod8_dst": "Filter: Cutoff"})
    patches.save("Matrix", values)
    window._load_patch("Matrix")
    c = window.controls
    assert c["mod1_src"].editor.currentText() == "Note Number"
    assert c["mod1_amt"].editor.value() == pytest.approx(0.6)
    assert c["mod1_dst"].editor.currentText() == "Osc 1: PWM"
    assert c["mod8_src"].editor.currentText() == "LFO 1"
    assert c["mod8_amt"].editor.value() == pytest.approx(-0.9)
    assert c["mod8_dst"].editor.currentText() == "Filter: Cutoff"


def test_size_hint_and_no_overlap(rig):
    *_, window = rig
    hint = window.sizeHint()
    assert hint.width() <= 1700
    assert window.centralWidget().sizeHint().height() <= 900
    window.resize(1700, 1000)
    window.show()
    QApplication.processEvents()
    rects = [c.geometry() for c in _box(window).findChildren(ParamControl)]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not rects[i].intersects(rects[j])
