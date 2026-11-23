import importlib
import json

import pytest

c = importlib.import_module("tameru.compress_context")


def broken_models():
    yield "model"
    raise ValueError("malformed model iterable")


@pytest.mark.parametrize("models", [broken_models(), [None],
                                    ["x" * 1025], 42, []])
def test_bad_model_configuration_fails_open(models, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("invalid configuration reached network")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", no_network)
    assert c._summarise_with_llm("hello", "query", model_candidates=models) is None


@pytest.mark.parametrize("form", ["iterator", "list", "string"])
def test_model_candidates_are_truncated(form, monkeypatch):
    advances = 0
    attempted = []

    def counting_models():
        nonlocal advances
        while True:
            advances += 1
            if advances > 100:
                raise AssertionError("candidate bound was not enforced")
            yield f"model-{advances}"

    def unavailable(self, request, **kwargs):
        attempted.append(json.loads(request.data)["model"])
        raise OSError("model unavailable")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", unavailable)
    models = counting_models() if form == "iterator" else [f"model-{i}" for i in range(1, 18)]
    if form == "string":
        models = ",".join(models) + "," + "x" * 1025
    assert c._summarise_with_llm("hello", "query", model_candidates=models,
                                 endpoint="http://localhost:11434/v1/chat/completions",
                                 timeout=60) is None
    assert advances == (16 if form == "iterator" else 0)
    assert attempted == [f"model-{i}" for i in range(1, 17)]
