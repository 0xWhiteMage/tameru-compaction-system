from tameru.compress_context import classify_line, _strip_anchor_prefix, compress_context

W = "1:M 21 Oct 2026 12:20:05.000 # Can't save in background: fork: Cannot allocate memory"


def _log() -> str:
    return (
        "\n".join(
            f"1:M 21 Oct 2026 12:{i:02d}:00.000 * 100 changes in 300 seconds. Saving...\n"
            f"1:M 21 Oct 2026 12:{i:02d}:00.010 * Background saving started by pid {400 + i}"
            for i in range(20)
        )
        + "\n"
        + W
        + "\n"
    )


def _five_warn_log() -> str:
    return (
        "\n".join(
            f"1:M 21 Oct 2026 12:{i:02d}:00.000 * 100 changes in 300 seconds. Saving...\n"
            f"1:M 21 Oct 2026 12:{i:02d}:00.010 * Background saving started by pid {400 + i}"
            for i in range(10)
        )
        + "\n"
        + "\n".join(
            f"1:M 21 Oct 2026 12:30:{i:02d}.000 # Redis warning {i} distinct message"
            for i in range(5)
        )
        + "\n"
    )


def test_classify_redis_lines() -> None:
    assert classify_line(W) == "log"
    assert classify_line("1:M 21 Oct 2026 12:00:00.010 * Background saving started by pid 412") == "log"


def test_strip_anchor_prefix_redis_warning() -> None:
    assert _strip_anchor_prefix(W) == "WARNING Can't save in background: fork: Cannot allocate memory"


def test_compress_context_redis_warning_anchor() -> None:
    r = compress_context(_log(), "", ccr=False, citations=False, anchor_errors=True)
    assert "Cannot allocate memory" in r.compressed_text
    assert len(r.compressed_text) < 0.5 * len(_log())


def test_isolated_warn_lines_redis() -> None:
    from tameru.compress_context import _isolated_warn_lines

    assert _isolated_warn_lines(_log().split("\n"), 8) == [W]
    assert _isolated_warn_lines(_five_warn_log().split("\n"), 8) == []
