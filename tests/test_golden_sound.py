"""Golden sound lock: the rendered default and "busy" patches must not drift.

The reference renders live in tests/golden/*.npz. If a change to the sound is
intentional, regenerate them with:

    .venv/Scripts/python.exe tools/regen_golden.py

Do not regenerate for refactors or new features that default to off.
"""
import os

import numpy as np
import pytest

from tests.golden_scenarios import SCENARIOS, new_engine, render_chord

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
HINT = ("Sound changed. If intentional, regenerate with "
        ".venv/Scripts/python.exe tools/regen_golden.py")


def _golden(name):
    with np.load(os.path.join(GOLDEN_DIR, name + ".npz")) as data:
        return data["audio"]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_render_matches_golden(name):
    expected = _golden(name)
    actual = SCENARIOS[name]()
    assert actual.shape == expected.shape, HINT
    worst = float(np.max(np.abs(actual - expected)))
    assert np.allclose(actual, expected, atol=1e-6), "max diff %.3g. %s" % (worst, HINT)


def test_golden_comparison_can_fail():
    expected = _golden("default")
    engine = new_engine()
    engine.set_master_gain(0.79)
    actual = render_chord(engine)
    assert actual.shape == expected.shape
    assert not np.allclose(actual, expected, atol=1e-6)
