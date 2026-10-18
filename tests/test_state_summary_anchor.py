try:
    from tameru.compress_context import compress_context, _anchor_regions, _state_summary_lines
except ImportError:
    from src.tameru.compress_context import compress_context, _anchor_regions, _state_summary_lines


def _dashboard_lines() -> list[str]:
    lines = [
        f"2026-10-18 09:20:{i:02d} INFO health: svc-{i} state={'healthy' if i % 2 else 'degraded'}"
        for i in range(40)
    ]
    lines.append("2026-10-18 09:21:00 INFO health: summary 20/40 degraded")
    return lines


def _pad_to_twenty(lines: list[str]) -> list[str]:
    padded = list(lines)
    i = 0
    while len(padded) < 20:
        padded.append(f"2026-10-18 09:20:{i:02d} INFO health: svc-pad-{i} state=healthy")
        i += 1
    return padded


def test_dashboard_summary_anchor_is_kept() -> None:
    text = "\n".join(_dashboard_lines())
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)

    assert "20/40 degraded" in r.compressed_text
    assert len(r.compressed_text) < len(text)


def test_dashboard_summary_anchor_region_is_summary_line() -> None:
    text = "\n".join(_dashboard_lines())

    assert _anchor_regions(text, 8) == ["summary 20/40 degraded"]


def test_dashboard_summary_anchor_caps_affected_rows() -> None:
    text = "\n".join(_dashboard_lines())
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)

    degraded_rows = [ln for ln in r.compressed_text.split("\n") if "state=degraded" in ln]
    assert 1 <= len(degraded_rows) <= 5
    assert len(degraded_rows) < 20 // 2


def test_of_phrase_summary_matches() -> None:
    line = "2026-10-18 09:21:00 INFO health: summary 3 of 12 nodes are unhealthy"
    lines = _pad_to_twenty([line])

    assert _state_summary_lines(lines, 2) == [line]


def test_zero_numerator_summary_does_not_match() -> None:
    line = "2026-10-18 09:21:00 INFO health: summary 0/40 degraded"
    lines = _pad_to_twenty([line])

    assert _state_summary_lines(lines, 2) == []


def test_non_incident_fraction_does_not_match() -> None:
    line = "2026-10-18 09:21:00 INFO health: page 2/40 loaded"
    lines = _pad_to_twenty([line])

    assert _state_summary_lines(lines, 2) == []


def test_short_log_does_not_match() -> None:
    lines = [f"2026-10-18 09:20:{i:02d} INFO health: svc-{i} state=healthy" for i in range(9)]
    lines.append("2026-10-18 09:21:00 INFO health: summary 20/40 degraded")

    assert len([line for line in lines if line.strip()]) == 10
    assert _state_summary_lines(lines, 2) == []


def test_three_summary_lines_do_not_match() -> None:
    lines = _pad_to_twenty(
        [
            "2026-10-18 09:21:00 INFO health: summary 20/40 degraded",
            "2026-10-18 09:21:01 INFO health: summary 21/40 degraded",
            "2026-10-18 09:21:02 INFO health: summary 22/40 degraded",
        ]
    )

    assert _state_summary_lines(lines, 2) == []


def test_error_anchor_takes_precedence_over_summary() -> None:
    lines = [
        "2026-10-18 09:20:00 ERROR health: svc-0 state=degraded",
        "2026-10-18 09:21:00 INFO health: summary 20/40 degraded",
    ]
    lines = _pad_to_twenty(lines)
    text = "\n".join(lines)

    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)

    assert "ERROR" in r.compressed_text
    assert not any("summary" in region for region in _anchor_regions(text, 8))
