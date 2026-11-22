import hashlib
import importlib
import json
import time

c = importlib.import_module("tameru.compress_context")


def test_oversized_ccr_records_are_not_read_or_stored(tmp_path, monkeypatch):
    original = "x" * 500
    digest = hashlib.sha256(original.encode()).hexdigest()[:24]
    record = tmp_path / f"{digest}.json"
    record.write_text(json.dumps({"hash": digest, "stored_at": time.time(), "ttl": 3600,
                                  "original": original}), encoding="utf-8")
    monkeypatch.setattr(c, "_CCR_MAX_RECORD_BYTES", 100, raising=False)
    assert c.retrieve(digest, tmp_path) is None
    assert c.list_ccr(tmp_path) == []
    assert c.sweep_ccr_cache(tmp_path) == 0
    assert record.exists()
    assert c._ccr_store(original, tmp_path) is None
