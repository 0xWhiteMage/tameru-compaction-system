import importlib

import pytest

c = importlib.import_module("tameru.compress_context")


def broken_models():
    yield "model"
    raise ValueError("malformed model iterable")


def excessive_models():
    for _ in range(100):
        yield "model"
    raise AssertionError("candidate bound was not enforced")


@pytest.mark.parametrize("models", [broken_models(), excessive_models(), [None],
                                    ["x" * 1025], 42, []])
def test_bad_model_configuration_fails_open(models, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("invalid configuration reached network")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", no_network)
    assert c._summarise_with_llm("hello", "query", model_candidates=models) is None
