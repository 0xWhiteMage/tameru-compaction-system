from tameru.agent_formats import _classify_pytest, _render_kept, preprocess_test_output
from tameru.compress_context import compress_context, error_fingerprints


def _long_info(i: int) -> str:
    return f"INFO app.order message number {i} with some extra padding to make the line longer"


def _pytest_output(body: list[str]) -> str:
    lines = [
        "============================= test session starts ==============================",
        "platform linux -- Python 3.11.0, pytest-8.0.0, pluggy-1.5.0",
        "rootdir: /repo",
        "collected 1 item",
        "",
        "tests/test_orders.py F                                                    [100%]",
        "",
        "=================================== FAILURES ===================================",
        "___________________________________ test_order ___________________________________",
        "    def test_order():",
        "        assert order.total == 10",
        ">       assert order.status == 'paid'",
        "E       AssertionError: assert 'pending' == 'paid'",
        "tests/test_orders.py:41: AssertionError",
        "------------------------------ Captured log call -------------------------------",
    ]
    lines.extend(body)
    lines.extend(
        [
            "=========================== short test summary info ============================",
            "FAILED tests/test_orders.py::test_order - AssertionError",
            "============================== 1 failed in 0.01s ===============================",
        ]
    )
    return "\n".join(lines)


def test_pytest_captured_log_call_collapses():
    body = []
    for i in range(1, 61):
        if i == 30:
            body.append(
                "ERROR app.order boom with some extra padding to make the line longer"
            )
        else:
            body.append(_long_info(i))

    text = _pytest_output(body)
    out = preprocess_test_output(text, query="", gap_marker=None)

    assert out is not None
    assert len(out) < 0.5 * len(text)

    assert "------------------------------ Captured log call -------------------------------" in out
    # 1.4.1: the first and last line of a long section are kept (the shape of
    # the log), the rest only when WARNING+ or an error fingerprint.
    assert _long_info(1) in out
    assert _long_info(2) not in out
    assert _long_info(59) not in out
    assert _long_info(60) in out
    assert "ERROR app.order boom" in out
    assert "E       AssertionError" in out
    assert "tests/test_orders.py:41: AssertionError" in out
    # the ERROR line splits the dropped lines into two runs (28 + 29)
    assert out.count("captured lines omitted …]") == 2


def test_pytest_short_captured_section_stays_whole():
    lines = [
        "=================================== FAILURES ===================================",
        "___________________________________ test_order ___________________________________",
        "E       AssertionError",
        "tests/test_orders.py:41: AssertionError",
        "------------------------------ Captured log call -------------------------------",
        "INFO app.order 1",
        "INFO app.order 2",
        "INFO app.order 3",
        "INFO app.order 4",
        "=========================== short test summary info ============================",
    ]

    keep, tests, suites, captured = _classify_pytest(lines)

    assert all(keep[4:9])
    assert all(c == 0 for c in captured)


def test_pytest_failure_block_without_captured_section_keeps_all():
    lines = [
        "=================================== FAILURES ===================================",
        "___________________________________ test_order ___________________________________",
        "    def test_order():",
        "        assert order.total == 10",
        ">       assert order.status == 'paid'",
        "E       AssertionError: assert 'pending' == 'paid'",
        "tests/test_orders.py:41: AssertionError",
        "=========================== short test summary info ============================",
    ]

    keep, tests, suites, captured = _classify_pytest(lines)

    assert all(keep)
    assert all(c == 0 for c in captured)


def test_render_kept_default_marker_only_for_captured_runs():
    lines = ["a", "b", "c", "d", "e", "f", "g", "h"]
    keep = [True, False, False, False, False, False, False, True]
    tests = [0] * len(lines)
    suites = [0] * len(lines)
    total = len("\n".join(lines))

    captured = [0, 1, 1, 1, 1, 1, 1, 0]
    out = _render_kept(lines, keep, tests, suites, None, total, captured=captured)
    assert "[… 6 captured lines omitted …]" in out

    captured_none = [0] * len(lines)
    out_plain = _render_kept(lines, keep, tests, suites, None, total, captured=captured_none)
    assert "[…" not in out_plain

    out_marker = _render_kept(
        lines,
        keep,
        tests,
        suites,
        lambda omitted, total_chars: "CALLER-MARKER",
        total,
        captured=captured,
    )
    assert "CALLER-MARKER" in out_marker


def test_fix1_imports_are_callable():
    assert callable(compress_context)
    assert callable(error_fingerprints)


def test_captured_stdout_with_blank_lines_is_one_section():
    """A blank line inside captured stdout does not end the section: before 1.4.1 only the
    first paragraph collapsed and everything after the first blank line was kept whole."""
    body = []
    for i in range(1, 41):
        body.append(_long_info(i))
        if i % 10 == 0:
            body.append("")
    text = _pytest_output(body).replace("Captured log call", "Captured stdout call")
    out = preprocess_test_output(text, query="", gap_marker=None)
    assert out is not None
    assert _long_info(1) in out and _long_info(40) in out
    assert not any(_long_info(i) in out for i in (11, 15, 25, 35))
    assert "FAILED tests/test_orders.py::test_order" in out


def test_captured_line_naming_the_query_is_restored():
    body = [_long_info(i) for i in range(1, 41)]
    body[19] = "INFO app.order reservation hold=h-7be559 released late"
    text = _pytest_output(body)
    out = preprocess_test_output(text, query="h-7be559", gap_marker=None)
    assert out is not None
    assert "hold=h-7be559" in out


def test_inlining_marker_keeps_a_short_captured_run():
    from tameru.compress_context import InliningGapMarker

    lines = ["keep a", "x", "keep b"]
    keep = [True, False, True]
    zeros = [0, 0, 0]
    marker = InliningGapMarker(lambda omitted, total: "<" + "m" * 40 + ">")
    out = _render_kept(lines, keep, zeros, zeros, marker, 20, captured=[0, 1, 0])
    assert out == "keep a\nx\nkeep b"
    plain = _render_kept(lines, keep, zeros, zeros, marker.fn, 20, captured=[0, 1, 0])
    assert "<mmmm" in plain and "\nx\n" not in plain
