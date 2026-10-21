from tameru.compress_context import (
    _anchor_regions,
    _is_weak_failure_line,
    _strip_anchor_prefix,
    compress_context,
)


def _php_error_log() -> str:
    notice = (
        "[17-Oct-2026 10:00:00 UTC] PHP Notice:  Undefined index: utm_1 "
        "in /var/www/html/track.php on line 1"
    )
    lines = [notice] * 90
    lines.extend(
        [
            "[17-Oct-2026 11:00:00 UTC] PHP Fatal error:  Uncaught Error: "
            "Call to a member function fetch() on bool in /var/www/html/src/Repo/UserRepo.php:58",
            "Stack trace:",
            "#0 /var/www/html/src/Controller/Login.php(31): App\\Repo\\UserRepo->byEmail('a@b.c')",
            "#1 /var/www/html/public/index.php(22): App\\Controller\\Login->post()",
            "#2 {main}",
            "  thrown in /var/www/html/src/Repo/UserRepo.php on line 58",
        ]
    )
    return "\n".join(lines)


def test_strip_anchor_prefix_php_error_log() -> None:
    assert (
        _strip_anchor_prefix(
            "[17-Oct-2026 11:00:00 UTC] PHP Fatal error:  Uncaught Error: boom in /a/B.php:58"
        )
        == "Fatal error:  Uncaught Error: boom in /a/B.php:58"
    )
    assert (
        _strip_anchor_prefix("PHP Parse error:  syntax error in /a.php on line 9")
        == "Parse error:  syntax error in /a.php on line 9"
    )


def test_php_error_log_anchor_regions_and_compression() -> None:
    text = _php_error_log()
    regions = _anchor_regions(text, 8)
    assert len(regions) == 1
    region = regions[0]
    assert "Uncaught Error" in region
    assert "#0 " in region
    assert "{main}" in region

    compressed = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    out = compressed.compressed_text
    assert "Call to a member function fetch() on bool" in out
    assert "UserRepo.php:58" in out
    assert "Login.php(31)" in out
    assert len(out) < 0.25 * len(text)


def test_is_weak_failure_line_php_warning_and_notice() -> None:
    assert (
        _is_weak_failure_line(
            "[17-Oct-2026 11:00:00 UTC] PHP Warning:  Undefined variable $x in /a.php on line 3"
        )
        is True
    )
    assert (
        _is_weak_failure_line(
            "[17-Oct-2026 10:00:00 UTC] PHP Notice:  Undefined index: utm_1 in /a.php on line 1"
        )
        is False
    )
