"""E8: ``recursion_markers`` — caller-declared "this input is already compressed".

The built-in guard looks for Tameru's own wrappers anywhere in the text. A host
that renders its own elision markers (Hermes writes
``⟪HERMES-CONTEXT-COMPRESSION: N of M chars omitted…⟫``) can list them here:
if any LINE of the input starts with one (after ``lstrip``) the call is a
no-op identical to the built-in guard. Matching is explicit and anchored; the
engine never guesses that a foreign marker means "compressed".
"""
from __future__ import annotations

import pytest

from tameru.compress_context import compress_context

HERMES = "⟪HERMES-CONTEXT-COMPRESSION:"
QUERY = "when does the deploy token ZX-9981-ALPHA rotate?"


def _doc(first_line: str = "") -> str:
    paras = [
        f"Section {i}: routine padding text number {i} about nothing in particular."
        for i in range(30)
    ]
    paras[12] = "Section 12: the deploy token is ZX-9981-ALPHA and must rotate nightly."
    body = "\n\n".join(paras)
    return first_line + "\n" + body if first_line else body


def _marked(prefix: str = "") -> str:
    return _doc(f"{prefix}{HERMES} 5 of 10 chars omitted here by Hermes's compressor.⟫")


def _assert_guard_noop(text: str, result) -> None:
    assert result.policy_name == "local-noop-recursion"
    assert result.fail_open is True
    assert result.reasons == ["input already compressed (recursion guard)"]
    assert result.compressed_text == text
    assert result.tokens_saved_pct == 0.0
    assert result.kept_tokens == result.original_tokens
    assert result.compression_risk == "low"


def test_listed_marker_at_line_start_is_a_noop():
    text = _marked()
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=[HERMES]
    )
    _assert_guard_noop(text, result)


def test_marker_after_lstrip_still_counts():
    text = _marked(prefix="    \t")
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=(HERMES,)
    )
    _assert_guard_noop(text, result)


def test_marker_on_a_later_line_counts():
    text = _doc() + "\n" + f"  {HERMES} 1 of 2 chars omitted⟫\nafter"
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=[HERMES]
    )
    _assert_guard_noop(text, result)


def test_result_matches_the_builtin_guard():
    builtin_text = _doc("<compressed_context version=\"1\">")
    builtin = compress_context(builtin_text, QUERY, ccr=False, citations=False)
    explicit = compress_context(
        _marked(), QUERY, ccr=False, citations=False, recursion_markers=[HERMES]
    )
    for field in (
        "policy_name", "fail_open", "reasons", "compression_risk", "confidence",
        "keep_ratio", "kept_line_ratio", "tokens_saved_pct", "mode",
    ):
        assert getattr(explicit, field) == getattr(builtin, field), field


def test_hermes_marker_alone_does_not_trigger_the_guard():
    text = _marked()
    result = compress_context(text, QUERY, ccr=False, citations=False)
    assert result.policy_name != "local-noop-recursion"
    assert not result.fail_open
    assert result.tokens_saved_pct > 50
    assert "ZX-9981-ALPHA" in result.compressed_text
    # ... and an explicitly empty list changes nothing either
    again = compress_context(text, QUERY, ccr=False, citations=False, recursion_markers=())
    assert again.compressed_text == result.compressed_text


def test_a_marker_mentioned_mid_line_is_not_a_match():
    text = _doc(f"The log line says {HERMES} 5 of 10 chars omitted⟫ somewhere.")
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=[HERMES]
    )
    assert result.policy_name != "local-noop-recursion"
    assert not result.fail_open


def test_other_markers_do_not_match_a_listed_one():
    text = _marked()
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=["[my-marker]", "<x>"]
    )
    assert result.policy_name != "local-noop-recursion"


def test_empty_marker_strings_are_ignored_not_wildcards():
    text = _doc()
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=["", None, 5]  # type: ignore[list-item]
    )
    assert result.policy_name != "local-noop-recursion"
    assert not result.fail_open


def test_a_bare_string_is_one_marker_not_a_set_of_characters():
    text = _marked()
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=HERMES
    )
    _assert_guard_noop(text, result)
    plain = _doc()
    result = compress_context(
        plain, QUERY, ccr=False, citations=False, recursion_markers="S"  # "S" starts "Section ..."
    )
    assert result.policy_name == "local-noop-recursion"  # one marker "S", anchored at line start
    result = compress_context(
        plain, QUERY, ccr=False, citations=False, recursion_markers="⟫"
    )
    assert result.policy_name != "local-noop-recursion"


def test_any_iterable_is_accepted():
    text = _marked()
    result = compress_context(
        text, QUERY, ccr=False, citations=False,
        recursion_markers=(m for m in ["[nope]", HERMES]),
    )
    _assert_guard_noop(text, result)


def test_guard_applies_through_the_auto_strategy():
    text = _marked()
    result = compress_context(
        text, QUERY, ccr=False, citations=False, strategy="auto",
        recursion_markers=[HERMES],
    )
    _assert_guard_noop(text, result)


@pytest.mark.parametrize("query", ["", "continue", "which token?"])
def test_noop_does_not_depend_on_the_query(query):
    text = _marked()
    result = compress_context(
        text, query, ccr=False, citations=False, recursion_markers=[HERMES]
    )
    _assert_guard_noop(text, result)


def test_a_non_matching_generator_is_read_once_and_the_auto_ladder_still_runs():
    text = _doc()
    result = compress_context(
        text, QUERY, ccr=False, citations=False, strategy="auto",
        recursion_markers=(m for m in ["[nope]", "<also-no>"]),
    )
    assert result.policy_name != "local-noop-recursion"
    assert not result.fail_open


@pytest.mark.parametrize("field", ["output", "content"])
@pytest.mark.parametrize("ensure_ascii", [True, False])
def test_marker_opening_a_tool_payload_line_counts_inside_the_json_wrapper(field, ensure_ascii):
    """A Hermes tool result is a JSON object around one payload string: the
    marker that opens the payload is escaped there and never opens a line of the
    wrapper text, so a re-wrapped compacted result used to be compressed again."""
    import json

    payload = _marked()
    text = json.dumps({field: payload, "exit_code": 0}, ensure_ascii=ensure_ascii)
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=[HERMES]
    )
    _assert_guard_noop(text, result)


def test_marker_mentioned_mid_line_of_a_wrapped_payload_is_still_not_a_match():
    import json

    payload = _doc("the host once wrote " + HERMES + " in a sentence")
    text = json.dumps({"output": payload, "exit_code": 0})
    result = compress_context(
        text, QUERY, ccr=False, citations=False, recursion_markers=[HERMES]
    )
    assert result.policy_name != "local-noop-recursion"
