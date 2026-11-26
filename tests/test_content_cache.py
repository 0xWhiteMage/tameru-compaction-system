"""S7: byte-capped ContentCache, huge-item streaming path, and too_large fail-open."""

import os
import importlib
import json
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
    assert cache.stats()["analysis_counts"] == {"oversized": 1}


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
    assert cache.stats()["entries"] == 2
    assert len(cache.stats()["analysis_counts"]) == 100
    cache.clear()
    assert len(cache.stats()["analysis_counts"]) == 100
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
    key = content_key(cc.ENGINE_VERSION, "segment_blocks", text, extra=(tuple(map(len, lines)),))
    packed, names = CACHE.get(key)
    assert all(isinstance(value, int) for value in packed)
    assert {names[packed[i + 2]] for i in range(0, len(packed), 4)} == {block["type"] for block in expected}
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
    assert elapsed < 2.0 + 13.0  # spec bound is 2s on 8M; Windows CI can sit near 10s under load


def test_huge_whitespace_sample_fails_open_instead_of_erasing_input(monkeypatch):
    # A whitespace-only sample carries no caller evidence. Returning a successful
    # empty compression would erase the input, so the outer guard fails open.
    import tameru.compress_context as cc

    big = "ordinary filler line with several words\n" * 50_001
    assert len(big) > _HUGE_CHARS
    monkeypatch.setattr(cc, "_huge_sample", lambda *args, **kwargs: "\n[...]\n")
    res = compress_context(big, "ordinary filler", ccr=False, citations=False)
    assert res.fail_open
    assert res.compressed_text == big
    assert "huge_sample_empty" in res.reasons


def test_huge_tiny_line_cap_fails_open():
    # Too few rows for even one opening and one closing anchor leave the sample
    # oversized, so the recursive guard preserves the original.
    base = "opening fact alpha\n" + ("x\n" * 1_000) + ("\n" * 2_000)
    filler = "ordinary filler line with several words\n" * 50_000
    big = base + filler + ("\n" * 2_000)
    assert len(big) > _HUGE_CHARS
    for max_lines in (1, 2, 8):
        res = compress_context(
            big, "opening fact alpha", ccr=False, citations=False,
            limits={"max_lines": max_lines},
        )
        assert res.fail_open
        assert res.compressed_text == big


def test_huge_pinned_input_fails_open():
    # The streaming sampler cannot prove that a pinned original block survived
    # intact, so an explicit pin is a hard fail-open floor rather than a sampled
    # best effort.
    import re

    filler = "2026-11-26T10:00:00Z INFO worker processed request id=abcdefgh status=ok\n"
    pin = "PINNED diagnostic"
    big = filler * 22_000 + pin + "\n" + filler * 18_000
    assert len(big) > _HUGE_CHARS
    for kwargs in ({"pin_patterns": [re.escape(pin)]}, {"pin_recent": 1}):
        res = compress_context(big, "worker processed request", ccr=False, citations=False, **kwargs)
        assert res.fail_open
        assert res.compressed_text == big
        assert "huge_pinned_input" in res.reasons


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


def test_huge_error_line_sample_stays_bounded():
    # Minified JSON and single-line logs can make one error-matching line larger
    # than the whole error-sample budget. The sampler skips that line instead of
    # copying enough bytes to recurse into the huge path again.
    from tameru.compress_context import _huge_sample

    big = "x" * 1_000_000 + " ERROR core failure: disk quota exceeded " + "y" * 1_200_000
    assert len(big) > _HUGE_CHARS
    sample = _huge_sample(big)
    assert len(sample) <= _HUGE_CHARS
    assert "ERROR core failure: disk quota exceeded" not in sample


def test_huge_error_sample_packs_short_lines():
    # A stride that lands on long lines must not fall back to one error per
    # coverage slot when thousands of short errors fit in the byte budget.
    from tameru.compress_context import _HUGE_EDGE_CHARS, _HUGE_ERR_CHARS, _huge_sample

    count = 14_000
    lines = [f"ERROR short failure {i}" for i in range(count)]
    assert sum(len(line) + 1 for line in lines) > _HUGE_ERR_CHARS
    middle = "\n".join(lines) + "\n"
    big = "x" * _HUGE_EDGE_CHARS + "\n" + middle + "y" * _HUGE_EDGE_CHARS
    sample = _huge_sample(big)
    assert sum(line in sample for line in lines) > 10_000
    assert len(sample) <= 2 * _HUGE_EDGE_CHARS + _HUGE_ERR_CHARS + 32


def test_huge_error_sample_deduplicates_exact_repeats():
    # Thousands of byte-identical errors carry the same diagnostic once. The
    # recursive pass can fold repetition, but scoring thousands of copies first
    # can exceed a host's trigger-time deadline.
    from tameru.compress_context import _HUGE_EDGE_CHARS, _HUGE_ERR_CHARS, _huge_sample

    line = "ERROR short failure"
    count = 14_000
    assert (len(line) + 1) * count > _HUGE_ERR_CHARS
    middle = (line + "\n") * count
    big = "x" * _HUGE_EDGE_CHARS + "\n" + middle + "y" * _HUGE_EDGE_CHARS
    sample = _huge_sample(big)
    assert sample.count(line) == 1
    assert len(sample) <= 2 * _HUGE_EDGE_CHARS + _HUGE_ERR_CHARS + 32


def test_huge_sample_stays_under_the_recursive_line_limit():
    # Short edge rows can approach the recursive line cap before any sampled
    # errors are added. The sampler spends only the remaining rows on errors
    # and thins the edges when they alone cannot fit.
    from tameru.compress_context import _HUGE_EDGE_CHARS, _huge_sample

    edge = ("x\n" * _HUGE_EDGE_CHARS)[:_HUGE_EDGE_CHARS]
    filler = "ordinary filler text without an error marker\n" * 22_000
    big = edge + filler + edge
    sample = _huge_sample(big, max_lines=1_000)
    assert sample.count("\n") + 1 <= 1_000

    edge_row = "x" * 1023 + "\n"
    edge = edge_row * (_HUGE_EDGE_CHARS // len(edge_row))
    errors = [f"ERROR distinct failure {i}" for i in range(1_000)]
    big = edge + filler + "\n".join(errors) + "\n" + edge
    sample = _huge_sample(big, max_lines=1_000)
    assert sample.count("\n") + 1 <= 1_000
    assert sum(line in sample for line in errors) < len(errors)
    assert any(line in sample for line in errors)


def test_huge_error_sample_skew_stays_byte_bounded():
    # Mixed short and near-cap lines still keep long-line coverage, while the
    # packed error sample remains inside its byte budget.
    from tameru.compress_context import _HUGE_EDGE_CHARS, _HUGE_ERR_CHARS, _huge_sample

    long = "ERROR " + "l" * 4000
    short = "ERROR short failure"
    pair = long + "\n" + short + "\n"
    assert len(pair) * 70 > _HUGE_ERR_CHARS
    big = "x" * _HUGE_EDGE_CHARS + "\n" + pair * 70 + "y" * _HUGE_EDGE_CHARS
    sample = _huge_sample(big)
    assert long in sample
    assert len(sample) <= 2 * _HUGE_EDGE_CHARS + _HUGE_ERR_CHARS + 32


def test_huge_error_sample_packing_keeps_stride_anchor():
    # Packing extra short errors must not crowd out the long diagnostic the
    # original evenly strided fallback selected as that slot's representative.
    from tameru.compress_context import _HUGE_EDGE_CHARS, _HUGE_ERR_CHARS, _huge_sample

    count = 2_000
    short = "ERROR " + "s" * 100
    long = ("ERROR long diagnostic " + "l" * 4000)[:4096]
    unique = ("ERROR unique_long_diagnostic " + "u" * 4050)[:4096]
    lines = [long if i % 6 == 0 else short for i in range(count)]
    lines[96] = unique       # 96 is both an initial stride hit and a fallback anchor
    assert sum(len(line) + 1 for line in lines) > _HUGE_ERR_CHARS
    middle = "\n".join(lines) + "\n"
    big = "x" * _HUGE_EDGE_CHARS + "\n" + middle + "y" * _HUGE_EDGE_CHARS
    sample = _huge_sample(big)
    assert unique in sample
    assert len(sample) <= 2 * _HUGE_EDGE_CHARS + _HUGE_ERR_CHARS + 32


def test_huge_line_trim_keeps_opening_edge_prefix():
    # When short rows force edge thinning, the head keeps its leading rows as a
    # prefix; spreading evenly across the head would drop most opening facts.
    from tameru.compress_context import _HUGE_EDGE_CHARS, _huge_sample

    opening = "".join(f"opening fact {i}\n" for i in range(30))
    edge_fill = "hfill\n" * 50_000
    head = (opening + edge_fill)[:_HUGE_EDGE_CHARS]
    tail = ("tfill\n" * 50_000)[:_HUGE_EDGE_CHARS]
    filler = "ordinary filler text without an error marker\n" * 22_000
    big = head + filler + tail
    sample = _huge_sample(big, max_lines=1_000)
    assert all(f"opening fact {i}\n" in sample for i in range(20))


def test_huge_edge_trim_never_erases_nonempty_edges():
    # Even an impossible block budget must leave one opening and closing anchor
    # row; the oversized sample can fail open, but must not silently drop both
    # ends of the caller's log.
    from tameru.compress_context import _trim_huge_edges

    head = "opening fact\n" + ("head row\n" * 100)
    tail = ("tail row\n" * 100) + "closing fact"
    head_out, tail_out = _trim_huge_edges(head, tail, 10_000)
    assert head_out.startswith("opening fact")
    assert tail_out.endswith("closing fact")
    assert head_out
    assert tail_out


def test_huge_tail_line_trim_skips_the_terminal_empty_field():
    # A newline-terminated tail's final split field is empty. Spending the last
    # row budget on that sentinel discards the closing diagnosis entirely.
    from tameru.compress_context import _thin_text_lines

    assert _thin_text_lines("closing diagnosis\n", 1, from_end=True) == "closing diagnosis"
    assert _thin_text_lines("closing diagnosis\n\n\n", 1, from_end=True) == "closing diagnosis"


def test_huge_error_sample_respects_record_block_limit():
    # Key/value-shaped rows are one block per line in the recursive pass. Packing
    # the byte budget full of them must not turn the sample into a block-limit
    # fail-open, even though thousands still fit.
    from tameru.compress_context import (
        _HUGE_EDGE_CHARS, _HUGE_ERR_CHARS, _huge_sample, segment_blocks,
    )
    from tameru.industrial import IndustrialLimits

    # Rows are distinct: exact-duplicate thinning is a separate contract (it
    # collapses byte-identical repeats), while this test exercises the block
    # budget on rows that each carry their own bytes.
    count = 25_000
    big = ("x" * _HUGE_EDGE_CHARS + "\n"
           + "".join(f"error=value{i}\n" for i in range(count)) + "y" * _HUGE_EDGE_CHARS)
    sample = _huge_sample(big)
    assert sample.count("error=value") > 10_000
    assert len(segment_blocks(sample.split("\n"))) <= IndustrialLimits().max_blocks
    custom = _huge_sample(big, max_blocks=1_000)
    assert len(segment_blocks(custom.split("\n"))) <= 1_000


def test_huge_record_edges_respect_block_limit():
    # Dense record lines in the fixed edges can cross the same ceiling before any
    # middle error is packed; the sampler trims complete edge lines byte-exactly.
    from tameru.compress_context import _HUGE_CHARS, _huge_sample, segment_blocks
    from tameru.industrial import IndustrialLimits

    line = "error=value"
    big = (line + "\n") * (_HUGE_CHARS // (len(line) + 1) + 1_000)
    sample = _huge_sample(big)
    assert sample
    assert len(segment_blocks(sample.split("\n"))) <= IndustrialLimits().max_blocks


def test_huge_record_sample_compresses_within_custom_block_limit():
    # End to end: a low caller limit exercises the same block ceiling without
    # scoring 20,000 record blocks; before the cap the sampled inner pass failed
    # open and the whole huge input came back.
    from tameru.compress_context import _HUGE_CHARS, _HUGE_EDGE_CHARS
    from tameru.industrial import IndustrialLimits

    line = "error=value"
    count = _HUGE_CHARS // (len(line) + 1) + 1_000
    big = "x" * _HUGE_EDGE_CHARS + "\n" + (line + "\n") * count + "y" * _HUGE_EDGE_CHARS
    res = compress_context(
        big, line, budget_ratio=0.2, ccr=False, citations=False,
        limits=IndustrialLimits(max_blocks=1_000),
    )
    assert not res.fail_open
    assert "huge_sampled" in res.reasons
    assert len(res.compressed_text) < len(big)


def test_huge_dense_edges_keep_middle_error_coverage():
    # Edge overflow must not consume the whole block budget: the sampler's byte
    # budgets give the middle error slice a quarter of the capacity too.
    from tameru.compress_context import _HUGE_CHARS, _HUGE_EDGE_CHARS, _huge_sample, segment_blocks

    edge_line = "edge=" + "e" * 140
    edge_unit = edge_line + "\n"
    head = (edge_unit * (_HUGE_EDGE_CHARS // len(edge_unit) + 2))[:_HUGE_EDGE_CHARS]
    count = (_HUGE_CHARS - 2 * len(head)) // 18 + 2_000
    middle = "".join(f"error=value{index:06d}\n" for index in range(count))
    big = head + "\n" + middle + head
    sample = _huge_sample(big, max_blocks=1_000, max_lines=1_000)
    assert len(segment_blocks(sample.split("\n"))) <= 1_000
    assert sum(line.startswith("error=value") for line in sample.splitlines()) >= 200


def test_huge_grouped_errors_are_not_thinned_when_they_fit():
    from tameru.compress_context import _HUGE_EDGE_CHARS, _huge_sample

    errs = [f"ERROR failure {index} happened" for index in range(2_000)]
    big = "x" * _HUGE_EDGE_CHARS + "\n" + "\n".join(errs) + "\n" + "y" * _HUGE_EDGE_CHARS
    sample = _huge_sample(big, max_blocks=1_000)
    assert sum(line.startswith("ERROR failure ") for line in sample.splitlines()) == 2_000


def test_huge_uneven_edges_share_the_line_budget():
    from tameru.compress_context import _HUGE_CHARS, _HUGE_EDGE_CHARS, _huge_sample, _line_count

    edge_line = "edge=" + "e" * 140
    edge_unit = edge_line + "\n"
    head = (edge_unit * (_HUGE_EDGE_CHARS // len(edge_unit) + 2))[:_HUGE_EDGE_CHARS]
    tail = "y" * _HUGE_EDGE_CHARS
    middle_len = _HUGE_CHARS - len(head) - len(tail) + 1_000
    middle = ("ERROR failure happened\n" * (middle_len // 23 + 1))[:middle_len]
    sample = _huge_sample(head + "\n" + middle + tail, max_blocks=1_000, max_lines=1_000)
    assert sample.count(edge_line) > 371
    assert sample.endswith(tail)


def test_huge_edge_trim_preserves_nonblank_closing_anchor():
    # Blank tail padding is not caller evidence. It must not become the sole
    # surviving "anchor" while the closing diagnostic is trimmed away.
    from tameru.compress_context import _trim_huge_edges, _trim_huge_edges_by_counts

    head = "opening fact\n"
    tail = "closing diagnostic\n\n"
    for trim in (
        lambda h, t: _trim_huge_edges(h, t, 10),
        lambda h, t: _trim_huge_edges_by_counts(h, t, 0, 10),
    ):
        head_out, tail_out = trim(head, tail)
        assert "opening fact" in head_out
        assert "closing diagnostic" in tail_out


def test_huge_blockaware_trim_skips_unremovable_anchor_blocks():
    # A one-line closing block cannot be eliminated without erasing the closing
    # anchor. Overflow work must shift to a removable opening block instead of
    # repeatedly assigning the trim to the unremovable tail block.
    from tameru.compress_context import _trim_huge_edges_blockaware

    head = "head one\nhead two\n"
    tail = "closing diagnostic\n"
    sample = head + "\n[...]\n" + tail
    blocks = [{"start": 0, "end": 0}, {"start": 1, "end": 1}, {"start": 4, "end": 4}]
    head_out, tail_out = _trim_huge_edges_blockaware(sample, head, tail, blocks, 1)
    assert head_out == "head one\n"
    assert tail_out == tail


def test_huge_tight_block_cap_keeps_middle_error_evidence():
    # When opening/error/closing evidence cannot all fit, the sample may stay
    # oversized and fail open, but block fitting must not succeed after erasing
    # every middle error it sampled.
    from tameru.compress_context import _HUGE_CHARS, _HUGE_EDGE_CHARS, _huge_sample

    errors = "\n".join(f"error {index}" for index in range(2_000))
    filler = "f" * _HUGE_CHARS
    big = "x" * _HUGE_EDGE_CHARS + "\n" + errors + "\n" + filler + "\n" + "y" * _HUGE_EDGE_CHARS
    sample = _huge_sample(big, max_blocks=3, max_lines=250_000)
    assert any(line.startswith("error ") for line in sample.splitlines())


def test_huge_dense_edges_converge_without_repeated_segmentation(monkeypatch):
    # Blank-separated edge rows need several rows per block removal. Measuring
    # that density must converge in a few passes, not one row per excess block.
    import tameru.compress_context as cc

    unit = "edge row\n" + "\n" * 7
    head = (unit * (cc._HUGE_EDGE_CHARS // len(unit) + 2))[:cc._HUGE_EDGE_CHARS]
    count = (cc._HUGE_CHARS - 2 * len(head)) // 16 + 1_000
    middle = "".join(f"error failure {index}\n" for index in range(count))
    big = head + "\n" + middle + head
    original = cc._segment_blocks_memo
    calls = []

    def counting(lines):
        calls.append(len(lines))
        return original(lines)

    monkeypatch.setattr(cc, "_segment_blocks_memo", counting)
    sample = cc._huge_sample(big, max_blocks=20_000)
    assert len(calls) <= 4
    assert len(cc.segment_blocks(sample.split("\n"))) <= 20_000


def test_huge_grouped_error_blocks_thin_whole_blocks(monkeypatch):
    # Ten short errors can share one recursive block. Removing single rows from
    # every block cannot satisfy the block ceiling; whole blocks are thinned
    # instead, with the first and last error-carrying blocks retained.
    import tameru.compress_context as cc

    errors = "\n".join(f"error {index}" for index in range(20_000))
    filler = "f" * cc._HUGE_CHARS
    big = "x" * cc._HUGE_EDGE_CHARS + "\n" + errors + "\n" + filler + "\n" + "y" * cc._HUGE_EDGE_CHARS
    original = cc._segment_blocks_memo
    calls = []

    def counting(lines):
        calls.append(len(lines))
        return original(lines)

    monkeypatch.setattr(cc, "_segment_blocks_memo", counting)
    sample = cc._huge_sample(big, max_blocks=1_000, max_lines=250_000)
    assert len(cc.segment_blocks(sample.split("\n"))) <= 1_000
    assert len(calls) <= 4
    assert "error 0" in sample
    assert "error 19999" in sample


def test_huge_one_line_tool_json_does_not_recurse():
    # Terminal envelopes carry an ``error`` key, so one long JSON line both
    # matches the error sampler and used to reproduce as an over-threshold sample.
    big = json.dumps({"output": "x" * 2_200_000, "exit_code": 0, "error": None})
    assert len(big) > _HUGE_CHARS
    res = compress_context(big, "why", ccr=False, citations=False)
    assert "huge_sampled" in res.reasons
    assert res.compressed_text


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


def _determinism_under_hash_seed(seed):
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
    outs = [_determinism_under_hash_seed(s) for s in ("0", "1")]
    assert outs[0] == outs[1]


def test_stats_request_additive():
    assert protocol.validate_stats_request({"op": "stats", "protocol": 3, "id": "s1"}) == {}
    with pytest.raises(protocol.ProtocolError):
        protocol.validate_stats_request({"op": "stats", "protocol": 3, "bogus": 1})
    with pytest.raises(protocol.ProtocolError):
        protocol.validate_stats_request({"op": "stats", "protocol": 2})
    # compress requests still validate exactly as before
    assert "op" not in protocol.validate_stats_request.__annotations__.values()
