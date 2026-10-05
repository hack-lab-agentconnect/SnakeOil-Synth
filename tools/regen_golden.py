"""Regenerate tests/golden/*.npz. Only run this for an intentional sound change.

Usage (from the repo root): .venv/Scripts/python.exe tools/regen_golden.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

from tests.golden_scenarios import SCENARIOS  # noqa: E402

GOLDEN_DIR = os.path.join(ROOT, "tests", "golden")


def main():
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for name, build in SCENARIOS.items():
        path = os.path.join(GOLDEN_DIR, name + ".npz")
        np.savez_compressed(path, audio=build())
        print("wrote %s (%d bytes)" % (path, os.path.getsize(path)))


if __name__ == "__main__":
    main()
