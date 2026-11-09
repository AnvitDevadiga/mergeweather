#!/usr/bin/env python3
"""Build the sample repositories: python3 examples/make_fixtures.py [DEST]."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from mergeweather.fixtures import build_all

if __name__ == "__main__":
    for r in build_all(Path(sys.argv[1] if len(sys.argv) > 1 else "build/fixtures")):
        print(r)
