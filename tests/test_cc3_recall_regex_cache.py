import importlib

c = importlib.import_module("tameru.compress_context")


def test_recall_matching_uses_compiled_pattern_cache(monkeypatch):
    def unexpected_search(*args, **kwargs):
        raise AssertionError("recall used re module search cache")

    monkeypatch.setattr(c.re, "search", unexpected_search)
    assert c._key_in_blob("cat", "cat")
    assert not c._key_in_blob("cat", "concatenate")
