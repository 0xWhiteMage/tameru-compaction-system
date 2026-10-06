"""E4: numbered reads (`cat -n`, Hermes `N|`, `N: `) are code, not tables."""
import json
import re

import pytest

from tameru.compress_context import compress_context
from tameru.format_adapters import detect_format


def _source(n: int = 300) -> list[str]:
    out = ["import os, sys, json", ""]
    for i in range(n):
        out += [
            f"def handler_{i}(request, context=None):",
            f'    """Handle route {i}."""',
            f"    value = request.get('key_{i}', {i}), context",
            "    if context is None:",
            f"        return value[0] + {i}",
            f"    return value, context, 'handler_{i}-done'",
            "",
        ]
    return out


def _render(fmt: str) -> str:
    lines = _source()
    if fmt == "tab":  # cat -n
        return "\n".join(f"{i + 1:6d}\t{ln}" for i, ln in enumerate(lines))
    if fmt == "pipe":  # Hermes read_file
        return "\n".join(f"{i + 1}|{ln}" for i, ln in enumerate(lines))
    return "\n".join(f"{i + 1}: {ln}" for i, ln in enumerate(lines))


BODY = [
    "def handler_240(request, context=None):",
    "value = request.get('key_240', 240), context",
    "return value[0] + 240",
    "return value, context, 'handler_240-done'",
]


@pytest.mark.parametrize("fmt", ["tab", "pipe", "colon"])
def test_numbered_read_keeps_the_whole_function_body(fmt):
    text = _render(fmt)
    assert detect_format(text) == "numbered_code"
    result = compress_context(
        text, "what does handler_240 do?", ccr=False, citations=False
    )
    assert not result.fail_open
    assert result.content_type not in {"csv", "tsv", "yaml"}
    assert len(result.compressed_text) < len(text) / 4
    out = result.compressed_text
    for fragment in BODY:
        assert fragment in out
    # the gutter is kept: the output lines are original lines
    assert re.search(r"^\s*\d+(?:\t|\||: )\s*def handler_240", out, re.M)
    assert not result.receipt["industrial"]["applied"]


def test_numbered_read_inside_a_hermes_tool_wrapper():
    lines = _render("pipe")
    payload = json.dumps({"content": lines, "total_lines": lines.count("\n") + 1})
    result = compress_context(
        payload, "what does handler_240 do?", ccr=False, citations=False
    )
    assert not result.fail_open
    assert result.content_type not in {"csv", "tsv", "yaml"}
    for fragment in BODY:
        assert fragment in result.compressed_text
    assert '"total_lines"' in result.compressed_text  # envelope metadata kept (G9)


def test_numbered_read_is_never_routed_to_a_table_even_with_a_generic_query():
    text = _render("tab")
    result = compress_context(text, "continue", ccr=False, citations=False)
    assert result.content_type not in {"csv", "tsv", "yaml"}
    assert "csv" not in " ".join(result.reasons).lower()


def test_numbered_read_scores_without_the_gutter():
    # "126" appears only as a line number: it must not select that line.
    text = _render("tab")
    result = compress_context(text, "show handler_77", ccr=False, citations=False)
    assert "def handler_77(request, context=None):" in result.compressed_text


def test_a_tsv_with_an_id_column_is_still_a_tsv():
    tsv = "id\tname\tstatus\n" + "\n".join(
        f"{i}\tuser{i}\t{'ok' if i % 3 else 'bad'}" for i in range(1, 40)
    )
    assert detect_format(tsv) == "tsv"
    pipes = "\n".join(f"{i}|user{i}|ok|admin" for i in range(1, 30))
    assert detect_format(pipes) != "numbered_code"


def test_prose_with_numbered_lines_minority_is_not_numbered_code():
    text = "\n".join(
        ["Release notes for the quarter, in no particular order."] * 6
        + [f"{i}: item" for i in range(1, 3)]
    )
    assert detect_format(text) != "numbered_code"
