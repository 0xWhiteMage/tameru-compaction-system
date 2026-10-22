from tameru.compress_context import _compiled_term_pattern, _term_test


def test_term_pattern_cache():
    assert _term_test("max")("set max_connections = 10") is True
    assert _term_test("max")("maximum") is False
    assert _term_test("42")("port 42 open") is True
    assert _term_test("42")("12:42:00") is False
    assert _term_test("a.b")("x a.b y") is True

    _compiled_term_pattern.cache_clear()
    _term_test("zz")
    _term_test("zz")
    assert _compiled_term_pattern.cache_info().hits >= 1
