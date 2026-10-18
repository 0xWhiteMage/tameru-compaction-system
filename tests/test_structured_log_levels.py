import json

from tameru.compress_context import compress_context, error_fingerprints, _is_error_line, _strip_anchor_prefix


def test_strip_anchor_prefix_logfmt():
    assert _strip_anchor_prefix(
        'ts=2026-10-18T06:01:10Z level=error caller=queue.go:212 msg="job crashed" job_id=4471 err="redis: connection pool timeout"'
    ) == 'ERROR job crashed redis: connection pool timeout'


def test_strip_anchor_prefix_json():
    assert _strip_anchor_prefix(
        '{"time": "t", "level": "error", "msg": "payment webhook rejected", "status": 422, "reason": "signature mismatch"}'
    ) == 'ERROR payment webhook rejected signature mismatch 422'


def test_strip_anchor_prefix_plain_lines_unchanged():
    assert _strip_anchor_prefix('java.lang.NullPointerException: boom') == 'java.lang.NullPointerException: boom'
    assert _strip_anchor_prefix('a=1 b=2') == 'a=1 b=2'


def test_error_fingerprints_is_callable():
    assert callable(error_fingerprints)


def test_is_error_line_true_for_structured_levels():
    assert _is_error_line('ts=2026-10-18T06:01:10Z level=error msg="job crashed"')
    assert _is_error_line('{"time": "t", "level": "error", "msg": "x"}')
    assert _is_error_line('lvl=FATAL msg=boom')
    assert _is_error_line('{"severity":"CRITICAL"}')


def test_is_error_line_false_for_non_error_structured_levels():
    assert not _is_error_line('level=info msg="error budget ok"')
    assert not _is_error_line('msg="levelled up"')
    assert not _is_error_line('{"level": "warn"}')
    assert not _is_error_line('errorlevel=0')


def test_compress_context_keeps_logfmt_structured_error():
    lines = [
        f'ts=2026-10-18T06:00:{i % 60:02d}Z level=info caller=queue.go:{100 + i} msg="job done" job_id={1000 + i}'
        for i in range(70)
    ]
    lines.append(
        'ts=2026-10-18T06:01:10Z level=error caller=queue.go:212 msg="job crashed" job_id=4471 err="redis: connection pool timeout"'
    )
    lines.extend(
        f'ts=2026-10-18T06:01:{20 + i:02d}Z level=info caller=queue.go:{200 + i} msg="job done" job_id={5000 + i}'
        for i in range(15)
    )

    text = "\n".join(lines)
    result = compress_context(text, "", ccr=False, citations=False, inline_short_gaps=True, anchor_errors=True, prose_brief=True, min_savings_ratio=0.1)

    assert not result.fail_open
    assert "job crashed" in result.compressed_text
    assert "redis: connection pool timeout" in result.compressed_text
    assert len(result.compressed_text) < 0.5 * len(text)


def test_compress_context_keeps_json_structured_error():
    lines = [
        json.dumps(
            {
                "time": f"2026-10-18T06:00:{i % 60:02d}Z",
                "level": "info",
                "msg": "cache hit",
                "key": f"user:{i}",
            }
        )
        for i in range(60)
    ]
    lines.append(
        json.dumps(
            {
                "time": "2026-10-18T06:01:10Z",
                "level": "error",
                "msg": "payment webhook rejected",
                "key": "user:4471",
            }
        )
    )
    lines.extend(
        json.dumps(
            {
                "time": f"2026-10-18T06:01:{20 + i:02d}Z",
                "level": "info",
                "msg": "cache hit",
                "key": f"user:{1000 + i}",
            }
        )
        for i in range(15)
    )

    text = "\n".join(lines)
    result = compress_context(text, "", ccr=False, citations=False, inline_short_gaps=True, anchor_errors=True, prose_brief=True, min_savings_ratio=0.1)

    assert not result.fail_open
    assert "payment webhook rejected" in result.compressed_text
    assert len(result.compressed_text) < 0.5 * len(text)
