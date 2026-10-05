"""Checks that pyproject.toml stays consistent with the source tree."""
import importlib
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject():
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def _names(specs):
    return {re.split(r"[<>=!~\[ ;]", s, maxsplit=1)[0].lower().replace("_", "-")
            for s in specs}


def _requirements():
    lines = (ROOT / "requirements.txt").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith(("#", "-"))]


def test_project_metadata():
    data = _pyproject()
    assert data["project"]["name"] == "midi-synth"
    assert data["project"]["requires-python"] == ">=3.10"


def test_console_scripts():
    scripts = _pyproject()["project"]["scripts"]
    assert scripts["midi-synth"] == "run:main"
    assert scripts["midi-synth-render"] == "render_demo:main"


def test_listed_modules_and_packages_exist():
    cfg = _pyproject()["tool"]["setuptools"]
    for mod in cfg["py-modules"]:
        assert (ROOT / (mod + ".py")).is_file()
    for pkg in cfg["packages"]:
        assert (ROOT / pkg.replace(".", "/") / "__init__.py").is_file()
    assert (ROOT / "run.py").is_file()
    assert (ROOT / "render_demo.py").is_file()


def test_dependencies_match_requirements_txt():
    deps = _pyproject()["project"]["dependencies"]
    assert _names(deps) == _names(_requirements())


def test_entry_points_are_callable():
    for modname in ("run", "render_demo"):
        assert callable(importlib.import_module(modname).main)
