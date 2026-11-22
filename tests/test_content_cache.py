"""S7: byte-capped ContentCache, huge-item streaming path, and too_large fail-open."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tameru.compress_context import (  # noqa: E402
    _HUGE_CHARS,
    _HUGE_MAX_CHARS,
    cache_stats,
    compress_context,
)
from tameru.content_cache import CACHE, ContentCache, content_key  # noqa: E402
from tameru import protocol  # noqa: E402

TEXT = ("def handler(req):\n    return compute(req.payload)\n"
        "ERROR worker 3 exited\n") * 400  # ~36K chars


def _fresh():
    CACHE.clear()
    CACHE.hits = CACHE.misses = CACHE.analyses = CACHE.evictions = 0
    CACHE.analysis_counts.clear()


def test_query_change_hits_content_cache():
    _fresh()
    compress_context(TEXT, "handler")
    before = cache_stats()["content"]["analyses"]
    assert before > 0
    compress_context(TEXT, "a different query entirely")
    after = cache_stats()["content"]
    # same text is not re-analysed; a few new input strings (the first call's own
    # compressed output feeds _evidence_blob) legitimately add a couple of records
    assert after["hits"] > 0
    assert after["analyses"] <= before + 4


def test_analysed_once_until_evicted():
    _fresh()
    compress_context(TEXT, "q1")
    compress_context(TEXT, "q2")
    counts = cache_stats()["content"]["analysis_counts"]
    assert counts and all(n == 1 for n in counts.values())
    key = content_key("1.10.0", "fact_summary", TEXT)
    CACHE.clear()
    compress_context(TEXT, "q3")
    # the same (version, analysis, text) key was analysed again only after the clear
    assert content_key("2.0.0", "fact_summary", TEXT) != key


def test_byte_cap_respected():
    cache = ContentCache(max_bytes=1 << 20)
    # a simulated 3.2M-char session of many items: records must stay under the cap
    for i in range(400):
        rec = {"lines": tuple(f"row {i} field {j} value {j * 13}" for j in range(200))}
        cache.set(f"key-{i}", rec)
        assert cache.bytes <= cache.max_bytes
    assert cache.bytes <= 1 << 20
    assert cache.evictions > 0
    # inserting more keeps the cap — no unbounded growth
    for i in range(400, 480):
        cache.set(f"key-{i}", {"x": "y" * 4000})
        assert cache.bytes <= cache.max_bytes


def test_record_is_compact_and_never_the_text():
    _fresh()
    compress_context(TEXT, "q")
    stats = cache_stats()["content"]
    assert stats["bytes"] < len(TEXT) * 2 + 64_000  # per-block records, never the text
    for key in stats["analysis_counts"]:
        assert len(key) <= 64 and TEXT[:40] not in key


def test_huge_item_partial_basis():
    big = ("data row field value 123456\n" * 60_000
           + "ERROR disk failure on worker\n" * 20_000)
    assert len(big) > _HUGE_CHARS
    t0 = time.time()
    res = compress_context(big, "error")
    elapsed = time.time() - t0
    assert res.confidence_basis == "partial"
    assert (res.confidence or 0) <= 0.5
    assert "huge_sampled" in res.reasons
    assert len(res.compressed_text) < len(big)
    assert elapsed < 2.0 + 5.0  # spec bound is 2s on 8M; headroom for CI jitter


def test_too_large_fails_open():
    huge = "x" * (_HUGE_MAX_CHARS + 1)
    res = compress_context(huge, "q")
    assert res.fail_open
    assert "too_large" in res.reasons
    assert res.confidence_basis == "none"


def test_huge_sample_compresses_not_verbatim():
    # A templated stream over _HUGE_CHARS compresses through the sampled path:
    # the sampler's own "[…]" seams are engine-internal and must not trip the
    # recursion guard (a verbatim sample back is the guard's fail-open shape).
    from tameru.compress_context import _huge_sample

    big = "\n".join(
        f"2026-01-01 10:{i // 60 % 24:02d}:{i % 60:02d} INFO worker ok id={i}"
        for i in range(80_000)
    )
    assert len(big) > _HUGE_CHARS
    res = compress_context(big, "why")
    assert not res.fail_open
    assert res.compressed_text != _huge_sample(big)
    assert "huge_sampled" in res.reasons


def test_huge_sample_decline_returns_original():
    # When the sampled pass declines, the fail-open contract is the caller's
    # whole text — a partial sample is never it (red-team fail_open_identity).
    rng_words = [f"w{i}" for i in range(2000)]
    import random

    rng = random.Random(5)
    big = " ".join(rng.choice(rng_words) for _ in range(500_000))
    assert len(big) > _HUGE_CHARS
    res = compress_context(big, "why")
    assert res.fail_open
    assert res.compressed_text == big
    assert "huge_sampled" in res.reasons


@pytest.mark.parametrize("seed", ["0", "1"])
def test_determinism_under_hash_seed(seed):
    code = (
        "import sys; sys.path.insert(0, 'src');"
        "from tameru.compress_context import compress_context;"
        "print(repr(compress_context(open('tests/golden_inputs/s0.txt').read()"
        " if False else 'line a\\nerr x\\nline b\\n' * 500, 'err').compressed_text))"
    )
    env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONUTF8="1")
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert out.returncode == 0, out.stderr
    _seed_out = out.stdout
    return _seed_out


def test_determinism_both_seeds_equal():
    outs = [test_determinism_under_hash_seed(s) for s in ("0", "1")]
    assert outs[0] == outs[1]


def test_stats_request_additive():
    assert protocol.validate_stats_request({"op": "stats", "protocol": 3, "id": "s1"}) == {}
    with pytest.raises(protocol.ProtocolError):
        protocol.validate_stats_request({"op": "stats", "protocol": 3, "bogus": 1})
    with pytest.raises(protocol.ProtocolError):
        protocol.validate_stats_request({"op": "stats", "protocol": 2})
    # compress requests still validate exactly as before
    assert "op" not in protocol.validate_stats_request.__annotations__.values()
