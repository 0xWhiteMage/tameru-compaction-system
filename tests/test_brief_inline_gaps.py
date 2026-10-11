"""1.4.1 fix-all: brief_context honours InliningGapMarker like compress_context does."""
from __future__ import annotations

from tameru.compress_context import InliningGapMarker, brief_context


def _marker(omitted: int, total: int) -> str:
    return f"<<{omitted:,} of {total:,} chars omitted here by the host's compressor, see the ref to recover>>"


def _text() -> str:
    lines = [f"2026-10-11 12:00:{i:02d} INFO worker-{i % 10} processed batch {i:03d} " + "x" * 40 for i in range(80)]
    lines[40] = "ERROR payment gateway timeout order=991"
    lines[41] = "retry 1/3"
    lines[42] = "FATAL db pool exhausted after 30s"
    return "\n".join(lines)


def test_brief_inlines_a_gap_shorter_than_its_marker():
    out = brief_context(_text(), budget_chars=1200, gap_marker=InliningGapMarker(_marker))
    assert "ERROR payment gateway" in out and "FATAL db pool" in out
    assert "ERROR payment gateway timeout order=991\nretry 1/3\nFATAL db pool exhausted after 30s" in out
    assert len(out) <= 1200


def test_a_plain_marker_still_marks_every_gap():
    out = brief_context(_text(), budget_chars=1200, gap_marker=_marker)
    assert "retry 1/3" not in out
    assert "ERROR payment gateway timeout order=991\n<<9 of" in out


def test_long_gaps_keep_their_marker_when_inlining():
    out = brief_context(_text(), budget_chars=1200, gap_marker=InliningGapMarker(_marker))
    assert out.count("<<") >= 2   # the long head/tail gaps are still marked
