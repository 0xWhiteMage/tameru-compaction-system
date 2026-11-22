"""Round-3 engine_bench corpus: deterministic build, family-pure split, non-overlap, minimums, sealed guard."""
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
from benchmarks.engine_bench.gen_cases_r2 import BLOCKED_FCLASSES, FAMILIES as R2_FAMILIES, generated_cases_r2  # noqa: E402
from benchmarks.engine_bench.gen_cases_r3 import FAMILIES, generated_cases_r3  # noqa: E402
from benchmarks.session_corpus import families as session_families  # noqa: E402

BENCH = ROOT / "benchmarks" / "engine_bench"


@pytest.fixture(scope="module")
def r3_cases():
    return corpus._build_r3()


@pytest.fixture(scope="module")
def r3_doc():
    return corpus.load_splits_r3()


def _canonical(cases):
    return json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_two_builds_byte_identical():
    assert _canonical(generated_cases_r3()) == _canonical(generated_cases_r3())


def test_family_purity_across_splits(r3_cases, r3_doc):
    fams = r3_doc["families"]
    assert set(fams) == {c["family"] for c in r3_cases}
    per_family = defaultdict(set)
    per_cluster = defaultdict(set)
    for c in r3_cases:
        per_family[c["family"]].add(fams[c["family"]])
        per_cluster[c["source_case"]].add(fams[c["family"]])
    assert all(len(v) == 1 for v in per_family.values())
    assert all(len(v) == 1 for v in per_cluster.values())
    assert set(fams.values()) <= {"dev", "validation", "sealed"}
    assert {"dev", "validation"} <= set(fams.values())


def test_non_overlap_with_prior_rounds_and_session_corpus(r3_cases):
    r3_ids = {f["id"] for f in FAMILIES}
    session_ids = {f.id for f in session_families.FAMILIES}
    assert not (r3_ids & session_ids), r3_ids & session_ids
    r1_shapes = {c["shape"] for c in corpus._build_all()} | {c["source_case"] for c in corpus._build_all()}
    assert not (r3_ids & r1_shapes), r3_ids & r1_shapes
    # Every r2 family — dev, validation AND the 20 burned sealed ones — is excluded:
    # a family the r2 look saw cannot measure the r3 look (ANALYSIS-PLAN-ROUND2).
    r2_ids = {f["id"] for f in R2_FAMILIES}
    assert not (r3_ids & r2_ids), r3_ids & r2_ids
    r2_shapes = {c["shape"] for c in generated_cases_r2()}
    r3_shapes = {c["shape"] for c in r3_cases}
    assert not (r3_shapes & r1_shapes), r3_shapes & r1_shapes
    assert not (r3_shapes & r2_shapes), r3_shapes & r2_shapes
    # format-class blocklist: no r3 family may be a class that duplicates r1/session formats
    blocked = {f["id"]: f["fclass"] for f in FAMILIES if f["fclass"] in BLOCKED_FCLASSES}
    assert not blocked, blocked
    assert all(f["fclass"] for f in FAMILIES)  # every family is tagged


def test_split_minimums_from_metadata(r3_doc):
    assert split.check_r3_minimums(r3_doc) == []
    counts = r3_doc["counts"]
    assert counts["dev"]["families"] >= 6
    assert counts["validation"]["families"] >= 6
    st = split.r3_sealed_stats(r3_doc)
    if not r3_doc.get("burn"):
        # No sealed holdout exists between a spent look and the next deal.
        assert r3_doc["counts"]["sealed"]["families"] >= 24
        assert st["cases"] >= 400 and st["clusters"] >= 250
        assert st["buried_en_clusters"] >= 40 and st["buried_zh_clusters"] >= 40
        assert st["csv_args_clusters"] >= 40 and st["superseded_clusters"] >= 20 and st["evidence_clusters"] >= 80
        assert st["s5_facts"] >= 200


def test_language_share(r3_cases):
    langs = Counter(c["language"] for c in r3_cases)
    share = (langs["zh"] + langs["mixed"]) / len(r3_cases)
    assert 0.20 <= share <= 0.45, langs


def test_query_conditions_present(r3_cases):
    for c in r3_cases:
        q = c["queries"]
        assert {"task_specific", "task_vague", "tool_call", "generic", "build_specific", "build_vague"} <= set(q)
        assert ("zh_user" in q) == (c["language"] in ("zh", "mixed"))
        import unicodedata
        nfkc = lambda s: unicodedata.normalize("NFKC", s)  # build_query emits the engine's NFKC view
        assert nfkc(q["tool_call"]) in nfkc(q["build_specific"]) and nfkc(q["tool_call"]) in nfkc(q["build_vague"])
        assert nfkc(q["task_specific"]) in nfkc(q["build_specific"]) and nfkc(q["task_vague"]) in nfkc(q["build_vague"])


def test_s5_fact_gold_in_text(r3_cases):
    s5 = [c for c in r3_cases if c["item_kind"] != "evidence"]
    assert s5 and all("fact" in c for c in s5)
    for c in s5:
        fact, text = c["fact"], c["text"]
        assert c["gold"] == [fact["line"]]
        assert fact["line"] in text
        assert fact["key"] in fact["line"] and fact["value"] in fact["line"]
        if c["item_kind"] == "s5_superseded":
            assert c["forbidden"] and all(f in text for f in c["forbidden"])


def test_sealed_r3_refusal_without_flags(r3_doc):
    with pytest.raises(corpus.SealedAccessError):
        corpus.load_cases_r3(["sealed"])
    with pytest.raises(corpus.SealedAccessError):
        corpus.load_cases_r3(["dev", "sealed"])
    looks = corpus.SEALED_LOOKS_R3_FILE
    before = looks.read_bytes() if looks.exists() else None
    assert run.main(["--round", "3", "--split", "sealed", "--quiet"]) == 2   # refuses: no --sealed
    assert run.main(["--round", "3", "--sealed", "--quiet"]) == 2           # refuses: no --candidate
    assert (looks.read_bytes() if looks.exists() else None) == before     # and logged nothing


def test_no_sealed_r3_text_in_committed_files(r3_cases, r3_doc):
    fams = r3_doc["families"]
    sealed = [c for c in r3_cases if fams[c["family"]] == "sealed"]
    sample = [c["fact"]["line"] for c in sealed if "fact" in c][::7]
    sample += [c["gold"][0] for c in sealed[::17]]
    for needle in sample:
        # results/ holds committed run evidence which legitimately quotes prior-round text
        # (e.g. r2 diagnosis rows); fact lines share a small key vocabulary, so a generic
        # "key: value" may collide there — that is not an r3 corpus leak.
        found = subprocess.run(["git", "grep", "-l", "-F", needle, "--",
                                ":!benchmarks/engine_bench/gen_cases_r3.py",
                                ":!benchmarks/engine_bench/results/"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        assert not found, f"sealed r3 text leaked into {found}"


def test_round1_split_check_unchanged():
    assert split.main(["--check"]) == 0


def test_r3_split_check():
    assert split.main(["--check", "--round", "3"]) == 0
