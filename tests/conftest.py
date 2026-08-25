"""Ensure the test suite always exercises this checkout's source tree."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC in sys.path:
    sys.path.remove(SRC)
sys.path.insert(0, SRC)
