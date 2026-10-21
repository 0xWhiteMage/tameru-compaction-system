from tameru.compress_context import classify_line, route_content_type, compress_context


def test_logfmt_lines_classify_as_log():
    assert classify_line('ts=2026-10-20T03:00:00Z level=info msg="consumer heartbeat" queue=orders lag=12') == "log"
    assert classify_line('time=2026-10-21T05:00:00Z level=info component=scheduler msg="tick" queued=88') == "log"
    assert classify_line('level=warn msg="disk low" pct=93') == "log"


def test_non_logfmt_lines_not_log():
    assert classify_line("ts=1 x") != "log"
    assert classify_line("name=foo value=bar") != "log"
    assert classify_line("a=1 b=2 c=3") != "log"
    assert classify_line("x = foo(a=1, b=2, c=3)") != "log"
    assert classify_line("export A=1 B=2 C=3") != "log"


def test_route_and_compress_logfmt_heartbeat():
    heartbeat = 'ts=2026-10-20T03:00:00Z level=info msg="consumer heartbeat" queue=orders lag=12'
    text = "\n".join(
        [heartbeat] * 40
        + ['ts=2026-10-20T03:41:00Z level=info msg="consumer rebalanced" queue=orders partitions_lost=7']
    )
    assert route_content_type(text.split("\n")) == "log"
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "partitions_lost=7" in r.compressed_text
    assert not r.fail_open
    assert len(r.compressed_text) < len(text) / 4

def test_rare_logfmt_anchor_extras():
    from tameru.compress_context import _anchor_regions

    lines = [
        f'ts=2026-10-20T03:{i:02d}:00Z level=info msg="consumer heartbeat" queue=orders lag={i}'
        for i in range(40)
    ]
    lines.append('ts=2026-10-20T03:41:00Z level=info msg="consumer rebalanced" queue=orders partitions_lost=7')
    assert _anchor_regions("\n".join(lines), 8) == [
        "INFO consumer rebalanced partitions_lost=7"
    ]


def test_rare_json_anchor_extras():
    import json

    from tameru.compress_context import _anchor_regions

    lines = [
        json.dumps(
            {
                "ts": f"2026-10-21T06:{i:02d}:00Z",
                "level": "info",
                "event": "sync",
                "rows": i + 10,
            }
        )
        for i in range(45)
    ]
    lines.append(
        json.dumps(
            {
                "ts": "2026-10-21T06:46:00Z",
                "level": "info",
                "event": "sync",
                "rows": 0,
                "note": "upstream returned empty page 17",
            }
        )
    )
    regions = _anchor_regions("\n".join(lines), 8)
    assert len(regions) == 1
    assert "note=upstream returned empty page 17" in regions[0]
    assert "rows=" not in regions[0]


def test_error_anchor_prefix_unchanged():
    from tameru.compress_context import _strip_anchor_prefix

    assert (
        _strip_anchor_prefix(
            'ts=2026-10-18T06:01:10Z level=error caller=queue.go:212 msg="job crashed" job_id=4471 err="redis: connection pool timeout"'
        )
        == "ERROR job crashed redis: connection pool timeout"
    )

def test_rare_scheduler_leader_lost_anchor_extras():
    from tameru.compress_context import _anchor_regions

    lines = [
        f'time=2026-10-21T05:{i:02d}:00Z level=info component=scheduler msg="tick" queued={i}'
        for i in range(42)
    ]
    lines.append('time=2026-10-21T05:43:00Z level=info component=scheduler msg="leader lost" term=88')
    lines.extend(
        f'time=2026-10-21T05:{i:02d}:00Z level=info component=scheduler msg="tick" queued={i}'
        for i in range(43, 47)
    )
    assert _anchor_regions("\n".join(lines), 8) == ["INFO leader lost term=88"]


def test_iso_struct_regexes_match_quoted_json_levels():
    from tameru.compress_context import _ISO_STRUCT_LEVEL_RE, _ISO_STRUCT_WARN_RE

    assert _ISO_STRUCT_LEVEL_RE.search('{"level": "info", "msg": "x"}')
    assert _ISO_STRUCT_WARN_RE.search('{"level": "warn"}')
    assert not _ISO_STRUCT_WARN_RE.search('{"level": "info"}')
