"""Round-2 engine_bench corpus: deterministic build, family-pure split, non-overlap, minimums, sealed guard."""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.engine_bench import corpus, run, split  # noqa: E402
from benchmarks.engine_bench.gen_cases_r2 import BLOCKED_FCLASSES, FAMILIES, generated_cases_r2  # noqa: E402
from benchmarks.session_corpus import families as session_families  # noqa: E402

BENCH = ROOT / "benchmarks" / "engine_bench"


@pytest.fixture(scope="module")
def r2_cases():
    return corpus._build_r2()


@pytest.fixture(scope="module")
def r2_doc():
    return corpus.load_splits_r2()


def _canonical(cases):
    return json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_two_builds_byte_identical():
    assert _canonical(generated_cases_r2()) == _canonical(generated_cases_r2())


def test_family_purity_across_splits(r2_cases, r2_doc):
    fams = r2_doc["families"]
    assert set(fams) == {c["family"] for c in r2_cases}
    per_family = defaultdict(set)
    per_cluster = defaultdict(set)
    for c in r2_cases:
        per_family[c["family"]].add(fams[c["family"]])
        per_cluster[c["source_case"]].add(fams[c["family"]])
    assert all(len(v) == 1 for v in per_family.values())
    assert all(len(v) == 1 for v in per_cluster.values())
    # A spent look burns its sealed families into dev (ANALYSIS-PLAN protocol), so
    # "sealed" may be absent between looks; dev and validation must always be present.
    assert set(fams.values()) <= {"dev", "validation", "sealed"}
    assert {"dev", "validation"} <= set(fams.values())


def test_non_overlap_with_round1_and_session_corpus():
    r2_ids = {f["id"] for f in FAMILIES}
    session_ids = {f.id for f in session_families.FAMILIES}
    assert not (r2_ids & session_ids), r2_ids & session_ids
    r1_shapes = {c["shape"] for c in corpus._build_all()} | {c["source_case"] for c in corpus._build_all()}
    assert not (r2_ids & r1_shapes), r2_ids & r1_shapes
    r2_shapes = {c["shape"] for c in generated_cases_r2()}
    assert not (r2_shapes & r1_shapes), r2_shapes & r1_shapes
    # format-class blocklist: no r2 family may be a class that duplicates r1/session formats
    blocked = {f["id"]: f["fclass"] for f in FAMILIES if f["fclass"] in BLOCKED_FCLASSES}
    assert not blocked, blocked
    assert all(f["fclass"] for f in FAMILIES)  # every family is tagged


def test_split_minimums_from_metadata(r2_doc):
    assert split.check_r2_minimums(r2_doc) == []
    counts = r2_doc["counts"]
    assert counts["dev"]["families"] >= 8
    assert counts["validation"]["families"] >= 8
    st = split.r2_sealed_stats(r2_doc)
    if not r2_doc.get("burn"):
        # No sealed holdout exists between a spent look and the next deal.
        assert st["cases"] >= 160 and st["clusters"] >= 40
        assert st["buried_en_clusters"] >= 30 and st["buried_zh_clusters"] >= 30
        assert st["csv_args_clusters"] >= 20 and st["superseded_clusters"] >= 10 and st["evidence_clusters"] >= 40
        assert st["s5_facts"] >= 120


def test_language_share(r2_cases):
    langs = Counter(c["language"] for c in r2_cases)
    share = (langs["zh"] + langs["mixed"]) / len(r2_cases)
    assert 0.20 <= share <= 0.45, langs


def test_query_conditions_present(r2_cases):
    for c in r2_cases:
        q = c["queries"]
        assert {"task_specific", "task_vague", "tool_call", "generic", "build_specific", "build_vague"} <= set(q)
        assert ("zh_user" in q) == (c["language"] in ("zh", "mixed"))
        import unicodedata
        nfkc = lambda s: unicodedata.normalize("NFKC", s)  # build_query emits the engine's NFKC view
        assert nfkc(q["tool_call"]) in nfkc(q["build_specific"]) and nfkc(q["tool_call"]) in nfkc(q["build_vague"])
        assert nfkc(q["task_specific"]) in nfkc(q["build_specific"]) and nfkc(q["task_vague"]) in nfkc(q["build_vague"])


def test_s5_fact_gold_in_text(r2_cases):
    s5 = [c for c in r2_cases if c["item_kind"] != "evidence"]
    assert s5 and all("fact" in c for c in s5)
    for c in s5:
        fact, text = c["fact"], c["text"]
        assert c["gold"] == [fact["line"]]
        assert fact["line"] in text
        assert fact["key"] in fact["line"] and fact["value"] in fact["line"]
        if c["item_kind"] == "s5_superseded":
            assert c["forbidden"] and all(f in text for f in c["forbidden"])


def test_sealed_r2_refusal_without_flags(r2_doc):
    with pytest.raises(corpus.SealedAccessError):
        corpus.load_cases_r2(["sealed"])
    with pytest.raises(corpus.SealedAccessError):
        corpus.load_cases_r2(["dev", "sealed"])
    looks = corpus.SEALED_LOOKS_R2_FILE
    before = looks.read_bytes() if looks.exists() else None
    assert run.main(["--round", "2", "--split", "sealed", "--quiet"]) == 2   # refuses: no --sealed
    assert run.main(["--round", "2", "--sealed", "--quiet"]) == 2           # refuses: no --candidate
    assert (looks.read_bytes() if looks.exists() else None) == before     # and logged nothing


def test_no_sealed_r2_text_in_committed_files(r2_cases, r2_doc):
    fams = r2_doc["families"]
    sealed = [c for c in r2_cases if fams[c["family"]] == "sealed"]
    sample = [c["fact"]["line"] for c in sealed if "fact" in c][::7]
    sample += [c["gold"][0] for c in sealed[::17]]
    for needle in sample:
        found = subprocess.run(["git", "grep", "-l", "-F", needle, "--", ":!benchmarks/engine_bench/gen_cases_r2.py"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        assert not found, f"sealed r2 text leaked into {found}"


def test_round1_split_check_unchanged():
    assert split.main(["--check"]) == 0
