from tameru.compress_context import _anchor_regions, _state_change_lines, compress_context


def _filler_lines(count: int, start: int = 0) -> list[str]:
    return [
        f"2026-10-18 09:00:{start + i:02d} INFO sync: lag {i + 1}ms on shard s{i + 1}"
        for i in range(count)
    ]


def _event_log(event: str) -> str:
    lines = _filler_lines(45)
    lines.append(f"2026-10-18 09:00:45 {event}")
    lines.extend(_filler_lines(8, start=46))
    return "\n".join(lines)


def _run_compress(text: str):
    return compress_context(text, "", ccr=False, citations=False, anchor_errors=True)


def test_state_change_anchor_marked_degraded():
    event = "INFO sync: shard s7 marked degraded"
    text = _event_log(event)
    regions = _anchor_regions(text, 8)
    assert len(regions) == 1
    assert "marked degraded" in regions[0]

    r = _run_compress(text)
    assert not getattr(r, "fail_open", False)
    assert "marked degraded" in r.compressed_text
    assert len(r.compressed_text) < 0.3 * len(text)


def test_state_change_anchor_circuit_state_changed():
    event = "INFO breaker: circuit pricing-svc state changed CLOSED -> OPEN"
    text = _event_log(event)
    regions = _anchor_regions(text, 8)
    assert len(regions) == 1
    assert "state changed CLOSED -> OPEN" in regions[0]

    r = _run_compress(text)
    assert not getattr(r, "fail_open", False)
    assert "state changed CLOSED -> OPEN" in r.compressed_text
    assert len(r.compressed_text) < 0.3 * len(text)


def test_state_change_anchor_failover_promoting_leader():
    event = "NOTICE patroni: failover started, promoting pg-2 to leader"
    text = _event_log(event)
    regions = _anchor_regions(text, 8)
    assert len(regions) == 1
    assert "failover started" in regions[0]
    assert "promoting pg-2 to leader" in regions[0]

    r = _run_compress(text)
    assert not getattr(r, "fail_open", False)
    assert "failover started" in r.compressed_text
    assert len(r.compressed_text) < 0.3 * len(text)


def test_state_change_anchor_marked_down():
    event = "INFO cluster: node-12 marked down after 3 missed heartbeats"
    text = _event_log(event)
    regions = _anchor_regions(text, 8)
    assert len(regions) == 1
    assert "marked down" in regions[0]

    r = _run_compress(text)
    assert not getattr(r, "fail_open", False)
    assert "marked down" in r.compressed_text
    assert len(r.compressed_text) < 0.3 * len(text)


def test_state_change_anchor_circuit_closed_again_recovered():
    event = "INFO breaker: circuit auth-svc closed again (recovered)"
    text = _event_log(event)
    regions = _anchor_regions(text, 8)
    assert len(regions) == 1
    assert "closed again" in regions[0]

    r = _run_compress(text)
    assert not getattr(r, "fail_open", False)
    assert "closed again" in r.compressed_text
    assert len(r.compressed_text) < 0.3 * len(text)


def test_state_change_anchor_rejects_repeated_healthy_degraded_states():
    lines = []
    for i in range(40):
        state = "healthy" if i % 2 == 0 else "degraded"
        lines.append(f"2026-10-18 09:00:{i:02d} INFO health: svc-{i} state={state}")
    lines.append("2026-10-18 09:00:40 INFO health: summary 20/40 degraded")
    text = "\n".join(lines)
    assert _state_change_lines(text.split("\n"), 8) == ["2026-10-18 09:00:40 INFO health: summary 20/40 degraded"]
    assert not any("svc-" in line for line in _state_change_lines(text.split("\n"), 8))


def test_state_change_anchor_rejects_more_than_two_matches():
    lines = _filler_lines(45)
    lines.append("2026-10-18 09:00:45 INFO sync: shard s1 marked degraded")
    lines.append("2026-10-18 09:00:46 INFO sync: shard s2 marked degraded")
    lines.append("2026-10-18 09:00:47 INFO sync: shard s3 marked degraded")
    text = "\n".join(lines)
    assert _anchor_regions(text, 8) == []


def test_state_change_anchor_rejects_short_log():
    lines = _filler_lines(11)
    lines.append("2026-10-18 09:00:11 INFO cluster: node-12 marked down")
    text = "\n".join(lines)
    assert _anchor_regions(text, 8) == []


def test_state_change_anchor_rejects_filler_only():
    text = "\n".join(_filler_lines(25))
    assert _anchor_regions(text, 8) == []


def test_state_change_anchor_rejects_open_without_circuit():
    text = _event_log("INFO runtime: open file handles 120")
    assert _state_change_lines(text.split("\n"), 8) == []


def test_state_change_anchor_rejects_went_home():
    text = _event_log("INFO ops: node went home")
    assert _state_change_lines(text.split("\n"), 8) == []


def test_error_anchor_precedes_state_change_anchor():
    lines = _filler_lines(22)
    lines.append("2026-10-18 09:00:22 ERROR db: connection refused")
    lines.extend(_filler_lines(2, start=23))
    lines.append("2026-10-18 09:00:25 INFO cluster: node-12 marked down")
    text = "\n".join(lines)

    regions = _anchor_regions(text, 8)
    joined = "\n".join(regions)
    assert "connection refused" in joined
    assert "marked down" not in joined
