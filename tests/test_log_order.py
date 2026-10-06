"""N6 (v1.4.0): restored error lines keep their chronological position.

``preprocess_logs`` guarantees that error lines are never lost to its own
transforms (progress-bar deletion, frame-run collapse, repeat folding). The old
restore re-added EVERY original error line that was not literally present —
which included the 499 copies a ``[×500] ...`` exemplar already stands for —
and put them all right after the first line, out of order.
"""
from __future__ import annotations

import re

from tameru import compress_context as cc
from tameru.compress_context import compress_context, preprocess_logs

COUNT_PREFIX = re.compile(r"^\[×\d+\]\s+")


def _original_positions(original: list[str], processed: list[str]) -> list[int]:
    """Index in `original` of each non-synthetic processed line, in output order."""
    positions = []
    for line in processed:
        bare = COUNT_PREFIX.sub("", line)
        if bare.lstrip().startswith("... ") and "frames omitted" in bare:
            continue
        positions.append(original.index(bare))
    return positions


def test_collapsed_duplicates_are_not_re_added():
    lines = []
    for i in range(500):
        lines.append(f"2026-03-14 12:00:{i % 60:02d} ERROR [worker-{i}] upstream timeout after {i}ms")
        lines.append(f"2026-03-14 12:00:{i % 60:02d} INFO  heartbeat ok node={i}")
    out = preprocess_logs(lines)
    errors = [ln for ln in out if "ERROR" in ln]
    assert len(errors) == 1
    assert errors[0].startswith("[×500] ")
    assert len(out) == 2  # one error exemplar, one info exemplar


def test_progress_looking_error_lines_return_in_place():
    lines = [
        "INFO  start of run",
        "ERROR step 5/10 failed badly",  # deleted as a "progress bar", must come back
        "INFO  middle line number one",
        "[####----] 20%",
        "WARN  something odd: warning: low disk",
        "INFO  middle line number two",
        "ERROR upload 3/7 failed: connection reset",
        "INFO  end of run",
    ]
    out = preprocess_logs(lines)
    assert "[####----] 20%" not in out
    positions = _original_positions(lines, out)
    assert positions == sorted(positions), out
    # Not hoisted to the top: the first restored error follows the first line.
    assert out.index("ERROR step 5/10 failed badly") == 1
    assert out.index("ERROR upload 3/7 failed: connection reset") == len(out) - 2


def test_restored_lines_keep_order_among_collapsed_exemplars():
    lines = []
    for i in range(60):
        lines.append(f"2026-03-14 12:00:{i:02d} INFO  w1 request {i} served in {i}ms")
        if i in (7, 21, 44):
            lines.append(f"2026-03-14 12:00:{i:02d} ERROR batch {i}/60 failed: backend {i} down")
        if i in (30,):
            lines.append(f"2026-03-14 12:00:{i:02d} WARN  slow response: warning: p99 {i}ms")
    out = preprocess_logs(lines)
    positions = _original_positions(lines, out)
    assert positions == sorted(positions)
    # One restored exemplar for the whole "batch N/60 failed" template.
    assert sum("batch" in ln for ln in out) == 1
    assert sum("slow response" in ln for ln in out) == 1


def test_frame_run_error_line_is_restored_between_first_and_last_frame():
    lines = [
        "ERROR request crashed",
        "\tat org.app.Main.run(Main.java:10)",
        "\tat org.app.Service.call(Service.java:20)",
        "\tat org.app.ExceptionHandler.handle(Handler.java:88)",
        "\tat org.app.Dao.load(Dao.java:31)",
        "\tat org.app.Dao.query(Dao.java:77)",
        "\tat org.app.Main.main(Main.java:5)",
        "INFO  recovered",
    ]
    out = preprocess_logs(lines)
    assert any("frames omitted" in ln for ln in out)
    handler = out.index("\tat org.app.ExceptionHandler.handle(Handler.java:88)")
    first = out.index("\tat org.app.Main.run(Main.java:10)")
    last = out.index("\tat org.app.Main.main(Main.java:5)")
    assert first < handler < last


def test_preprocessing_is_idempotent_with_restored_lines():
    lines = [
        "INFO  start",
        "ERROR step 5/10 failed badly",
        "INFO  a long enough middle line to fingerprint properly",
        "ERROR step 6/10 failed badly",
        "INFO  end",
    ]
    once = preprocess_logs(lines)
    twice = preprocess_logs(once)
    assert once == twice


def test_end_to_end_output_keeps_original_line_order():
    """Through compress_context with a query that triggers log preprocessing."""
    lines = []
    for i in range(300):
        lines.append(f"2026-03-14 12:{i // 60:02d}:{i % 60:02d} INFO  w{i % 5} request req-{i:04d} served in {i}ms")
        if i % 97 == 40:
            lines.append(f"2026-03-14 12:{i // 60:02d}:{i % 60:02d} ERROR w{i % 5} step {i}/300 failed: dependency {i} unreachable")
    log = "\n".join(lines)
    result = compress_context(
        log, "what happened to request req-0150?", ccr=False, citations=False
    )
    assert not result.fail_open
    assert "req-0150" in result.compressed_text
    kept = [
        ln
        for ln in result.compressed_text.split("\n")
        if ln and not ln.startswith("[") and "frames omitted" not in ln
    ]
    positions = [lines.index(ln) for ln in kept]
    assert positions == sorted(positions)
    for fingerprint in cc.error_fingerprints(log):
        assert fingerprint in cc.error_fingerprints(result.compressed_text)
