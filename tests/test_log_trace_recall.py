import re
from tameru.compress_context import compress_context


def _java_log() -> str:
    lines = []
    for i in range(80):
        lines.append(
            f"2026-10-18 11:{i // 60:02d}:{i % 60:02d}.123 INFO  "
            f"[http-nio-8080-exec-1] o.e.billing.Api - handled request id={1000 + i}"
        )
    lines.append(
        "2026-10-18 11:59:00.001 ERROR [http-nio-8080-exec-3] o.e.billing.Api - request failed"
    )
    lines.append(
        'java.lang.NullPointerException: Cannot invoke "String.length()" because "name" is null'
    )
    for i in range(25):
        lines.append(f"\tat org.example.billing.Step{i}.run(Step{i}.java:{100 + i})")
    lines.append("Caused by: java.io.IOException: stream closed")
    for i in range(6):
        lines.append(f"\tat org.example.io.Rd{i}.read(Rd{i}.java:{50 + i})")
    lines.append("\t... 12 more")
    return "\n".join(lines)


def _compress(text: str, query: str = ""):
    return compress_context(
        text,
        query,
        ccr=False,
        citations=False,
        inline_short_gaps=True,
        anchor_errors=True,
        prose_brief=True,
        min_savings_ratio=0.1,
    )


def test_log_trace_recall_does_not_fail_open_on_collapsed_frames():
    text = _java_log()
    result = _compress(text)
    compressed_text = result.compressed_text or ""

    assert not result.fail_open
    assert len(compressed_text) < 0.7 * len(text)
    assert "NullPointerException" in compressed_text
    assert "Caused by: java.io.IOException: stream closed" in compressed_text
    assert "request failed" in compressed_text


def test_log_trace_recall_with_error_anchored_query():
    text = _java_log()
    result = _compress(text, "why did the billing request fail")
    compressed_text = result.compressed_text or ""

    assert not result.fail_open
    assert len(compressed_text) < 0.7 * len(text)
    assert "NullPointerException" in compressed_text
    assert "Caused by: java.io.IOException: stream closed" in compressed_text
    assert "request failed" in compressed_text


def test_named_middle_frame_is_preserved_or_fails_open():
    text = _java_log()
    result = _compress(text, "what does org.example.billing.Step12.run do")
    compressed_text = result.compressed_text or ""

    assert "Step12" in compressed_text or result.fail_open




def _twenty_five_frames() -> list[str]:
    return [
        f"    at org.example.billing.Step{i}.run(Step{i}.java:{i})"
        for i in range(1, 26)
    ]


def test_preprocess_logs_keeps_named_middle_frame():
    from tameru.compress_context import preprocess_logs

    out = preprocess_logs(_twenty_five_frames(), "org.example.billing.Step12.run")

    assert any("Step12.run" in line for line in out)

    markers = [
        int(match.group(1))
        for match in re.finditer(r"  ... (\d+) frames omitted", "\n".join(out))
    ]
    assert len(markers) == 2

    kept_frames = sum(1 for line in out if "frames omitted" not in line)
    assert sum(markers) + kept_frames == 25


def test_preprocess_logs_empty_query_collapses_to_single_marker():
    from tameru.compress_context import preprocess_logs

    out = preprocess_logs(_twenty_five_frames(), "")

    assert len(out) == 7
    assert out[3] == "  ... 19 frames omitted"


def test_full_frame_query_collapses_to_single_marker() -> None:
    frames = _twenty_five_frames()
    text = "\n".join(
        [
            "2026-10-18 11:59:00.001 ERROR [http-nio-8080-exec-3] o.e.billing.Api - request failed",
            'java.lang.NullPointerException: Cannot invoke "String.length()" because "name" is null',
            *frames,
        ]
    )

    result = compress_context(text, query="\n".join(frames))
    compressed_text = result.compressed_text or ""

    markers = re.findall(r"  \.\.\. \d+ frames omitted", compressed_text)
    assert markers == ["  ... 19 frames omitted"]


from tameru.compress_context import (  # noqa: E402
    _ANCHOR_LOG_PREFIX_RE,
    _anchor_regions,
    _strip_anchor_prefix,
)


def test_anchor_regions_strips_log_prefix_keeps_level():
    log = (
        "2026-10-18 11:59:00.001 ERROR [http-nio-8080-exec-3] o.e.billing.Api - request failed\n"
        "java.lang.NullPointerException: boom\n"
        "\tat org.example.billing.Step1.run(Step1.java:10)\n"
        "\tat org.example.billing.Step2.run(Step2.java:11)\n"
        "\tat org.example.billing.Step3.run(Step3.java:12)\n"
    )
    regions = _anchor_regions(log, 8)
    assert regions, "expected at least one anchor region"
    first = regions[0]
    assert first.startswith("ERROR request failed")
    assert "http-nio-8080-exec-3" not in first


def test_anchor_errors_avoids_fail_open_on_logback_log():
    ts = "2026-10-18 11:59:00.001"
    info_lines = [
        f"{ts} INFO  [http-nio-8080-exec-1] o.e.billing.Api - handled request id={i}"
        for i in range(30)
    ]
    frames = [
        f"\tat org.example.billing.Step{i}.run(Step{i}.java:{10 + i})"
        for i in range(8)
    ]
    text = "\n".join(
        info_lines
        + [
            f"{ts} ERROR [http-nio-8080-exec-3] o.e.billing.Api - request failed",
            "java.lang.NullPointerException: boom",
        ]
        + frames
    )
    result = compress_context(
        text,
        query="",
        anchor_errors=True,
        prose_brief=True,
        inline_short_gaps=True,
        ccr=False,
        citations=False,
        min_savings_ratio=0.1,
    )
    assert not result.fail_open
    assert len(result.compressed_text) < 0.6 * len(text)
    assert "request failed" in result.compressed_text
    assert "NullPointerException" in result.compressed_text


def test_non_log_pytest_anchor_unchanged():
    line = "E       assert 1 == 2"
    assert _strip_anchor_prefix(line) == line
    assert not _ANCHOR_LOG_PREFIX_RE.match(line)


def test_strip_anchor_prefix_rewrites_jvm_line_numbers():
    from tameru.compress_context import _strip_anchor_prefix

    assert _strip_anchor_prefix("at org.example.billing.Step0.run(Step0.java:10)") == "at org.example.billing.Step0.run(Step0.java)"
    assert _strip_anchor_prefix('  File "/app/x.py", line 3, in f') == '  File "/app/x.py", line 3, in f'
    assert _strip_anchor_prefix("at Native Method") == "at Native Method"
