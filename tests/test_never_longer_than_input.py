from tameru.compress_context import compress_context


def test_never_longer_than_input_small_systemd_gap():
    text = (
        "● worker.service - Queue worker\n"
        "     Loaded: loaded (/etc/systemd/system/worker.service; enabled; preset: enabled)\n"
        "     Active: failed (Result: exit-code) since Wed 2026-10-21 14:02:11 KST; 3min ago\n"
        "    Process: 9921 ExecStart=/usr/bin/worker --queue jobs (code=exited, status=78/CONFIG)\n"
        "   Main PID: 9921 (code=exited, status=78/CONFIG)\n"
        "\n"
        + "\n".join(
            f"Oct 21 14:0{i}:0{i} host worker[9921]: loaded plugin p{i}"
            for i in range(9)
        )
        + "\n"
        "Oct 21 14:02:11 host worker[9921]: config: missing required key queue.url\n"
        "Oct 21 14:02:11 host systemd[1]: worker.service: Failed with result 'exit-code'.\n"
    )

    for query in ("why did the worker fail", ""):
        r = compress_context(
            text,
            query,
            ccr=False,
            citations=False,
            inline_short_gaps=True,
            min_savings_ratio=0.1,
            anchor_errors=True,
            prose_brief=True,
        )
        assert len(r.compressed_text) <= len(text)
        assert "status=78/CONFIG" in r.compressed_text
        assert "missing required key queue.url" in r.compressed_text


def test_large_repetitive_log_still_compresses():
    lines = [
        f"2026-10-21 10:00:{i % 60:02d} INFO worker heartbeat ok seq={i}"
        for i in range(300)
    ]
    lines.append("2026-10-21 10:05:00 ERROR worker crashed: disk full")
    text = "\n".join(lines)

    r = compress_context(
        text,
        "",
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        min_savings_ratio=0.1,
        anchor_errors=True,
        prose_brief=True,
    )
    assert len(r.compressed_text) < len(text) * 0.5
    assert "disk full" in r.compressed_text
