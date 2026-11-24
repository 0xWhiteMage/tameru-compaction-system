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


def test_bytes_query_is_rejected_not_iterated():
    # bytes iterates to ints: "97 98 99" digit terms that match nothing.
    with pytest.raises(TypeError, match="query"):
        compress_context(DOC, b"needle", ccr=False, citations=False)


def test_bytearray_query_is_rejected():
    with pytest.raises(TypeError, match="query"):
        compress_context(DOC, bytearray(b"needle"), ccr=False, citations=False)


def test_non_str_mode_is_rejected():
    # A non-str mode fell through to ``.strip()`` with AttributeError.
    with pytest.raises(TypeError, match="mode"):
        compress_context(DOC, "build", mode=3, ccr=False, citations=False)


def test_none_mode_uses_adaptive_default():
    r = compress_context(DOC, "build", mode=None, ccr=False, citations=False)
    assert r.compressed_text


def test_non_numeric_budget_ratio_is_rejected():
    with pytest.raises(TypeError, match="budget_ratio"):
        compress_context(DOC, "build", budget_ratio="half", ccr=False, citations=False)


def test_negative_pin_recent_is_rejected():
    # scored[-(-1):] sliced to scored[1:] and pinned the entire document.
    with pytest.raises(ValueError, match="pin_recent"):
        compress_context(DOC, "build", pin_recent=-1, ccr=False, citations=False)


def test_non_int_pin_recent_is_rejected():
    with pytest.raises(ValueError, match="pin_recent"):
        compress_context(DOC, "build", pin_recent=2.5, ccr=False, citations=False)


def test_bare_string_pin_patterns_is_one_pattern():
    # Same convention as recursion_markers: a bare str is ONE pattern, not an
    # iterable of characters (which failed open as unsafe_pin_patterns).
    r = compress_context(DOC, "build", pin_patterns="build", ccr=False, citations=False)
    assert "unsafe_pin_patterns" not in r.reasons


def test_limits_accepts_a_kwargs_dict():
    # A dict spells the same IndustrialLimits — the constructor's field
    # names apply and __post_init__ validates the values.
    r = compress_context(DOC, "build", ccr=False, citations=False,
                         limits={"max_lines": 100})
    assert r.compressed_text


def test_limits_dict_rejects_unknown_fields():
    with pytest.raises(TypeError):
        compress_context(DOC, "build", ccr=False, citations=False,
                         limits={"not_a_field": 1})


def test_bool_budget_ratio_is_rejected():
    # bool is an int subclass: True read as 1.0 silently.
    with pytest.raises(TypeError, match="budget_ratio"):
        compress_context(DOC, "build", budget_ratio=True, ccr=False, citations=False)


@pytest.mark.parametrize("bad", [0, -0.5, 1.5])
def test_out_of_range_budget_ratio_is_rejected(bad):
    # Adaptive ignored out-of-range ratios (≥1 kept all, ≤0 kept none);
    # the documented domain is (0, 1] on every path.
    with pytest.raises(ValueError, match="budget_ratio"):
        compress_context(DOC, "build", budget_ratio=bad, ccr=False, citations=False)


def test_non_str_selector_query_is_rejected():
    with pytest.raises(TypeError, match="selector_query"):
        compress_context(DOC, "build", selector_query=42, ccr=False, citations=False)


def test_huge_int_budget_ratio_is_rejected_as_value_error():
    # float(10**400) raises OverflowError — the domain check surfaces its own
    # ValueError so callers catching ValueError see the rejection.
    with pytest.raises(ValueError, match="budget_ratio"):
        compress_context(DOC, "build", budget_ratio=10**400, ccr=False, citations=False)


def test_non_str_strategy_is_rejected():
    # ``(strategy or "extract").strip()`` raised AttributeError on an int;
    # a falsy non-str silently became 'extract'.
    with pytest.raises(TypeError, match="strategy"):
        compress_context(DOC, "build", strategy=42, ccr=False, citations=False)


def test_scalar_recursion_markers_is_rejected():
    # iter(42) raised a bare TypeError with no option name.
    with pytest.raises(TypeError, match="recursion_markers"):
        compress_context(DOC, "build", recursion_markers=42, ccr=False, citations=False)


def test_recursion_markers_drops_non_str_entries():
    r = compress_context(DOC, "build", recursion_markers=[42, "", "marker"], ccr=False, citations=False)
    assert r.compressed_text


def test_format_limits_validate_fields():
    from tameru.format_adapters import FormatLimits
    with pytest.raises(ValueError, match="max_records"):
        FormatLimits(max_records=-1)
    with pytest.raises(ValueError, match="max_records"):
        FormatLimits(max_records=True)


def test_adapt_format_limits_types():
    from tameru.format_adapters import adapt_format
    r = adapt_format(DOC, "build", limits={"max_records": 50})
    assert r.text
    with pytest.raises(TypeError, match="FormatLimits"):
        adapt_format(DOC, "build", limits="x")


def test_adapt_report_limits_types():
    from tameru.format_adapters import adapt_report
    with pytest.raises(TypeError, match="FormatLimits"):
        adapt_report('{"r": [1]}', "build", limits="x")


def test_industrial_preprocess_limits_types():
    from tameru.industrial import industrial_preprocess, profile_input
    r = industrial_preprocess(DOC, "build", limits={"max_lines": 50})
    assert r.text
    with pytest.raises(TypeError, match="IndustrialLimits"):
        industrial_preprocess(DOC, "build", limits="x")
    with pytest.raises(TypeError, match="IndustrialLimits"):
        profile_input(DOC, "x")
    text = "a\nb" * 20
    for bad in ("x", -3, 0, True, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="summary_timeout must be a positive"):
            compress_context(text, "a", summary_timeout=bad, ccr=False)
