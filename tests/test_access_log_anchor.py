import random

from tameru.compress_context import _strip_anchor_prefix, compress_context


def test_access_log_anchor_combined_log_with_query():
    line = (
        '10.0.9.9 - - [18/Oct/2026:07:21:00 +0000] '
        '"POST /api/checkout?x=1 HTTP/1.1" 502 157 "-" "Mozilla/5.0"'
    )
    assert _strip_anchor_prefix(line) == "POST /api/checkout 502"


def test_access_log_anchor_common_log_with_ident_user():
    line = (
        '127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] '
        '"GET /apache_pb.gif HTTP/1.0" 503 2326'
    )
    assert _strip_anchor_prefix(line) == "GET /apache_pb.gif 503"


def test_access_log_anchor_unchanged_lines():
    assert _strip_anchor_prefix('"GET /a 200"') == '"GET /a 200"'
    assert (
        _strip_anchor_prefix('2026-10-18 06:21:00 ERROR api: boom')
        == 'ERROR boom'
    )
    assert _strip_anchor_prefix('just text') == 'just text'


def test_access_log_anchor_end_to_end():
    rng = random.Random(5)
    lines = []

    for i in range(60):
        r = rng.randint(10, 999)
        lines.append(
            f'10.0.{i}.{r} - - [18/Oct/2026:07:20:{i % 60:02d} +0000] '
            f'"GET /api/items/{r} HTTP/1.1" 200 {r} "-" "curl/8.4"'
        )

    lines.append(
        '10.0.9.9 - - [18/Oct/2026:07:21:00 +0000] '
        '"POST /api/checkout HTTP/1.1" 502 157 "-" "Mozilla/5.0"'
    )

    for _ in range(8):
        r = rng.randint(10, 999)
        lines.append(
            f'10.0.9.{r} - - [18/Oct/2026:07:21:01 +0000] '
            f'"GET /api/items/{r} HTTP/1.1" 200 {r} "-" "curl/8.4"'
        )

    text = "\n".join(lines)
    result = compress_context(text, "", anchor_errors=True)

    assert not result.fail_open
    assert "/api/checkout" in result.compressed_text
    assert "502" in result.compressed_text
    assert len(result.compressed_text) < 0.5 * len(text)
