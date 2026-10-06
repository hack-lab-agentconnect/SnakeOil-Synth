import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OLD_NAME = re.compile(r"\bmidi[- ]synth\b", re.IGNORECASE)

# Lines (stripped) allowed to mention the old name: the README rename note and the
# legacy-folder constant in profiles.py (not scanned here, listed for clarity).
ALLOWED_LINES = {
    "SnakeOil Synth was formerly called midi-synth. The config folder moved to `snakeoil-synth`;",
    "the legacy `midi-synth` folder is left untouched. The console commands are now",
}


def _files():
    names = ["README.md", "pyproject.toml", "run.py", "render_demo.py"]
    files = [ROOT / n for n in names]
    files += sorted((ROOT / "midi_synth" / "gui").glob("*.py"))
    return files


def test_no_old_product_name_in_user_facing_files():
    hits = []
    for path in _files():
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip() in ALLOWED_LINES:
                continue
            # `midi_synth` (the package) never matches: the pattern needs - or space.
            if OLD_NAME.search(line):
                hits.append("%s:%d: %s" % (path.relative_to(ROOT), no, line.strip()))
    assert not hits, "old product name found:\n" + "\n".join(hits)


def test_legacy_dir_constant_is_the_only_old_name_in_profiles():
    from midi_synth import profiles
    assert profiles.LEGACY_DIR_NAME == "midi-synth"
    assert profiles.DEFAULT_DIR_NAME == "snakeoil-synth"
