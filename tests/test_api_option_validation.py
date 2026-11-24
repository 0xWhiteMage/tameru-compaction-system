"""Public-API option validation: bad inputs fail loudly or coerce, never crash weird."""
import pytest

from tameru.compress_context import compress_context

DOC = "ERROR: build failed\n" + "filler\n" * 60


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), "abc", object()])
def test_pin_recent_rejects_non_finite_or_non_numeric(bad):
    with pytest.raises(ValueError, match="pin_recent"):
        compress_context(DOC, "build", ccr=False, citations=False, pin_recent=bad)


def test_scalar_query_is_coerced():
    r = compress_context(DOC, 42, ccr=False, citations=False)
    assert r.compressed_text


def test_generator_query_survives_double_join():
    r = compress_context(DOC, iter(["build", "failed"]), ccr=False, citations=False)
    assert "build failed" in r.compressed_text


def test_crashing_gap_marker_falls_back_to_default():
    def boom(omitted, total):
        raise ZeroDivisionError()
    r = compress_context(DOC, "build", ccr=False, citations=False, gap_marker=boom)
    assert r.compressed_text  # no crash; gap marked with the default marker


def test_limits_must_be_industrial_limits():
    with pytest.raises(TypeError, match="IndustrialLimits"):
        compress_context(DOC, "build", ccr=False, citations=False, limits="x")
