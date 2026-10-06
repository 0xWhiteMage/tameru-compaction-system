"""E5: unified-diff and grep/rg adapters."""
import re

from tameru.agent_formats import (
    adapt_grep_lines,
    adapt_unified_diff,
    detect_grep_lines,
    detect_unified_diff,
)
from tameru.compress_context import compress_context
from tameru.format_adapters import detect_format


def _diff(nfiles: int = 3, nh: int = 6) -> str:
    out = []
    for f in range(nfiles):
        out += [
            f"diff --git a/src/m{f}.py b/src/m{f}.py",
            "index 111..222 100644",
            f"--- a/src/m{f}.py",
            f"+++ b/src/m{f}.py",
        ]
        for h in range(nh):
            base = h * 40 + 1
            out += [
                f"@@ -{base},3 +{base},3 @@ def fn_{f}_{h}():",
                " ctx a",
                f"-    old_{f}_{h} = 1",
                f"+    new_{f}_{h} = 2",
                " ctx b",
            ]
    return "\n".join(out) + "\n"


def _hunks(text: str) -> list[list[str]]:
    hunks: list[list[str]] = []
    for ln in text.split("\n"):
        if ln.startswith("@@"):
            hunks.append([ln])
        elif hunks and ln[:1] in {" ", "-", "+"} and not ln.startswith(("--- ", "+++ ")):
            hunks[-1].append(ln)
    return hunks


def _marker(omitted: int, total: int) -> str:
    return f"<<gap {omitted}/{total}>>"


class TestDiff:
    def test_detection(self):
        d = _diff()
        assert detect_unified_diff(d)
        assert detect_format(d) == "diff"
        assert not detect_unified_diff("--- a\n+++ b\nnothing else")
        assert not detect_unified_diff("just text\nwith lines\n")
        assert adapt_unified_diff("not a diff", "x", gap_marker=None) is None

    def test_file_headers_stats_and_hunk_headers_are_always_kept(self):
        d = _diff()
        res = adapt_unified_diff(d, "what changed in new_1_3?", gap_marker=None)
        out = res.text
        for f in range(3):
            assert f"diff --git a/src/m{f}.py b/src/m{f}.py" in out
            assert f"--- a/src/m{f}.py" in out and f"+++ b/src/m{f}.py" in out
            assert f"# src/m{f}.py: +6 -6 in 6 hunks" in out
        for f in range(3):
            for h in range(6):
                assert f"@@ -{h * 40 + 1},3 +{h * 40 + 1},3 @@ def fn_{f}_{h}():" in out

    def test_query_matching_hunk_is_kept_whole_and_pairs_never_split(self):
        res = adapt_unified_diff(_diff(), "what changed in new_1_3?", gap_marker=None)
        assert res.kept_records == 1
        for body in _hunks(res.text):
            minus = [ln for ln in body if ln.startswith("-")]
            plus = [ln for ln in body if ln.startswith("+")]
            assert len(minus) == len(plus)  # a kept hunk has both sides
            if body[1:]:
                assert len(body) == 5  # header + ctx + - + + + ctx: never partial
        assert "-    old_1_3 = 1" in res.text and "+    new_1_3 = 2" in res.text
        assert "old_0_0" not in res.text and "old_2_5" not in res.text

    def test_identifier_in_hunk_header_context_selects_the_hunk(self):
        res = adapt_unified_diff(_diff(), "explain fn_2_4", gap_marker=None)
        assert "+    new_2_4 = 2" in res.text
        assert res.kept_records == 1

    def test_path_in_query_keeps_that_files_hunks(self):
        res = adapt_unified_diff(_diff(), "what changed in src/m1.py", gap_marker=None)
        assert res.kept_records == 6
        assert "new_1_0" in res.text and "new_0_0" not in res.text

    def test_weak_or_empty_query_keeps_first_and_last_hunk_per_file(self):
        for query in ("", "continue", "thanks"):
            res = adapt_unified_diff(_diff(), query, gap_marker=None)
            assert res.kept_records == 6  # 2 per file
            for f in range(3):
                assert f"new_{f}_0 = 2" in res.text and f"new_{f}_5 = 2" in res.text
                assert f"new_{f}_2 = 2" not in res.text

    def test_one_marker_per_contiguous_omitted_run(self):
        res = adapt_unified_diff(_diff(nfiles=1, nh=8), "new_0_3 or new_0_6", gap_marker=None)
        markers = re.findall(r"\[… (\d+) hunks? omitted …\]", res.text)
        # hunks 0-2 | keep 3 | 4-5 | keep 6 | 7  -> three runs
        assert markers == ["3", "2", "1"]
        custom = adapt_unified_diff(_diff(nfiles=1, nh=8), "new_0_3 or new_0_6", gap_marker=_marker)
        assert custom.text.count("<<gap") == 3
        assert "omitted …" not in custom.text
        total = len(_diff(nfiles=1, nh=8))
        assert all(f"/{total}>>" in m for m in re.findall(r"<<gap [^>]*>>", custom.text))

    def test_marker_counts_the_dropped_bodies(self):
        d = _diff(nfiles=1, nh=3)
        res = adapt_unified_diff(d, "new_0_1", gap_marker=_marker)
        counts = [int(m) for m in re.findall(r"<<gap (\d+)/", res.text)]
        hunks = _hunks(d)
        assert counts == [len("\n".join(hunks[0][1:])), len("\n".join(hunks[2][1:]))]

    def test_removed_dashes_line_is_not_a_file_header(self):
        d = (
            "diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n"
            "@@ -1,3 +1,2 @@\n select 1;\n--- old comment\n+-- new comment\n"
            "diff --git a/r.sql b/r.sql\n--- a/r.sql\n+++ b/r.sql\n"
            "@@ -1,1 +1,1 @@\n-a\n+b\n"
        )
        res = adapt_unified_diff(d, "", gap_marker=None)
        assert res.total_records == 2  # not 3: "--- old comment" belongs to hunk 1

    def test_nothing_dropped_returns_text_unchanged(self):
        d = _diff(nfiles=1, nh=2)
        res = adapt_unified_diff(d, "", gap_marker=None)
        assert res.text == d

    def test_idempotent_on_its_own_output(self):
        res = adapt_unified_diff(_diff(), "new_1_3", gap_marker=None)
        again = adapt_unified_diff(res.text, "new_1_3", gap_marker=None)
        assert again is not None and again.text.count("# src/m1.py") == 1

    def test_through_compress_context(self):
        d = _diff(nfiles=4, nh=12)
        result = compress_context(
            d, "what changed in new_2_7?", ccr=False, citations=False,
            gap_marker=_marker,
        )
        assert not result.fail_open
        assert result.receipt["adapter"]["name"] == "diff"
        assert "+    new_2_7 = 2" in result.compressed_text
        assert "<<gap" in result.compressed_text
        assert len(result.compressed_text) < len(d) * 0.6
        for f in range(4):
            assert f"diff --git a/src/m{f}.py b/src/m{f}.py" in result.compressed_text
        hinted = compress_context(
            d, "what changed in new_2_7?", ccr=False, citations=False,
            content_hint="diff",
        )
        assert hinted.receipt["adapter"]["name"] == "diff"
        assert hinted.receipt["content_hint"] == "diff"
        assert "[… " in hinted.compressed_text and "hunk" in hinted.compressed_text

    def test_weak_query_makes_no_cut_through_the_engine(self):
        d = _diff(nfiles=1, nh=60)
        for query in ("continue", "thanks", ""):
            result = compress_context(d, query, ccr=False, citations=False)
            assert result.fail_open and result.compressed_text == d
            assert result.receipt["adapter"] is None


GREP = "\n".join(
    [f"src/core/engine.py:{10 + i * 7}:    handler_{i} = lookup(key_{i})" for i in range(30)]
    + [f"src/core/util.py:{3 + i}:    helper_{i}()" for i in range(5)]
    + ["tests/test_engine.py:12:def test_handler_4():"]
)


class TestGrep:
    def test_detection(self):
        assert detect_grep_lines(GREP)
        assert detect_format(GREP) == "grep"
        assert not detect_grep_lines("12:00:03 INFO started\n12:00:04 INFO ok\n12:00:05 WARN x")
        assert not detect_grep_lines("2026-03-14 12:00:00,123 INFO a\n2026-03-14 12:00:01,000 INFO b")
        assert adapt_grep_lines("plain text\nmore text", "x") is None
        ctx = "a/b.py-4-ctx\na/b.py:5:hit\na/b.py-6-ctx\n--\na/c.py:9:hit"
        assert detect_grep_lines(ctx)

    def test_query_matches_are_kept_grouped_with_counts(self):
        res = adapt_grep_lines(GREP, "where is handler_4 used?", gap_marker=None)
        lines = res.text.split("\n")
        assert lines[0] == "src/core/engine.py  (30 matches)"
        assert "  L38: " + "    handler_4 = lookup(key_4)" in lines
        assert "tests/test_engine.py  (1 match)" in lines
        assert "  L12: def test_handler_4():" in lines
        assert "src/core/util.py  (5 matches)" in lines
        # util.py has no hit: its first matches (up to the cap) stand in
        assert sum(ln.startswith("  L") for ln in lines) <= 1 + 1 + 5 + 1

    def test_per_file_cap_and_one_marker_per_omitted_run(self):
        res = adapt_grep_lines(GREP, "unrelated_zzz", gap_marker=None, per_file_cap=8)
        eng = [ln for ln in res.text.split("\n") if ln.startswith("  L")]
        assert len([ln for ln in eng if "lookup(" in ln]) == 8
        assert res.text.count("[… 22 matches omitted …]") == 1
        res2 = adapt_grep_lines(GREP, "handler_3 handler_9", gap_marker=_marker)
        engine_part = res2.text.split("src/core/util.py")[0]
        assert engine_part.count("<<gap") == 3  # 0-2 | 3 | 4-8 | 9 | 10-29
        assert "omitted …" not in res2.text

    def test_no_query_is_a_lossless_regroup_when_shorter(self):
        long_path = "services/billing/internal/handlers/invoices.py"
        text = "\n".join(f"{long_path}:{i}:    value_{i} = {i}" for i in range(1, 40))
        res = adapt_grep_lines(text, "", gap_marker=None)
        assert len(res.text) < len(text)
        assert res.kept_records == 39 and "omitted" not in res.text
        body = [ln for ln in res.text.split("\n") if ln.startswith("  L")]
        assert body == [f"  L{i}:     value_{i} = {i}" for i in range(1, 40)]
        assert res.text.split("\n")[0] == f"{long_path}  (39 matches)"

    def test_context_lines_follow_their_kept_match(self):
        text = (
            "a/b.py-4-before\na/b.py:5:needle here\na/b.py-6-after\n--\n"
            "a/b.py-40-far before\na/b.py:41:other thing\na/b.py-42-far after"
        )
        res = adapt_grep_lines(text, "needle", gap_marker=None, per_file_cap=1)
        assert "  L4- before" in res.text and "  L6- after" in res.text
        assert "far before" not in res.text and "other thing" not in res.text

    def test_weak_query_only_allows_the_lossless_regroup(self):
        long_path = "services/billing/internal/handlers/invoices.py"
        lossless = "\n".join(f"{long_path}:{i}:    value_{i} = {i}" for i in range(1, 40))
        result = compress_context(lossless, "continue", ccr=False, citations=False)
        assert result.receipt["adapter"] is None or result.receipt["adapter"]["kept_records"] == 39
        capped = compress_context(GREP, "thanks", ccr=False, citations=False)
        assert capped.fail_open and capped.compressed_text == GREP

    def test_through_compress_context(self):
        big = "\n".join(
            f"src/pkg/module_{i % 7}.py:{i}:    call_{i}(arg)  # item {i}" for i in range(600)
        )
        result = compress_context(
            big, "where is call_321 invoked?", ccr=False, citations=False
        )
        assert result.receipt["adapter"]["name"] == "grep"
        assert "call_321(arg)" in result.compressed_text
        assert len(result.compressed_text) < len(big) / 3
        assert not result.fail_open
