from tameru.compress_context import classify_line, route_content_type, compress_context


def test_classify_slash_date_log():
    assert classify_line("2026/10/21 13:00:00 [notice] 1#1: signal process started") == "log"


def test_route_slash_date_lines():
    lines = (
        ["2026/10/21 13:%02d:00 [notice] 1#1: signal process started" % i for i in range(30)]
        + [
            "2026/10/21 13:30:12 [crit] 22#22: *4411 connect() to unix:/run/php/php8.2-fpm.sock failed (2: No such file or directory) while connecting to upstream"
        ]
    )
    assert route_content_type(lines) == "log"


def test_compress_slash_date_lines():
    lines = (
        ["2026/10/21 13:%02d:00 [notice] 1#1: signal process started" % i for i in range(30)]
        + [
            "2026/10/21 13:30:12 [crit] 22#22: *4411 connect() to unix:/run/php/php8.2-fpm.sock failed (2: No such file or directory) while connecting to upstream"
        ]
    )
    r = compress_context("\n".join(lines) + "\n", "why does php return 502", ccr=False, citations=False)
    assert "php8.2-fpm.sock" in r.compressed_text
    assert "No such file or directory" in r.compressed_text
    assert len(r.compressed_text) < len("\n".join(lines)) * 0.5


def test_non_log_slash_words():
    assert classify_line("a/b/c 12:00 plain words") != "log"
