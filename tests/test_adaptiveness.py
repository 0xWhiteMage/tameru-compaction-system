"""Adaptiveness invariants: the engine's keep behaviour must scale with
document size, respond to query specificity, and bound itself under
saturation — the properties the adaptive pipeline promises."""
import pytest

from tameru.compress_context import compress_context


def _doc(n_lines: int, needle: str | None = None, needle_at: int | None = None) -> str:
    lines = [f"report row {i} metric_alpha={i % 37} metric_beta={i % 11}" for i in range(n_lines)]
    if needle is not None and needle_at is not None:
        lines[needle_at] = needle
    return "\n".join(lines)


def test_keep_ratio_nonincreasing_as_document_grows():
    # Same needle, same query: a larger document must not keep a LARGER
    # fraction of itself — adaptiveness means savings scale with size.
    ratios = []
    for n in (500, 2000, 8000):
        r = compress_context(
            _doc(n, needle="UNIQUE_NEEDLE_X9 here", needle_at=n // 2),
            "UNIQUE_NEEDLE_X9", ccr=False, citations=False,
        )
        ratios.append(len(r.compressed_text) / len(_doc(n, needle="UNIQUE_NEEDLE_X9 here", needle_at=n // 2)))
    assert ratios[0] >= ratios[1] >= ratios[2], ratios


def test_specific_query_saves_more_than_weak_query():
    doc = _doc(2000, needle="UNIQUE_NEEDLE_X9 here", needle_at=1000)
    strong = compress_context(doc, "UNIQUE_NEEDLE_X9", ccr=False, citations=False)
    weak = compress_context(doc, "the and or of", ccr=False, citations=False)
    assert len(strong.compressed_text) <= len(weak.compressed_text)
    assert "UNIQUE_NEEDLE_X9" in strong.compressed_text


def test_saturation_fails_open_or_bounds_keeps():
    # Every line matches the query term: saturating the floor must not emit
    # a "compressed" output that is silently lossy — it either keeps a
    # bounded core or fails open on the full text.
    doc = _doc(2000)
    r = compress_context(doc, "metric_alpha", ccr=False, citations=False)
    if not r.fail_open:
        assert len(r.compressed_text) < len(doc)


def test_no_query_still_terminates_and_marks_risk():
    r = compress_context(_doc(1000), "", ccr=False, citations=False)
    assert r.compressed_text
    assert r.compression_risk in ("low", "medium", "high")
