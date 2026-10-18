"""Weak failure anchors: fallback anchors for the no-query error-anchored objective."""
from tameru.compress_context import (
    _anchor_regions,
    _is_weak_failure_line,
    compress_context,
)


def test_weak_failure_line_true():
    assert _is_weak_failure_line(
        "2026-10-18 07:01:00 WARN mailer: smtp connect to relay-2:587 refused, will retry"
    )
    assert _is_weak_failure_line('ts=t level=warn msg="probe timeout" target=db-7')
    assert _is_weak_failure_line(
        "Oct 18 07:31:00 host systemd[1]: Failed to start backup.service - Nightly backup."
    )
    assert _is_weak_failure_line("worker-1 exited with code 137")
    assert _is_weak_failure_line(
        '10.0.9.9 - - [18/Oct/2026:07:21:00 +0000] "POST /api/checkout HTTP/1.1" 502 157 "-" "Mozilla/5.0"'
    )


def test_weak_failure_line_false():
    assert not _is_weak_failure_line("WARN sched: clock skew 120ms detected")
    assert not _is_weak_failure_line("INFO job failed=0 ok")
    assert not _is_weak_failure_line("WARN retry succeeded after timeout")
    assert not _is_weak_failure_line("WARN 0 failed, 12 passed")
    assert not _is_weak_failure_line("worker-1 exited with code 0")
    assert not _is_weak_failure_line('10.0.1.2 - - [x] "GET /a HTTP/1.1" 200 512 "-" "curl"')
    assert not _is_weak_failure_line('10.0.1.2 - - [x] "GET /a HTTP/1.1" 200 503 "-" "curl"')
    assert not _is_weak_failure_line("INFO handled request in 502ms")
    assert not _is_weak_failure_line("WARN failover drill scheduled")


def _make_log(with_warn: bool) -> str:
    lines = [
        f"2026-10-18 07:00:{n:02d} INFO mailer: queued message {n}" for n in range(32)
    ]
    if with_warn:
        lines.append(
            "2026-10-18 07:00:32 WARN mailer: smtp connect to relay-2:587 refused, will retry"
        )
    lines += [
        f"2026-10-18 07:00:{n:02d} INFO mailer: queued message {n}" for n in range(33, 45)
    ]
    return "\n".join(lines)


def test_end_to_end_warn_anchor():
    text = _make_log(with_warn=True)
    r = compress_context(text, "", anchor_errors=True)
    assert not r.fail_open
    assert "relay-2:587 refused" in r.compressed_text
    assert len(r.compressed_text) < 0.6 * len(text)


def test_end_to_end_no_warn_no_regions():
    text = _make_log(with_warn=False)
    assert _anchor_regions(text, 8) == []


def test_strong_errors_ignore_weak():
    text = (
        "2026-10-18 07:00:00 INFO start\n"
        "2026-10-18 07:00:01 ERROR db down\n"
        "2026-10-18 07:00:02 WARN cache refused\n"
        "2026-10-18 07:00:03 INFO end\n"
    )
    regions = _anchor_regions(text, 8)
    assert regions
    for region in regions:
        assert "db down" in region
        assert "cache refused" not in region
