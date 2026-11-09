#!/usr/bin/env python3
"""Run the demo from a source checkout without installing: python3 scripts/demo.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from mergeweather.cli import main

sys.exit(main(["demo", *sys.argv[1:]]))
