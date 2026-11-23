import importlib

c = importlib.import_module("tameru.compress_context")


def test_sweep_leaves_unrelated_json_untouched(tmp_path):
    unrelated = tmp_path / "settings.json"
    unrelated.write_text("{}", encoding="utf-8")
    invalid = tmp_path / ("a" * 24 + ".json")
    invalid.write_text("{}", encoding="utf-8")
    assert c.sweep_ccr_cache(tmp_path) == 1
    assert unrelated.exists()
    assert not invalid.exists()
    assert c.sweep_ccr_cache(tmp_path) == 0
