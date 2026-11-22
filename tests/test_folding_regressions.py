import json

from tameru.folding import fold_lossless, json_brief


def test_json_brief_ignores_container_values_in_scalar_ranking():
    rows = [{"status": "ok"} for _ in range(40)]
    rows[13] = {"status": {"detail": "pending"}}
    rows[20] = {"status": "failed"}
    rows[27] = {"status": ["partial"]}
    out = json_brief(json.dumps(rows), budget_chars=260)
    assert out is not None
    assert {"status": "failed"} in json.loads(out)["_notable"]


def test_json_brief_escapes_ascii_delete_in_values_and_keys():
    rows = [{"a\x7f": "b\x7f"} for _ in range(40)]
    out = json_brief(json.dumps(rows), budget_chars=260)
    assert out is not None
    assert "\x7f" not in out
    assert json.loads(out)["_head"][0] == rows[0]


def test_folding_does_not_minify_nonfinite_json_constants():
    for literal in ("NaN", "Infinity", "-Infinity"):
        raw = f'{{\n  "a": {literal},\n  "b": 2\n}}'
        out, stats = fold_lossless(raw)
        assert out == raw
        assert not stats["json_minified"]


def test_carriage_returns_in_json_are_whitespace_not_redraws():
    raw = '{\r  "a": "keep",\r  "b": 2\r}'
    out, stats = fold_lossless(raw)
    assert out == '{"a":"keep","b":2}'
    assert stats["json_minified"]
    assert stats["cr_redraws"] == 0
    assert stats["saved_chars"] == len(raw) - len(out)


def test_nested_ansi_past_pass_cap_preserves_original_text_and_stats():
    nested = "\x1b[3" * 6 + "\x1b[0m" + "1m" * 6
    raw = "old\rnew  \n" + nested + "visible"
    out, stats = fold_lossless(raw)
    assert out == raw
    assert not any(stats.values())


def test_json_brief_returns_none_for_invalid_budgets():
    text = '[{"status":"ok"},{"status":"pending"}]'
    for budget in (float("inf"), float("-inf"), float("nan"), None, "invalid", 0, -1):
        assert json_brief(text, budget_chars=budget) is None
