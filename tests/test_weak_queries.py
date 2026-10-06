"""E6: a query made only of conversational filler is an empty query everywhere.

Measured on 1.3.0 with the query "continue": a 1 MB log kept 0 of 106 ERROR
lines (99.88% cut, risk "high"), a CSV collapsed to one row (98%), a markdown
file to the one section containing the word (94%). "thanks", "go ahead" and
"proceed" behaved the same way; only "ok" and "fix it" happened to fail open.
"""
from __future__ import annotations

import json
import random

import pytest

from tameru import compress_context as cc
from tameru import format_adapters as fa
from tameru.compress_context import compress_context

FILLER_QUERIES = ["continue", "thanks", "go ahead", "proceed", "ok", "fix it"]


def _markdown() -> str:
    return "\n\n".join(
        f"## Section {i}\n\nThis section covers topic number {i}. We will continue to "
        f"describe the proceed steps and thanks to contributors. Step {i} uses config "
        f"value alpha-{i}."
        for i in range(40)
    )


def _csv() -> str:
    rows = [
        f"{i},row{i},{'continue' if i == 5 else 'ok' if i % 2 else 'done'},user{i % 7}"
        for i in range(200)
    ]
    return "id,name,status,owner\n" + "\n".join(rows)


def _json() -> str:
    return json.dumps(
        [
            {
                "id": i,
                "name": f"item-{i}",
                "status": "ok" if i % 3 else "continue",
                "tags": ["a", "b"],
                "note": "please proceed with details",
            }
            for i in range(300)
        ],
        indent=1,
    )


def _log() -> str:
    rng = random.Random(3)
    out = []
    for i in range(1500):
        ts = f"2026-03-14 12:{i // 60 % 60:02d}:{i % 60:02d}"
        h = "%08x" % rng.getrandbits(32)
        if i % 97 == 40:
            out.append(f"{ts} ERROR w1 upstream timeout after {rng.randint(1, 999)}ms req={h}")
        else:
            out.append(f"{ts} INFO  w1 GET /api/v1/users/{h}/profile 200 {rng.randint(1, 999)}ms")
    return "\n".join(out)


def _diff() -> str:
    hunks = []
    for i in range(60):
        hunks += [
            f"@@ -{i * 10},6 +{i * 10},7 @@ def handler_{i}():",
            f"     x = {i}",
            f"-    y = old_{i}",
            f"+    y = new_{i}",
            f"+    z = extra_{i}",
            "     return x",
        ]
    header = ["diff --git a/src/app.py b/src/app.py", "--- a/src/app.py", "+++ b/src/app.py"]
    return "\n".join(header + hunks)


DOCUMENTS = {
    "markdown": _markdown(),
    "csv": _csv(),
    "json": _json(),
    "log": _log(),
    "diff": _diff(),
}


@pytest.mark.parametrize("query", FILLER_QUERIES)
@pytest.mark.parametrize("kind", sorted(DOCUMENTS))
def test_filler_query_never_makes_a_high_risk_deep_cut(kind, query):
    text = DOCUMENTS[kind]
    result = compress_context(text, query, ccr=False, citations=False)
    assert not (result.compression_risk == "high" and result.tokens_saved_pct > 90)
    # Stronger: it behaves like an empty query, so nothing is cut at all.
    assert result.fail_open
    assert result.compressed_text == text


@pytest.mark.parametrize("query", ["OK", "LGTM", "Thanks!", "Go ahead.", "keep going", "carry on", "sounds good"])
def test_other_filler_spellings_are_filler_too(query):
    for kind in ("csv", "log", "markdown"):
        result = compress_context(DOCUMENTS[kind], query, ccr=False, citations=False)
        assert result.fail_open, (kind, query)


@pytest.mark.parametrize("query", ["continue", "OK", "fix it", "go ahead"])
def test_filler_query_matches_the_empty_query_result(query):
    for kind in ("csv", "log"):
        filler = compress_context(DOCUMENTS[kind], query, ccr=False, citations=False)
        empty = compress_context(DOCUMENTS[kind], "", ccr=False, citations=False)
        assert filler.fail_open == empty.fail_open
        assert filler.compressed_text == empty.compressed_text
        assert filler.compression_risk == empty.compression_risk


def test_receipt_keeps_the_callers_words():
    result = compress_context(DOCUMENTS["csv"], "continue", ccr=False, citations=False)
    import hashlib

    assert result.receipt["query_hash"] == hashlib.sha256(b"continue").hexdigest()[:12]


def test_topic_terms_ignore_filler():
    for query in ("continue", "thanks", "proceed", "go ahead", "sounds good", "keep going"):
        assert cc._topic_terms(query) == [], query
    assert cc._topic_terms("which tasks are done?") == ["tasks"]
    assert "continue" in cc._extract_terms("continue")  # scoring terms are unchanged


def test_weak_next_chat_has_the_new_filler():
    expected = {
        "continue", "thanks", "thank", "ahead", "proceed", "okay", "sure", "lgtm",
        "sounds", "good", "great", "yes", "yeah", "yep", "cool", "done", "again",
        "retry", "going", "carry", "nice", "perfect", "please",
    }
    assert expected <= cc._WEAK_NEXT_CHAT
    # the pre-existing entries stay
    assert {"keep", "track", "every", "detail", "details", "next", "chat"} <= cc._WEAK_NEXT_CHAT


@pytest.mark.parametrize(
    "query", ["continue", "thanks", "ok", "OK", "LGTM", "go ahead", "fix it"]
)
def test_adapters_do_not_fall_back_to_filler_words(query):
    assert fa._query_selectors(query) == ()
    result = fa.adapt_format(DOCUMENTS["csv"], query)
    assert not result.applied


def test_adapter_fallback_is_kept_for_real_queries():
    assert fa._query_selectors("row5") == ("row5",)
    assert "done" in fa._query_selectors("which tasks are done")
    selected = fa.adapt_format(DOCUMENTS["csv"], "row5")
    assert selected.applied and "row5" in selected.text


def test_a_real_question_still_compresses():
    result = compress_context(
        DOCUMENTS["csv"], "what is the status of row5?", ccr=False, citations=False
    )
    assert "row5" in result.compressed_text
    assert result.tokens_saved_pct > 50


def test_mixed_query_keeps_working():
    """Filler plus a real selector is a real query."""
    text = DOCUMENTS["log"]
    result = compress_context(
        text, "thanks, now continue with the upstream timeout errors", ccr=False, citations=False
    )
    assert "ERROR" in result.compressed_text
