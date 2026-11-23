import pytest

from tameru.semantic import SemanticTier


@pytest.mark.parametrize("vector", [[1.0], [1.0, 2.0, 3.0]])
def test_similarity_rejects_dimension_mismatch(vector):
    tier = object.__new__(SemanticTier)
    with pytest.raises(ValueError):
        tier.similarity([1.0, 2.0], [vector])


def test_similarity_normal_and_empty_vectors():
    tier = object.__new__(SemanticTier)
    assert tier.similarity([1.0, 2.0], [[3.0, 4.0]]) == [11.0]
    assert tier.similarity([1.0], []) == []
    assert tier.similarity([], [[]]) == [0]
