import json

import pytest

import run
from midi_synth import patches
from midi_synth.engine import SynthEngine
from midi_synth.params import CHOICE, CONTINUOUS, TOGGLE, build_registry
from midi_synth.patches import (
    PATCH_EXCLUDED, PatchError, PatchStore, apply, capture,
)


def make_registry():
    engine = SynthEngine(sr=44100, block_size=64, max_voices=2)
    return engine, build_registry(engine)


def non_default_values(registry):
    values = {}
    for p in registry:
        if p.id in PATCH_EXCLUDED:
            continue
        if p.kind == CONTINUOUS:
            values[p.id] = p.minimum + 0.37 * (p.maximum - p.minimum)
        elif p.kind == TOGGLE:
            values[p.id] = not p.get()
        else:
            values[p.id] = [c for c in p.choices if c != p.get()][-1]
    return values


@pytest.fixture
def store(tmp_path):
    return PatchStore(tmp_path / "cfg")


# ---- capture / apply --------------------------------------------------

def test_capture_excludes_master_gain_and_covers_everything_else():
    _, registry = make_registry()
    values = capture(registry)
    assert "master_gain" not in values
    assert set(values) == set(registry.ids()) - {"master_gain"}


def test_round_trip_every_param_with_non_default_values():
    engine_a, reg_a = make_registry()
    wanted = non_default_values(reg_a)
    for pid, value in wanted.items():
        assert value != reg_a.get(pid), pid
    defaults = capture(reg_a)
    assert apply(reg_a, wanted, defaults) == []
    snapshot = capture(reg_a)
    engine_b, reg_b = make_registry()
    assert apply(reg_b, json.loads(json.dumps(snapshot)), capture(reg_b)) == []
    assert capture(reg_b) == snapshot
    assert engine_b.params == engine_a.params
    for pid in wanted:
        assert reg_b.get(pid) != defaults[pid], pid


def test_master_gain_is_neither_captured_nor_applied():
    engine, registry = make_registry()
    engine.set_master_gain(0.9)
    warnings = apply(registry, {"master_gain": 0.1}, capture(registry))
    assert engine.params["master_gain"] == 0.9
    assert len(warnings) == 1


def test_mod_mode_applied_before_fm_depth():
    engine, registry = make_registry()
    defaults = capture(registry)
    apply(registry, {"mod_mode": "fm", "fm_depth": 0.37}, defaults)
    assert engine.params["mod_mode"] == "fm"
    assert engine.params["fm_depth"] == pytest.approx(0.37)
    ids = registry.ids()
    assert ids.index("mod_mode") < ids.index("fm_depth")


def test_missing_params_take_defaults():
    engine, registry = make_registry()
    defaults = capture(registry)
    apply(registry, non_default_values(registry), defaults)
    assert apply(registry, {"osc1_level": 0.2}, defaults) == []
    assert registry.get("osc1_level") == pytest.approx(0.2)
    assert capture(registry) == {**defaults, "osc1_level": pytest.approx(0.2)}


def test_unknown_ids_warn_and_are_ignored():
    _, registry = make_registry()
    defaults = capture(registry)
    warnings = apply(registry, {"nope": 1, "osc1_level": 0.3}, defaults)
    assert len(warnings) == 1 and "nope" in warnings[0]
    assert registry.get("osc1_level") == pytest.approx(0.3)


def test_invalid_values_warn_and_are_skipped():
    _, registry = make_registry()
    defaults = capture(registry)
    warnings = apply(
        registry, {"mod_mode": "bogus", "osc1_level": "loud", "osc2_level": None}, defaults)
    assert len(warnings) == 3
    assert registry.get("mod_mode") == defaults["mod_mode"]
    assert registry.get("osc1_level") == defaults["osc1_level"]


def test_values_are_clamped_and_notify_listeners():
    _, registry = make_registry()
    seen = []
    registry.add_listener(seen.append)
    apply(registry, {"osc1_level": 7.0}, capture(registry))
    assert registry.get("osc1_level") == 1.0
    assert "osc1_level" in seen


# ---- store --------------------------------------------------------------

def test_save_load_round_trip_and_file_format(store):
    store.save("Lead", {"osc1_level": 0.5})
    path = store.patches_dir / "Lead.json"
    assert json.loads(path.read_text()) == {
        "version": 1, "name": "Lead", "params": {"osc1_level": 0.5}}
    assert store.load("lead") == {"osc1_level": 0.5}


def test_names_sorted_with_init_first(store):
    store.save("zed", {})
    store.save("Alpha", {})
    store.ensure_init({"osc1_level": 1.0})
    assert store.names() == ["Init", "Alpha", "zed"]


def test_names_case_insensitive_overwrite(store):
    store.save("Lead", {"a": 1})
    store.save("LEAD", {"a": 2})
    assert store.names() == ["Lead"]
    assert store.load("Lead") == {"a": 2}


def test_invalid_name_rejected(store):
    for bad in ("", "a/b", "CON", "x."):
        with pytest.raises(PatchError):
            store.save(bad, {})


def test_create_from_refuses_existing(store):
    store.create_from("A", {"x": 1})
    with pytest.raises(PatchError):
        store.create_from("a", {"x": 2})


def test_duplicate_rename_delete(store):
    store.save("A", {"x": 1})
    store.duplicate("A", "B")
    assert store.load("B") == {"x": 1}
    with pytest.raises(PatchError):
        store.duplicate("A", "b")
    store.rename("B", "C")
    assert store.names() == ["A", "C"]
    with pytest.raises(PatchError):
        store.rename("C", "a")
    store.rename("C", "c")
    assert "c" in store.names()
    store.delete("c")
    assert store.names() == ["A"]
    with pytest.raises(PatchError):
        store.delete("zzz")
    with pytest.raises(PatchError):
        store.load("zzz")


def test_init_cannot_be_deleted_or_renamed_but_can_be_reset(store):
    store.ensure_init({"x": 1})
    with pytest.raises(PatchError):
        store.delete("init")
    with pytest.raises(PatchError):
        store.rename("Init", "Other")
    store._write("Init", {"x": 2})
    store.reset_init({"x": 1})
    assert store.load("Init") == {"x": 1}


def test_ensure_init_does_not_overwrite(store):
    store.ensure_init({"x": 1})
    store._write("Init", {"x": 5})
    store.ensure_init({"x": 1})
    assert store.load("Init") == {"x": 5}


def test_last_used_round_trip_and_rename_delete_follow(store):
    assert store.last_used() is None
    store.save("A", {})
    store.ensure_init({})
    store.set_last_used("A")
    assert store.last_used() == "A"
    store.rename("A", "B")
    assert store.last_used() == "B"
    store.delete("B")
    assert store.last_used() == "Init"
    assert (store.directory / "patch_settings.json").is_file()
    assert not (store.directory / "settings.json").exists()


def test_corrupt_files_are_skipped_with_warning(store):
    store.save("Good", {})
    (store.patches_dir / "Bad.json").write_text("{nope")
    (store.patches_dir / "List.json").write_text("[]")
    (store.patches_dir / "NoParams.json").write_text('{"version": 1}')
    assert store.names() == ["Good"]
    assert len(store.warnings) == 3
    with pytest.raises(PatchError):
        store.load("Bad")


def test_newer_version_raises(store):
    store.patches_dir.mkdir(parents=True)
    (store.patches_dir / "Future.json").write_text(
        json.dumps({"version": 99, "name": "Future", "params": {}}))
    with pytest.raises(PatchError, match="newer format"):
        store.load("Future")
    assert "Future" not in store.names()


def test_migration_hook_applies_in_order(store, monkeypatch):
    monkeypatch.setattr(patches, "CURRENT_VERSION", 3)
    monkeypatch.setattr(patches, "MIGRATIONS", {
        1: lambda d: {**d, "params": {**d["params"], "one": True}},
        2: lambda d: {**d, "params": {**d["params"], "two": True}},
    })
    store.patches_dir.mkdir(parents=True)
    (store.patches_dir / "Old.json").write_text(
        json.dumps({"version": 1, "name": "Old", "params": {"a": 1}}))
    assert store.load("Old") == {"a": 1, "one": True, "two": True}


def test_missing_migration_raises(store, monkeypatch):
    monkeypatch.setattr(patches, "CURRENT_VERSION", 2)
    store.patches_dir.mkdir(parents=True)
    (store.patches_dir / "Old.json").write_text(
        json.dumps({"version": 1, "params": {}}))
    with pytest.raises(PatchError):
        store.load("Old")


def test_atomic_write_leaves_no_temp_files(store):
    store.save("A", {"x": 1})
    store.save("A", {"x": 2})
    store.set_last_used("A")
    assert [p.name for p in store.patches_dir.iterdir()] == ["A.json"]
    assert not list(store.directory.glob("*.tmp"))


def test_patches_do_not_collide_with_profile_files(tmp_path):
    from midi_synth.profiles import ProfileStore
    profiles = ProfileStore(tmp_path)
    profiles.open_active()
    store = PatchStore(tmp_path)
    store.ensure_init({})
    store.set_last_used("Init")
    assert profiles.names() == ["Default"]
    assert profiles.active_name() == "Default"
    assert store.names() == ["Init"]


# ---- CLI / console ------------------------------------------------------

def test_patch_flag_parsing():
    assert run.parse_args([]).patch is None
    assert run.parse_args(["--patch", "Lead"]).patch == "Lead"


def run_console(monkeypatch, capsys, lines, **kwargs):
    import builtins
    feed = iter(lines + ["quit"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(feed))
    run.console_loop(**kwargs)
    return capsys.readouterr().out


def test_console_patch_commands(monkeypatch, capsys, store):
    engine, registry = make_registry()
    defaults = capture(registry)
    store.ensure_init(defaults)
    kw = dict(engine=engine, registry=registry, patch_store=store,
              patch_defaults=defaults)
    engine.set_osc_level(1, 0.25)
    out = run_console(monkeypatch, capsys, ["patch save Mine", "patch list"], **kw)
    assert "Init" in out and "Mine" in out
    assert store.load("Mine")["osc1_level"] == 0.25
    assert store.last_used() == "Mine"

    engine.set_osc_level(1, 0.9)
    run_console(monkeypatch, capsys, ["patch load init"], **kw)
    assert engine.params["osc1_level"] == defaults["osc1_level"]
    run_console(monkeypatch, capsys, ["patch load mine"], **kw)
    assert engine.params["osc1_level"] == 0.25

    run_console(monkeypatch, capsys, ["patch delete Mine"], **kw)
    assert store.names() == ["Init"]


def test_console_patch_load_prints_warnings_and_errors(monkeypatch, capsys, store):
    engine, registry = make_registry()
    defaults = capture(registry)
    store.save("Odd", {"bogus_param": 1})
    kw = dict(engine=engine, registry=registry, patch_store=store,
              patch_defaults=defaults)
    out = run_console(monkeypatch, capsys,
                      ["patch load Odd", "patch load Missing", "patch delete Init"], **kw)
    assert "bogus_param" in out
    assert "no such patch" in out
    assert "cannot be deleted" in out


def test_console_patch_usage_and_unavailable(monkeypatch, capsys, store):
    engine, registry = make_registry()
    kw = dict(engine=engine, registry=registry, patch_store=store,
              patch_defaults=capture(registry))
    out = run_console(monkeypatch, capsys,
                      ["patch", "patch save", "patch bogus", "patch load"], **kw)
    assert out.count("usage: patch") == 4
    out = run_console(monkeypatch, capsys, ["patch list"], engine=engine)
    assert "patches unavailable" in out


def test_help_mentions_patch():
    assert "patch" in run.HELP_TEXT


def test_load_startup_patch_helper(store):
    engine, registry = make_registry()
    defaults = capture(registry)
    store.ensure_init(defaults)
    store.save("Lead", {"osc1_level": 0.4})
    store.set_last_used("Lead")
    assert run.load_startup_patch(registry, store, defaults, None) == ([], "Lead")
    assert registry.get("osc1_level") == pytest.approx(0.4)
    # explicit name wins; unknown name warns and leaves defaults
    apply(registry, defaults, defaults)
    warnings, applied = run.load_startup_patch(registry, store, defaults, "Nope")
    assert applied is None
    assert any("Nope" in w for w in warnings)
    assert registry.get("osc1_level") == defaults["osc1_level"]


def test_startup_patch_unreadable_warns_and_continues(store):
    engine, registry = make_registry()
    defaults = capture(registry)
    store.patches_dir.mkdir(parents=True)
    (store.patches_dir / "Broken.json").write_text("{")
    store.set_last_used("Broken")
    warnings, applied = run.load_startup_patch(registry, store, defaults, None)
    assert applied is None
    assert warnings and "Broken" in warnings[0]
    assert capture(registry) == defaults
