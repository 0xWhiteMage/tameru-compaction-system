"""1.10.0 protocol: engine-owned request schema, v1 compatibility, hostile pin_patterns."""
from __future__ import annotations

import json
import re
import time

import pytest

from tameru import protocol
from tameru.compress_context import ENGINE_VERSION, RESULT_SCHEMA, compress_context
from tameru.decide import Decision
from tameru.protocol import ProtocolError, validate_request

V1 = {"op": "compress", "id": 1, "text": "a\nb\n" * 50, "query": "b", "mode": "fixed", "budget_ratio": 0.3,
      "pin_recent": 2, "min_savings_ratio": 0.2, "derive_query": True, "citations": False}


def code(request):
    with pytest.raises(ProtocolError) as err:
        validate_request(request)
    return err.value.code


def test_v1_request_validates_to_the_1_9_worker_options():
    got = validate_request(V1)
    assert got == {"context": V1["text"], "query": "b", "strategy": "extract", "citations": False, "mode": "fixed",
                   "budget_ratio": 0.3, "min_savings_ratio": 0.2, "pin_recent": 2, "derive_query": True, "ccr": False}
    minimal = validate_request({"text": "t"})
    assert minimal == {"context": "t", "query": "", "strategy": "extract", "citations": False, "mode": "adaptive", "ccr": False}


def test_v1_rejections_unchanged():
    assert code({"text": 1}) == "bad_text"
    assert code({"text": "t", "query": 3}) == "bad_query"
    assert code({"text": "t", "mode": "x"}) == "bad_mode"
    assert code({"text": "t", "budget_ratio": 0.0}) == "bad_budget_ratio"
    assert code({"text": "t", "min_savings_ratio": True}) == "bad_min_savings_ratio"
    assert code({"text": "t", "pin_recent": 51}) == "bad_pin_recent"
    assert code({"text": "t", "derive_query": "yes"}) == "bad_derive_query"
    assert code({"text": "t", "ccr": True}) == "unknown_field"
    assert code({"text": "t", "log_dir": "/x"}) == "unknown_field"
    assert code([1]) == "bad_request"


def test_v2_fields_and_closed_enums():
    got = validate_request({"text": "t", "preset": "dsh-tool-result@1", "content_hint": "log", "anchor_errors": True,
                            "redact_secrets": True, "protocol": 2})
    assert got["min_savings_ratio"] == 0.25 and got["content_hint"] == "log" and got["redact_secrets"] is True
    assert got["ccr"] is False
    assert code({"text": "t", "preset": "other@9"}) == "bad_preset"
    assert code({"text": "t", "content_hint": "yaml"}) == "bad_content_hint"
    assert code({"text": "t", "strategy": "summarise"}) == "bad_strategy"
    assert code({"text": "t", "protocol": 3}) == "bad_protocol"
    assert code({"text": "t", "protocol": 1, "preset": "tool-result@1"}) == "field_needs_protocol_2"
    assert validate_request({"text": "t", "protocol": 1})["mode"] == "adaptive"


def test_explicit_field_beats_preset():
    got = validate_request({"text": "t", "preset": "tool-result@1", "min_savings_ratio": 0.4})
    assert got["min_savings_ratio"] == 0.4 and got["inline_short_gaps"] is True


def test_validated_request_runs_the_engine():
    kwargs = validate_request({"text": "x\n" * 400 + "ERROR boom\n", "query": "boom", "preset": "tool-result@1"})
    res = compress_context(**kwargs)
    assert protocol.result_to_dict(res)["result_schema"] == RESULT_SCHEMA


def test_lone_surrogates_are_cleaned():
    request = {"text": "a\ud800b", "query": "q\udfff"}
    got = validate_request(request)
    assert got["context"] == "a�b" and got["query"] == "q�"
    assert protocol.request_was_sanitized(request) and not protocol.request_was_sanitized({"text": "ok"})


def test_pin_patterns_literals_and_regexes():
    got = validate_request({"text": "t", "pin_patterns": ["ERROR \\d+", {"literal": "a.b(c)"}]})
    assert got["pin_patterns"] == ["ERROR \\d+", re.escape("a.b(c)")]
    assert code({"text": "t", "pin_patterns": ["x"] * 17}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": ["x" * 201]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": ["("]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": [""]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": [5]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": [{"literal": "x", "re": "y"}]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": "ERROR"}) == "bad_pin_patterns"


HOSTILE = ["(a+)+", "(a*)*", "(a+)*b", "(.*)+x", "(a|aa)+", "(a|a)*", "((a+)b)+", "(x+x+)+y", "(a{2,})+",
           r"(a)\1+", "(?P<n>a)(?P=n)"]
BENIGN = ["ERROR \\d+", "(foo|bar)", "(?:ab)?c", "[(a+)+]+", "\\(a+\\)+", "fail(ed|ure)?", "^id=[0-9a-f]{8}$",
          "(a+)b", "a+b*"]


@pytest.mark.parametrize("pattern", HOSTILE)
def test_catastrophic_regexes_are_rejected(pattern):
    assert code({"text": "t", "pin_patterns": [pattern]}) == "bad_pin_patterns"


@pytest.mark.parametrize("pattern", BENIGN)
def test_ordinary_regexes_pass(pattern):
    assert validate_request({"text": "t", "pin_patterns": [pattern]})["pin_patterns"] == [pattern]


def test_hostile_patterns_never_reach_the_engine_and_answer_fast():
    started = time.perf_counter()
    for pattern in HOSTILE:
        code({"text": "a" * 5000 + "!", "pin_patterns": [pattern]})
    assert time.perf_counter() - started < 1.0


def test_errors_never_echo_request_text():
    marker = "CANARY-9f3a1c"
    requests = [
        {"text": 5, "query": marker}, {"text": marker, "mode": marker}, {marker: 1}, {"text": "t", "preset": marker},
        {"text": "t", "content_hint": marker}, {"text": "t", "pin_patterns": [marker + "("]},
        {"text": "t", "pin_patterns": [marker * 40]}, {"text": "t", "strategy": marker},
        {"text": "t", "protocol": marker}, {"text": marker, "budget_ratio": marker},
    ]
    for request in requests:
        with pytest.raises(ProtocolError) as err:
            validate_request(request)
        assert marker not in err.value.code and marker not in str(err.value)
        assert re.fullmatch(r"[a-z0-9_]+", err.value.code)


def test_version_info_and_describe():
    info = protocol.version_info()
    assert info == {"engine": ENGINE_VERSION, "protocol": 2, "result_schema": 1,
                    "presets": ["dsh-tool-result@1", "tool-result@1"]}
    json.dumps(info)
    res = compress_context("x\n" * 50, "x", ccr=False)
    assert protocol.describe(res, preset="p", decision=Decision(True, "ok")) == {
        "result_schema": 1, "preset": "p", "decision": {"accept": True, "reason": "ok", "basis": None}}


def test_result_dict_keeps_the_v1_keys():
    res = compress_context("x\n" * 50, "x", ccr=False)
    keys = set(protocol.result_to_dict(res))
    assert keys == {"text", "fail_open", "original_tokens", "kept_tokens", "tokens_saved_pct", "risk",
                    "confidence", "content_type", "reasons", "sanitized", "result_schema"}
