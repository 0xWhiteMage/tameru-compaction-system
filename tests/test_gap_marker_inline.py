from tameru.compress_context import InliningGapMarker, _render, compress_context
from tameru.format_adapters import _with_gaps


def test_with_gaps_plain_marker_short_span_uses_marker():
    units = ["a", "bb", "c"]
    keep = [True, False, True]
    marker = "X" * 90
    out = _with_gaps(units, keep, "\n", lambda omitted, total: marker, 100)
    assert out == ["a", marker, "c"]


def test_with_gaps_inlining_marker_short_span_is_verbatim():
    units = ["a", "bb", "c"]
    keep = [True, False, True]
    marker = InliningGapMarker(lambda omitted, total: "X" * 90)
    out = _with_gaps(units, keep, "\n", marker, 100)
    assert out == ["a", "bb", "c"]


def test_with_gaps_inlining_marker_long_span_uses_marker():
    middle = "y" * 2000
    units = ["a", middle, "c"]
    keep = [True, False, True]
    marker = InliningGapMarker(lambda omitted, total: "X" * 90)
    out = _with_gaps(units, keep, "\n", marker, 100)
    assert out == ["a", "X" * 90, "c"]


def test_with_gaps_inlining_marker_equal_length_is_verbatim():
    middle = "y" * 90
    units = ["a", middle, "c"]
    keep = [True, False, True]
    marker = InliningGapMarker(lambda omitted, total: "X" * 90)
    out = _with_gaps(units, keep, "\n", marker, 100)
    assert out == ["a", middle, "c"]


def test_with_gaps_blank_run_gets_nothing():
    plain = _with_gaps(
        ["a", "", "c"],
        [True, False, True],
        "\n",
        lambda omitted, total: "X" * 90,
        100,
    )
    inlining = _with_gaps(
        ["a", "", "c"],
        [True, False, True],
        "\n",
        InliningGapMarker(lambda omitted, total: "X" * 90),
        100,
    )
    assert plain == ["a", "c"]
    assert inlining == ["a", "c"]


def test_with_gaps_no_marker_is_quiet():
    out = _with_gaps(["a", "bb", "c"], [True, False, True], "\n", None, 100)
    assert out == ["a", "c"]


def test_render_plain_marker_short_span_uses_marker():
    lines = ["a", "b", "c", "d", "e"]
    blocks = [{"id": 0, "start": 2, "end": 2, "score": 1.0}]
    marker = "X" * 90
    out = _render(
        lines,
        blocks,
        {0},
        gap_marker=lambda omitted, total: marker,
        total_chars=10,
    )
    assert out == f"{marker}\nc\n{marker}"


def test_render_inlining_marker_short_span_is_verbatim():
    lines = ["a", "b", "c", "d", "e"]
    blocks = [{"id": 0, "start": 2, "end": 2, "score": 1.0}]
    marker = InliningGapMarker(lambda omitted, total: "X" * 90)
    out = _render(
        lines,
        blocks,
        {0},
        gap_marker=marker,
        total_chars=10,
    )
    assert out == "a\nb\nc\nd\ne"


def test_render_inlining_marker_equal_length_is_verbatim():
    lines = ["a", "b", "c", "d", "e"]
    blocks = [{"id": 0, "start": 2, "end": 2, "score": 1.0}]
    marker = InliningGapMarker(lambda omitted, total: "X" * 3)
    out = _render(
        lines,
        blocks,
        {0},
        gap_marker=marker,
        total_chars=10,
    )
    assert out == "a\nb\nc\nd\ne"


def test_render_inlining_marker_long_span_uses_marker():
    lines = ["a", "y" * 2000, "c"]
    blocks = [
        {"id": 0, "start": 0, "end": 0, "score": 1.0},
        {"id": 1, "start": 2, "end": 2, "score": 1.0},
    ]
    marker = "X" * 90
    out = _render(
        lines,
        blocks,
        {0, 1},
        gap_marker=InliningGapMarker(lambda omitted, total: marker),
        total_chars=10,
    )
    assert out == f"a\n{marker}\nc"


def _build_compress_text() -> str:
    # Paragraphs (blank-line separated) are the engine's blocks: the 10-char
    # paragraph between the two query hits is a block of its own, dropped by
    # default and inlined with ``inline_short_gaps``.
    paras: list[str] = []
    for i in range(30):
        if i in (10, 12):
            paras.append(f"needle {i:03d} the payment gateway timed out on order {i}")
        elif i == 11:
            paras.append("shortline1")
        else:
            paras.append(f"filler paragraph {i:03d} " + "lorem ipsum dolor sit amet " * 2)
    return "\n\n".join(paras)


def test_compress_context_inline_short_gaps_flag():
    text = _build_compress_text()
    query = "needle"
    marker = "Z" * 90

    default = compress_context(
        text,
        query,
        citations=False,
        ccr=False,
        gap_marker=lambda omitted, total: marker,
    )
    assert default is not None
    assert not default.fail_open
    assert marker in default.compressed_text
    assert "shortline1" not in default.compressed_text

    inlined = compress_context(
        text,
        query,
        citations=False,
        ccr=False,
        gap_marker=lambda omitted, total: marker,
        inline_short_gaps=True,
    )
    assert inlined is not None
    assert not inlined.fail_open
    assert "shortline1" in inlined.compressed_text
    assert len(inlined.compressed_text) <= len(text)


def test_inlining_gap_marker_passes_calls_through():
    calls: list[tuple[int, int]] = []

    def fn(omitted: int, total: int) -> str:
        calls.append((omitted, total))
        return "M"

    marker = InliningGapMarker(fn)
    assert marker.inline_short is True
    assert marker(3, 10) == "M"
    assert calls == [(3, 10)]


def test_compress_context_does_not_double_wrap_inlining_marker():
    text = _build_compress_text()
    marker = InliningGapMarker(lambda omitted, total: "Z" * 90)
    out = compress_context(
        text,
        "needle",
        citations=False,
        ccr=False,
        gap_marker=marker,
        inline_short_gaps=True,
    )
    assert out is not None
    assert not out.fail_open
    assert "shortline1" in out.compressed_text
