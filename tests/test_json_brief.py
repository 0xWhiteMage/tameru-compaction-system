"""E11: json_brief is valid JSON with correct counts and respects the budget."""
from __future__ import annotations

import json

from tameru.compress_context import brief_context
from tameru.folding import json_brief


def _rows(n=300):
    return [
        {"id": i, "name": f"user-{i}", "status": "error" if i == 137 else "ok", "n": i * 3}
        for i in range(n)
    ]


def test_array_brief_is_valid_json_and_counts_add_up():
    text = json.dumps(_rows(), indent=1)
    out = json_brief(text, budget_chars=1500)
    assert out is not None and len(out) <= 1500
    b = json.loads(out)
    assert b["_count"] == 300
    assert b["_keys"] == ["id", "name", "status", "n"]
    shown = len(b["_head"]) + len(b["_tail"]) + len(b["_notable"])
    assert b["_omitted"] == 300 - shown
    assert b["_head"][0]["id"] == 0 and b["_tail"][-1]["id"] == 299
    assert len(b["_head"]) == len(b["_tail"]) >= 1
    assert len(b["_notable"]) <= 5


def test_notable_includes_outlier_by_low_cardinality_field():
    out = json_brief(json.dumps(_rows()), budget_chars=1500)
    assert 137 in [it["id"] for it in json.loads(out)["_notable"]]


def test_notable_includes_query_hits():
    out = json_brief(json.dumps(_rows()), budget_chars=1500, query="user-211")
    assert 211 in [it["id"] for it in json.loads(out)["_notable"]]


def test_budget_respected_and_k_adapts():
    text = json.dumps(_rows())
    small = json_brief(text, budget_chars=700)
    big = json_brief(text, budget_chars=4000)
    assert len(small) <= 700 and len(big) <= 4000
    assert len(json.loads(big)["_head"]) > len(json.loads(small)["_head"]) >= 1


def test_returns_none_when_it_cannot_fit_or_not_applicable():
    assert json_brief(json.dumps(_rows()), budget_chars=50) is None
    assert json_brief("[1,2,3]", budget_chars=500) is None
    assert json_brief("not json", budget_chars=500) is None
    assert json_brief(json.dumps({"a": [1, 2]}), budget_chars=500) is None


def test_object_wrapper_keeps_scalars():
    obj = {"total": 300, "page": "1", "items": _rows(), "meta": {"x": 1}}
    out = json_brief(json.dumps(obj), budget_chars=1800)
    b = json.loads(out)
    assert list(b)[0] == "items" and b["total"] == 300 and b["page"] == "1"
    assert "meta" not in b
    assert b["items"]["_count"] == 300 and len(out) <= 1800


def test_object_needs_ten_rows():
    assert json_brief(json.dumps({"items": _rows(9)}), budget_chars=5000) is None


def test_brief_context_uses_json_brief_first():
    text = json.dumps(_rows(), indent=2)
    out = brief_context(text, budget_chars=1200)
    assert json.loads(out)["_count"] == 300
    # non-JSON input still goes through the line brief
    assert not out.startswith("[… ")
    assert brief_context("x\n" * 2000, budget_chars=100).count("[…") >= 1


def test_deterministic():
    text = json.dumps(_rows())
    assert json_brief(text, budget_chars=1500) == json_brief(text, budget_chars=1500)


def test_brief_is_none_rather_than_invalid_json_for_nan():
    import json
    from tameru.folding import json_brief

    assert json_brief('[{"a":NaN},{"a":1}]', budget_chars=500) is None
    rows = json.dumps([{"id": i, "v": 1.5} for i in range(40)])
    json.loads(json_brief(rows, budget_chars=600))  # finite input still works


def test_query_term_present_in_every_row_does_not_crowd_out_anomalies():
    import json
    from tameru.folding import json_brief

    rows = [{"id": i, "status": "ok" if i != 777 else "error"} for i in range(1000)]
    out = json.loads(json_brief(json.dumps(rows), budget_chars=1200, query="status"))
    assert any(r["id"] == 777 for r in out["_notable"])


def test_brief_never_materialises_surrogates_or_bidi_controls():
    """Escaped ``\\ud800`` / ``\\u202e`` in the input stay escaped in the brief:
    a raw lone surrogate cannot be encoded, a raw override is a live control."""
    rows = [{"id": i, "s": "\\ud800\\u202e".encode().decode("unicode_escape", "surrogatepass")} for i in range(30)]
    text = json.dumps(rows)  # ensure_ascii=True: escapes in the source text
    out = json_brief(text, budget_chars=600)
    assert out is not None
    out.encode("utf-8")
    assert out.isascii()
    assert json.loads(out)["_head"][0]["s"] == rows[0]["s"]
    astral = json.dumps([{"i": i, "s": "\U000e0001"} for i in range(30)], ensure_ascii=False)
    out = json_brief(astral, budget_chars=600)
    assert out is not None and out.isascii()
    assert json.loads(out)["_head"][0]["s"] == "\U000e0001"
