from tameru.compress_context import estimate_tokens


def test_long_dot_run_costs_tokens():
    assert estimate_tokens("." * 1000) >= 200


def test_short_run_unchanged():
    assert estimate_tokens("=" * 15) <= 1


def test_ordinary_code_unchanged():
    assert estimate_tokens("def f(a, b): return a+b") == 7


def test_box_drawing_not_double_counted():
    assert estimate_tokens("─" * 200) == 200
