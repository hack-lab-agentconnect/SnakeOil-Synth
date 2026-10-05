import json
import os
import re
import sys
from pathlib import Path

from .bindings import Profile, default_profile, DEFAULT_NAME


class ProfileError(Exception):
    pass


_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {
    "LPT%d" % i for i in range(1, 10)
}


def default_config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "midi-synth"


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
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


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
            data = json.loads(path.read_text(encoding="utf-8"))
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
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
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
            self.set_active(profile.name)
            return profile
        self.reset_default()
        profile = self.load(DEFAULT_NAME)
        self.set_active(profile.name)
        return profile
