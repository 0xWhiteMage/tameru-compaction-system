from tameru.compress_context import compress_context


def test_negated_query_excludes_positive_boilerplate():
    text = (
        "\n".join(
            f"2026/10/21 12:{i:02d}:00 [notice] 1#1: signal process started"
            for i in range(18)
        )
        + "\n2026/10/21 12:30:00 [emerg] 1#1: bind() to 0.0.0.0:443 failed (98: Address already in use)\n"
    )
    out = compress_context(
        text,
        "why did nginx not start",
        ccr=False,
        citations=False,
        anchor_errors=True,
    ).compressed_text
    assert "Address already in use" in out
    assert "signal process started" not in out


def test_positive_query_still_matches_started():
    text2 = (
        "\n".join(
            f"2026-10-21 12:{i:02d}:00 INFO worker-{i} heartbeat ok"
            for i in range(30)
        )
        + "\n2026-10-21 12:40:00 INFO scheduler started job 7781\n"
    )
    out = compress_context(
        text2,
        "when did the scheduler start",
        ccr=False,
        citations=False,
    ).compressed_text
    assert "scheduler started job 7781" in out


def test_failure_lines_still_match_negated_verb():
    text3 = (
        "\n".join(
            f"2026-10-21 12:{i:02d}:00 INFO worker-{i} heartbeat ok"
            for i in range(30)
        )
        + "\n2026-10-21 12:40:00 ERROR Failed to start backup.service\n"
    )
    out = compress_context(
        text3,
        "why did backup not start",
        ccr=False,
        citations=False,
    ).compressed_text
    assert "Failed to start backup.service" in out
