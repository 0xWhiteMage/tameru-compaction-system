import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tameru._protect_patterns import compile_pin_patterns

cc = importlib.import_module("tameru.compress_context")

UNSAFE = [
    "(a+)+$", "(?:a|aa)+$", "a*x", ".*.*x", "a{1,}x", "a{0,33}x",
    ".{0,4294967294}x", ".{0,16}.{0,16}x", "a?" * 8 + "b",
    r"(a)\1", r"(?P<n>a)(?P=n)", r"(a)?(?(1)b|c)",
    r"(?=(a)\1)", r"(?=(a+)+$)", r"(?:a?){32}b", r"(?:a|aa){1,12}b",
    "(", "a" * 201,
]


@pytest.mark.parametrize("pattern", UNSAFE)
def test_unsafe_patterns_preserve_full_input(pattern):
    text = "ordinary output\n" * 100 + "important final fact"
    result = cc.compress_context(text, "ordinary", pin_patterns=[pattern], ccr=False, citations=False)
    assert result.fail_open
    assert result.compressed_text == text
    assert result.reasons == ["unsafe_pin_patterns"]
    assert result.tokens_saved_pct == 0.0
    assert result.dropped == ()


@pytest.mark.parametrize("patterns", ["ERROR", [None], [5], [b"ERROR"], ["ok", "("], ["x"] * 33,
                                      ["a?" * 7 + chr(0x100 + i) for i in range(3)]])
def test_invalid_or_over_budget_pattern_sets_preserve_input(patterns):
    text = "important output\n" * 100
    result = cc.compress_context(text, "output", pin_patterns=patterns, ccr=False)
    assert result.fail_open
    assert result.compressed_text == text


def test_unsafe_private_searches_never_execute_the_pattern():
    text = "a" * 100_000 + "!"
    assert cc._source_pin_texts(text, ["(a+)+$"], 0) == [text]
    blocks = [{"id": 0, "text": text, "score": 1.0}]
    cc._apply_pins(pin_patterns=["(a+)+$"], pin_recent=0, scored=blocks)
    assert blocks[0]["pinned"]


@pytest.mark.parametrize("pattern", ["(a+)+$", "a*x", r"(?:a?){32}b", r"(?=(a+)+$)"])
def test_pathological_patterns_finish_under_a_subprocess_deadline(pattern):
    code = r"""
import sys, importlib
sys.path.insert(0, sys.argv[1])
cc = importlib.import_module('tameru.compress_context')
pattern = sys.argv[2]
text = ('a' * 30 + '!\n\n') * 200
result = cc.compress_context(text, 'q', pin_patterns=[pattern], ccr=False)
assert result.fail_open and result.compressed_text == text
text = 'a' * 200_000 + '!'
assert cc._source_pin_texts(text, [pattern], 0) == [text]
blocks = [{'id': 0, 'text': text, 'score': 1.0}]
cc._apply_pins(pin_patterns=[pattern], pin_recent=0, scored=blocks)
assert blocks[0]['pinned']
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code,
         str(Path(__file__).resolve().parents[1] / "src"), pattern],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr


SAFE = ["ERROR", r"\bID-\d{1,12}\b", "(?:foo|bar)", "fail(ed|ure)?",
        r"[(a+)+]{1,3}", r"\*\+\{1,\}", r"\\1", "(?i)error", "(?=ERROR)ERROR",
        "(?<=ID-)42", "", "a" * 200]


@pytest.mark.parametrize("pattern", SAFE)
def test_safe_patterns_keep_reference_search_behavior(pattern):
    compiled = compile_pin_patterns([pattern])
    assert compiled is not None
    for text in ("", "ERROR ID-42 failed foo", "bar failure", "α ERROR\nID-123", "*+{1,} \\1"):
        expected = re.compile(pattern).search(text)
        actual = compiled[0].search(text)
        assert (actual.span() if actual else None) == (expected.span() if expected else None)


def test_safe_patterns_leave_engine_output_byte_identical(monkeypatch):
    text = "INFO ordinary filler\n" * 150 + "ID-42 critical fact\n\nERROR failed\n" + "INFO other filler\n" * 150
    patterns = [r"\bID-\d{1,12}\b", "ERROR", "fail(ed|ure)?"]
    cc._clear_memos()
    actual = cc.compress_context(text, "critical", pin_patterns=patterns, ccr=False, citations=False).to_dict()
    cc._clear_memos()
    monkeypatch.setattr(cc, "compile_pin_patterns", lambda items: tuple(re.compile(p) for p in items or ()))
    expected = cc.compress_context(text, "critical", pin_patterns=patterns, ccr=False, citations=False).to_dict()
    assert actual == expected


def test_no_patterns_keep_positional_pins_and_empty_input_behavior():
    assert compile_pin_patterns(None) == compile_pin_patterns([]) == ()
    assert cc._source_pin_texts("", [], 0) == []
    text = "first\n\nsecond\n\nthird"
    assert cc._source_pin_texts(text, [], 1) == ["first", "third"]
