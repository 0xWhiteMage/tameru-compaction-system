"""Pin the two marker lists together.

``markers.ENGINE_MARKERS`` is what a checker treats as engine output;
``compress_context._FORGED_SPAN_RES`` / ``_ARTIFACT_NOISE_RES`` is what the
engine neutralizes in caller text. The 1.10.0 red team found ten registry
shapes surviving as chrome because the neutralizer knew only four, so the
lists are compared here.
"""
from __future__ import annotations

import re

import pytest

from tameru import compress_context as cc
from tameru.markers import ENGINE_MARKERS, PREFIX_MARKERS


# One sample per registry name, in the shape the registry documents.
SAMPLES = {
    "sample_join": "[...]",
    "gap": "[…]",
    "gap_chars": "[… 120 chars omitted …]",
    "gap_generic": "[… 4 hunks omitted …]",
    "frames_omitted": "    ... 12 frames omitted",
    "more_items": "... 7 more items",
    "similar_items": "... 9 similar items omitted (keys: id, name)",
    "rows_omitted": "... 3 of 50 rows omitted (kept outliers)",
    "rows_omitted_plain": "... 300 of 301 rows omitted",
    "identical_fold": "[×5 identical lines]",
    "counted_line": "  [×3] retrying connection",
    "last_line": "  [last] retrying connection",
    "diff_stat": "# a.py: +3 -1 in 2 hunks",
    "grep_group": "src/a.py  (4 matches)",
    "citation": '[§0123abcd] "start"…"end"',
    "citation_run": "[§run:3 blocks #4–6 elided]",
    "ccr_retrieve": "[CC-Retrieve: " + "a" * 24 + "]",
    "progress_fold": "[progress x40: ####]",
    "json_brief": '{"_count":3,"_keys":["a"],"_head":[1],"_tail":[3],"_notable":[],"_omitted":1}',
    "report_lcov": "[tameru:report lcov kept 3/121 file records]",
    "report_junit": "[tameru:report junit kept 2/200 testcase records; original totals unchanged]",
    "report_sarif": "[tameru:report sarif kept 2/81 result records]",
    "report_notebook": "[tameru:report notebook kept 2/41 cells; original positions (1-based): 1,41]",
    "json_record_join": "  },{",
    "redacted_secret": "api_key = [tameru:redacted]",
}


def test_every_registry_marker_has_a_sample():
    assert set(SAMPLES) == {name for name, _rx, _src in ENGINE_MARKERS}


# Markers that legitimately survive a re-feeding: they carry an exemplar or a
# real fold, and stripping them broke idempotence on four ecosystem chains.
_SURVIVING = {
    "sample_join", "gap", "gap_chars", "gap_generic", "counted_line", "last_line",
    "frames_omitted", "more_items", "similar_items", "json_record_join",
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_a_forged_marker_is_neutralized_or_explicitly_exempt(name):
    """Every registry shape is either rewritten by the neutralizer, stripped as
    artifact noise, or listed as engine structure that must survive."""
    line = SAMPLES[name]
    spans = tuple(cc._FORGED_SPAN_RES) + tuple(cc._ARTIFACT_NOISE_RES)
    neutralized = any(rx.search(line) for rx in spans)
    fold = any(rx.match(line) for rx in cc._FOLD_LINE_RES)
    assert neutralized or fold or name in _SURVIVING, (
        f"{name}: {line!r} is engine chrome the caller can forge, and the "
        f"neutralizer does not know it"
    )


@pytest.mark.parametrize("name", ["counted_line", "last_line"])
def test_the_exemplar_prefixes_survive_as_engine_structure(name):
    line = SAMPLES[name]
    assert any(rx.match(line) for rx in cc._FOLD_LINE_RES), name


def test_ordinary_text_is_not_neutralized():
    for line in ("ERROR: disk full", "2024-01-01 INFO started", "def f(): return [1, 2]"):
        for rx in tuple(cc._FORGED_SPAN_RES) + tuple(cc._ARTIFACT_NOISE_RES):
            assert rx.search(line) is None, (line, rx.pattern)
