import copy

import pytest

from tameru.semantic import SemanticUnavailable, _DisabledTier


def test_disabled_tier_does_not_claim_protocol_methods():
    tier = _DisabledTier()
    for name in ("__anything__", "__array__", "__deepcopy__"):
        assert not hasattr(tier, name)
    assert copy.deepcopy(tier).available is False


def test_disabled_tier_methods_still_report_unavailable():
    with pytest.raises(SemanticUnavailable):
        _DisabledTier().encode([])
