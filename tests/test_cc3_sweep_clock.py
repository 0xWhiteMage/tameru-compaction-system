import importlib
import json

import pytest

c = importlib.import_module("tameru.compress_context")


@pytest.mark.parametrize("now", [float("nan"), float("inf"), -1, "invalid", 10**400])
def test_invalid_sweep_clock_cannot_delete_records(tmp_path, now):
    record = tmp_path / ("a" * 24 + ".json")
    record.write_text(json.dumps({"stored_at": 10, "ttl": 3600}), encoding="utf-8")
    assert c.sweep_ccr_cache(tmp_path, now=now) == 0
    assert record.exists()
