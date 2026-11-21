"""1.10.0 S5: fact-shaped lines — detection, newest-wins, the selection floor, stage exemptions,
``selector_query``, ``fact_lines_dropped`` and the confidence caps."""
from __future__ import annotations

import pytest

from tameru import compress_context as cc
from tameru.transcript import build_query, build_selector_query

OPTS = dict(ccr=False, citations=False, min_savings_ratio=0.10, strategy="extract")
TICK = "2026-03-14 12:00:00 INFO worker processed a batch of events ok"


def _protected(lines):
    return [ln for _i, _k, _v, ln in cc._protected_fact_lines(lines)]


# ----------------------------------------------------------------------------- detection


@pytest.mark.parametrize("line", [
    "host=web-07",
    "max_workers: 4343",
    "region -> eu-west",
    "limit => 5",
    "10:00:01 INFO retries: 7",
    "# comment timeout = 30s",
    "; semicolon key: value",
    "// limit => 5",
    "-- arrow -> target",
    '{"level":"info","msg":"fan_out=314"}',
    "batch,id=7,ok",
    "超时阈值: 30",
])
def test_fact_parts_positives(line):
    key, value = cc._fact_parts(line)
    assert key and value


@pytest.mark.parametrize("line", [
    "a,b,c,d,e",                          # pure CSV row, no assignment
    "10:00:01 job finished normally",     # the only colons are the timestamp's
    "just some prose words here",         # no assignment at all
    "",                                   # empty
])
def test_fact_parts_negatives(line):
    assert cc._fact_parts(line) is None


def test_error_lines_are_never_protected():
    lines = ["ERROR code: 500", "ERROR code: 501", "ok=1"]
    assert _protected(lines) == ["ok=1"]


def test_repeated_template_is_not_a_fact():
    lines = [f"retry_count: {i}" for i in range(5)]  # one fingerprint, > _FACT_PROTECT_FP_MAX
    assert _protected(lines) == []


def test_newest_same_key_wins():
    lines = [TICK, "max_workers: 4", TICK, "max_workers: 4343", TICK]
    assert _protected(lines) == ["max_workers: 4343"]


# ----------------------------------------------------------------------------- exemptions


def test_preprocess_csv_never_drops_a_fact_row():
    rows = ["host,port,status"] + [f"host-{i:02d},8{i}0,up" for i in range(10)]
    rows.insert(5, "aux,port=8080,up")
    out = cc.preprocess_csv("\n".join(rows), "show host-07")
    assert "aux,port=8080,up" in out and "host-03" not in out


def test_flat_record_rows_are_facts():
    text = "\n".join([
        "alpha: 1", "beta.host: web", "gamma: 3", "delta: four", "eps: 5", "zeta: six"])
    assert cc.preprocess_flat_records(text, "find alpha") == text


def test_filler_comment_that_is_fact_shaped_survives():
    text = "# filler noise\n# filler setting = 42\nbody a\nbody b\nbody c"
    out = cc.preprocess_filler_comments(text, "order9 tail7")
    assert "setting = 42" in out and "filler noise" not in out


def test_restore_fact_lines_appends_what_a_stage_deleted():
    before = "first\nconfig_key = 7\nsecond"
    assert cc._restore_fact_lines(before, "first\nsecond") == "first\nsecond\nconfig_key = 7"
    assert cc._restore_fact_lines(before, before) == before


def test_preprocess_logs_keeps_newest_fact_verbatim():
    lines = [TICK] * 12 + ["max_workers: 4", TICK, "max_workers: 4343"] + [TICK] * 4
    out = cc.preprocess_logs(lines, "")
    assert "max_workers: 4343" in out


def test_fold_repeated_sentences_skips_fact_lines():
    fact = ("quota = 1234567890123456789012345 " * 4).rstrip()
    lines = ["noise a", fact, "noise b"]
    assert cc._fold_repeated_sentences(lines) == lines


# ----------------------------------------------------------------------------- selection floor


def test_floor_restores_dropped_fact_lines():
    lines = [TICK for _ in range(400)]
    facts = [f"cfg_{chr(97 + i)} = {1000 + i * 37}" for i in range(12)]
    for i, f in enumerate(facts):
        lines.insert(10 + i, f)
    r = cc.compress_context("\n".join(lines), "find cfg_a value", budget_ratio=0.3, **OPTS)
    kept = [f for f in facts if f in r.compressed_text]
    # floor: <= 8 appended + whatever selection kept; every protected fact is kept or counted
    assert len(kept) + r.fact_lines_dropped == len(facts)
    assert r.confidence <= 0.98 or r.fact_lines_dropped == 0


def test_floor_never_on_fail_open():
    r = cc.compress_context(TICK, "q", **OPTS)
    # tiny input fails open or keeps everything; a dropped fact can never appear
    assert r.fact_lines_dropped == 0


def test_fact_lines_dropped_and_confidence_cap():
    lines = [TICK for _ in range(400)]
    facts = [f"cfg_{chr(97 + i)} = {1000 + i * 37}" for i in range(20)]
    for i, f in enumerate(facts):
        lines.insert(10 + i, f)
    r = cc.compress_context("\n".join(lines), "find cfg_a value", budget_ratio=0.3, **OPTS)
    assert r.fact_lines_dropped > 0
    assert r.confidence <= 0.98
    assert r.receipt["fact_lines_dropped"] == r.fact_lines_dropped


def test_fact_drop_confidence_caps(monkeypatch):
    text = "\n".join([TICK] * 60 + ["cfg_x = 9"])
    monkeypatch.setattr(cc, "_count_fact_lines_dropped", lambda facts, out: 3)
    with_selectors = cc.compress_context(text, "cfg_x 7order9", **OPTS)
    assert with_selectors.fact_lines_dropped == 3
    assert with_selectors.confidence <= 0.98
    monkeypatch.setattr(cc, "_count_fact_lines_dropped", lambda facts, out: 5)
    no_selectors = cc.compress_context(text, "continue", **OPTS)
    assert no_selectors.confidence <= max(0.0, 1.0 - 0.1 * 5)


# ----------------------------------------------------------------------------- selector_query


def test_build_selector_query_drops_the_producing_call():
    messages = [
        {"role": "user", "content": "check why the deploy is failing"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "terminal", "arguments": {"command": "grep ERROR /log"}}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "log text"},
        {"role": "assistant", "content": "looking now"},
    ]
    full = build_query(messages, 2)
    sel = build_selector_query(messages, 2)
    assert "terminal" in full and "grep" in full
    assert "terminal" not in sel and "grep" not in sel
    assert "check why the deploy is failing" in sel


def test_selector_query_gates_the_destructive_prefilters(monkeypatch):
    """A selector query with no distinctive terms turns every destructive selector pre-filter off —
    a token that only occurs in the producing tool call cannot delete rows."""
    calls = []
    orig = cc.preprocess

    def spy(text, query, content_hint=None):
        calls.append(query)
        return orig(text, query, content_hint)

    monkeypatch.setattr(cc, "preprocess", spy)
    text = "host,port,status\n" + "\n".join(f"host-{i:02d},8{i:02d}0,up" for i in range(20))
    full = "terminal\nquery_metrics --instance host-07\nwhat happened"
    cc.compress_context(text, full, selector_query="what happened", **OPTS)
    assert calls == []
    cc.compress_context(text, full, **OPTS)
    assert calls and calls[0] == full


def test_selector_query_reaches_csv_prefilter(monkeypatch):
    seen = []
    orig = cc.preprocess_csv

    def spy(text, query, gap_marker=None):
        seen.append(query)
        return orig(text, query, gap_marker)

    monkeypatch.setattr(cc, "preprocess_csv", spy)
    text = "host,port,status\n" + "\n".join(f"host-{i:02d},8{i:02d}0,up" for i in range(20))
    cc.compress_context(
        text, "terminal\nquery_metrics host-07\nshow host-99", selector_query="show host-99", **OPTS)
    assert seen and all(q == "show host-99" for q in seen)


def test_selector_query_in_stable_key():
    text = "\n".join([TICK] * 30 + ["cfg_x = 9"])
    plain = cc.compress_context(text, "what happened", **OPTS)
    with_sel = cc.compress_context(text, "what happened", selector_query="continue", **OPTS)
    assert plain.stable_key != with_sel.stable_key
    again = cc.compress_context(text, "what happened", selector_query="continue", **OPTS)
    assert again.stable_key == with_sel.stable_key
