import pytest

from tameru import industrial


def test_default_profiles_reuse_limits_even_on_cache_hits(monkeypatch):
    def unexpected():
        raise AssertionError("default limits were reconstructed")

    monkeypatch.setattr(industrial, "IndustrialLimits", unexpected)
    for text in ("", "plain text", "profile-cache-default\n" * 1000):
        first = industrial.profile_input(text)
        assert industrial.profile_input(text) == first
        assert not first.limit_reason


def test_explicit_profile_limits_still_apply():
    limits = industrial.IndustrialLimits(max_input_chars=2)
    result = industrial.profile_input("long text", limits)
    assert result.limit_reason == "character limit exceeded: 9 > 2"


@pytest.mark.parametrize("value", [0, -1, True, "2"])
def test_explicit_invalid_limits_are_still_validated(value):
    with pytest.raises(ValueError, match="max_input_chars must be a positive integer"):
        industrial.IndustrialLimits(max_input_chars=value)
