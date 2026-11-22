import importlib

import pytest

c = importlib.import_module("tameru.compress_context")


@pytest.mark.parametrize("value", [[], {}, 42, None, "invalid"])
def test_invalid_frozen_decisions_are_undecided(value):
    block = {"id": 0, "type": "prose", "text": "hello"}
    cache = {"decisions": {c._block_fingerprint(block): value}}
    result = c._apply_freeze(cache, [block], "hello")
    assert result[0]["freeze_decision"] is None
    assert not result[0]["frozen"]
