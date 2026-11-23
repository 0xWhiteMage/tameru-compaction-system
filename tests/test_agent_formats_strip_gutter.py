"""``tameru.agent_formats.strip_gutter`` is public submodule API since 1.4.0."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tameru.agent_formats import strip_gutter


def test_strip_gutter_removes_line_number_gutter():
    assert strip_gutter("12|text") == "text"
    assert strip_gutter("  7\tvalue") == "value"


def test_strip_gutter_leaves_ungutted_line_unchanged():
    assert strip_gutter("no gutter here") == "no gutter here"
