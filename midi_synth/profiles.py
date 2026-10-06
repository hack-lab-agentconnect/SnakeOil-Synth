import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .bindings import Profile, default_profile, DEFAULT_NAME


class ProfileError(Exception):
    pass


_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {
    "LPT%d" % i for i in range(1, 10)
}


# Folder name before the rename to SnakeOil Synth; its contents are copied once.
LEGACY_DIR_NAME = "midi-synth"
DEFAULT_DIR_NAME = "snakeoil-synth"


def default_config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / DEFAULT_DIR_NAME


def migrate_legacy_config(new_dir, legacy_dir=None):
    """Copy the legacy config folder to `new_dir` once; never touches the legacy folder.

    Returns a message describing what happened, or None when nothing was needed.
    OSErrors are returned as a warning message instead of being raised.
    """
    new_dir = Path(new_dir)
    legacy_dir = Path(legacy_dir) if legacy_dir is not None else new_dir.parent / LEGACY_DIR_NAME
    try:
        if not legacy_dir.is_dir():
            return None
        if new_dir.exists() and any(new_dir.iterdir()):
            return None
        shutil.copytree(legacy_dir, new_dir, dirs_exist_ok=True)
    except OSError as exc:
        return "warning: could not copy old settings from %s to %s: %s" % (
            legacy_dir, new_dir, exc)
    return "Copied your old settings from %s to %s (the old folder was left untouched)" % (
        legacy_dir, new_dir)


def validate_name(name):
    name = (name or "").strip()
    if (
        not name
        or name in (".", "..")
        or name.endswith(".")
        or _INVALID_CHARS.search(name)
        or name.split(".")[0].upper() in _RESERVED
    ):
        raise ProfileError("invalid profile name: %r" % name)
    return name


def _atomic_write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class ProfileStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.profiles_dir = self.directory / "profiles"
        self.settings_path = self.directory / "settings.json"
        self.warnings = []

    def _warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def _find(self, name):
        if not self.profiles_dir.is_dir():
            return None
        wanted = name.lower()
        for path in self.profiles_dir.glob("*.json"):
            if path.stem.lower() == wanted:
                return path
        return None

    def _read(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return Profile.from_dict(path.stem, data)
        except (OSError, ValueError) as exc:
            raise ProfileError("%s: %s" % (path.name, exc))

    def names(self):
        found = []
        if self.profiles_dir.is_dir():
            for path in self.profiles_dir.glob("*.json"):
                try:
                    self._read(path)
                except ProfileError as exc:
                    self._warn("Skipped unreadable profile %s" % exc)
                    continue
                found.append(path.stem)
        found.sort(key=lambda n: (n.lower() != DEFAULT_NAME.lower(), n.lower()))
        return found

    def load(self, name):
        path = self._find(name)
        if path is None:
            raise ProfileError("no such profile: %s" % name)
        return self._read(path)

    def save(self, profile):
        name = validate_name(profile.name)
        path = self._find(name) or (self.profiles_dir / (name + ".json"))
        _atomic_write_json(path, profile.to_dict())

    def create(self, name):
        name = validate_name(name)
        if self._find(name) is not None:
            raise ProfileError("profile already exists: %s" % name)
        profile = Profile(name)
        self.save(profile)
        return profile

    def duplicate(self, source_name, new_name):
        new_name = validate_name(new_name)
        if self._find(new_name) is not None:
            raise ProfileError("profile already exists: %s" % new_name)
        copy = self.load(source_name).copy(new_name)
        self.save(copy)
        return copy

    def rename(self, old, new):
        if old.lower() == DEFAULT_NAME.lower():
            raise ProfileError("the Default profile cannot be renamed")
        new = validate_name(new)
        src = self._find(old)
        if src is None:
            raise ProfileError("no such profile: %s" % old)
        clash = self._find(new)
        if clash is not None and clash != src:
            raise ProfileError("profile already exists: %s" % new)
        os.replace(src, self.profiles_dir / (new + ".json"))
        if self.active_name().lower() == old.lower():
            self.set_active(new)

    def delete(self, name):
        if name.lower() == DEFAULT_NAME.lower():
            raise ProfileError("the Default profile cannot be deleted")
        path = self._find(name)
        if path is None:
            raise ProfileError("no such profile: %s" % name)
        path.unlink()
        if self.active_name().lower() == name.lower():
            self.set_active(DEFAULT_NAME)

    def ensure_default(self):
        if self._find(DEFAULT_NAME) is None:
            self.save(default_profile())

    def reset_default(self):
        self.save(default_profile())

    def active_name(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8-sig"))
            return str(data.get("active") or DEFAULT_NAME)
        except (OSError, ValueError, AttributeError):
            return DEFAULT_NAME

    def set_active(self, name):
        _atomic_write_json(self.settings_path, {"active": name})

    def open_active(self, preferred=None):
        self.ensure_default()
        for name in (preferred, self.active_name(), DEFAULT_NAME):
            if not name:
                continue
            try:
                profile = self.load(name)
            except ProfileError as exc:
                if name.lower() == DEFAULT_NAME.lower():
                    self._warn("Default profile was unreadable (%s); restored defaults" % exc)
                continue
            if preferred and name != preferred:
                self._warn("Profile %r not found; using %s" % (preferred, profile.name))
            self.set_active(profile.name)
            return profile
        self.reset_default()
        profile = self.load(DEFAULT_NAME)
        self.set_active(profile.name)
        return profile
