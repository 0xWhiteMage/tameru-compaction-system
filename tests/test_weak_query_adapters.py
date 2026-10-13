"""Weak queries (plain words, no identifier) must not bypass the diff / grep
adapters: a diff is cut by whole hunks only, never mid-hunk by the block scorer.

"where was frobnicate changed?" and "what changed in the rollback handling?"
carry no distinctive selector, so ``apply_agent_adapters`` used to discard the
adapter result and the generic scorer cut the diff inside hunks, dropped ``@@``
headers and split -/+ pairs.
"""
import re

import pytest

from tameru.agent_formats import (
    adapt_unified_diff,
    apply_agent_adapters,
)
from tameru import agent_formats
from tameru.compress_context import compress_context

FILES = ("src/net/retry.py", "src/store/journal.py", "src/util/text.py")
HITS = {  # (file index, hunk index) -> body lines that carry the query words
    (0, 7): ["-    frobnicate(x, retry=1)", "+    frobnicate(x, retry=3)"],
    (1, 11): ["-    handle_rollback(tx)", "+    handle_rollback(tx, force=True)"],
    (1, 12): ["-    rollbackAll(txs)", "+    rollbackAll(txs, safe=True)"],
    (2, 3): ["-    n = 1  # one change", "+    n = 2  # one change"],
}
PER_FILE = 20  # 3 files x 20 hunks = 60 hunks


def _gap(omitted: int, total: int) -> str:
    return f"<<gap {omitted}/{total}>>"


def make_diff() -> str:
    out: list[str] = []
    for f, name in enumerate(FILES):
        out += [
            f"diff --git a/{name} b/{name}",
            "index 1111111..2222222 100644",
            f"--- a/{name}",
            f"+++ b/{name}",
        ]
        for h in range(PER_FILE):
            base = h * 30 + 1
            body = HITS.get((f, h)) or [
                f"-    value_{f}_{h} = old_{h}",
                f"+    value_{f}_{h} = new_{h}",
            ]
            old = 2 + sum(ln[0] == "-" for ln in body)
            new = 2 + sum(ln[0] == "+" for ln in body)
            out.append(f"@@ -{base},{old} +{base},{new} @@ def fn_{f}_{h}():")
            out += [f"     before_{f}_{h} = {h}", *body, "     return None"]
    return "\n".join(out) + "\n"


def split_hunks(text: str) -> list[list[str]]:
    """Every ``@@`` hunk of a (possibly compacted) diff: header + body lines."""
    hunks: list[list[str]] = []
    cur: list[str] | None = None
    for ln in text.split("\n"):
        if ln.startswith("@@"):
            cur = [ln]
            hunks.append(cur)
        elif ln.startswith(("diff --git", "# ", "[…", "<<gap")):
            cur = None  # a file or marker line ends the hunk's body
        elif cur is not None and ln[:1] in {" ", "-", "+"}:
            cur.append(ln)
    return hunks


DIFF = make_diff()
ORIGINAL = {h[0]: h for h in split_hunks(DIFF)}
WEAK_QUERIES = ["where was frobnicate changed?", "what changed in the rollback handling?"]


def _compact(query, *, marker=None, hint=None, **kw):
    return compress_context(
        DIFF, query, ccr=False, citations=False, content_hint=hint, gap_marker=marker, **kw
    )


def test_fixture_is_a_60_hunk_multi_file_diff():
    assert len(ORIGINAL) == 60
    assert DIFF.count("diff --git ") == 3


@pytest.mark.parametrize("hint", [None, "diff"])
@pytest.mark.parametrize("marker", [None, _gap])
@pytest.mark.parametrize("query", WEAK_QUERIES)
def test_weak_query_diff_is_cut_by_whole_hunks_only(query, marker, hint):
    result = _compact(query, marker=marker, hint=hint)
    assert not result.fail_open
    assert result.receipt["adapter"]["name"] == "diff"
    text = result.compressed_text
    assert len(text) < len(DIFF) * 0.7
    lines = text.split("\n")
    # every file header and per-file stats line, every @@ header
    for f, name in enumerate(FILES):
        assert f"diff --git a/{name} b/{name}" in lines
        assert f"--- a/{name}" in lines and f"+++ b/{name}" in lines
        assert any(ln.startswith(f"# {name}: +") and ln.endswith(f"in {PER_FILE} hunks") for ln in lines)
    kept = split_hunks(text)
    assert [h[0] for h in kept] == list(ORIGINAL)
    # a hunk is either whole (same as the input) or header-only: never partial,
    # so a -/+ pair is never split
    whole = [h for h in kept if len(h) > 1]
    for h in kept:
        assert h == ORIGINAL[h[0]] or len(h) == 1, h[0]
    # first and last hunk of each file stay whole
    for f in range(len(FILES)):
        first, last = f"fn_{f}_0", f"fn_{f}_{PER_FILE - 1}"
        for name in (first, last):
            hunk = next(h for h in whole if h[0].endswith(f"def {name}():"))
            assert len(hunk) > 1
    # one marker per omitted run
    omitted = [h[0] for h in kept if len(h) == 1]
    runs = 0
    prev_omitted = False
    for h in kept:
        is_omitted = len(h) == 1
        runs += is_omitted and not prev_omitted
        prev_omitted = is_omitted
    marks = text.count("<<gap") if marker else len(re.findall(r"\[… \d+ hunks? omitted …\]", text))
    assert omitted and marks == runs


def test_frobnicate_query_keeps_the_hunk_that_names_it():
    text = _compact(WEAK_QUERIES[0]).compressed_text
    assert "-    frobnicate(x, retry=1)" in text and "+    frobnicate(x, retry=3)" in text
    # 3 files x (first, last) + the hunk naming frobnicate + the hunk that says
    # "change" (changed~change)
    assert _compact(WEAK_QUERIES[0]).receipt["adapter"]["kept_records"] == 8


def test_stemmed_words_select_hunks():
    text = _compact(WEAK_QUERIES[1]).compressed_text
    # handling~handle_rollback, rollback~rollbackAll, changed~"one change"
    for needle in ("handle_rollback(tx, force=True)", "rollbackAll(txs, safe=True)", "# one change"):
        assert needle in text
    assert "value_1_5 = new_5" not in text and "value_0_9 = new_9" not in text


def test_plain_word_in_a_path_does_not_keep_the_whole_file():
    text = _compact("what changed in the journal?").compressed_text
    assert "value_1_5 = new_5" not in text


def test_weak_query_without_any_hit_keeps_first_and_last_hunk_per_file():
    result = _compact("where was zzfrobulate widgetized?")
    assert result.receipt["adapter"]["name"] == "diff"
    assert result.receipt["adapter"]["kept_records"] == 6
    for h in split_hunks(result.compressed_text):
        assert h == ORIGINAL[h[0]] or len(h) == 1


def test_direct_adapter_call_agrees():
    res = adapt_unified_diff(DIFF, WEAK_QUERIES[0], gap_marker=None)
    assert res.kept_records == 8
    text, info = apply_agent_adapters(
        DIFF, WEAK_QUERIES[0], hint="diff", weak_query=True
    )
    assert info and info["kept_records"] == 8 and text == res.text


@pytest.mark.parametrize("query", ["continue", "thanks", "", "what is this?"])
def test_content_free_query_still_licenses_no_cut(query):
    result = _compact(query)
    assert result.fail_open and result.compressed_text == DIFF


def test_distinctive_query_that_hits_nothing_still_fails_open():
    result = _compact("frobnicate_widget zzz_missing")
    assert result.compressed_text == DIFF


def test_distinctive_query_keeps_only_what_it_names():
    result = _compact("what changed in value_1_5?")
    assert result.receipt["adapter"]["kept_records"] == 1


@pytest.mark.parametrize(
    "a,b",
    [("changed", "change"), ("handling", "handle"), ("handlers", "handle"),
     ("retried", "retry"), ("retries", "retry"), ("rollbacks", "rollback"),
     ("stopped", "stopping"), ("frobnication", "frobnicate")],
)
def test_light_stem_conflates_inflections(a, b):
    assert agent_formats.light_stem(a) == agent_formats.light_stem(b)


def test_light_stem_keeps_distinct_words_apart():
    stem = agent_formats.light_stem
    assert stem("rollback") != stem("roll")
    assert stem("retry") != stem("handle")


# --- grep / rg -------------------------------------------------------------

def _saturated_grep() -> str:
    lines = [f"src/pkg/mod_{i % 12}.py:{i * 3 + 1}:    frobnicate(x)" for i in range(300)]
    lines.insert(137, "src/core/frob.py:10:def frobnicate(item, mode):")
    return "\n".join(lines)


@pytest.mark.parametrize(
    "query",
    ["where is frobnicate defined?", "rg -n frobnicate src", "where is frobnicate defined"],
)
def test_weak_query_saturated_grep_keeps_the_definition(query):
    grep = _saturated_grep()
    result = compress_context(grep, query, ccr=False, citations=False)
    assert not result.fail_open
    assert result.receipt["adapter"]["name"] == "grep"
    assert "def frobnicate(item, mode):" in result.compressed_text
    assert len(result.compressed_text) < len(grep) / 4


def test_weak_query_grep_regroups_by_file():
    grep = "\n".join(
        f"src/pkg/mod_{i % 9}.py:{i * 3 + 1}:    result_{i} = compute(item_{i})" for i in range(400)
    ) + "\nsrc/core/lookup.py:10:def lookup(table, key):\n"
    result = compress_context(grep, "where is lookup defined?", ccr=False, citations=False)
    assert result.receipt["adapter"]["name"] == "grep"
    assert "def lookup(table, key):" in result.compressed_text


@pytest.mark.parametrize("query", ["continue", "thanks", ""])
def test_content_free_query_grep_only_regroups_losslessly(query):
    grep = _saturated_grep()
    result = compress_context(grep, query, ccr=False, citations=False)
    # the lossless regroup by file may apply (every match kept); a cut may not
    assert result.receipt["adapter"]["kept_records"] == result.receipt["adapter"]["total_records"] == 301
    assert "def frobnicate(item, mode):" in result.compressed_text
    assert result.compressed_text.count("frobnicate(x)") == 300


# --- test runners: reduction never depended on the query's specificity -------

def _pytest_run() -> str:
    rows = ["============================= test session starts =============================",
            "collected 160 items", ""]
    rows += [f"tests/test_mod_{f}.py {'.' * 9}{'F' if f == 3 else '.'} [{(f + 1) * 8}%]" for f in range(12)]
    rows += ["", "=================================== FAILURES ===================================",
             "______________________________ test_retry_backoff ______________________________",
             "    def test_retry_backoff():", "        delay = compute_backoff(3)",
             "E       assert delay == 8", "E       AssertionError: assert 4 == 8",
             "tests/test_mod_3.py:41: AssertionError",
             "=========================== short test summary info ============================",
             "FAILED tests/test_mod_3.py::test_retry_backoff - AssertionError: assert 4 == 8",
             "========================= 1 failed, 159 passed in 2.31s ========================="]
    rows += [f"tests/test_extra_{i}.py::test_case_{i} PASSED" for i in range(150)]
    return "\n".join(rows) + "\n"


@pytest.mark.parametrize("query", ["which tests failed?", "where was the backoff wrong?"])
def test_test_runner_reduction_is_not_gated_on_query_specificity(query):
    run = _pytest_run()
    result = compress_context(run, query, ccr=False, citations=False)
    assert result.receipt["adapter"]["name"] == "test_output"
    assert "AssertionError: assert 4 == 8" in result.compressed_text
    assert len(result.compressed_text) < len(run) / 4
