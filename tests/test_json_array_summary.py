import json

from tameru import compress_context as cc


def test_suspended_accounts_are_kept():
    data = {
        "items": [
            {"id": i, "status": "active"} for i in range(40)
        ] + [
            {"id": 999, "status": "suspended", "reason": "chargeback"}
        ]
    }
    text = json.dumps(data, indent=2)
    out = cc.preprocess_json(text, "which accounts are suspended")
    assert "999" in out
    assert "chargeback" in out
    assert "similar items omitted" in out
    assert len(out) < len(text) / 2


def test_top_level_array_keeps_error_item():
    data = [{"user": f"u-{i}", "plan": "pro", "usage_pct": i} for i in range(50)]
    data.append({"user": "u-77", "plan": "pro", "usage_pct": 100, "error": "quota exceeded"})
    text = json.dumps(data, indent=2)
    out = cc.preprocess_json(text, "")
    assert "u-77" in out
    assert "quota exceeded" in out
    assert len(out) < len(text) / 2


def test_uniform_array_is_unchanged():
    data = {"items": [{"id": i, "status": "active"} for i in range(40)]}
    text = json.dumps(data, indent=2)
    assert cc.preprocess_json(text, "") == text


def test_too_many_unusual_items_is_unchanged():
    data = [{"status": "active"} for _ in range(20)] + [{"status": "failed"} for _ in range(10)]
    text = json.dumps(data, indent=2)
    assert cc.preprocess_json(text, "") == text


def test_short_list_is_unchanged():
    data = [{"id": i, "status": "active"} for i in range(9)] + [{"id": 99, "status": "suspended"}]
    text = json.dumps(data, indent=2)
    assert cc.preprocess_json(text, "") == text


def test_compress_context_uses_json_array_summary():
    data = {
        "items": [
            {"id": i, "status": "active"} for i in range(40)
        ] + [
            {"id": 999, "status": "suspended", "reason": "chargeback"}
        ]
    }
    text = json.dumps(data, indent=2)
    result = cc.compress_context(text, "which accounts are suspended", ccr=False, citations=False)
    assert "999" in result.compressed_text
    assert "chargeback" in result.compressed_text
    assert len(result.compressed_text) < len(text)

try:
    from tameru.compress_context import compress_context, preprocess_json
except ImportError:
    from src.tameru.compress_context import compress_context, preprocess_json


def test_preprocess_json_keeps_refunded_order():
    payload = {
        "page": 1,
        "total": 61,
        "data": [
            {"order": f"ord-{1000 + i}", "status": "paid", "amount": i}
            for i in range(60)
        ]
        + [
            {
                "order": "ord-5555",
                "status": "refunded",
                "amount": 412,
                "note": "duplicate charge",
            }
        ],
    }
    text = json.dumps(payload)
    out = preprocess_json(text, "which order was refunded and why")
    assert "ord-5555" in out
    assert "duplicate charge" in out
    assert len(out) < len(text) / 2


def test_compress_context_generic_json_summary():
    users = [
        {"id": f"u-{i}", "name": f"User {i}", "plan": "pro", "status": "active"}
        for i in range(50)
    ]
    users.append(
        {
            "id": "u-77",
            "name": "Quota User",
            "plan": "pro",
            "status": "active",
            "error": "quota exceeded",
        }
    )
    text = json.dumps({"users": users})
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert not r.fail_open
    assert "quota exceeded" in r.compressed_text
    assert len(r.compressed_text) < len(text) / 2
