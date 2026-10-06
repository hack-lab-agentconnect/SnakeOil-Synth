import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midi_synth.bindings import CC, Source  # noqa: E402
from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.bridge import Bridge  # noqa: E402
from midi_synth.gui.main_window import MainWindow  # noqa: E402
from midi_synth.midi_router import MidiRouter  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402
from midi_synth.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def rig(qapp, tmp_path):
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    store = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, store.open_active())
    router.on_profile_changed = store.save
    bridge = Bridge(registry, router)
    window = MainWindow(engine, registry, router, store, ["Test Port"], bridge)
    return engine, registry, router, store, window


def test_every_param_has_a_control(rig):
    _, registry, _, _, window = rig
    assert set(window.controls) == set(registry.ids())


def test_default_bindings_show_as_badges(rig):
    *_, window = rig
    assert window.controls["fm_depth"].badge.text() == "CC 1"


def test_gui_edit_reaches_engine(rig):
    engine, *_, window = rig
    window.controls["osc1_level"].editor.valueChanged.emit(0.4)
    assert engine.params["osc1_level"] == 0.4


def test_midi_change_moves_gui_control(rig):
    _, _, router, _, window = rig
    router.handle_cc(0, 7, 127)
    assert window.controls["master_gain"].editor.value() == pytest.approx(1.2)


def test_learn_flow_binds_saves_and_updates_badge(rig):
    _, _, router, store, window = rig
    window._on_learn_requested("osc1_level")
    assert router.armed == "osc1_level"
    assert "Move" in window.controls["osc1_level"].badge.text()
    router.handle_cc(2, 74, 10)
    assert window.controls["osc1_level"].badge.text() == "CC 74 ch3"
    assert window.controls["osc1_level"]._learning is False
    assert store.load("Default").source_for("osc1_level") == Source(CC, 74, 3)


def test_escape_cancels_learn(rig):
    _, _, router, _, window = rig
    window._on_learn_requested("osc1_level")
    window.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert router.armed is None
    assert window.controls["osc1_level"]._learning is False


def test_clear_binding(rig):
    _, _, router, store, window = rig
    window._on_clear_requested("fm_depth")
    assert window.controls["fm_depth"].badge.text() == ""
    assert store.load("Default").source_for("fm_depth") is None


def test_profile_switch_swaps_bindings(rig):
    _, _, router, store, window = rig
    store.create("Blank")
    window._reload_profiles("Blank")
    window._switch("Blank")
    assert router.profile.name == "Blank"
    assert window.controls["fm_depth"].badge.text() == ""
    assert store.active_name() == "Blank"
    window._switch("Default")
    assert window.controls["fm_depth"].badge.text() == "CC 1"


def test_delete_and_default_protection(rig):
    _, _, _, store, window = rig
    assert window.btn["delete"].isEnabled() is False
    assert window.btn["reset"].isEnabled() is True
    store.create("X")
    window._reload_profiles("X")
    window._switch("X")
    assert window.btn["delete"].isEnabled() is True
    assert window.btn["reset"].isEnabled() is False


def test_last_message_shown_in_footer(rig):
    _, _, router, _, window = rig
    router.handle_cc(0, 99, 5)
    assert "CC 99 ch1 = 5" in window.msg_label.text()


def test_oscillator_groups_hold_their_controls(rig):
    *_, window = rig
    from PySide6.QtWidgets import QGroupBox
    from midi_synth.gui.controls import ParamControl

    def ids(title):
        box = next(b for b in window.findChildren(QGroupBox) if b.title() == title)
        return [c.param.id for c in box.findChildren(ParamControl)]

    assert ids("Oscillator 2") == [
        "osc2_level", "detune2_semitones", "detune2_cents", "osc2_pwm", "osc2_octave",
    ]
    assert ids("Oscillator 1") == [
        "osc1_level", "osc1_square", "osc1_square_level", "osc1_pwm", "osc1_octave",
    ]


def _effects_layout(window):
    from PySide6.QtWidgets import QGroupBox

    box = next(b for b in window.findChildren(QGroupBox) if b.title() == "Effects")
    layout = box.layout()

    def cell(pid):
        idx = layout.indexOf(window.controls[pid])
        assert idx >= 0
        return layout.getItemPosition(idx)

    return cell


def _root(registry, pid):
    while registry[pid].under:
        pid = registry[pid].under
    return pid


def test_effect_dependents_sit_below_toggle_inside_its_span(rig):
    _, registry, _, _, window = rig
    cell = _effects_layout(window)
    toggles = [p.id for p in registry if p.group == "Effects" and not p.under]
    assert toggles == ["fx_chorus", "fx_delay", "fx_reverb", "fx_bitcrush"]
    spans = []
    for t in toggles:
        trow, tcol, trs, tcs = cell(t)
        assert trow == 0 and tcs >= 1
        spans.append(range(tcol, tcol + tcs))
    for a in range(len(spans)):
        for b in range(a + 1, len(spans)):
            assert not set(spans[a]) & set(spans[b])
    for p in registry:
        if p.group != "Effects" or not p.under:
            continue
        trow, tcol, _, tcs = cell(_root(registry, p.id))
        row, col, rs, cs = cell(p.id)
        assert row > trow and (rs, cs) == (1, 1)
        assert tcol <= col < tcol + tcs


def test_effect_blocks_flow_in_one_row_under_their_toggle(rig):
    _, registry, _, _, window = rig
    cell = _effects_layout(window)

    def rc(pid):
        return cell(pid)[:2]

    d = rc("fx_delay")[1]
    delay_deps = ["fx_delay_time", "fx_delay_pingpong", "fx_delay_feedback",
                  "fx_delay_damp", "fx_delay_sync", "fx_delay_division"]
    assert cell("fx_delay")[3] == len(delay_deps)
    assert [rc(pid) for pid in delay_deps] == [(1, d + i) for i in range(6)]
    r = rc("fx_reverb")[1]
    assert [rc(pid) for pid in
            ("fx_reverb_amount", "fx_reverb_size", "fx_reverb_damp")] == [
        (1, r), (1, r + 1), (1, r + 2)]
    assert rc("fx_chorus_depth") == (1, rc("fx_chorus")[1])
    assert rc("fx_bitcrush_amount") == (1, rc("fx_bitcrush")[1])


def test_pingpong_is_below_delay_toggle(rig):
    window = rig[-1]
    cell = _effects_layout(window)
    trow, tcol, _, tcs = cell("fx_delay")
    prow, pcol, *_ = cell("fx_delay_pingpong")
    assert prow > trow and tcol <= pcol < tcol + tcs


def _fit(window, width=1500, height=900):
    window.resize(width, height)
    window.show()
    QApplication.processEvents()


def test_window_size_hint_fits_a_small_screen(rig):
    hint = rig[-1].sizeHint()
    assert hint.width() <= 1500 and hint.height() <= 880


def test_body_is_inside_a_scroll_area(rig):
    from PySide6.QtWidgets import QScrollArea

    window = rig[-1]
    assert isinstance(window.centralWidget(), QScrollArea)
    area = window.centralWidget()
    assert area.widgetResizable()
    assert area.widget().isAncestorOf(window.controls["master_gain"])


def test_every_group_present_and_controls_do_not_overlap(rig):
    from PySide6.QtWidgets import QGroupBox
    from midi_synth.gui.controls import ParamControl
    from midi_synth.gui.main_window import GROUP_POSITIONS

    _, registry, _, _, window = rig
    _fit(window, 1700, 1000)
    boxes = {b.title(): b for b in window.findChildren(QGroupBox)}
    assert set(boxes) == {p.group for p in registry} == set(GROUP_POSITIONS)
    for title, box in boxes.items():
        controls = [c for c in box.findChildren(ParamControl)]
        assert controls
        rects = [c.geometry() for c in controls]
        inside = box.rect()
        for rect in rects:
            assert inside.contains(rect), (title, rect)
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not rects[i].intersects(rects[j]), (title, i, j)
    window.close()


def test_small_window_scrolls_instead_of_clipping(rig):
    window = rig[-1]
    _fit(window, 900, 600)
    area = window.centralWidget()
    assert area.verticalScrollBar().maximum() > 0
    assert area.verticalScrollBar().isVisible()
    window.close()
