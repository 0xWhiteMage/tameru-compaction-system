import importlib

c = importlib.import_module("tameru.compress_context")


def test_invalid_utf8_records_are_skipped(tmp_path):
    record = tmp_path / ("a" * 24 + ".json")
    record.write_bytes(b"\xff")
    assert c.retrieve("a" * 24, tmp_path) is None
    assert c.list_ccr(tmp_path) == []
    assert c.sweep_ccr_cache(tmp_path) == 0
    assert record.exists()
