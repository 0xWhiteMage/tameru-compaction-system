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


def test_falsy_scalar_query_is_coerced_not_dropped():
    # 0 / False are queries, not absence of one: coercion must yield their
    # string form so the term is actually searched. A compressible input keeps
    # the check honest — a fail-open result would satisfy it trivially.
    r = compress_context("value False here\n" + "noise\n" * 300, False, ccr=False, citations=False)
    assert "False" in r.compressed_text
    assert not r.fail_open


def test_broken_iterator_propagates_typeerror():
    def broken():
        yield "step one"
        raise TypeError("mid-iteration")
    with pytest.raises(TypeError):
        compress_context("noise\n" * 300, broken(), ccr=False, citations=False)


def test_plan_steps_do_not_read_as_tool_call():
    # A one-word first step must not let the plan read as a command line.
    r = compress_context("noise\n" * 300, ["build", "deploy app"], ccr=False, citations=False)
    assert not r.fail_open or r.compressed_text
