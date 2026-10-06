"""E3: a log keeps one exemplar of every level-tagged error fingerprint.

Before 1.4.0 a 650 KB INFO/ERROR log compressed under "why are requests
failing?" lost every ERROR line (0 of 61 kept): the stale-error penalty capped
error blocks below the adaptive floor, `_important()` skipped them, and the
floor-saturated path reduced the keep-set to `_important` alone. "continue"
cut 98.6% of the log and kept none either.
"""
from __future__ import annotations

import random

import pytest

from tameru import compress_context as cc
from tameru.compress_context import compress_context, error_fingerprints

ERROR_TEMPLATES = [
    "ERROR w{w} upstream timeout calling payments-svc after {n}ms req={h}",
    "ERROR w{w} db pool exhausted: 0 of {n} connections (pool=orders)",
    "ERROR w{w} failed to decode /api/v2/inventory/{h}: unexpected EOF",
    "ERROR w{w} circuit breaker OPEN for auth-svc after {n} failures",
    "ERROR w{w} TLS handshake with 10.0.{m}.7:443 failed: certificate expired",
]
INFO_TEMPLATES = [
    "INFO  w{w} GET /api/v1/users/{h}/profile 200 {n}ms",
    "INFO  w{w} POST /api/v1/orders/{h} 201 {n}ms",
    "INFO  w{w} cache hit key=session:{h} ttl={n}s",
    "INFO  w{w} job sync-{n} done path=/var/jobs/{h}.json",
    "INFO  w{w} heartbeat ok node-{m} up={n}s",
    "INFO  w{w} loaded /etc/app/conf.d/{h}.yaml",
]


def make_log(n_lines: int = 9000, seed: int = 11, error_rate: float = 0.01) -> str:
    """~1% ERROR (five distinct templates), the rest INFO with random ids/paths."""
    rng = random.Random(seed)
    out = []
    for i in range(n_lines):
        ts = f"2026-03-14 {12 + i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}"
        fields = dict(
            w=rng.randint(1, 16),
            h="%08x" % rng.getrandbits(32),
            n=rng.randint(1, 50000),
            m=rng.randint(1, 250),
        )
        pool = ERROR_TEMPLATES if rng.random() < error_rate else INFO_TEMPLATES
        out.append(ts + " " + rng.choice(pool).format(**fields))
    return "\n".join(out)


@pytest.fixture(scope="module")
def big_log() -> str:
    return make_log()


@pytest.fixture(scope="module")
def level_fingerprints(big_log) -> dict[str, str]:
    return error_fingerprints(big_log)


def test_fixture_is_the_650kb_9000_line_log(big_log, level_fingerprints):
    lines = big_log.split("\n")
    errors = [ln for ln in lines if " ERROR " in ln]
    assert len(lines) == 9000
    assert 600_000 < len(big_log) < 700_000
    assert 0.005 < len(errors) / len(lines) < 0.02
    assert len(level_fingerprints) == len(ERROR_TEMPLATES)


@pytest.mark.parametrize("query", ["why are requests failing?", "continue"])
def test_every_error_fingerprint_survives_and_output_is_smaller(
    big_log, level_fingerprints, query
):
    result = compress_context(big_log, query, ccr=False, citations=False)
    if result.fail_open:
        # Fail-open returns the caller's bytes: nothing was lost.
        assert result.compressed_text == big_log
        return
    kept = error_fingerprints(result.compressed_text)
    missing = set(level_fingerprints) - set(kept)
    assert not missing, f"error fingerprints lost: {sorted(missing)}"
    assert len(result.compressed_text) < len(big_log)


def test_a_real_question_compresses_the_log_and_keeps_every_error(
    big_log, level_fingerprints
):
    result = compress_context(
        big_log, "why are requests failing?", ccr=False, citations=False
    )
    assert not result.fail_open
    assert len(result.compressed_text) < 0.9 * len(big_log)
    assert set(level_fingerprints) <= set(error_fingerprints(result.compressed_text))
    assert result.receipt["log_error_fingerprints"] == {
        "total": len(level_fingerprints),
        "kept": len(level_fingerprints),
    }
    assert "error exemplar" in result.reasons


def test_kept_exemplars_are_verbatim_original_lines(big_log, level_fingerprints):
    result = compress_context(
        big_log, "why are requests failing?", ccr=False, citations=False
    )
    original = set(big_log.split("\n"))
    for fingerprint, exemplar in error_fingerprints(result.compressed_text).items():
        assert exemplar in original, fingerprint


def test_error_retention_holds_with_a_distinctive_query(big_log, level_fingerprints):
    # A query naming an id takes the needle path (and preprocess_logs collapse).
    needle = next(
        ln.split("key=session:")[1].split()[0]
        for ln in big_log.split("\n")
        if "key=session:" in ln
    )
    result = compress_context(
        big_log, f"what happened with session {needle}?", ccr=False, citations=False
    )
    assert not result.fail_open
    assert needle in result.compressed_text
    assert set(level_fingerprints) <= set(error_fingerprints(result.compressed_text))


def test_fixed_budget_mode_keeps_error_exemplars(big_log, level_fingerprints):
    result = compress_context(
        big_log,
        "why are requests failing?",
        mode="fixed",
        budget_ratio=0.05,
        ccr=False,
        citations=False,
    )
    assert set(level_fingerprints) <= set(error_fingerprints(result.compressed_text)) or (
        result.fail_open and result.compressed_text == big_log
    )


def test_exemption_is_for_level_tagged_lines_not_traceback_frames():
    """OldErrorPurgeTests (v0.7) still holds: an old traceback with no query
    hit is purged; a level-tagged log error in the same document survives."""
    filler = "\n\n".join(
        f"2026-03-14 12:00:{i:02d} INFO  w1 routine status record {i}" for i in range(14)
    )
    error_dump = (
        "Traceback (most recent call last):\n"
        '  File "/app/service.py", line 88, in handler\n'
        "ConnectionError: upstream timeout after 30s\n"
        + "\n".join(f"  frame {j}: stack detail line {j}" for j in range(20))
    )
    ctx = (
        "2026-03-14 11:59:59 ERROR w1 payment gateway unreachable\n\n"
        + error_dump
        + "\n\n"
        + filler
        + "\n\nThe fix landed in commit abc123def."
    )
    result = compress_context(ctx, "what fixed the issue?", ccr=False, citations=False)
    assert "stack detail line 5" not in result.compressed_text
    assert "abc123def" in result.compressed_text
    assert "ERROR w1 payment gateway unreachable" in result.compressed_text


def test_non_log_content_is_not_affected():
    """Exemplar logic applies to content routed as a log only."""
    paragraphs = [
        f"Section {i}: the quarterly review covers topic {i} in detail." for i in range(40)
    ]
    paragraphs[3] = "Section 3: ERROR is the name of the sentinel enum value."
    doc = "\n\n".join(paragraphs)
    blocks = cc.segment_blocks(doc.split("\n"))
    scored = cc.score_blocks(blocks, "which topics are in review 31?", content_type="text")
    assert not any(b["error_exemplar"] for b in scored)
    scored_log = cc.score_blocks(blocks, "which topics are in review 31?", content_type="log")
    assert sum(1 for b in scored_log if b["error_exemplar"]) == 1


def test_selectors_force_exemplars_even_when_everything_else_is_dropped():
    def block(i, text, exemplar=False):
        return {
            "id": i,
            "start": i,
            "end": i,
            "type": "log",
            "text": text,
            "tokens": 8,
            "score": 0.0,
            "reason": "error exemplar" if exemplar else "context",
            "entity_hits": 0,
            "term_hits": 0,
            "rare_term_hits": 0,
            "trust_risk": False,
            "error_exemplar": exemplar,
        }

    blocks = [block(i, f"INFO w1 tick {i}") for i in range(80)]
    blocks[40] = block(40, "ERROR w1 disk full", exemplar=True)
    kept, _fail, _risk = cc.select_adaptive(blocks)
    assert 40 in kept
    kept, _fail, _risk = cc.select_fixed(blocks, 0.05)
    assert 40 in kept


def test_structural_collapse_only_is_reported():
    """E7: when the query's terms are absent the engine fails open, but a log
    that folds to a fraction of its size is still returned folded. That result
    is a structural collapse, not an answer-driven extract, and says so."""
    log = "\n".join(
        f"2026-03-14 12:00:{i % 60:02d} INFO  w1 heartbeat ok node={i}" for i in range(400)
    )
    result = compress_context(
        log, "what happened to req-9999zz?", ccr=False, citations=False
    )
    assert not result.fail_open  # the CompressResult shape is unchanged
    assert result.compressed_text.startswith("[×400] ")
    assert result.receipt["structural_collapse_only"] is True
    assert "structural collapse only (query terms absent)" in result.reasons

    # An answer-driven extract, a generic fail-open and an early fail-open all
    # report False (the key is always present).
    extract = compress_context(log, "heartbeat node=57", ccr=False, citations=False)
    assert extract.receipt["structural_collapse_only"] is False
    assert "structural collapse only (query terms absent)" not in extract.reasons
    generic = compress_context(log, "", ccr=False, citations=False)
    assert generic.fail_open and generic.receipt["structural_collapse_only"] is False
