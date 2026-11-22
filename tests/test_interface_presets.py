"""1.10.0 presets: named option sets that reproduce the 1.9.x host calls byte for byte."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from golden_compress import corpus
from tameru import presets
from tameru.compress_context import compress_context

PRESETS_SHA256 = "f67f239cc4e4e7bfc1378faded952cb99a2073ea037c80334bbd9a9406efd7a6"
QUERIES = ["", "handshake refused", "payment gateway timeout", "why did the job fail"]


def _blob(result) -> str:
    return json.dumps(dataclasses.asdict(result), sort_keys=True, default=str)


def _cases(n: int = 20):
    items = [(name, text) for name, text in corpus().items() if text.strip()]
    assert len(items) >= n
    return items[:n]


def _marker(omitted: int, total: int) -> str:
    return f"[… {omitted}/{total} …]"


def test_presets_file_is_hash_pinned():
    data = Path(presets.__file__).with_name("presets.json").read_bytes()
    assert hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() == PRESETS_SHA256


def test_names_and_unknown_preset():
    assert presets.preset_names() == ["dsh-tool-result@1", "tool-result@1"]
    with pytest.raises(ValueError):
        presets.resolve_preset("nope@1")
    with pytest.raises(ValueError):
        presets.resolve_preset("tool-result@1", {"log_dir": "x"})
    with pytest.raises(ValueError) as err:
        presets.resolve_preset("tool-result@1", {"ccr_dir": "SECRET-PATH"})
    assert "SECRET-PATH" not in str(err.value)


def test_overrides_win_and_are_copied():
    got = presets.resolve_preset("tool-result@1", {"min_savings_ratio": 0.3, "content_hint": "log"})
    assert got["min_savings_ratio"] == 0.3 and got["content_hint"] == "log"
    got["ccr"] = True
    assert presets.resolve_preset("tool-result@1")["ccr"] is False


def test_tool_result_preset_equals_the_1_9_hermes_call():
    for name, text in _cases():
        for query in QUERIES:
            by_hand = compress_context(
                text, query, ccr=False, citations=False, content_hint=None, pin_patterns=None,
                gap_marker=_marker, inline_short_gaps=True, anchor_errors=True, prose_brief=True,
                recursion_markers=("[tameru:",), min_savings_ratio=0.10,
            )
            via = compress_context(text, query, **presets.resolve_preset(
                "tool-result@1", {"gap_marker": _marker, "recursion_markers": ("[tameru:",)}))
            assert _blob(via) == _blob(by_hand), (name, query)


def test_dsh_preset_equals_the_1_9_dsh_call():
    for name, text in _cases():
        for query in QUERIES:
            by_hand = compress_context(text, query, min_savings_ratio=0.25, ccr=False, citations=False, strategy="extract")
            via = compress_context(text, query, **presets.resolve_preset("dsh-tool-result@1"))
            assert _blob(via) == _blob(by_hand), (name, query)


def test_fixed_budget_override_equals_the_hermes_retry_call():
    text = corpus()["log_errors"]
    by_hand = compress_context(
        text, "handshake refused", ccr=False, citations=False, inline_short_gaps=True,
        anchor_errors=True, prose_brief=True, min_savings_ratio=0.10, mode="fixed", budget_ratio=0.3,
    )
    via = compress_context(text, "handshake refused", **presets.resolve_preset(
        "tool-result@1", {"mode": "fixed", "budget_ratio": 0.3}))
    assert _blob(via) == _blob(by_hand)
