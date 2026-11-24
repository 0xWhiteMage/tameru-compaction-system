"""Oversized single lines: bounded render, bounded floors, honest token estimate."""

from tameru.compress_context import (
    _estimate_tokens,
    _window_oversized_line,
    compress_context,
)


def _giant_line() -> str:
    return "x" * 1_000_000 + " ERROR needle_in_haystack " + "y" * 100


def test_long_word_run_counts_real_tokens():
    # BPE-style tokenizers split a 1 MB word run into ~250K tokens; counting
    # it as one word broke every savings gate downstream.
    est = _estimate_tokens("x" * 1_000_000)
    assert est > 100_000


def test_short_word_runs_do_not_inflate_estimate():
    est = _estimate_tokens("the quick brown fox jumps over the lazy dog")
    assert est <= 16


def test_megabyte_line_is_windowed_not_failed_open():
    r = compress_context(_giant_line(), "needle_in_haystack",
                         ccr=False, citations=False)
    assert not r.fail_open
    assert "needle_in_haystack" in r.compressed_text
    assert len(r.compressed_text) < 20_000


def test_windowed_output_starts_with_input_prefix():
    # Extractive checkers read an emitted line as "truncated input line"
    # only when it starts with a real prefix — a marker may never lead.
    r = compress_context(_giant_line(), "needle_in_haystack",
                         ccr=False, citations=False)
    first = r.compressed_text.split("\n")[0]
    assert _giant_line()[:60] == first[:60]


def test_megabyte_line_bounded_when_query_misses():
    r = compress_context(_giant_line(), "absent_term_zzz",
                         ccr=False, citations=False)
    assert len(r.compressed_text) < 20_000 or r.fail_open


def test_folded_hit_offsets_stay_linear_memory_on_ascii():
    import tracemalloc
    line = "A" * 1_000_000
    tracemalloc.start()
    _window_oversized_line(line, 8192, (), None, len(line))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 20 * 1024 * 1024


def test_casefold_combining_mark_still_matches_query():
    line = "x" * 40000 + "İstanbul harbor" + "y" * 40000
    out = _window_oversized_line(line, 8192, ("istanbul",), None, len(line))
    assert "İstanbul" in out


def test_budget_filling_clip_does_not_reemit_tail():
    import re
    line = "H" * 64 + "hit1" + "m" * 200 + "hit2" + "t" * 1000
    out = _window_oversized_line(line, 200, ("hit1", "hit2"), None, len(line))
    content = re.sub(r"\[… \d+ chars omitted …\]", "", out)
    assert len(content) <= 200
    assert "hit2" in out


def test_fact_variant_must_compare_is_case_sensitive():
    from tameru.compress_context import _fact_variant_present, _MAX_KEPT_LINE_CHARS
    ln = "KEY=Value_" + "v" * (_MAX_KEPT_LINE_CHARS + 800)
    kept = ln[:2048].replace("Value", "value") + ln[2048:8000]
    assert _fact_variant_present(ln, [kept], must=("Value",)) is False
    assert _fact_variant_present(ln, [ln[:8000]], must=("Value",)) is True


def test_cancelling_fold_lengths_do_not_drift_offsets():
    # 'ß' folds to two chars and a bare combining mark to zero: they cancel
    # in total length, so a len-equal folded text is NOT proof of identity
    # offsets — a hit between them must still land.
    line = "x" * 40000 + "ß" + "needle" + "̇" + "y" * 40000
    out = _window_oversized_line(line, 8192, ("needle",), None, len(line))
    assert "needle" in out


def test_verbatim_hit_outranks_folded_only_windows():
    # More folded-only matches than the window cap must not spend the emit
    # budget ahead of a later verbatim occurrence.
    line = ("z" * 3000 + "İstanbul" + "z" * 3000) * 40 + " istanbul " + "q" * 5000
    out = _window_oversized_line(line, 8192, ("istanbul",), None, len(line))
    assert " istanbul " in out


def test_exact_case_identifier_outranks_casefold_variants():
    # hit_terms arrive casefolded; preference must judge the QUERY's
    # original case so a lowercase 'foo' window never displaces 'FOO'.
    line = ("z" * 3000 + "token_foo" + "z" * 3000) * 40 + " token_FOO " + "q" * 5000
    out = _window_oversized_line(
        line, 8192, ("token_foo",), None, len(line), raw_terms=("token_FOO",)
    )
    assert " token_FOO " in out


def test_folded_only_window_over_budget_is_clipped_not_dropped():
    line = "H" * 64 + "hit1" + "m" * 200 + "hit2" + "t" * 1000
    out = _window_oversized_line(line, 200, ("hit1", "hit2"), None, len(line))
    assert "hit2" in out


def test_duplicate_hit_window_yields_to_unique_term_window():
    from tameru.compress_context import _window_oversized_line
    # Two folded-only hits for 'ss' (ß folds to ss) sandwich a lone verbatim
    # hit for 'zzzuniq': once the first ß window emits, the second is a pure
    # duplicate and must not clip its way into the unique term's budget.
    line = (
        "h" * 5000
        + "ß" + "a" * 4000
        + "ß" + "b" * 4000
        + "zzzuniq"
        + "c" * 8000
    )
    out = _window_oversized_line(
        line, cap=2000, hit_terms=("ss", "zzzuniq"), marker_fn=None,
        total_chars=len(line), raw_terms=("ss", "zzzuniq"),
    )
    assert "zzzuniq" in out


def test_cap_prefers_case_only_over_spelling_variant():
    from tameru.compress_context import _window_oversized_line
    # 33+ 'Straße' windows ahead of one 'STRASSE' window: the 32-span cap must
    # not let file order crowd the case-only match the ranking prefers.
    line = ("Straße" + "x" * 6000) * 40 + "STRASSE" + "y" * 6000
    out = _window_oversized_line(
        line, cap=8192, hit_terms=("strasse",), marker_fn=None,
        total_chars=len(line), raw_terms=("strasse",),
    )
    assert "STRASSE" in out
