import json

from tameru.compress_context import compress_context, preprocess_json


def test_ndjson_keeps_odd_sync_line():
    lines = [
        json.dumps(
            {
                "ts": f"2026-10-21T06:{i:02d}:00Z",
                "level": "info",
                "event": "sync",
                "rows": 100 + i,
            }
        )
        for i in range(45)
    ]
    odd = json.dumps(
        {
            "ts": "2026-10-21T06:46:00Z",
            "level": "info",
            "event": "sync",
            "rows": 0,
            "note": "upstream returned empty page 17",
        }
    )
    text = "\n".join(lines + [odd])

    out = preprocess_json(text, "why was a sync empty")
    assert odd in out
    assert "similar items omitted" in out
    assert len(out.splitlines()) < 6

    res = compress_context(text, "why was a sync empty", ccr=False, citations=False, anchor_errors=True)
    assert "empty page 17" in res.compressed_text
    assert len(res.compressed_text) < 0.25 * len(text)


def test_ndjson_keeps_negative_invoice():
    lines = [
        json.dumps(
            {
                "t": f"2026-10-21T07:{i:02d}:00Z",
                "svc": "billing",
                "msg": "invoice generated",
                "invoice": f"INV-{1000 + i}",
                "amount": 10 + i,
            }
        )
        for i in range(40)
    ]
    odd = json.dumps(
        {
            "t": "2026-10-21T07:41:00Z",
            "svc": "billing",
            "msg": "invoice generated",
            "invoice": "INV-1041",
            "amount": -250,
            "warning": "negative total after credit",
        }
    )
    text = "\n".join(lines + [odd])

    res = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "INV-1041" in res.compressed_text
    assert "-250" in res.compressed_text
    assert not res.fail_open
    assert len(res.compressed_text) < 0.3 * len(text)


def test_ndjson_guards():
    small = "\n".join(json.dumps({"i": i}) for i in range(10))
    assert preprocess_json(small, "why") == small

    bad = [json.dumps({"i": i}) for i in range(30)]
    bad[5] = "not json"
    bad_text = "\n".join(bad)
    assert preprocess_json(bad_text, "why") == bad_text

    assert preprocess_json(bad_text, "INV-1041") is not None
