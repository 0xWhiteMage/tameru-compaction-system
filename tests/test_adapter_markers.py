"""E8 completion: every industrial format-adapter cut carries a gap marker when
``gap_marker`` is given, and the output is byte-identical when it is ``None``."""
import re

import pytest

from tameru.compress_context import compress_context, preprocess_csv
from tameru.format_adapters import adapt_format, detect_format

MARK = "<<GAP>>"


def marker(omitted: int, total: int) -> str:
    return f"<<GAP {omitted}/{total}>>"


def _csv(sep: str) -> str:
    rows = [sep.join(["id", "name", "status"])]
    rows += [sep.join([str(i), f"item-{i:02d}", "ok"]) for i in range(1, 21)]
    return "\n".join(rows)


def _ndjson() -> str:
    return "\n".join(f'{{"id": {i}, "name": "item-{i:02d}"}}' for i in range(12))


def _markdown() -> str:
    parts = ["# Runbook", "intro text"]
    for i in range(8):
        parts += ["", f"## Step {i}", f"do thing-{i:02d} carefully"]
    return "\n".join(parts)


def _yaml() -> str:
    return "\n".join(
        [
            "alpha:", "  x: 1",
            "bravo:", "  y: target-one",
            "charlie:", "  z: 3",
            "delta:", "  w: target-two",
            "echo:", "  v: 5",
        ]
    )


def _xml() -> str:
    return "\n".join(
        ["<records>"]
        + [f'<rec id="{i}">item-{i:02d}</rec>' for i in range(10)]
        + ["</records>"]
    )


def _sql() -> str:
    return "\n".join(f"INSERT INTO t VALUES ({i}, 'item-{i:02d}');" for i in range(12))


def _ini() -> str:
    return "\n\n".join(f"[sec{i}]\nname = item-{i:02d}\nport = {8000 + i}" for i in range(8))


def _html() -> str:
    return "\n".join(
        ["<!doctype html>", "<html>", "<body>"]
        + [f"<p>item-{i:02d}</p>" for i in range(10)]
        + ["</body>", "</html>"]
    )


# format, text, query, expected number of runs
CASES = [
    ("csv", _csv(","), "item-05 item-12", 3),
    ("tsv", _csv("\t"), "item-05 item-12", 3),
    ("ndjson", _ndjson(), "item-03 item-08", 3),
    ("markdown", _markdown(), "thing-02 thing-05", 3),
    ("yaml", _yaml(), "target-one target-two", 3),
    ("xml", _xml(), "item-02 item-06", 3),
    ("sql", _sql(), "item-03 item-08", 3),
    ("ini", _ini(), "item-02 item-05", 3),
    ("html", _html(), "item-02 item-06", 3),
]


@pytest.mark.parametrize("fmt,text,query,runs", CASES, ids=[c[0] for c in CASES])
def test_every_cut_is_marked(fmt, text, query, runs):
    assert detect_format(text) == fmt
    plain = adapt_format(text, query)
    marked = adapt_format(text, query, gap_marker=marker)
    assert plain.applied and marked.applied
    marker_lines = [ln for ln in marked.text.split("\n") if ln.startswith("<<GAP ")]
    assert len(marker_lines) == runs
    # removing the markers gives back exactly what the unmarked adapter emits
    stripped = "\n".join(ln for ln in marked.text.split("\n") if not ln.startswith("<<GAP "))
    if fmt in {"markdown", "ini"}:  # blank-line separated: a marker sits between blanks
        stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip("\n")
        assert re.sub(r"\n{3,}", "\n\n", plain.text) == stripped
    else:
        assert stripped == plain.text
    # total is the original length, and omitted chars are positive
    for ln in marker_lines:
        omitted, total = ln[len("<<GAP "):-2].split("/")
        assert int(total) == len(text) and int(omitted) > 0
    assert marked.kept_records == plain.kept_records


@pytest.mark.parametrize("fmt,text,query,runs", CASES, ids=[c[0] for c in CASES])
def test_none_marker_is_byte_identical(fmt, text, query, runs):
    explicit = adapt_format(text, query, gap_marker=None)
    default = adapt_format(text, query)
    assert explicit == default
    assert "GAP" not in default.text and "omitted" not in default.text


def test_markers_stand_where_the_cut_was():
    marked = adapt_format(_csv(","), "item-05 item-12", gap_marker=marker)
    lines = marked.text.split("\n")
    assert lines[0] == "id,name,status"
    assert lines[1].startswith("<<GAP ") and lines[2].startswith("5,item-05")
    assert lines[3].startswith("<<GAP ") and lines[4].startswith("12,item-12")
    assert lines[5].startswith("<<GAP ") and len(lines) == 6
    first = len("\n".join(f"{i},item-{i:02d},ok" for i in range(1, 5)))
    assert lines[1] == f"<<GAP {first}/{len(_csv(','))}>>"


def test_leading_and_trailing_runs_in_ndjson():
    marked = adapt_format(_ndjson(), "item-03 item-08", gap_marker=marker)
    lines = marked.text.split("\n")
    assert lines[0].startswith("<<GAP ") and lines[-1].startswith("<<GAP ")


def test_engine_wiring_total_is_the_callers_length():
    text = _csv(",") + "\n"
    result = compress_context(text, "item-05 item-12", ccr=False, citations=False, gap_marker=marker)
    assert result.receipt["industrial"]["applied"]
    assert result.compressed_text.count("<<GAP ") == 3
    assert f"/{len(text)}>>" in result.compressed_text
    plain = compress_context(text, "item-05 item-12", ccr=False, citations=False)
    assert "GAP" not in plain.compressed_text
    again = compress_context(text, "item-05 item-12", ccr=False, citations=False, gap_marker=None)
    assert again.compressed_text == plain.compressed_text


def test_preprocess_csv_marks_cuts_too():
    text = _csv(",")
    plain = preprocess_csv(text, "item-05 item-12")
    marked = preprocess_csv(text, "item-05 item-12", gap_marker=marker)
    assert preprocess_csv(text, "item-05 item-12", gap_marker=None) == plain
    assert marked.count("<<GAP ") == 3
    assert "\n".join(ln for ln in marked.split("\n") if not ln.startswith("<<GAP ")) == plain


def test_blank_only_runs_get_no_marker():
    text = "alpha:\n  x: target-one\n\n\n\nbravo:\n  y: 2\n"
    marked = adapt_format(text, "target-one", gap_marker=marker)
    # `bravo:` and its child are dropped (one marker); the blank lines are not a run of their own
    assert marked.text.count("<<GAP ") == 1
