"""Session corpus (round 2, P2a): determinism, family/split purity, sizes, language and real shares, trigger-crossing
lengths, holdout refusal, no holdout text in committed files.  Tests that need the Squeez file skip without it."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.session_corpus import build, corpus, equivalence, families, real  # noqa: E402
from benchmarks.session_corpus import generator as g  # noqa: E402

HERE = ROOT / "benchmarks" / "session_corpus"
HAVE_SQUEEZ = real.DEFAULT_SQUEEZ.is_file()
needs_squeez = pytest.mark.skipif(not HAVE_SQUEEZ, reason=f"Squeez file absent: put canonical_test.jsonl at {real.DEFAULT_SQUEEZ}")


@pytest.fixture(scope="module")
def plans():
    return {s: corpus._plans(s) for s in corpus.SPLITS}


@pytest.fixture(scope="module")
def texts():
    return real.RealTexts() if HAVE_SQUEEZ else None


def test_families_registry():
    assert len(families.FAMILIES) >= 32
    burned = {f.id for f in families.FAMILIES if f.burned_round1}
    assert burned == set(corpus.BURNED_ROUND1_FAMILIES.values())
    for f in families.FAMILIES:
        assert f.fill_en and f.fill_zh and len(f.shapes) >= 2
        assert "{keys}" in f.task_en and "{keys}" in f.task_zh and "{keys}" not in f.vague_en + f.vague_zh


def test_splits_match_the_logged_deal_and_are_family_pure(plans):
    doc = corpus.load_splits()
    assert corpus.SPLITS_FILE.read_text(encoding="utf-8") == corpus.splits_blob(corpus.splits_doc(doc["deal"]["seed"], doc["deal"]["attempt"]))
    fams = doc["families"]
    assert set(fams) == {f.id for f in families.FAMILIES}
    for split, ps in plans.items():
        assert {p.family.id for p in ps} == {f for f, s in fams.items() if s == split}
    seen = defaultdict(set)
    for split, ps in plans.items():
        for p in ps:
            seen[p.family.id].add(split)
    assert all(len(v) == 1 for v in seen.values())
    for fid in corpus.BURNED_ROUND1_FAMILIES.values():
        assert fams[fid] == "dev"


def test_split_sizes(plans):
    nfam = Counter(corpus.family_split().values())
    assert nfam["dev"] >= 8 and nfam["validation"] >= 8 and nfam["holdout"] >= 24
    assert 250 <= len(plans["holdout"]) <= 300
    for split, ps in plans.items():
        assert len({p.seed for p in ps}) >= 40, split            # clusters = independent scenario seeds
        per_family = Counter(p.family.id for p in ps)
        assert all(8 <= n <= 12 for n in per_family.values())


def test_language_share_about_thirty_percent_chinese(plans):
    allp = [p for ps in plans.values() for p in ps]
    share = sum(p.language == "zh" for p in allp) / len(allp)
    assert 0.27 <= share <= 0.33, share
    for split, ps in plans.items():
        s = sum(p.language == "zh" for p in ps) / len(ps)
        assert 0.22 <= s <= 0.38, (split, s)
    assert {p.style for ps in plans.values() for p in ps} == {"specific", "vague"}


def test_real_output_share_at_least_thirty_percent(plans):
    for split, ps in plans.items():
        tot = sum(sum(p.chars) for p in ps)
        rc = sum(c for p in ps for c, k in zip(p.chars, p.kinds) if k == "real")
        assert rc / tot >= 0.30, (split, rc / tot)
        for p in ps:                                                # every gated window's slice too
            n = p.windows[252_000]
            assert sum(c for c, k in zip(p.chars[:n], p.kinds[:n]) if k == "real") / sum(p.chars[:n]) >= 0.25, p.id


def test_real_pools_by_repository_never_shared_with_the_holdout(plans):
    m = real.load_manifest()
    holdout_repos = {r for r, s in m["repo_splits"].items() if "holdout" in s}
    assert all(m["repo_splits"][r] == ["holdout"] for r in holdout_repos)
    by_id = {o["id"]: o["repo"] for o in m["outputs"]}
    for split, ps in plans.items():
        repos = {by_id[o] for p in ps for o in p.real_ids if o}
        assert (repos <= holdout_repos) if split == "holdout" else not (repos & holdout_repos), split


def test_trigger_crossing_lengths(plans):
    for ps in plans.values():
        for p in ps:
            assert 2000 <= min(p.chars) and max(p.chars) <= 60000
            for w in g.WINDOWS:
                total = sum(p.chars[:p.windows[w]])
                for trig in (g.ds_trigger(w), g.hermes_trigger(w)):
                    assert total >= 1.6 * g.CHARS_PER_TOKEN * trig, (p.id, w)
    for split, ps in plans.items():                                 # rho 0.3 retention model, gated windows
        for w in (128_000, 252_000, 500_000):
            for trig in (g.ds_trigger(w), g.hermes_trigger(w)):
                c = [equivalence.crossings(p.chars[:p.windows[w]], trig) for p in ps]
                assert sum(x >= 1 for x in c) / len(c) >= 0.70 and sum(x >= 2 for x in c) / len(c) >= 0.30, (split, w)
    assert g.ds_trigger(252_000) == 178_464 and g.ds_trigger(500_000) == 400_000 and g.ds_trigger(1_000_000) == 800_000
    assert g.ds_trigger(128_000) == 54_464 and g.ds_trigger(200_000) == 126_464


def test_plan_is_window_independent_and_deterministic(plans):
    p = plans["dev"][3]
    q = corpus._plans("dev")[3]
    assert (p.chars, p.kinds, p.real_ids, p.windows) == (q.chars, q.kinds, q.real_ids, q.windows)
    assert [vars(f) for f in p.facts] == [vars(f) for f in q.facts]
    for i in range(0, 40):
        if p.kinds[i] == "synthetic":
            assert g.step_text(p, i) == g.step_text(q, i)


@needs_squeez
def test_two_builds_byte_identical_and_slices_are_prefixes(plans, texts):
    for p in plans["dev"][::29] + plans["validation"][::29]:
        a = corpus.canonical(corpus.export(p, texts, 128_000))
        b = corpus.canonical(corpus.export(next(x for x in corpus._plans(p.pool) if x.id == p.id), texts, 128_000))
        assert a == b
        small, big = corpus.export(p, texts, 128_000), corpus.export(p, texts, 252_000)
        assert big["steps"][:len(small["steps"])] == small["steps"]


@needs_squeez
def test_export_schema_facts_and_questions(plans, texts):
    for p in plans["dev"][:4] + plans["validation"][:2]:
        sc = corpus.export(p, texts, 252_000)
        assert sc["language"] in ("en", "zh", "mixed") and sc["task_style"] in ("specific", "vague")
        ids = {}
        for st in sc["steps"]:
            assert st["kind"] in ("filler", "fact", "error", "real")
            lines = st["output_text"].split("\n")
            for f in st["facts"]:
                assert f["value"] in lines[f["line_index"]]
                if f["kind"] != "real":
                    assert f["key"] in lines[f["line_index"]]
                ids[f["id"]] = st["index"]
        strata = Counter(q["stratum"] for q in sc["questions"])
        assert strata["buried"] + strata["superseded"] >= 2 and strata["absent"] == 1 and strata["single"] >= 4
        for q in sc["questions"]:
            assert q["first_window"] <= 252_000 and all(fid in ids for fid in q["fact_ids"])
        keys = [f["key"] for st in sc["steps"] for f in st["facts"] if f["kind"] in ("natural", "error", "buried")]
        if sc["task_style"] == "specific":
            assert all(k in sc["task"] for k in keys)
        else:
            assert not any(k in sc["task"] for k in keys)


@needs_squeez
def test_manifest_rebuild_is_byte_identical(texts):
    assert real.manifest_blob(real.build_manifest(real.read_rows())) == real.MANIFEST_FILE.read_text(encoding="utf-8")
    for o in real.load_manifest()["outputs"][::37]:
        assert hashlib.sha256(texts.text(o["id"]).encode("utf-8")).hexdigest() == o["sha256"]


@needs_squeez
def test_sealed_holdout_hash_matches(texts):
    assert corpus.split_digest(corpus._plans("holdout"), texts) == corpus.SEALED_HASH_FILE.read_text().split()[0]


def test_holdout_refused_without_flags():
    before = corpus.LOOKS_FILE.read_bytes() if corpus.LOOKS_FILE.exists() else None
    with pytest.raises(corpus.HoldoutAccessError):
        next(corpus.scenarios("holdout"))
    with pytest.raises(corpus.HoldoutAccessError):
        next(corpus.scenarios("holdout", holdout=True))
    with pytest.raises(corpus.HoldoutAccessError):
        next(corpus.scenarios("holdout", candidate="x"))
    assert build.main(["--split", "holdout"]) == 2
    assert build.main(["--split", "holdout", "--holdout"]) == 2
    assert build.main(["--split", "dev", "--holdout", "--candidate", "x"]) == 2
    assert (corpus.LOOKS_FILE.read_bytes() if corpus.LOOKS_FILE.exists() else None) == before


def test_no_holdout_text_in_committed_files(plans):
    files = [f for f in HERE.rglob("*") if f.is_file() and "__pycache__" not in f.parts]
    assert all(f.stat().st_size < 1_500_000 for f in files)
    blob = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files)
    vocab = set(families.PKGS) | set(families.WORDS) | set(families.REASONS) | set(families.TF_TYPES)  # single vocabulary words
    needles = set()
    for p in plans["holdout"]:
        for f in p.facts:
            if f.kind in ("natural", "error", "buried", "stale"):
                needles.update(s for s in (f.key, f.value) if len(s) >= 8 and s not in vocab)
        if p.style == "specific":
            needles.add(g.task_text(p))
    assert len(needles) > 500
    leaked = [n for n in needles if n in blob]
    assert not leaked, f"{len(leaked)} holdout strings found in committed files"


def test_equivalence_result_registered_and_passing():
    res = json.loads(equivalence.RESULT_FILE.read_text(encoding="utf-8"))
    body = {k: v for k, v in res.items() if k != "result_sha256"}
    assert hashlib.sha256(corpus.canonical(body).encode("utf-8")).hexdigest() == res["result_sha256"]
    assert res["pass"] is True and res["deal"] == corpus.load_splits()["deal"]
    assert res["sealed_holdout_sha256"] == corpus.SEALED_HASH_FILE.read_text().split()[0]
    for c in res["comparisons"].values():
        assert c["auc_family_grouped"] <= 0.65
    for a in res["acceptance"].values():
        assert a["gap_points"] <= 10.0
    desc = equivalence.DESCRIPTORS_FILE.read_text(encoding="utf-8")
    assert hashlib.sha256(desc.encode("utf-8")).hexdigest() == res["descriptors_sha256"]
