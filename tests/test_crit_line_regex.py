"""E1: the critical-line regex is module-level, case-insensitive, and a bare
leading timestamp does not make a line critical.

History: ``score_blocks`` compiled ``_CRIT_LINE_RE`` per call and invoked
``.search(line, re.IGNORECASE)``. ``re.IGNORECASE`` is the int 2, so the flag
was passed as ``pos``: matching stayed case-sensitive and skipped the first two
characters of every line. Fixing only that would make the date alternative
match the leading timestamp of every log line, so the fix also scopes dates.
"""
from __future__ import annotations

import re

import pytest

from tameru import compress_context as cc


def test_regex_is_module_level_and_case_insensitive():
    assert isinstance(cc._CRIT_LINE_RE, re.Pattern)
    assert cc._CRIT_LINE_RE.flags & re.IGNORECASE


@pytest.mark.parametrize(
    "line",
    [
        "ERROR boom",
        "Error: boom",
        "error: boom",
        "FATAL: out of memory",
        "Traceback (most recent call last):",
        "Exception in thread main",
        "CRITICAL disk full",
    ],
)
def test_error_keywords_match_from_column_zero_in_any_case(line):
    m = cc._CRIT_LINE_RE.search(line)
    assert m is not None
    assert m.start() == 0  # not "pos=2"
    assert cc._is_critical_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "2026-03-14 12:00:03.123 INFO  [worker-3] heartbeat ok",
        "2026-03-14T12:00:03Z INFO started",
        "[2026-03-14 12:00:03] INFO started",
        "  2026-03-14 12:00:03 INFO indented",
        "(2026-03-14) INFO started",
    ],
)
def test_the_regex_object_itself_ignores_a_line_leading_date(line):
    assert cc._CRIT_LINE_RE.search(line) is None


@pytest.mark.parametrize(
    "line",
    [
        "deployed on 2026-03-14 to production",
        "started=2026-03-14",
        "INFO 2026-03-14 rollout begins",
    ],
)
def test_the_regex_object_still_counts_a_date_that_is_not_first(line):
    assert cc._CRIT_LINE_RE.search(line) is not None


def test_old_call_shape_could_not_see_leading_uppercase_errors():
    # Documents the bug: flags passed as `pos` skip two characters and, with no
    # IGNORECASE flag compiled in, never match "ERROR".
    legacy = re.compile(r"\b(?:error|exception|traceback|fatal|critical)\b")
    assert legacy.search("ERROR boom", re.IGNORECASE) is None
    assert cc._CRIT_LINE_RE.search("ERROR boom") is not None


@pytest.mark.parametrize(
    "line",
    [
        "2026-03-14 12:00:03.123 INFO  [worker-3] heartbeat ok",
        "2026-03-14T12:00:03Z INFO started",
        "2026-03-14T12:00:03+02:00 INFO started",
        "[2026-03-14 12:00:03] INFO started",
        "12:00:03.123 INFO started",
        "[12:00:03] INFO started",
        "Mar 14 12:00:03 host sshd[311]: session opened",
        "2026-03-14 deployed to production",
    ],
)
def test_bare_leading_timestamp_is_not_critical(line):
    assert not cc._is_critical_line(line)


@pytest.mark.parametrize(
    "line",
    [
        "2026-03-14 12:00:03.123 ERROR [worker-3] upstream timeout",
        "[2026-03-14 12:00:03] FATAL cannot bind",
        "release shipped on 2026-03-14 to production",  # a date that is not the first token
        "2026-03-14 12:00:03 INFO build version 1.4.0 ready",
        "2026-03-14 12:00:03 INFO host=db-prod-01 port=5432",
    ],
)
def test_facts_after_a_timestamp_are_still_critical(line):
    assert cc._is_critical_line(line)


def test_chat_role_label_is_not_a_user_key_value():
    # IGNORECASE made "User:" match `user\s*[:=]`; a speaker tag is not a fact.
    assert not cc._is_critical_line("User: What is the database host?")
    assert not cc._is_critical_line("Tool: The database host is db.internal.corp.")
    assert cc._is_critical_line("User: connection failed: error 500")
    assert cc._is_critical_line("user=alice")


def test_verifier_does_not_count_every_timestamped_line_as_critical():
    info = [
        f"2026-03-14 12:00:{i % 60:02d}.123 INFO  [worker-{i % 7}] heartbeat ok"
        for i in range(200)
    ]
    errors = [
        "2026-03-14 12:01:00.001 ERROR [worker-1] upstream timeout calling payments",
        "2026-03-14 12:02:00.002 ERROR [worker-2] db pool exhausted",
    ]
    text = "\n".join(info[:100] + errors[:1] + info[100:] + errors[1:])
    critical = cc._extract_critical_lines(text)
    # Before: 202 (every timestamp satisfied the time/date rules). Now: errors only.
    assert len(critical) == 2
    assert all("ERROR" in line for line in critical)


def test_error_loss_is_visible_to_the_verifier():
    info = [f"2026-03-14 12:00:{i % 60:02d} INFO  [w] heartbeat ok" for i in range(150)]
    original = "\n".join(
        info[:75] + ["2026-03-14 12:01:00 ERROR [w] upstream timeout"] + info[75:]
    )
    without_error = "\n".join(info)
    kept, total = cc._critical_line_recall(original, without_error)
    assert total == 1 and kept == 0  # the lone error is the whole critical set
    kept, total = cc._critical_line_recall(original, original)
    assert (kept, total) == (1, 1)
    verdict = cc.verify_compression(original, without_error, "why did it fail")
    assert verdict["critical_lines_dropped"] == 1
    assert verdict["risk"] == "high"


def test_scoring_boosts_uppercase_error_blocks_but_not_plain_timestamps():
    blocks = []
    for i in range(10):
        text = f"2026-03-14 12:00:{i:02d} INFO  [w] heartbeat ok"
        if i == 4:
            text = "2026-03-14 12:00:04 ERROR [w] upstream timeout"
        blocks.append(
            {"id": i, "start": i, "end": i, "type": "log", "text": text, "tokens": 8}
        )
    scored = cc.score_blocks(blocks, "unrelated question about widgets")
    by_id = {b["id"]: b for b in scored}
    assert by_id[4]["reason"] in {"critical lines", "log error"}
    # A plain timestamped INFO line is not boosted as a "critical line".
    assert by_id[2]["reason"] != "critical lines"
