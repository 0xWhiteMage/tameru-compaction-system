import importlib

c = importlib.import_module("tameru.compress_context")


def test_malformed_freeze_prefix_cannot_expand_hashing_work():
    cache = {"ctx_prefix_len": 10**100}
    c._apply_freeze(cache, [], "x" * 2000)
    assert cache["ctx_prefix_len"] == 500
    c._apply_freeze(cache, [], "x" * 2000 + "append")
    assert cache["ctx_prefix_len"] == 500
