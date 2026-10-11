"""1.4.1: grep output under a caller's (long) gap marker, and command-line options in the query."""
from tameru.agent_formats import adapt_grep_lines
from tameru.compress_context import InliningGapMarker, compress_context
from tameru.format_adapters import _query_selectors

HOST_MARKER = "\u27eaHOST-CONTEXT-COMPRESSION: {0:,} of {1:,} chars omitted here by the host's context compressor.\u27eb"


def host_marker(omitted: int, total: int) -> str:
    return HOST_MARKER.format(omitted, total)


def _grep_text() -> str:
    uses = [
        "raise StockConflict(sku)",
        "except StockConflict as exc:",
        "from shop.errors import StockConflict",
        "with pytest.raises(StockConflict):",
    ]
    rows = []
    for f in range(12):
        for j in range(5):
            rows.append(f"src/pkg{f:02d}/mod.py:{10 + j}:    {uses[(f + j) % 4]}")
    rows.insert(30, "src/errors.py:12:class StockConflict(RuntimeError):")
    return "\n".join(rows) + "\n"


def test_cli_flags_are_not_query_selectors():
    selectors = _query_selectors("rg -n StockConflict src")
    assert "-n" not in selectors and "stockconflict" in selectors
    assert "--stat" not in _query_selectors("git log --stat ORD-1234")
    assert "ord-1234" in _query_selectors("git log --stat ORD-1234")


def test_flag_in_query_no_longer_hides_the_searched_name():
    text = _grep_text()
    res = adapt_grep_lines(text, "terminal rg -n StockConflict src where is StockConflict defined?")
    assert res is not None and res.hit
    assert "class StockConflict(RuntimeError):" in res.text
    assert res.kept_records < res.total_records


def test_fully_omitted_files_share_one_host_marker():
    text = _grep_text()
    res = adapt_grep_lines(text, "where is StockConflict defined?", gap_marker=host_marker)
    assert res is not None
    body = res.text
    # every file keeps its header line (where the name is used, and how often)
    for f in range(12):
        assert f"src/pkg{f:02d}/mod.py  (5 matches)" in body
    assert "src/errors.py  (1 match)" in body
    assert "L12: class StockConflict(RuntimeError):" in body
    per_file = adapt_grep_lines(text, "where is StockConflict defined?")
    # the default marker keeps one per file (unchanged); the host marker is shared per run
    assert per_file.text.count("[…") > body.count("HOST-CONTEXT-COMPRESSION")
    assert body.count("HOST-CONTEXT-COMPRESSION") <= 4


def test_inlining_marker_inlines_a_short_grep_run():
    text = "\n".join(f"a.py:{i}:    use Needle{i}" if i != 3 else "a.py:3:Needle zz" for i in range(1, 8)) + "\n"
    long_marker = InliningGapMarker(lambda o, t: "#" * 200)
    res = adapt_grep_lines(text, "zz", gap_marker=long_marker)
    assert res is not None
    # the omitted runs are shorter than the marker, so they are inlined: nothing is lost
    assert "#" * 200 not in res.text
    assert res.kept_records == res.total_records


def test_compress_context_grep_with_host_marker_keeps_the_definition():
    text = _grep_text()
    res = compress_context(
        text, ["terminal", "rg -n StockConflict src", "where is StockConflict defined?"],
        ccr=False, citations=False, content_hint="grep", gap_marker=host_marker,
    )
    assert not res.fail_open
    assert "class StockConflict(RuntimeError):" in res.compressed_text
    assert len(res.compressed_text) < 0.6 * len(text)
