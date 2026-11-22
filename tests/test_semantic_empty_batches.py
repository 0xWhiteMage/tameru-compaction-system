import pytest

from tameru.semantic import SemanticTier


class Model:
    def encode(self, *args, **kwargs):
        raise RuntimeError("model called")

    def predict(self, *args, **kwargs):
        raise RuntimeError("model called")


def tier():
    value = object.__new__(SemanticTier)
    value._bi = Model()
    value._ce = Model()
    return value


def test_empty_batches_do_not_call_models():
    value = tier()
    assert value.encode([]) == []
    assert value.cross_scores("q", []) == []
    assert value.score_against_query("q", []) == ([], [])
    value._ce = None
    assert value.cross_scores("q", []) == []
    assert value.cross_scores("q", ["text"]) is None


def test_nonempty_model_errors_propagate():
    value = tier()
    with pytest.raises(RuntimeError, match="model called"):
        value.encode(["text"])
    with pytest.raises(RuntimeError, match="model called"):
        value.cross_scores("q", ["text"])
