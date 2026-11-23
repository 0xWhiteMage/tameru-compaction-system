import importlib

c = importlib.import_module("tameru.compress_context")


def test_source_key_collection_preserves_order_and_deduplicates(monkeypatch):
    monkeypatch.setattr(c, "_extract_entities", lambda query: ["alpha", "beta", "alpha"])
    monkeypatch.setattr(c, "_extract_terms", lambda query: ["beta", "gamma", "missing"])
    assert c._source_keys("query", "alpha beta gamma") == ["alpha", "beta", "gamma"]
    assert c._source_keys("query", "") == []
