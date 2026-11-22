import importlib

import pytest

c = importlib.import_module("tameru.compress_context")


@pytest.mark.parametrize("ratio", [float("nan"), float("inf"), -1, 0, 2, None, "bad", 10**400])
def test_invalid_summary_ratio_fails_open(ratio):
    assert c._summarise_with_llm("hello", "query", ratio, endpoint="invalid") is None
