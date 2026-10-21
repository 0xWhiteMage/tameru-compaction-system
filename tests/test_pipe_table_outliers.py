from tameru.format_adapters import detect_format, adapt_format
from tameru.compress_context import compress_context


def _make_table(rows):
    lines = [
        "| host | region | p99_ms | status |",
        "|---|---|---|---|",
    ]
    lines.extend(rows)
    return "\n".join(lines)


def _ok_rows(count=30):
    return [
        f"| api-{i} | ap-northeast-2 | {20 + i} | ok |"
        for i in range(count)
    ]


def test_pipe_table_no_query_keeps_outlier():
    rows = _ok_rows(30)
    rows.append("| api-77 | ap-northeast-2 | 4100 | degraded |")
    text = _make_table(rows)

    assert detect_format(text) == "markdown_table"

    result = adapt_format(text, "")
    assert result.applied is True
    assert "api-77" in result.text
    assert "4100" in result.text
    assert "| host | region | p99_ms | status |" in result.text
    assert "|---|---|---|---|" in result.text
    assert "rows omitted" in result.text

    empty = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert not empty.fail_open
    assert "api-77" in empty.compressed_text
    assert "4100" in empty.compressed_text
    assert len(empty.compressed_text) < 0.3 * len(text)

    weak = compress_context(
        text,
        "which host is degraded",
        ccr=False,
        citations=False,
        anchor_errors=True,
    )
    assert not weak.fail_open
    assert "api-77" in weak.compressed_text
    assert "4100" in weak.compressed_text
    assert len(weak.compressed_text) < 0.3 * len(text)


def test_small_or_non_table_inputs_decline():
    doc = (
        "# Title\n"
        "\n"
        "| a | b |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "| 3 | 4 |\n"
    )
    assert detect_format(doc) == "markdown"

    small_rows = _ok_rows(10)
    small_text = _make_table(small_rows)
    assert adapt_format(small_text, "").applied is False

    half_rows = []
    for i in range(10):
        half_rows.append(f"| api-{i} | ap-northeast-2 | {20 + i} | ok |")
    for i in range(10):
        half_rows.append(f"| api-{100 + i} | ap-northeast-2 | {4100 + i} | degraded |")
    half_text = _make_table(half_rows)
    assert adapt_format(half_text, "").applied is False


def test_distinctive_query_declines():
    rows = _ok_rows(30)
    rows.append("| api-77 | ap-northeast-2 | 4100 | degraded |")
    text = _make_table(rows)

    result = adapt_format(text, "api-7")
    assert result.applied is False
