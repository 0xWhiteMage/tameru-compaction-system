from tameru.compress_context import (
    _is_error_line,
    _strip_anchor_prefix,
    compress_context,
)

_CRIT_LINE = (
    "2026/10/21 13:30:12 [crit] 22#22: *4411 connect() to unix:/run/php/php8.2-fpm.sock "
    "failed (2: No such file or directory) while connecting to upstream"
)

_APACHE_LINE = (
    "[Wed Oct 21 10:25:13.441201 2026] [proxy:error] [pid 88:tid 140] "
    "(111)Connection refused: AH00957: http: attempt to connect to 127.0.0.1:9000 "
    "(backend) failed"
)


def test_bracket_error_levels_are_error_lines():
    assert _is_error_line(_CRIT_LINE)
    assert _is_error_line(_CRIT_LINE.replace("[crit]", "[error]"))
    assert _is_error_line(_CRIT_LINE.replace("[crit]", "[alert]"))
    assert _is_error_line(_CRIT_LINE.replace("[crit]", "[emerg]"))
    assert _is_error_line(_APACHE_LINE)


def test_notice_and_warn_are_not_error_lines():
    assert not _is_error_line("2026/10/21 13:00:00 [notice] 1#1: signal process started")
    assert not _is_error_line("2026/10/21 13:00:00 [warn] 1#1: signal process started")


def test_compress_context_keeps_bracket_crit_line():
    lines = [
        "2026/10/21 13:%02d:00 [notice] 1#1: signal process started" % i
        for i in range(30)
    ]
    lines.append(_CRIT_LINE)

    r = compress_context(
        "\n".join(lines) + "\n",
        "",
        ccr=False,
        citations=False,
        anchor_errors=True,
    )
    assert "php8.2-fpm.sock" in r.compressed_text
    assert len(r.compressed_text) < len("\n".join(lines) + "\n")


def test_strip_anchor_prefix_normalizes_nginx_and_apache():
    assert _strip_anchor_prefix(_CRIT_LINE).startswith("crit connect()")
    assert _strip_anchor_prefix(_APACHE_LINE).startswith("error (111)Connection refused")
