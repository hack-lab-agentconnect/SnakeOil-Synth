import json

import pytest

from midi_synth.bindings import CC, Source, default_profile, DEFAULT_NAME
from midi_synth.profiles import ProfileStore, ProfileError


@pytest.fixture
def store(tmp_path):
    s = ProfileStore(tmp_path / "cfg")
    s.ensure_default()
    return s


def test_first_run_seeds_default(store):
    assert store.names() == ["Default"]
    assert store.load("Default").param_for(CC, 1, 1) == "fm_depth"


def test_names_default_first_then_sorted(store):
    store.create("zeta")
    store.create("Alpha")
    assert store.names() == ["Default", "Alpha", "zeta"]


def test_save_load_roundtrip(store):
    p = default_profile()
    p.bind(Source(CC, 74, 3), "osc1_level")
    store.save(p)
    loaded = store.load("Default")
    assert loaded.source_for("osc1_level") == Source(CC, 74, 3)
    assert loaded.param_for(CC, 1, 1) == "fm_depth"


def test_unknown_params_survive_roundtrip(store):
    path = store.profiles_dir / "future.json"
    path.write_text(json.dumps({
        "version": 1,
        "bindings": [{"source": "cc:*:5", "param": "future_param"}],
    }))
    store.save(store.load("future"))
    assert "future_param" in path.read_text()


def test_duplicate_copies_bindings(store):
    p = store.load("Default")
    p.bind(Source(CC, 74, 1), "osc1_level")
    store.save(p)
    copy = store.duplicate("Default", "Mine")
    assert copy.name == "Mine"
    assert store.load("Mine").source_for("osc1_level") == Source(CC, 74, 1)


def test_create_is_blank(store):
    assert store.create("Blank").items() == []


def test_names_are_case_insensitive_unique(store):
    store.create("Live")
    with pytest.raises(ProfileError):
        store.create("live")


@pytest.mark.parametrize("bad", ["", "   ", "a/b", "a:b", "CON", "nul.x", "x.", "..", "a?b"])
def test_invalid_names_rejected(store, bad):
    with pytest.raises(ProfileError):
        store.create(bad)


def test_rename_updates_active(store):
    store.create("a")
    store.set_active("a")
    store.rename("a", "b")
    assert store.names() == ["Default", "b"]
    assert store.active_name() == "b"


def test_rename_default_or_onto_existing_refused(store):
    store.create("a")
    with pytest.raises(ProfileError):
        store.rename("Default", "x")
    with pytest.raises(ProfileError):
        store.rename("a", "default")


def test_rename_case_only_allowed(store):
    store.create("live")
    store.rename("live", "Live")
    assert "Live" in store.names()


def test_delete_active_falls_back_to_default(store):
    store.create("x")
    store.set_active("x")
    store.delete("x")
    assert store.names() == ["Default"]
    assert store.active_name() == DEFAULT_NAME


def test_delete_default_refused(store):
    with pytest.raises(ProfileError):
        store.delete("Default")


def test_reset_default_restores_factory(store):
    p = store.load("Default")
    p.clear("fm_depth")
    store.save(p)
    store.reset_default()
    assert store.load("Default").source_for("fm_depth") is not None


def test_corrupt_file_skipped_with_warning(store):
    (store.profiles_dir / "bad.json").write_text("{not json")
    assert store.names() == ["Default"]
    assert any("bad.json" in w for w in store.warnings)
    with pytest.raises(ProfileError):
        store.load("bad")


def test_load_missing_raises(store):
    with pytest.raises(ProfileError):
        store.load("nope")


def test_open_active_prefers_arg_then_stored_then_default(store):
    store.create("x")
    store.set_active("x")
    assert store.open_active().name == "x"
    assert store.open_active("nope").name == "x"
    assert store.open_active("Default").name == "Default"
    assert store.active_name() == "Default"


def test_open_active_recovers_corrupt_default(store):
    (store.profiles_dir / "Default.json").write_text("garbage")
    store.set_active("Default")
    p = store.open_active()
    assert p.param_for(CC, 1, 1) == "fm_depth"
    assert any("Default" in w for w in store.warnings)


def test_settings_file_corruption_ignored(store):
    store.settings_path.write_text("{{{")
    assert store.active_name() == DEFAULT_NAME
