import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from midi_synth.engine import SynthEngine  # noqa: E402
from midi_synth.gui.bridge import Bridge  # noqa: E402
from midi_synth.gui.main_window import MainWindow  # noqa: E402
from midi_synth.midi_router import MidiRouter  # noqa: E402
from midi_synth.params import build_registry  # noqa: E402
from midi_synth.patches import PatchStore, capture  # noqa: E402
from midi_synth.profiles import ProfileStore  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


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
    return engine, registry, patches, window


def set_ui(window, pid, value):
    window.registry.set(pid, value)


def test_window_without_patch_store_has_no_patch_ui(qapp, tmp_path):
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    registry = build_registry(engine)
    profiles = ProfileStore(tmp_path / "cfg")
    router = MidiRouter(registry, profiles.open_active())
    window = MainWindow(engine, registry, router, profiles, [], Bridge(registry, router))
    assert window.patch_box is None


def test_gui_patch_load_resets_held_limiter(rig):
    engine, registry, _, window = rig
    registry.set("auto_limiter", True)
    engine._run_limiter(np.full((2, 64), 2.0))
    assert engine.limiter_reduction_db() > 0.0
    window._load_patch("Init")
    assert engine.limiter_reduction_db() == 0.0


def test_combo_lists_init_and_selects_it(rig):
    *_, window = rig
    assert [window.patch_box.itemText(i) for i in range(window.patch_box.count())] == ["Init"]
    assert window.patch_box.currentText() == "Init"
    assert not window.patch_modified


def test_init_protections(rig):
    *_, window = rig
    assert not window.patch_btn["save"].isEnabled()
    assert window.patch_btn["save"].toolTip()
    assert not window.patch_btn["rename"].isEnabled()
    assert not window.patch_btn["delete"].isEnabled()
    assert window.patch_btn["save_as"].isEnabled()


def test_save_as_stores_current_sound_and_selects_it(rig, monkeypatch):
    engine, registry, patches, window = rig
    set_ui(window, "osc2_level", 0.6)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Pad", True))
    window.patch_btn["save_as"].click()
    assert patches.load("Pad")["osc2_level"] == pytest.approx(0.6)
    assert window.patch_box.currentText() == "Pad"
    assert patches.last_used() == "Pad"
    assert window.patch_btn["save"].isEnabled()
    assert window.patch_btn["delete"].isEnabled()
    assert not window.patch_modified


def test_load_applies_patch_without_marking_modified(rig, monkeypatch):
    engine, registry, patches, window = rig
    patches.save("Bright", {"lpf_cutoff": 3000.0, "osc2_level": 0.5})
    window._reload_patches("Init")
    window._load_patch("Bright")
    assert engine.params["lpf_cutoff"] == pytest.approx(3000.0)
    assert engine.params["osc2_level"] == pytest.approx(0.5)
    assert window.patch_box.currentText() == "Bright"
    assert not window.patch_modified
    # fully defined: params missing from the file went back to defaults
    assert engine.params["osc1_level"] == window.patch_defaults["osc1_level"]
    assert patches.last_used() == "Bright"


def test_param_change_marks_modified_and_save_clears(rig):
    engine, registry, patches, window = rig
    patches.save("A", {})
    window._reload_patches("Init")
    window._load_patch("A")
    set_ui(window, "osc1_level", 0.3)
    assert window.patch_modified
    assert window.patch_box.currentText() == "A*"
    window.patch_btn["save"].click()
    assert not window.patch_modified
    assert window.patch_box.currentText() == "A"
    assert patches.load("A")["osc1_level"] == pytest.approx(0.3)


def test_master_gain_change_does_not_mark_modified(rig):
    *_, window = rig
    window._load_patch("Init")
    set_ui(window, "master_gain", 0.5)
    assert not window.patch_modified


def test_combo_choice_loads_immediately(rig):
    engine, registry, patches, window = rig
    patches.save("Wide", {"osc1_level": 0.1})
    window._reload_patches("Init")
    window.patch_box.activated.emit(window.patch_box.findData("Wide"))
    assert engine.params["osc1_level"] == pytest.approx(0.1)


def test_load_missing_patch_shows_message_and_keeps_selection(rig):
    *_, window = rig
    window._load_patch("Ghost")
    assert window.patch_box.currentText() == "Init"
    assert "no such patch" in window.statusBar().currentMessage()


def test_load_warnings_reach_status_bar(rig):
    engine, registry, patches, window = rig
    patches.save("Odd", {"bogus": 1})
    window._reload_patches("Init")
    window._load_patch("Odd")
    assert "bogus" in window.statusBar().currentMessage()


def test_delete_and_rename(rig, monkeypatch):
    engine, registry, patches, window = rig
    patches.save("Tmp", {})
    window._reload_patches("Init")
    window._load_patch("Tmp")
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renamed", True))
    window.patch_btn["rename"].click()
    assert patches.names() == ["Init", "Renamed"]
    assert window.patch_box.currentText() == "Renamed"
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    window.patch_btn["delete"].click()
    assert patches.names() == ["Init"]
    assert window.patch_box.currentText() == "Init"


def test_loading_init_resets_to_factory_sound(rig):
    engine, registry, patches, window = rig
    set_ui(window, "osc2_level", 0.9)
    window._load_patch("Init")
    assert engine.params["osc2_level"] == window.patch_defaults["osc2_level"]
    assert not window.patch_modified
