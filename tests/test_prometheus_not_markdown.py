from tameru.compress_context import compress_context


def test_prometheus_not_markdown():
    text = "".join(
        f"# HELP http_requests_total_{i} Total requests.\n"
        f"# TYPE http_requests_total_{i} counter\n"
        f"http_requests_total_{i}{{code=\"200\"}} {100 + i}\n"
        for i in range(30)
    ) + (
        "# HELP db_pool_exhausted_total Pool exhaustion events.\n"
        "# TYPE db_pool_exhausted_total counter\n"
        "db_pool_exhausted_total 412\n"
    )
    out = compress_context(text, "db pool exhausted count", ccr=False, citations=False).compressed_text
    assert "db_pool_exhausted_total 412" in out


def test_markdown_still_markdown():
    md = (
        "# Intro\n"
        "Some intro text here.\n\n"
        + "".join(
            f"# Section {i}\n"
            f"Filler paragraph number {i} about nothing in particular.\n\n"
            for i in range(12)
        )
        + "# Pool settings\n"
        "The pool is exhausted above 50 connections.\n"
    )
    out_md = compress_context(md, "pool exhausted", ccr=False, citations=False).compressed_text
    assert "The pool is exhausted above 50 connections." in out_md
    assert len(out_md) < len(md)
