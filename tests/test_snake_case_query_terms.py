from tameru.compress_context import _term_test, compress_context


def test_short_alphabetic_terms_match_snake_case():
    assert _term_test("max")("max_connections | 100") is True
    assert _term_test("pool")("db_pool_exhausted_total 412") is True


def test_letters_still_block_short_alphabetic_terms():
    assert _term_test("max")("maximum 5") is False
    assert _term_test("pool")("spool 3") is False
    assert _term_test("max")("max2 5") is False


def test_digit_terms_keep_clock_time_safe_matching():
    assert _term_test("12")("at 10:12:30") is False


def test_end_to_end_snake_case_query_term():
    rows = "".join(f"param_{i} | {100 + i} | kB\n" for i in range(60))
    text = (
        "name | setting | unit\n"
        + rows
        + "max_connections | 100 | \n"
        + "shared_buffers | 16384 | 8kB\n"
    )
    out = compress_context(text, "max connections setting", ccr=False, citations=False).compressed_text
    assert "max_connections | 100" in out
    assert len(out) < 0.6 * len(text)

def test_literal_first_pattern_matches_same_boundaries():
    import re

    term = "max"
    pattern = re.compile(rf"{re.escape(term)}(?<![^\W_]{re.escape(term)})(?![^\W_])")

    for text in ("max", "_max_", "a max.", "max_x", "x_max"):
        assert pattern.search(text) is not None

    for text in ("xmax", "max2", "2max", "ümax", "maxes"):
        assert pattern.search(text) is None
