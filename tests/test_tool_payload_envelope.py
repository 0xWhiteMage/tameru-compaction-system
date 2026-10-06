"""G9: Hermes tool wrappers keep their envelope through the engine.

Hermes tools return JSON objects such as
``{"output": "...", "exit_code": 1, "error": null}`` (terminal) or
``{"content": "1|...", "total_lines": 220}`` (read_file). The engine used to
score only the inner text and drop everything else, so ``exit_code``,
``error`` and ``total_lines`` vanished — and with them the fields Hermes' own
``"exit_code":`` regexes read. ``unwrap_tool_payload`` / ``rewrap_tool_payload``
expose the split; ``compress_context`` re-emits the scalar metadata as one
compact JSON line ahead of a compressed body.
"""
from __future__ import annotations

import json
import re

import pytest

from tameru.compress_context import (
    ToolPayload,
    compress_context,
    rewrap_tool_payload,
    unwrap_hermes_tool,
    unwrap_tool_payload,
)

NEEDLE = "the deploy token is ZX-9981-ALPHA"


def _body(lines: int = 160) -> str:
    rows = [f"line {i}: routine output with nothing of interest" for i in range(lines)]
    rows[lines // 2] = f"line {lines // 2}: {NEEDLE}"
    return "\n".join(rows)


def _terminal(exit_code: int = 1, error=None) -> str:
    return json.dumps(
        {"output": _body(), "exit_code": exit_code, "error": error}, ensure_ascii=False
    )


def _read_file() -> str:
    numbered = "\n".join(f"{i + 1}|{ln}" for i, ln in enumerate(_body().split("\n")))
    return json.dumps(
        {"content": numbered, "total_lines": 160, "file_size": 8123, "truncated": False}
    )


# ------------------------------------------------------------------ the helpers


def test_unwrap_terminal_payload():
    p = unwrap_tool_payload(_terminal(exit_code=2, error="boom"))
    assert isinstance(p, ToolPayload)
    assert p.wrapped and p.field == "output"
    assert p.inner == _body()
    assert p.meta == {"exit_code": 2, "error": "boom"}
    assert list(p.meta) == ["exit_code", "error"]  # original key order


def test_unwrap_read_file_payload():
    p = unwrap_tool_payload(_read_file())
    assert p.wrapped and p.field == "content"
    assert p.inner.startswith("1|line 0:")
    assert p.meta == {"total_lines": 160, "file_size": 8123, "truncated": False}


def test_meta_holds_scalars_only():
    raw = json.dumps(
        {
            "output": _body(),
            "exit_code": 0,
            "error": None,
            "cwd": "/srv/app",
            "ratio": 0.5,
            "ok": True,
            "tags": ["a", "b"],
            "nested": {"k": 1},
        }
    )
    p = unwrap_tool_payload(raw)
    assert p.meta == {"exit_code": 0, "error": None, "cwd": "/srv/app", "ratio": 0.5, "ok": True}


def test_content_wins_over_output_and_is_detected_like_unwrap_hermes_tool():
    raw = json.dumps({"output": "short", "content": _body(), "exit_code": 0})
    p = unwrap_tool_payload(raw)
    assert p.field == "content" and p.meta["output"] == "short"
    assert unwrap_hermes_tool(raw) == p.inner
    # content too short -> falls through to output
    raw = json.dumps({"content": "tiny", "output": _body(), "exit_code": 0})
    assert unwrap_tool_payload(raw).field == "output"


@pytest.mark.parametrize(
    "raw",
    [
        "plain text, not json",
        json.dumps({"output": "x" * 200, "exit_code": 0}),  # exactly 200: not "longer than 200"
        json.dumps({"stdout": _body()}),
        json.dumps([{"output": _body()}]),
        json.dumps({"output": 123456}),
        '{"output": "unterminated',
        "",
    ],
)
def test_not_a_wrapper(raw):
    p = unwrap_tool_payload(raw)
    assert p == ToolPayload(inner=raw, field=None, meta={}, wrapped=False)
    assert unwrap_hermes_tool(raw) == raw


def test_threshold_is_longer_than_200_chars():
    assert unwrap_tool_payload(json.dumps({"output": "x" * 201})).wrapped


def test_payload_equals_a_hand_built_four_field_payload():
    p = unwrap_tool_payload(_terminal(exit_code=2, error="boom"))
    assert p == ToolPayload(
        inner=_body(), field="output", meta={"exit_code": 2, "error": "boom"}, wrapped=True
    )
    assert "order" not in repr(p)
    # a payload without the key order still rewraps (payload first, then meta)
    bare = ToolPayload(inner="x", field="output", meta={"exit_code": 2}, wrapped=True)
    assert json.loads(rewrap_tool_payload(bare, "y")) == {"output": "y", "exit_code": 2}


def test_payload_is_frozen():
    p = unwrap_tool_payload(_terminal())
    with pytest.raises(Exception):
        p.inner = "changed"  # type: ignore[misc]


def test_rewrap_round_trip_keeps_meta_and_key_order():
    original = _terminal(exit_code=3, error="failed")
    p = unwrap_tool_payload(original)
    rebuilt = rewrap_tool_payload(p, "SHORT BODY")
    obj = json.loads(rebuilt)
    assert obj == {"output": "SHORT BODY", "exit_code": 3, "error": "failed"}
    assert list(obj) == ["output", "exit_code", "error"]
    assert "\n" not in rebuilt  # one line
    # round trip with the unchanged inner reproduces the original object
    assert json.loads(rewrap_tool_payload(p, p.inner)) == json.loads(original)


def test_rewrap_read_file_order():
    p = unwrap_tool_payload(_read_file())
    obj = json.loads(rewrap_tool_payload(p, "1|x"))
    assert list(obj) == ["content", "total_lines", "file_size", "truncated"]
    assert obj["content"] == "1|x" and obj["total_lines"] == 160


def test_rewrap_unwrapped_payload_is_the_new_text():
    p = unwrap_tool_payload("plain")
    assert rewrap_tool_payload(p, "other") == "other"


def test_rewrap_output_is_readable_by_hermes_exit_code_regex():
    rebuilt = rewrap_tool_payload(unwrap_tool_payload(_terminal(exit_code=-9)), "x")
    assert re.search(r'"exit_code"\s*:\s*(-?\d+)', rebuilt).group(1) == "-9"


# --------------------------------------------------------------- compress_context


def _compress(raw: str, query: str = "what is the deploy token ZX-9981-ALPHA?"):
    return compress_context(raw, query, ccr=False, citations=False)


def test_exit_code_error_and_total_lines_survive_compression():
    result = _compress(_terminal(exit_code=1, error="Traceback: boom"))
    assert not result.fail_open
    first, _, body = result.compressed_text.partition("\n")
    assert json.loads(first) == {"exit_code": 1, "error": "Traceback: boom"}
    assert NEEDLE in body
    assert len(result.compressed_text) < 0.6 * len(_terminal())
    # Hermes' own regex still finds the exit code in the first line
    assert re.search(r'"exit_code"\s*:\s*(-?\d+)', result.compressed_text).group(1) == "1"


def test_read_file_total_lines_survive():
    result = _compress(_read_file(), "what is the deploy token ZX-9981-ALPHA?")
    assert not result.fail_open
    first, _, body = result.compressed_text.partition("\n")
    assert json.loads(first) == {"total_lines": 160, "file_size": 8123, "truncated": False}
    assert NEEDLE in body
    assert re.search(r"^\d+\|", body, re.M)  # the N| gutter is untouched


def test_meta_line_is_compact_json_on_one_line():
    result = _compress(_terminal(exit_code=0))
    first = result.compressed_text.split("\n")[0]
    assert first == json.dumps({"exit_code": 0, "error": None}, separators=(",", ":"))


def test_meta_line_is_non_ascii_safe():
    raw = json.dumps({"output": _body(), "exit_code": 0, "cwd": "/tmp/日本語"}, ensure_ascii=False)
    first = _compress(raw).compressed_text.split("\n")[0]
    assert json.loads(first)["cwd"] == "/tmp/日本語"


def test_empty_meta_emits_nothing():
    raw = json.dumps({"output": _body()})
    result = _compress(raw)
    assert not result.fail_open
    assert not result.compressed_text.startswith("{")
    assert NEEDLE in result.compressed_text


def test_non_scalar_only_meta_emits_nothing():
    raw = json.dumps({"output": _body(), "files": ["a", "b"]})
    assert not _compress(raw).compressed_text.startswith("{")


def test_fail_open_returns_the_callers_wrapper_untouched():
    raw = _terminal(exit_code=1)
    result = _compress(raw, "continue")
    assert result.fail_open
    assert result.compressed_text == raw


def test_unwrapped_text_gets_no_meta_line():
    result = _compress(_body())
    assert not result.fail_open
    assert not result.compressed_text.startswith("{")


def test_meta_is_counted_in_the_token_accounting():
    result = _compress(_terminal(exit_code=1, error="x" * 50))
    assert result.kept_tokens >= len(result.compressed_text.split("\n")[0].split())  # not ignored
    assert result.tokens_saved_pct > 0


def test_auto_strategy_keeps_the_envelope():
    result = compress_context(
        _terminal(exit_code=4),
        "what is the deploy token ZX-9981-ALPHA?",
        ccr=False,
        citations=False,
        strategy="auto",
    )
    assert not result.fail_open
    assert json.loads(result.compressed_text.split("\n")[0])["exit_code"] == 4


def test_a_huge_integer_is_not_json_and_never_crashes():
    """CPython refuses to parse a 4300+ digit integer with a plain ValueError
    (not a JSONDecodeError): a tool that prints one huge number must neither
    crash the unwrap nor the format detection in front of it."""
    big = "9" * 20000
    wrapped = '{"n": ' + big + ', "output": "' + "x\\n" * 200 + '"}'
    assert not unwrap_tool_payload(wrapped).wrapped
    for text in (
        "header\n" + big + "\ntrailer\nERROR boom",
        wrapped,
        "[" + big + ", 2, 3]",
        '{"a": ' + big + '}\n{"a": 2}\n',
    ):
        result = compress_context(text, "why is it failing?", ccr=False, citations=False)
        assert result.compressed_text
