from tameru.compress_context import compress_context, _anchor_regions, _rare_template_lines


def _cron_text() -> str:
    lines = []
    for i in range(40):
        minute = i % 60
        ms = 300 + i
        lines.append(f"2026-10-18 10:{minute:02d}:00 INFO cron: job cleanup finished in {ms}ms")
    lines.append("2026-10-18 10:41:00 INFO cron: job export skipped (lock held by pid 4410)")
    for i in range(4):
        minute = 42 + i
        ms = 310 + i
        lines.append(f"2026-10-18 10:{minute:02d}:00 INFO cron: job cleanup finished in {ms}ms")
    return "\n".join(lines)


def test_rare_template_anchor_keeps_odd_cron_line():
    text = _cron_text()
    odd = "2026-10-18 10:41:00 INFO cron: job export skipped (lock held by pid 4410)"
    assert _rare_template_lines(text.splitlines(), 3) == [odd]

    result = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "lock held by pid 4410" in result.compressed_text
    assert not result.fail_open
    assert len(result.compressed_text) < len(text) / 3


def test_two_dominant_templates_with_one_odd_line():
    prefix = "2026-10-20 02:00:00 INFO backup: "
    lines = [prefix + f"snapshot vol-{i} completed in {i}s" for i in range(40)]
    lines += [prefix + f"snapshot vol-x{i} completed in {i}s" for i in range(6)]
    odd = prefix + "snapshot vol-db skipped, retention policy missing"
    lines.append(odd)
    assert _rare_template_lines(lines, 3) == [odd]


def test_uniform_log_has_no_rare_template():
    lines = [f"INFO service ok in {i}ms" for i in range(30)]
    assert _rare_template_lines(lines, 3) == []


def test_three_odd_lines_rejected():
    lines = [f"INFO service ok in {i}ms" for i in range(30)]
    lines += [
        "WARN alpha beta gamma",
        "WARN delta epsilon zeta",
        "WARN theta iota kappa",
    ]
    assert _rare_template_lines(lines, 3) == []


def test_too_few_lines_rejected():
    lines = [f"INFO service ok in {i}ms" for i in range(20)]
    assert _rare_template_lines(lines, 3) == []


def test_odd_line_without_new_word_rejected():
    lines = [f"INFO cron: job cleanup finished in {i}ms" for i in range(30)]
    lines.append("INFO cron: job cleanup finished")
    assert _rare_template_lines(lines, 3) == []


def test_error_tier_precedes_rare_template_tier():
    text = _cron_text() + "\n2026-10-18 10:42:00 ERROR db: connection refused"
    regions = _anchor_regions(text, 3)
    assert any("connection refused" in region for region in regions)
    assert not any("export skipped" in region for region in regions)


def test_rare_template_csv_table_not_leveled_log():
    lines = ["endpoint,p50_ms,p99_ms,errors"]
    lines.extend(f"/api/v1/r{i},{10 + i},{100 + i},0" for i in range(40))
    lines.append("/api/v1/checkout,35,9800,212")
    text = "\n".join(lines)

    assert _rare_template_lines(text.split("\n"), 8) == []
    assert _anchor_regions(text, 8) == []


def test_rare_template_logfmt_returns_unique_line():
    lines = [
        f'ts=2026-10-20T03:{i:02d}:00Z level=info msg="consumer heartbeat" queue=orders lag={i}'
        for i in range(40)
    ]
    lines.append(
        'ts=2026-10-20T03:41:00Z level=info msg="consumer rebalanced" queue=orders partitions_lost=7'
    )
    text = "\n".join(lines)

    assert _rare_template_lines(text.split("\n"), 8) == [
        'ts=2026-10-20T03:41:00Z level=info msg="consumer rebalanced" queue=orders partitions_lost=7'
    ]
