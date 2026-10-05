import json
import math
import os
from pathlib import Path

from .profiles import ProfileError, _atomic_write_json, validate_name

CURRENT_VERSION = 1
PATCH_EXCLUDED = ("master_gain",)
INIT_NAME = "Init"
MIGRATIONS = {}


class PatchError(Exception):
    pass


def capture(registry):
    """Snapshot every patch-worthy parameter as {param_id: value}."""
    return {p.id: p.get() for p in registry if p.id not in PATCH_EXCLUDED}


def apply(registry, values, defaults):
    """Load a patch into the registry; returns a list of warning strings.

    Parameters are set in registry order. Ones missing from `values` take
    their factory value from `defaults`, so a patch always fully defines the
    sound.
    """
    warnings = []
    for pid in values:
        if pid in PATCH_EXCLUDED or pid not in registry:
            warnings.append("Ignored unknown parameter %r" % pid)
    for param in registry:
        pid = param.id
        if pid in PATCH_EXCLUDED:
            continue
        if pid in values:
            value = values[pid]
        elif pid in defaults:
            value = defaults[pid]
        else:
            continue
        try:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("not a finite number")
            registry.set(pid, value)
        except (ValueError, TypeError, OverflowError, ArithmeticError) as exc:
            warnings.append("Skipped invalid value for %s: %s" % (pid, exc))
    return warnings


class PatchStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.patches_dir = self.directory / "patches"
        self.settings_path = self.directory / "patch_settings.json"
        self.warnings = []

    def _warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    @staticmethod
    def _valid_name(name):
        try:
            return validate_name(name)
        except ProfileError:
            raise PatchError("invalid patch name: %r" % name)

    def _find(self, name):
        if not self.patches_dir.is_dir():
            return None
        wanted = name.lower()
        for path in self.patches_dir.glob("*.json"):
            if path.stem.lower() == wanted:
                return path
        return None

    def _read(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise PatchError("%s: %s" % (path.name, exc))
        if not isinstance(data, dict):
            raise PatchError("%s: not a patch file" % path.name)
        version = data.get("version", 1)
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise PatchError("%s: bad version %r" % (path.name, version))
        if version > CURRENT_VERSION:
            raise PatchError(
                "%s: newer format (version %d, this app reads up to %d)"
                % (path.name, version, CURRENT_VERSION))
        while version < CURRENT_VERSION:
            migrate = MIGRATIONS.get(version)
            if migrate is None:
                raise PatchError("%s: no migration from version %d" % (path.name, version))
            try:
                data = migrate(data)
            except Exception as exc:
                raise PatchError("%s: migration failed: %s" % (path.name, exc))
            version += 1
        params = data.get("params")
        if not isinstance(params, dict):
            raise PatchError("%s: missing params" % path.name)
        return dict(params)

    def names(self):
        found = []
        if self.patches_dir.is_dir():
            for path in self.patches_dir.glob("*.json"):
                try:
                    self._read(path)
                except PatchError as exc:
                    self._warn("Skipped unreadable patch %s" % exc)
                    continue
                found.append(path.stem)
        found.sort(key=lambda n: (n.lower() != INIT_NAME.lower(), n.lower()))
        return found

    def load(self, name):
        path = self._find(name)
        if path is None:
            raise PatchError("no such patch: %s" % name)
        return self._read(path)

    def save(self, name, values):
        name = self._valid_name(name)
        if name.lower() == INIT_NAME.lower():
            raise PatchError("the Init patch is read-only")
        self._write(name, values)

    def _write(self, name, values):
        name = self._valid_name(name)
        path = self._find(name) or (self.patches_dir / (name + ".json"))
        _atomic_write_json(path, {
            "version": CURRENT_VERSION, "name": path.stem, "params": dict(values)})

    def create_from(self, name, values):
        name = self._valid_name(name)
        if self._find(name) is not None:
            raise PatchError("patch already exists: %s" % name)
        self.save(name, values)

    def duplicate(self, source, new_name):
        new_name = self._valid_name(new_name)
        if self._find(new_name) is not None:
            raise PatchError("patch already exists: %s" % new_name)
        self.save(new_name, self.load(source))

    def rename(self, old, new):
        if old.lower() == INIT_NAME.lower():
            raise PatchError("the Init patch cannot be renamed")
        new = self._valid_name(new)
        src = self._find(old)
        if src is None:
            raise PatchError("no such patch: %s" % old)
        clash = self._find(new)
        if clash is not None and clash != src:
            raise PatchError("patch already exists: %s" % new)
        values = self._read(src)
        if clash is None:
            self.save(new, values)
            src.unlink()
        else:
            os.replace(src, self.patches_dir / (new + ".json"))
            self.save(new, values)
        if (self.last_used() or "").lower() == old.lower():
            self.set_last_used(new)

    def delete(self, name):
        if name.lower() == INIT_NAME.lower():
            raise PatchError("the Init patch cannot be deleted")
        path = self._find(name)
        if path is None:
            raise PatchError("no such patch: %s" % name)
        path.unlink()
        if (self.last_used() or "").lower() == name.lower():
            self.set_last_used(INIT_NAME)

    def ensure_init(self, defaults):
        if self._find(INIT_NAME) is None:
            self._write(INIT_NAME, defaults)

    def reset_init(self, defaults):
        self._write(INIT_NAME, defaults)

    def last_used(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8-sig"))
            name = data.get("last_used")
            return str(name) if name else None
        except (OSError, ValueError, AttributeError):
            return None

    def set_last_used(self, name):
        _atomic_write_json(self.settings_path, {"last_used": name})
