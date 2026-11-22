import importlib
import itertools

import pytest

c = importlib.import_module("tameru.compress_context")


def broken_models():
    yield "model"
    raise ValueError("malformed model iterable")


@pytest.mark.parametrize("models", [broken_models(), itertools.repeat("model"), [None],
                                    ["x" * 1025], 42, []])
def test_bad_model_configuration_fails_open(models, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("invalid configuration reached network")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    assert c._summarise_with_llm("hello", "query", model_candidates=models) is None
