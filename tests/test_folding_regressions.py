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
