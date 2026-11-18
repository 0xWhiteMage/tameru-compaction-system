"""1.10.0: opt-in redact_secrets, kind-aware gap_marker, deprecated unwrap alias."""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tameru.compress_context as cc  # noqa: E402
from benchmarks.redteam.corpus import build_corpus  # noqa: E402
from tameru.compress_context import (  # noqa: E402
    _SECRETS_EXTRA_RE, _SECRETS_RE, compress_context, contains_secret,
)
from tameru.gap_kind import call_gap_marker, gap_accepts_kind  # noqa: E402
from tameru.markers import GAP_KINDS, REDACTED_MARKER, marker_name  # noqa: E402


def _planted():
    return [c for c in build_corpus() if c.get("secret")]


def _has_match(text: str) -> bool:
    return _SECRETS_RE.search(text) is not None or _SECRETS_EXTRA_RE.search(text) is not None


def test_there_are_planted_secret_cases():
    assert len(_planted()) >= 6


def _query_naming_the_secret(case) -> str:
    return case["secret"].split("=")[0].split(":")[0]   # the key name makes the engine keep the line


def test_redaction_leaves_no_match_and_is_deterministic():
    leaked = 0
    for case in _planted():
        query = _query_naming_the_secret(case)
        kwargs = dict(ccr=False, citations=False, anchor_errors=True)
        plain = compress_context(case["text"], query, **kwargs)
        red = compress_context(case["text"], query, redact_secrets=True, **kwargs)
        again = compress_context(case["text"], query, redact_secrets=True, **kwargs)
        assert red.compressed_text == again.compressed_text
        assert (red.fail_open, red.compression_risk, red.confidence) == (plain.fail_open, plain.compression_risk, plain.confidence)
        if red.fail_open:
            assert red.compressed_text == plain.compressed_text   # the original comes back unredacted
            continue
        assert not _has_match(red.compressed_text), case["id"]
        if _has_match(plain.compressed_text):
            leaked += 1
            assert REDACTED_MARKER in red.compressed_text and "redacted_secrets" in red.reasons
            line = next(ln for ln in red.compressed_text.splitlines() if REDACTED_MARKER in ln)
            assert marker_name(line) == "redacted_secret"
    assert leaked >= 3   # the matrix really exercises redaction


def test_redaction_off_is_byte_identical_and_clean_text_is_untouched():
    text = "INFO fine\n" * 300 + "OPENAI_API_KEY=sk-" + "a1b2c3d4" * 6 + "\nERROR boom happened\n"
    base = compress_context(text, "boom", ccr=False, citations=False)
    assert compress_context(text, "boom", ccr=False, citations=False, redact_secrets=False) == base
    clean = "INFO fine\n" * 300 + "ERROR boom happened\n"
    assert (compress_context(clean, "boom", ccr=False, citations=False, redact_secrets=True)
            == compress_context(clean, "boom", ccr=False, citations=False))


def test_redaction_never_flips_fail_open_over_the_planted_matrix():
    for case in _planted():
        for query in ("", case["query"], _query_naming_the_secret(case), "unrelated words here"):
            a = compress_context(case["text"], query, ccr=False, citations=False)
            b = compress_context(case["text"], query, ccr=False, citations=False, redact_secrets=True)
            assert (a.fail_open, a.compression_risk, a.confidence) == (b.fail_open, b.compression_risk, b.confidence)


def test_redact_helper_is_idempotent():
    token = "OPENAI_API_KEY=sk-" + "a1b2c3d4" * 6
    once = cc.redact_secrets_in("x\n" + token + "\ny")
    assert contains_secret(token) and not contains_secret(once)
    assert cc.redact_secrets_in(once) == once


# ---- kind-aware gap_marker --------------------------------------------------------------------

def _doc() -> str:
    paras = [f"Section {i}: routine padding text number {i} about nothing in particular." for i in range(40)]
    paras[20] = "Section 20: the deploy token is ZX-9981-ALPHA and must rotate nightly."
    return "\n\n".join(paras)


def test_arity_detection():
    assert not gap_accepts_kind(None)
    assert not gap_accepts_kind(lambda o, t: "")
    assert not gap_accepts_kind(lambda *a: "")
    assert gap_accepts_kind(lambda o, t, kind="lines": "")
    assert gap_accepts_kind(lambda o, t, *, kind=None: "")
    assert call_gap_marker(lambda o, t: f"{o}/{t}", 1, 2, "rows") == "1/2"
    assert call_gap_marker(lambda o, t, kind="x": f"{o}/{t}/{kind}", 1, 2, "rows") == "1/2/rows"


def test_two_argument_marker_behaves_as_before_and_three_argument_sees_kinds():
    seen = []

    def old(omitted, total):
        return f"<<{omitted}/{total}>>"

    def new(omitted, total, kind="lines"):
        seen.append(kind)
        return f"<<{omitted}/{total}>>"

    a = compress_context(_doc(), "ZX-9981-ALPHA", ccr=False, citations=False, gap_marker=old)
    b = compress_context(_doc(), "ZX-9981-ALPHA", ccr=False, citations=False, gap_marker=new)
    assert "<<" in a.compressed_text
    assert a.compressed_text == b.compressed_text
    assert seen and set(seen) <= set(GAP_KINDS)
    assert a == b


def test_kind_reaches_a_marker_through_the_inlining_wrapper_and_adapters():
    seen = set()

    def new(omitted, total, kind="lines"):
        seen.add(kind)
        return f"<<{kind}>>"

    diff = "\n".join(
        ["diff --git a/a.py b/a.py", "--- a/a.py", "+++ b/a.py"]
        + [line for i in range(40) for line in (f"@@ -{i * 9},3 +{i * 9},3 @@ def f{i}():", f" ctx {i}", f"-old {i}", f"+new {i}")]
    )
    compress_context(diff, "new 7", ccr=False, citations=False, gap_marker=new, inline_short_gaps=True)
    compress_context(_doc(), "ZX-9981-ALPHA", ccr=False, citations=False, gap_marker=new, inline_short_gaps=True)
    assert seen and seen <= set(GAP_KINDS)


def test_default_marker_text_is_unchanged():
    out = compress_context(_doc(), "ZX-9981-ALPHA", ccr=False, citations=False)
    assert "[…]" in out.compressed_text


# ---- deprecated alias ---------------------------------------------------------------------------

def test_unwrap_hermes_tool_is_a_one_time_deprecated_alias():
    raw = '{"output": "' + "line\\n" * 80 + '", "exit_code": 0}'
    cc._UNWRAP_ALIAS_WARNED = False
    with pytest.warns(DeprecationWarning):
        first = cc.unwrap_hermes_tool(raw)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        second = cc.unwrap_hermes_tool(raw)
    assert first == second == cc.unwrap_tool_payload(raw).inner
