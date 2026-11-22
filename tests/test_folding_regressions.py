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
