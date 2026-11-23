from tameru.compress_context import _strip_anchor_prefix, compress_context


def test_overnested_warn_anchor_fails_open():
    warn = (
        '{"level":"WARN","message":"capacity notice","detail":'
        + "[" * 10_000 + "0" + "]" * 10_000 + "}"
    )
    text = "INFO background sync complete\n" * 30 + warn

    result = compress_context(text, "", anchor_errors=True, ccr=False)

    assert result.compressed_text == text


def test_overnested_anchor_preserves_java_line_number():
    line = (
        '{"level":"WARN","message":"capacity notice (Worker.java:12)","detail":'
        + "[" * 10_000 + "0" + "]" * 10_000 + "}"
    )
    text = "INFO background sync complete\n" * 30 + line

    assert _strip_anchor_prefix(line) == line
    result = compress_context(text, "", anchor_errors=True, ccr=False)

    assert result.compressed_text == text
    assert "(Worker.java:12)" in result.compressed_text
