"""The shared drawings: the set the spec names, on one grid, with valid path data."""
from __future__ import annotations

import json
import re
from pathlib import Path

ICONS = Path(__file__).resolve().parent.parent / "docs" / "ui-icons.json"
PATH_DATA = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE.,\s-]+$")


def test_the_named_drawings_exist_on_one_grid() -> None:
    data = json.loads(ICONS.read_text(encoding="utf-8"))
    assert data["grid"] == 16 and data["stroke"] == 1.4 and data["size"] == 14
    assert set(data["icons"]) == {"star", "lock", "lockFilled", "undo", "arrow"}


def test_every_path_is_plain_path_data_inside_the_grid() -> None:
    data = json.loads(ICONS.read_text(encoding="utf-8"))
    for name, icon in data["icons"].items():
        assert icon["paths"], name
        for path in icon["paths"]:
            assert PATH_DATA.match(path["d"]), (name, path["d"])
            start = re.match(r"M\s*(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)", path["d"])
            assert start, (name, "a path starts with an absolute move")
            assert all(0 <= float(n) <= 16 for n in start.groups()), (name, "starts on the 16 grid")


def test_the_filled_lock_is_the_lock_with_its_body_filled() -> None:
    icons = json.loads(ICONS.read_text(encoding="utf-8"))["icons"]
    assert [p["d"] for p in icons["lock"]["paths"]] == [p["d"] for p in icons["lockFilled"]["paths"]]
    assert [bool(p.get("fill")) for p in icons["lockFilled"]["paths"]] == [False, True]
    assert not any(p.get("fill") for p in icons["lock"]["paths"])
