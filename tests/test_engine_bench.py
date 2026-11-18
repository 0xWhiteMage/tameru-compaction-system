"""Engine benchmark harness: deterministic cluster-pure split, sealed guard, arm-vs-self 0, byte-deterministic runs."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.engine_bench import corpus, report, run, split  # noqa: E402

BENCH = ROOT / "benchmarks" / "engine_bench"


@pytest.fixture(scope="module")
def all_cases():
    return corpus._build_all()


def test_corpus_size_and_shapes(all_cases):
    assert len(all_cases) >= 150
    splits = corpus.load_splits()
    assert sum(1 for v in splits.values() if v == "sealed") >= 40
    shapes = [c["shape"] for c in all_cases]
    assert sum(s == "trace-java" for s in shapes) + sum(c["id"].startswith("gen-java-chain") for c in all_cases) >= 6
    assert len({c["source_case"] for c in all_cases if c["id"].startswith("gen-java-chain")}) >= 6
    assert len({c["source_case"] for c in all_cases if c["id"].startswith("gen-dotnet-chain")}) >= 6
    assert {c["language"] for c in all_cases} >= {"en", "zh", "mixed"}
    for c in all_cases:
        assert {"task", "tool_call", "generic"} <= set(c["queries"])
        assert ("zh_user" in c["queries"]) == (c["language"] in ("zh", "mixed"))


def test_split_is_deterministic_and_matches_committed_files(all_cases):
    a, b = split.assign(all_cases), split.assign(list(reversed(all_cases)))
    assert a == b
    assert json.loads((BENCH / "splits.json").read_text(encoding="utf-8")) == a
    sealed = [c for c in all_cases if a[c["id"]] == "sealed"]
    assert corpus.sealed_digest(sealed) == (BENCH / "SEALED.sha256").read_text().split()[0]


def test_split_is_cluster_pure(all_cases):
    splits = corpus.load_splits()
    seen = defaultdict(set)
    for c in all_cases:
        seen[c["source_case"]].add(splits[c["id"]])
    assert all(len(v) == 1 for v in seen.values())
    assert set(splits.values()) == {"dev", "validation", "sealed"}


def test_sealed_texts_unreadable_without_flag(tmp_path):
    with pytest.raises(corpus.SealedAccessError):
        corpus.load_cases(["sealed"])
    with pytest.raises(corpus.SealedAccessError):
        corpus.load_cases(["dev", "sealed"])
    splits = corpus.load_splits()
    assert all(splits[c["id"]] != "sealed" for c in corpus.load_cases(["dev", "validation"]))
    looks = BENCH / "sealed_looks.json"
    before = looks.read_bytes() if looks.exists() else None
    assert run.main(["--split", "sealed", "--quiet"]) == 2           # refuses: no --sealed
    assert run.main(["--sealed", "--quiet"]) == 2                    # refuses: no --candidate
    assert (looks.read_bytes() if looks.exists() else None) == before  # and logged nothing


def _subset(n=14):
    cases = corpus.load_cases(["dev"])
    seen, out = set(), []
    for c in cases:                                                   # one case per shape, first n
        if c["shape"] not in seen:
            seen.add(c["shape"])
            out.append(c)
    return out[:n]


def _strip(rows):
    return [run.dumps({k: v for k, v in r.items() if k != "wall_ms"}) for r in rows]


def test_runner_is_byte_deterministic():
    splits = corpus.load_splits()
    cases = _subset()
    first, second = run.run(cases, splits), run.run(cases, splits)
    assert _strip(first) == _strip(second)
    assert first and all(r["bench"] == "engine" and r["engine"] for r in first)
    assert {"deepseek", "hermes"} == {r["profile"] for r in first}


def test_arm_vs_self_difference_is_exactly_zero():
    rows = run.run(_subset(10), corpus.load_splits())
    assert report.selfcheck(rows)
    for metric in ("saved_pct", "gold_kept", "confidence"):
        d = report.paired_diff(rows, rows, metric)
        assert (d["mean"], d["lo"], d["hi"]) == (0, 0, 0) and d["clusters"] > 1
    shifted = [dict(r, saved_pct=r["saved_pct"] + 1.0) for r in rows]
    assert report.paired_diff(rows, shifted, "saved_pct")["mean"] == pytest.approx(1.0)


def test_auroc_and_bootstrap_helpers():
    assert report.auroc([0.1, 0.2, 0.8, 0.9], [False, False, True, True]) == 1.0
    assert report.auroc([0.5, 0.5, 0.5, 0.5], [False, True, False, True]) == 0.5
    assert report.auroc([0.9, 0.8], [True, True]) is None
    pairs = [(f"c{i % 5}", float(i)) for i in range(50)]
    assert report.cluster_mean(pairs) == report.cluster_mean(pairs)    # seeded
    assert report.cluster_mean(pairs)["clusters"] == 5
