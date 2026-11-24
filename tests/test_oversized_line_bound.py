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


def test_bounded_variant_resolves_to_its_original_index():
    """A kept bounded variant of an oversized stale line is absent from
    orig_index; without ``_bounded_orig_index`` it counted as later than
    every candidate and vetoed restoring its own replacement."""
    import tameru.compress_context as cc

    stale = "config_key = " + "7" * (cc._MAX_KEPT_LINE_CHARS + 200)
    orig_lines = [stale, "filler", "config_key = 9"]
    orig_index = {ln: i for i, ln in enumerate(orig_lines)}
    kept = [cc._bound_fact_line(stale), "filler"]
    bidx = cc._bounded_orig_index(kept, orig_index)
    assert bidx[kept[0]] == 0
    assert not cc._fact_superseded_in(
        "config_key = 9", kept, orig_index, bounded_index=bidx
    )
    # ordering still works: a bounded stale line that stands later vetoes
    idx2 = {"config_key = 9": 0, "filler": 1, stale: 2}
    kept2 = [cc._bound_fact_line(stale)]
    assert cc._fact_superseded_in(
        "config_key = 9", kept2, idx2, bounded_index=cc._bounded_orig_index(kept2, idx2)
    )


def test_accented_kept_text_does_not_cover_a_missing_fact():
    from tameru.compress_context import _fact_variant_present
    # 'café' decomposes to 'cafe' + U+0301 — a plain substring search then
    # counts a kept 'café' as covering the dropped 'cafe' value. The match
    # ends inside a combining sequence, so it must not count.
    ln = "A" * 3000 + " cafe " + "B" * 6000
    kept = [ln.replace(" cafe ", " café ")]
    assert _fact_variant_present(ln, kept, must=("cafe",)) is False
    assert _fact_variant_present(ln, kept, must=("café",)) is True


def test_clip_anchor_prefers_verbatim_hit_over_accent_variant():
    # Same term hit twice inside one merged window — 'café' (folded-only)
    # before 'cafe' (verbatim): the clip anchor must rank the HIT's own
    # exactness, not the window's, so budget goes to the verbatim match.
    line = "café" + "x" * 200 + "cafe" + "t" * 500
    out = _window_oversized_line(
        line, 100, ("cafe",), None, len(line), raw_terms=("cafe",)
    )
    assert "cafe" in out


def test_cancelling_folds_still_build_the_offset_map():
    # Fifty combining marks fold to nothing (-50) and fifty 'ﬁ' expand to
    # 'fi' (+50): folded length equals source length and the fold is pure
    # ASCII, yet offsets before 'cafe' drift by -50. The map check must
    # inspect the input, not the folded text — else the clip starts 50
    # chars early, inside the 'x' run.
    line = (
        "h" * 400 + "hit1" + "x" * 400 + "́" * 50
        + "cafe" + "ﬁ" * 50 + "t" * 400
    )
    out = _window_oversized_line(
        line, 600, ("hit1", "cafe"), None, len(line),
        raw_terms=("hit1", "cafe"),
    )
    assert "cafe" in out
    assert "xcafe" not in out


def test_clip_anchor_keeps_another_terms_only_hit():
    # Term 'cafe' hits twice — 'café' (variant) then 'cafe' (verbatim) —
    # while 'onlyB' has its single hit in between. Anchoring at the
    # verbatim repeat would start the clip past onlyB's only match; the
    # anchor is the earliest of each still-missing term's best hit.
    line = "m" * 200 + "café" + "x" * 46 + "onlyB" + "y" * 145 + "cafe" + "t" * 300
    out = _window_oversized_line(
        line, 300, ("cafe", "onlyb"), None, len(line),
        raw_terms=("cafe", "onlyB"),
    )
    assert "onlyB" in out
    assert "cafe" in out


def test_reserved_clip_marks_only_emitted_hits_covered():
    # Window 1 ('café' variant + 'onlyb') clips to its first hit to reserve
    # budget for the later verbatim window; window 2 holds 'onlyb''s second
    # occurrence. Marking the clipped-out hit covered would let window 2's
    # clip anchor past it — 'onlyb' would vanish entirely.
    line = (
        "m" * 100 + "café" + "x" * 176 + "onlyb" + "y" * 400
        + "onlyb" + "z" * 206 + "nice" + "t" * 500
    )
    out = _window_oversized_line(
        line, 400, ("cafe", "onlyb", "nice"), None, len(line),
        raw_terms=("cafe", "onlyb", "nice"),
    )
    assert "onlyb" in out


def test_head_hits_are_covered_before_clipping():
    # Every 'alpha' hit merges into one oversized window; the first is
    # already visible in the emitted head. Without head coverage the clip
    # anchors at the earliest 'still-missing' hit — an alpha repeat — and
    # 'delta's only match falls just past the clip end.
    line = ("x" * 60 + "alpha" + "y" * 60) * 3 + ("z" * 60 + "delta" + "w" * 60)
    out = _window_oversized_line(
        line, 330, ("alpha", "delta"), None, len(line),
        raw_terms=("alpha", "delta"),
    )
    assert "delta" in out
