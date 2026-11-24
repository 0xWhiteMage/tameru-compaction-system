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
    assert code({"text": "t", "protocol": 4}) == "bad_protocol"
    assert code({"text": "t", "protocol": 2, "selector_query": "q"}) == "field_needs_protocol_3"
    assert code({"text": "t", "protocol": 1, "derive_selector_query": True}) == "field_needs_protocol_3"
    assert code({"text": "t", "protocol": 1, "preset": "tool-result@1"}) == "field_needs_protocol_2"
    assert validate_request({"text": "t", "protocol": 1})["mode"] == "adaptive"


def test_min_savings_ratio_range_is_exclusive_at_one():
    # the engine requires [0, 1): a wire value of 1 must fail validation, not reach the engine as a ValueError
    assert code({"text": "t", "min_savings_ratio": 1}) == "bad_min_savings_ratio"
    assert code({"text": "t", "min_savings_ratio": 1.0}) == "bad_min_savings_ratio"
    assert code({"text": "t", "min_savings_ratio": -0.1}) == "bad_min_savings_ratio"
    import math
    just_under = math.nextafter(1.0, 0.0)
    assert validate_request({"text": "t", "min_savings_ratio": just_under})["min_savings_ratio"] == just_under


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
    got = validate_request({"text": "t", "pin_patterns": ["ERROR \\d{1,6}", {"literal": "a.b(c)"}]})
    assert got["pin_patterns"] == ["ERROR \\d{1,6}", re.escape("a.b(c)")]
    assert code({"text": "t", "pin_patterns": ["x"] * 17}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": ["x" * 201]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": ["("]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": [""]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": [5]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": [{"literal": "x", "re": "y"}]}) == "bad_pin_patterns"
    assert code({"text": "t", "pin_patterns": "ERROR"}) == "bad_pin_patterns"


HOSTILE = ["(a+)+", "(a*)*", "(a+)*b", "(.*)+x", "(a|aa)+", "(a|a)*", "((a+)b)+", "(x+x+)+y", "(a{2,})+",
           r"(a)\1+", "(?P<n>a)(?P=n)"]
BS = chr(92)
BENIGN = ["ERROR "+BS+"d{1,8}", "(foo|bar)", "(?:ab)?c", "[(a+)+]{1,3}", BS+"(a"+BS+")", "fail(ed|ure)?", "^id=[0-9a-f]{8}$",
          "(a{1,3})b", "foo.{0,20}bar", "x{2,5}y", "a{1,20}b", "(?:ab)|(?:cd)", r"^"+BS+"[ERR"+BS+"] "+BS+"w{1,9}", "plain literal text"]


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
    assert info["engine"] == ENGINE_VERSION and info["protocol"] == 3 and info["result_schema"] == 4
    assert info["presets"] == ["dsh-tool-result@1", "tool-result@1"]
    assert info["capabilities"]["selector_query"] is True
    assert info["capabilities"]["plan"]["max_items"] == protocol.MAX_PLAN_ITEMS
    assert set(info["capabilities"]["plan"]["host_modes"]) == {"prune", "compact"}
    assert info["capabilities"]["ev"]["strengths"] == ["less", "normal", "more"]
    json.dumps(info)
    res = compress_context("x\n" * 50, "x", ccr=False)
    assert protocol.describe(res, preset="p", decision=Decision(True, "ok")) == {
        "result_schema": 4, "preset": "p", "decision": {"accept": True, "reason": "ok", "basis": None}}


def test_result_dict_keeps_the_v1_keys():
    res = compress_context("x\n" * 50, "x", ccr=False)
    keys = set(protocol.result_to_dict(res))
    assert keys == {"text", "fail_open", "original_tokens", "kept_tokens", "tokens_saved_pct", "risk",
                    "confidence", "content_type", "reasons", "sanitized", "result_schema"} | {
        "confidence_basis", "stable_key", "dropped", "preset", "fact_lines_dropped", "query_specific"}
        # result schema 2 + 3 + 4, additive


SLOW_SHAPES = ["a*b", "foo.*bar", "a+", "a*a*a*a*a*b", "(a|a)*b", "(a+)+", ".*.*.*x", "a*a*b", ".*x.*y", "a+b*", r"\d+\.\d+", "a?a?a?a?a?aaaaa",
               "a{2,}a{2,}b", "a{1,100}a{1,100}b", "|".join("abcdefgh")]


@pytest.mark.parametrize("pattern", SLOW_SHAPES)
def test_polynomial_and_exponential_shapes_are_rejected(pattern):
    assert code({"text": "t", "pin_patterns": [pattern]}) == "bad_pin_patterns"


def test_literals_always_pass_the_static_check():
    assert not protocol.regex_risk(re.escape("a*a*a*a*a*b|(a+)+" * 5))
    assert validate_request({"text": "t", "pin_patterns": [{"literal": "a*a*a*a*a*b"}]})["pin_patterns"]


def test_pin_patterns_that_validate_cannot_stall_compress_context():
    """Every pattern the protocol accepts runs on a 50K adversarial input in about a second at most."""
    import threading

    candidates = BENIGN + [".{0,40}x", "a{1,40}b", "(?:ab){1,9}c", "x?y?z?a?b"]
    inputs = ["a" * 50_000, "ab" * 25_000, "1" * 50_000, "x" * 50_000, ("a" * 99 + "\n") * 500]
    for pattern in candidates:
        pins = validate_request({"text": "t", "pin_patterns": [pattern]})["pin_patterns"]
        for text in inputs:
            thread = threading.Thread(
                target=lambda: compress_context(text, "q", ccr=False, citations=False, pin_patterns=pins),
                daemon=True,
            )
            started = time.perf_counter()
            thread.start()
            thread.join(10)
            assert not thread.is_alive(), f"{pattern!r} stalled compress_context"
            assert time.perf_counter() - started < 1.5, pattern


def test_a_literal_pin_still_keeps_its_line():
    text = "INFO a\n" * 400 + "needle-line-42\n" + "INFO b\n" * 400
    got = validate_request({"text": text, "query": "zzz", "pin_patterns": [{"literal": "needle-line-42"}]})
    assert "needle-line-42" in compress_context(**got).compressed_text


def test_a_literal_pin_deep_in_a_50k_block_is_still_found():
    text = "z" * 30_000 + "needle-42" + "z" * 20_000
    got = validate_request({"text": text, "query": "zzz", "pin_patterns": [{"literal": "needle-42"}, "needle-4"+"2"]})
    assert "needle-42" in compress_context(**got).compressed_text


# ---------- protocol 3: selector_query and the plan request ----------

from tameru.decide import EVPolicy, Policy
from tameru.plan import Candidate, CacheState, PlanInput, PlanItem, plan


def _plan_body(**overrides):
    body = {
        "op": "plan",
        "protocol": 3,
        "event": "trigger",
        "host_mode": "prune",
        "prompt_tokens": 100_000,
        "trigger_tokens": 80_000,
        "items": [
            {"id": "a", "position": 0, "tokens": 5000, "chars": 20_000, "stock_action": "cut",
             "stock_kept_chars": 200,
             "candidate": {"compressed_chars": 150, "tokens_saved": 4960, "confidence": 0.95,
                           "fail_open": False, "risk": "low", "fingerprints_ok": True}},
            {"id": "b", "position": 1, "tokens": 3000, "chars": 12_000, "stock_action": "cut",
             "stock_kept_chars": 200},
            {"id": "c", "position": 2, "tokens": 1000, "chars": 4000, "stock_action": "keep"},
        ],
        "cache": {"warm": False, "n_eff": 10},
        "policy": {"ev": {"price_profile": "deepseek-flash", "loss_profile": "replay-2026-11-21"}},
        "steps_since_last_act": 5,
        "growth_tokens_per_step": 250.5,
        "margin_steps": 6,
        "replace_compaction": True,
    }
    body.update(overrides)
    return body


def _plan_input(**overrides):
    kwargs = {
        "event": "trigger",
        "host_mode": "prune",
        "prompt_tokens": 100_000,
        "trigger_tokens": 80_000,
        "items": (
            PlanItem(id="a", position=0, tokens=5000, chars=20_000, stock_action="cut",
                     stock_kept_chars=200,
                     candidate=Candidate(compressed_chars=150, tokens_saved=4960, confidence=0.95,
                                         fail_open=False, risk="low", fingerprints_ok=True)),
            PlanItem(id="b", position=1, tokens=3000, chars=12_000, stock_action="cut",
                     stock_kept_chars=200),
            PlanItem(id="c", position=2, tokens=1000, chars=4000, stock_action="keep"),
        ),
        "cache": CacheState(warm=False, n_eff=10.0),
        "policy": Policy(ev=EVPolicy(price_profile="deepseek-flash", loss_profile="replay-2026-11-21")),
        "steps_since_last_act": 5,
        "growth_tokens_per_step": 250.5,
        "margin_steps": 6,
        "replace_compaction": True,
    }
    kwargs.update(overrides)
    return PlanInput(**kwargs)


def plan_code(request):
    with pytest.raises(ProtocolError) as err:
        protocol.validate_plan_request(request)
    return err.value.code


def test_v2_compress_requests_validate_identically_to_before():
    request = {"text": "t", "query": "q", "protocol": 2, "preset": "dsh-tool-result@1",
               "anchor_errors": True, "budget_ratio": 0.5}
    got = validate_request(request)
    assert got == {"context": "t", "query": "q", "strategy": "extract", "citations": False,
                   "min_savings_ratio": 0.25, "anchor_errors": True, "mode": "adaptive",
                   "budget_ratio": 0.5, "ccr": False}
    assert "selector_query" not in got and "derive_selector_query" not in got


def test_v3_selector_query_validates_and_passes_through():
    got = validate_request({"text": "t", "query": "q", "selector_query": "sel", "protocol": 3})
    assert got["selector_query"] == "sel"
    got = validate_request({"text": "t", "selector_query": "s\ud800x", "protocol": 3})
    assert got["selector_query"] == "s\ufffdx"


def test_v3_selector_query_round_trip_equals_direct_call():
    text = "metric,status\nweb-01,200\n" * 60 + "Error: db refused\n" + "web-02,200\n" * 20
    via_protocol = compress_context(**validate_request(
        {"text": text, "query": "what failed", "selector_query": "db refused", "protocol": 3}))
    direct = compress_context(text, "what failed", selector_query="db refused", ccr=False)
    assert via_protocol.compressed_text == direct.compressed_text
    assert protocol.result_to_dict(via_protocol) == protocol.result_to_dict(direct)


def test_derive_selector_query_flag_reaches_the_worker_for_parts_resolution():
    got = validate_request({"text": "t", "derive_selector_query": True, "protocol": 3})
    assert got.pop("derive_selector_query") is True        # the worker pops and resolves it
    compress_context(**got)                                 # remaining kwargs are engine-legal


def test_selector_query_rejections_are_type_only():
    assert code({"text": "t", "selector_query": 7, "protocol": 3}) == "bad_selector_query"
    assert code({"text": "t", "derive_selector_query": "yes", "protocol": 3}) == "bad_derive_selector_query"
    assert code({"text": "t", "selector_query": "s", "derive_selector_query": True,
                 "protocol": 3}) == "selector_and_derive"


def test_plan_request_builds_the_same_planinput_and_plan_output():
    got = protocol.validate_plan_request(_plan_body())
    assert got == _plan_input()
    assert protocol.plan_to_dict(plan(got)) == protocol.plan_to_dict(plan(_plan_input()))


def test_plan_to_dict_shape():
    reply = protocol.plan_to_dict(plan(_plan_input()))
    assert set(reply) == {"event", "host_mode", "acted", "gate", "actions",
                          "predicted_chars_after", "predicted_chars_stock", "predicted_V",
                          "predicted_L", "reaches_target"}
    assert reply["acted"] is True and reply["gate"] == "acted"
    assert [a["id"] for a in reply["actions"]] == ["a", "b", "c"]
    assert set(reply["actions"][0]) == {"id", "event", "action", "reason", "p_hat", "V", "L",
                                        "alternative"}
    assert reply["actions"][0]["action"] == "extract" and reply["actions"][0]["V"] is not None
    assert reply["actions"][0]["alternative"] == "stub"
    assert reply["actions"][1]["action"] == "stub"
    json.dumps(reply)


def test_plan_request_accepts_compact_mode_and_policy_fields():
    body = _plan_body(host_mode="compact", retained_budget_chars=500)
    body["policy"] = {"min_saved_ratio": 0.1, "max_risk": "medium", "require_fingerprints": True,
                      "ev": {"price_profile": "deepseek-flash", "loss_profile": "replay-2026-11-21",
                             "strength": "less", "quantile": 0.9}}
    got = protocol.validate_plan_request(body)
    assert got.host_mode == "compact" and got.retained_budget_chars == 500
    assert got.policy.max_risk == "medium" and got.policy.ev.strength == "less"
    assert got.policy.ev.quantile == 0.9 and got.policy.ev.calibrator is None


def test_plan_request_rejections():
    assert plan_code({"op": "plan"}) == "bad_event"
    assert plan_code(_plan_body(event="daily")) == "bad_event"
    assert plan_code(_plan_body(host_mode="rewrite")) == "bad_host_mode"
    assert plan_code(_plan_body(protocol=2)) == "bad_protocol"
    assert plan_code(_plan_body(protocol=3.5)) == "bad_protocol"
    assert plan_code(_plan_body(prompt_tokens=-1)) == "bad_prompt_tokens"
    assert plan_code(_plan_body(prompt_tokens=True)) == "bad_prompt_tokens"
    assert plan_code(_plan_body(trigger_tokens="x")) == "bad_trigger_tokens"
    assert plan_code(_plan_body(steps_since_last_act=-1)) == "bad_steps"
    assert plan_code(_plan_body(K=-1)) == "bad_K"
    assert plan_code(_plan_body(H=-1)) == "bad_H"
    assert plan_code(_plan_body(steps_to_trigger=-2)) == "bad_steps"
    assert plan_code(_plan_body(retained_budget_chars=-1)) == "bad_retained_budget"
    assert plan_code(_plan_body(replace_compaction="yes")) == "bad_replace_compaction"
    assert plan_code(_plan_body(replace_compaction=1)) == "bad_replace_compaction"
    assert plan_code(_plan_body(growth_tokens_per_step=-1)) == "bad_growth"
    assert plan_code(_plan_body(growth_tokens_per_step="x")) == "bad_growth"
    assert plan_code(_plan_body(margin_steps=-1)) == "bad_steps"
    assert plan_code(_plan_body(margin_steps=1.5)) == "bad_steps"
    assert plan_code(_plan_body(items="no")) == "bad_items"
    assert plan_code(_plan_body(items=[{}] * 2001)) == "bad_items"
    assert plan_code(_plan_body(cache={"warm": True})) == "bad_cache"
    assert plan_code(_plan_body(cache={"warm": "y", "n_eff": 1})) == "bad_cache"
    assert plan_code(_plan_body(cache={"warm": True, "n_eff": -1})) == "bad_cache"
    assert plan_code(_plan_body(policy=None)) == "bad_policy"


def test_plan_request_rejects_extra_and_nested_fields():
    body = _plan_body(ccr=True)
    assert plan_code(body) == "unknown_field"
    body = _plan_body()
    body["items"][0]["evil"] = 1
    assert plan_code(body) == "bad_item"
    body = _plan_body()
    body["items"][0]["candidate"]["evil"] = 1
    assert plan_code(body) == "bad_candidate"
    body = _plan_body()
    body["policy"]["log_dir"] = "/x"
    assert plan_code(body) == "bad_policy"
    body = _plan_body()


def test_compress_response_carries_query_specific():
    text = "metric,status\nweb-01,200\n" * 60 + "Error: db refused\n" + "web-02,200\n" * 20
    res = compress_context(**validate_request(
        {"text": text, "query": "what failed on db-9", "protocol": 3}))
    body = protocol.result_to_dict(res)
    assert body["query_specific"] is res.query_specific
    assert isinstance(res.query_specific, bool)
    # a vague query reports False; a selector-heavy one True — every path, including fail-open
    vague = compress_context(**validate_request({"text": text, "query": "", "protocol": 3}))
    assert isinstance(vague.query_specific, bool)
    huge = compress_context("x" * 9_000_000, "q")
    assert huge.fail_open and huge.query_specific is False


def test_plan_candidate_accepts_schema4_fields_and_rejects_bad_ones():
    body = _plan_body()
    body["items"][0]["candidate"].update(confidence_basis="lexical", query_specific=True)
    inp = protocol.validate_plan_request(body)
    cand = next(i.candidate for i in inp.items if i.id == "a")
    assert cand.confidence_basis == "lexical" and cand.query_specific is True

    for patch in (
        {"confidence_basis": "not-a-basis"},
        {"confidence_basis": "lexical|vague"},   # a stratum key is not a basis
        {"confidence_basis": 5},
        {"query_specific": "yes"},
        {"query_specific": 1},
    ):
        body = _plan_body()
        body["items"][0]["candidate"].update(patch)
        assert plan_code(body) == "bad_candidate", patch
