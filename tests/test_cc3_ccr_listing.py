import hashlib
import importlib
import json
import time

import pytest

c = importlib.import_module("tameru.compress_context")


def test_listing_rejects_tampered_content(tmp_path):
    text = "original"
    digest = hashlib.sha256(text.encode()).hexdigest()[:24]
    record = tmp_path / f"{digest}.json"
    data = {"hash": digest, "stored_at": time.time(), "ttl": 3600, "original": "tampered"}
    record.write_text(json.dumps(data), encoding="utf-8")
    assert c.list_ccr(tmp_path) == []
    data["original"] = text
    record.write_text(json.dumps(data), encoding="utf-8")
    assert c.list_ccr(tmp_path)[0]["preview"] == text
    assert c.retrieve(digest, tmp_path) == text


def test_listing_skips_symlink_record(tmp_path):
    original = "hello"
    digest = hashlib.sha256(original.encode()).hexdigest()[:24]
    target = tmp_path / "target"
    target.write_text(json.dumps({"hash": digest, "stored_at": time.time(), "ttl": 3600,
                                  "original": original}), encoding="utf-8")
    try:
        (tmp_path / f"{digest}.json").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert c.list_ccr(tmp_path) == []
