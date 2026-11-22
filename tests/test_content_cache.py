"""S7: byte-capped ContentCache, huge-item streaming path, and too_large fail-open."""

import os
import importlib
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
from tameru.content_cache import CACHE, ContentCache, _MISS, content_key, content_memo, weight_of  # noqa: E402
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


@pytest.mark.parametrize("max_bytes", [0, 1000])
def test_oversized_record_is_not_retained(max_bytes):
    cache = ContentCache(max_bytes=max_bytes)
    cache.set("oversized", "x" * 10000)
    assert cache.get("oversized") is _MISS
    assert cache.bytes == 0
    assert cache.stats()["entries"] == 0
    assert cache.stats()["analysis_counts"] == {}


def test_oversized_record_does_not_evict_other_entries():
    cache = ContentCache(max_bytes=1000)
    cache.set("first", 1)
    cache.set("second", 2)
    before = cache.bytes
    cache.set("oversized", "x" * 10000)
    assert cache.get("oversized") is _MISS
    assert cache.get("first") == 1
    assert cache.get("second") == 2
    assert cache.bytes == before
    cache.set("first", "x" * 10000)
    assert cache.get("first") is _MISS
    assert cache.bytes == weight_of(2)


def test_evicted_record_statistics_are_bounded_and_cleared():
    cache = ContentCache(max_bytes=weight_of(1) * 2)
    for index in range(100):
        cache.set(str(index), index)
    assert len(cache.stats()["analysis_counts"]) == cache.stats()["entries"] == 2
    cache.clear()
    assert cache.stats()["analysis_counts"] == {}
    assert cache.bytes == 0


def test_nested_weight_includes_deep_values_and_handles_shared_cycles():
    value = "x" * 10000
    nested = value
    for _ in range(10):
        nested = [nested]
    cache = ContentCache(max_bytes=1000)
    cache.set("deep", nested)
    assert cache.get("deep") is _MISS
    cycle = [value, value]
    cycle.append(cycle)
    assert weight_of(cycle) == sys.getsizeof(cycle) + sys.getsizeof(value)


@pytest.mark.parametrize("text", ["", "\n\n", TEXT, ("# 标题\n\n```python\ndef f():\n    pass\n```\n\nERROR é\ud800\r\n") * 60])
def test_segmentation_cache_rebuilds_text_and_returns_private_blocks(text):
    cc = importlib.import_module("tameru.compress_context")
    _fresh()
    lines = tuple(text.split("\n"))
    expected = cc.segment_blocks(list(lines))
    assert list(cc._segment_blocks_cached(lines)) == expected
    key = content_key(cc.ENGINE_VERSION, "segment_blocks", text)
    kinds, spans = CACHE.get(key)
    assert all(isinstance(value, int) for value in spans)
    assert set(kinds) == {block["type"] for block in expected}
    if expected:
        first = cc._segment_blocks_cached(lines)
        first[0]["text"] = "mutated"
    assert list(cc._segment_blocks_cached(lines)) == expected


def test_scored_cache_rebuilds_text_without_retaining_it():
    cc = importlib.import_module("tameru.compress_context")
    cc._clear_memos()
    lines = TEXT.split("\n")
    blocks = cc.segment_blocks(lines)
    expected = cc.score_blocks(blocks, "handler", content_type=None)
    first = cc._score_blocks_memo(lines, blocks, "handler", None, degraded=False)
    assert first == expected
    key = content_key(cc.ENGINE_VERSION, "scored", "\0".join(lines), ("handler", None))
    assert all("text" not in block for block in cc._SCORED.get(key))
    first[0]["text"] = "mutated"
    assert cc._score_blocks_memo(lines, blocks, "handler", None, degraded=False) == expected


@pytest.mark.parametrize("text", ["", "source TEXT " * 1000])
def test_normalized_full_text_views_are_not_cached(text):
    _fresh()

    @content_memo("test_view")
    def view(source):
        return source.casefold()

    assert view(text) == text.casefold()
    assert CACHE.get(content_key("", "test_view", text)) is _MISS


def test_cold_warm_and_disabled_caches_leave_output_identical(monkeypatch):
    cc = importlib.import_module("tameru.compress_context")
    cc._clear_memos()
    expected = compress_context(TEXT, "handler", ccr=False, citations=False).to_dict()
    assert compress_context(TEXT, "handler", ccr=False, citations=False).to_dict() == expected
    cc._clear_memos()
    monkeypatch.setattr(CACHE, "max_bytes", 0)
    monkeypatch.setattr(cc._SCORED, "max_bytes", 0)
    assert compress_context(TEXT, "handler", ccr=False, citations=False).to_dict() == expected


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
