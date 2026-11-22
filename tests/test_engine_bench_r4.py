"""Round-4 engine_bench corpus: deterministic build, family-pure split, non-overlap, minimums, sealed guard."""
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
from benchmarks.engine_bench.gen_cases_r3 import FAMILIES as R3_FAMILIES, generated_cases_r3  # noqa: E402
from benchmarks.engine_bench.gen_cases_r4 import FAMILIES, generated_cases_r4  # noqa: E402
from benchmarks.session_corpus import families as session_families  # noqa: E402

BENCH = ROOT / "benchmarks" / "engine_bench"


@pytest.fixture(scope="module")
def r4_cases():
    return corpus._build_r4()


@pytest.fixture(scope="module")
def r4_doc():
    return corpus.load_splits_r4()


def _canonical(cases):
    return json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_two_builds_byte_identical():
    assert _canonical(generated_cases_r4()) == _canonical(generated_cases_r4())


def test_family_purity_across_splits(r4_cases, r4_doc):
    fams = r4_doc["families"]
    assert set(fams) == {c["family"] for c in r4_cases}
    per_family = defaultdict(set)
    per_cluster = defaultdict(set)
    for c in r4_cases:
        per_family[c["family"]].add(fams[c["family"]])
        per_cluster[c["source_case"]].add(fams[c["family"]])
    assert all(len(v) == 1 for v in per_family.values())
    assert all(len(v) == 1 for v in per_cluster.values())
    assert set(fams.values()) <= {"dev", "validation", "sealed"}
    assert {"dev", "validation"} <= set(fams.values())


def test_non_overlap_with_prior_rounds_and_session_corpus(r4_cases):
    r4_ids = {f["id"] for f in FAMILIES}
    session_ids = {f.id for f in session_families.FAMILIES}
    assert not (r4_ids & session_ids), r4_ids & session_ids
    r1_shapes = {c["shape"] for c in corpus._build_all()} | {c["source_case"] for c in corpus._build_all()}
    assert not (r4_ids & r1_shapes), r4_ids & r1_shapes
    # Every prior-round family — dev, validation AND every burned sealed one — is excluded:
    # a family an earlier look saw cannot measure the r4 look (ANALYSIS-PLAN-ROUND2).
    r2_ids = {f["id"] for f in R2_FAMILIES}
    assert not (r4_ids & r2_ids), r4_ids & r2_ids
    r3_ids = {f["id"] for f in R3_FAMILIES}
    assert not (r4_ids & r3_ids), r4_ids & r3_ids
    r2_shapes = {c["shape"] for c in generated_cases_r2()}
    r3_shapes = {c["shape"] for c in generated_cases_r3()}
    r4_shapes = {c["shape"] for c in r4_cases}
    assert not (r4_shapes & r1_shapes), r4_shapes & r1_shapes
    assert not (r4_shapes & r2_shapes), r4_shapes & r2_shapes
    assert not (r4_shapes & r3_shapes), r4_shapes & r3_shapes
    # format-class blocklist: no r4 family may be a class that duplicates r1/session formats
    blocked = {f["id"]: f["fclass"] for f in FAMILIES if f["fclass"] in BLOCKED_FCLASSES}
    assert not blocked, blocked
    assert all(f["fclass"] for f in FAMILIES)  # every family is tagged


def test_split_minimums_from_metadata(r4_doc):
    assert split.check_r4_minimums(r4_doc) == []
    counts = r4_doc["counts"]
    assert counts["dev"]["families"] >= 6
    assert counts["validation"]["families"] >= 6
    st = split.r4_sealed_stats(r4_doc)
    if not r4_doc.get("burn"):
        # No sealed holdout exists between a spent look and the next deal.
        assert r4_doc["counts"]["sealed"]["families"] >= 24
        assert st["cases"] >= 400 and st["clusters"] >= 250
        assert st["buried_en_clusters"] >= 40 and st["buried_zh_clusters"] >= 40
        assert st["csv_args_clusters"] >= 40 and st["superseded_clusters"] >= 20 and st["evidence_clusters"] >= 80
        assert st["s5_facts"] >= 200


def test_language_share(r4_cases):
    langs = Counter(c["language"] for c in r4_cases)
    share = (langs["zh"] + langs["mixed"]) / len(r4_cases)
    assert 0.20 <= share <= 0.45, langs


def test_query_conditions_present(r4_cases):
    for c in r4_cases:
        q = c["queries"]
        assert {"task_specific", "task_vague", "tool_call", "generic", "build_specific", "build_vague"} <= set(q)
        assert ("zh_user" in q) == (c["language"] in ("zh", "mixed"))
        import unicodedata
        nfkc = lambda s: unicodedata.normalize("NFKC", s)  # build_query emits the engine's NFKC view
        assert nfkc(q["tool_call"]) in nfkc(q["build_specific"]) and nfkc(q["tool_call"]) in nfkc(q["build_vague"])
        assert nfkc(q["task_specific"]) in nfkc(q["build_specific"]) and nfkc(q["task_vague"]) in nfkc(q["build_vague"])


def test_s5_fact_gold_in_text(r4_cases):
    s5 = [c for c in r4_cases if c["item_kind"] != "evidence"]
    assert s5 and all("fact" in c for c in s5)
    for c in s5:
        fact, text = c["fact"], c["text"]
        assert c["gold"] == [fact["line"]]
        assert fact["line"] in text
        assert fact["key"] in fact["line"] and fact["value"] in fact["line"]
        if c["item_kind"] == "s5_superseded":
            assert c["forbidden"] and all(f in text for f in c["forbidden"])


def test_sealed_r4_refusal_without_flags(r4_doc):
    with pytest.raises(corpus.SealedAccessError):
        corpus.load_cases_r4(["sealed"])
    with pytest.raises(corpus.SealedAccessError):
        corpus.load_cases_r4(["dev", "sealed"])
    looks = corpus.SEALED_LOOKS_R4_FILE
    before = looks.read_bytes() if looks.exists() else None
    assert run.main(["--round", "4", "--split", "sealed", "--quiet"]) == 2   # refuses: no --sealed
    assert run.main(["--round", "4", "--sealed", "--quiet"]) == 2           # refuses: no --candidate
    assert (looks.read_bytes() if looks.exists() else None) == before     # and logged nothing


def test_no_sealed_r4_text_in_committed_files(r4_cases, r4_doc):
    fams = r4_doc["families"]
    sealed = [c for c in r4_cases if fams[c["family"]] == "sealed"]
    sample = [c["fact"]["line"] for c in sealed if "fact" in c][::7]
    sample += [c["gold"][0] for c in sealed[::17]]
    for needle in sample:
        # results/ holds committed run evidence which legitimately quotes prior-round text
        # (e.g. r3 diagnosis rows); fact lines share a small key vocabulary, so a generic
        # "key: value" may collide there — that is not an r4 corpus leak.
        found = subprocess.run(["git", "grep", "-l", "-F", needle, "--",
                                ":!benchmarks/engine_bench/gen_cases_r4.py",
                                ":!benchmarks/engine_bench/results/"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        assert not found, f"sealed r4 text leaked into {found}"


def test_round1_split_check_unchanged():
    assert split.main(["--check"]) == 0


def test_r4_split_check():
    assert split.main(["--check", "--round", "4"]) == 0
