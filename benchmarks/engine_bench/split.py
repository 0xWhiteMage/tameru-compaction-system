"""Deterministic dev / validation / sealed split by source cluster.

Rule: within each stratum (content_type, plus "-nonen" when the language is not English) the
clusters are ordered by sha256(source_case); cluster i of n gets u = (i + off) / n where
off = fraction from sha256(stratum); u < 0.50 -> dev, < 0.70 -> validation, else sealed.  So every
stratum is split 50/20/30 within one cluster of rounding, and a cluster never straddles splits.

    python -m benchmarks.engine_bench.split            # (re)write splits.json + SEALED.sha256
    python -m benchmarks.engine_bench.split --check    # verify the committed files, change nothing

The sealed split may be run only via ``run.py --sealed --candidate NAME`` and each such run appends
{date, engine version, candidate, command} to sealed_looks.json.  The analysis plan allows exactly one
look per host on the final candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter

from . import corpus


def _u(text: str) -> float:
    return int(hashlib.sha256(text.encode()).hexdigest()[:12], 16) / float(16 ** 12)


def assign(cases: list[dict]) -> dict[str, str]:
    stratum_of: dict[str, str] = {}
    for c in sorted(cases, key=lambda c: c["id"]):
        stratum_of.setdefault(c["source_case"], c["content_type"] + ("" if c["language"] == "en" else "-nonen"))
    groups: dict[str, list[str]] = {}
    for source, stratum in stratum_of.items():
        groups.setdefault(stratum, []).append(source)
    split_of: dict[str, str] = {}
    for stratum, sources in groups.items():
        sources.sort(key=lambda s: hashlib.sha256(s.encode()).hexdigest())
        n, off = len(sources), _u("stratum:" + stratum)
        for i, source in enumerate(sources):
            u = (i + off) / n
            split_of[source] = "dev" if u < 0.5 else "validation" if u < 0.7 else "sealed"
    return {c["id"]: split_of[c["source_case"]] for c in sorted(cases, key=lambda c: c["id"])}


def build() -> tuple[dict[str, str], str, list[dict]]:
    cases = corpus._build_all()
    splits = assign(cases)
    sealed = [c for c in cases if splits[c["id"]] == "sealed"]
    return splits, corpus.sealed_digest(sealed), cases


# ---------------------------------------------------------------- round 2
R2_SEED_DEFAULT = "r2-deal-2026-11-21-a"
R2_DEAL_RULE = ("families ordered by sha256('<seed>:<family>'); first 10 -> dev, next 10 -> "
                "validation, rest -> sealed")


def deal_r2(families: list[str], seed: str) -> dict[str, str]:
    """Family-level deal for the round-2 split; seed-logged so a failed equivalence check re-deals."""
    order = sorted(families, key=lambda f: hashlib.sha256(f"{seed}:{f}".encode()).hexdigest())
    out = {}
    for i, f in enumerate(order):
        out[f] = "dev" if i < 10 else "validation" if i < 20 else "sealed"
    return out


def r2_doc(seed: str, attempt: int) -> tuple[dict, list[dict]]:
    cases = corpus._build_r2()
    fams = deal_r2(sorted({c["family"] for c in cases}), seed)
    counts = {s: {"families": 0, "cases": 0, "clusters": 0} for s in ("dev", "validation", "sealed")}
    for s in counts:
        sub = [c for c in cases if fams[c["family"]] == s]
        counts[s] = {"families": len({c["family"] for c in sub}), "cases": len(sub),
                     "clusters": len({c["source_case"] for c in sub})}
    return {"deal": {"seed": seed, "attempt": attempt, "rule": R2_DEAL_RULE},
            "families": {f: fams[f] for f in sorted(fams)}, "counts": counts}, cases


def r2_sealed_stats(doc: dict) -> dict:
    """Metadata-only sealed stats for the minimums check (no text is read)."""
    fams = doc["families"]
    cases = [c for c in corpus._build_r2() if fams[c["family"]] == "sealed"]
    return {"cases": len(cases), "clusters": len({c["source_case"] for c in cases}),
            "buried_en_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_buried" and c["language"] == "en"}),
            "buried_zh_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_buried" and c["language"] == "zh"}),
            "csv_args_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "csv_args"}),
            "superseded_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_superseded"}),
            "evidence_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "evidence"}),
            "s5_facts": sum(1 for c in cases if "fact" in c)}


def check_r2_minimums(doc: dict) -> list[str]:
    fams = doc["families"]
    n = {s: sum(1 for v in fams.values() if v == s) for s in ("dev", "validation", "sealed")}
    bad = []
    if n["dev"] < 8:
        bad.append(f"dev families {n['dev']} < 8")
    if n["validation"] < 8:
        bad.append(f"validation families {n['validation']} < 8")
    # A spent look burns its sealed families into dev (the "burn" block records
    # the look, hash and moved families); between looks there is no sealed
    # holdout to check. Fresh deals carry no "burn" key, so the sealed floors
    # still gate any newly dealt corpus.
    if doc.get("burn"):
        return bad
    if n["sealed"] < 16:
        bad.append(f"sealed families {n['sealed']} < 16")
    st = r2_sealed_stats(doc)
    for name, floor in (("cases", 160), ("clusters", 40), ("buried_en_clusters", 30),
                        ("buried_zh_clusters", 30), ("csv_args_clusters", 20),
                        ("superseded_clusters", 10), ("evidence_clusters", 40), ("s5_facts", 120)):
        if st[name] < floor:
            bad.append(f"sealed {name} {st[name]} < {floor}")
    return bad


def _main_r2(args) -> int:
    stored = json.loads(corpus.SPLITS_R2_FILE.read_text(encoding="utf-8")) if corpus.SPLITS_R2_FILE.exists() else None
    if args.check:
        assert stored, "splits_r2.json missing"
        doc, cases = r2_doc(stored["deal"]["seed"], stored["deal"]["attempt"])
        blob = json.dumps(doc, indent=1, sort_keys=True) + "\n"
        digest = corpus.sealed_digest([c for c in cases if doc["families"][c["family"]] == "sealed"])
        ok = (corpus.SPLITS_R2_FILE.read_text(encoding="utf-8") == blob
              and corpus.SEALED_R2_HASH_FILE.read_text().split()[0] == digest)
        print("splits_r2.json and SEALED-R2.sha256 match" if ok else "MISMATCH: r2 corpus or deal changed")
        return 0 if ok else 1
    seed = args.seed or R2_SEED_DEFAULT
    attempt = args.attempt if args.attempt is not None else (stored["deal"]["attempt"] + 1 if stored else 1)
    doc, cases = r2_doc(seed, attempt)
    bad = check_r2_minimums(doc)
    if bad:
        print("sealed/split minimums violated:\n  " + "\n  ".join(bad))
        return 1
    corpus.SPLITS_R2_FILE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    digest = corpus.sealed_digest([c for c in cases if doc["families"][c["family"]] == "sealed"])
    corpus.SEALED_R2_HASH_FILE.write_text(f"{digest}  sealed-r2-cases(id,text_sha256,gold)\n", encoding="utf-8")
    if not corpus.SEALED_LOOKS_R2_FILE.exists():
        corpus.SEALED_LOOKS_R2_FILE.write_text("[]\n", encoding="utf-8")
    print(f"round 2 deal seed={seed} attempt={attempt}: {json.dumps(doc['counts'], sort_keys=True)}\n"
          f"sealed stats={r2_sealed_stats(doc)}\nSEALED-R2.sha256={digest}")
    return 0


# ---------------------------------------------------------------- round 3
R3_SEED_DEFAULT = "r3-deal-2026-11-25"
R3_DEAL_RULE = ("families ordered by sha256('<seed>:<family>'); first 6 -> dev, next 6 -> "
                "validation, rest -> sealed")


def deal_r3(families: list[str], seed: str) -> dict[str, str]:
    """Family-level deal for the round-3 split; seed-logged so a failed equivalence check re-deals."""
    order = sorted(families, key=lambda f: hashlib.sha256(f"{seed}:{f}".encode()).hexdigest())
    out = {}
    for i, f in enumerate(order):
        out[f] = "dev" if i < 6 else "validation" if i < 12 else "sealed"
    return out


def r3_doc(seed: str, attempt: int) -> tuple[dict, list[dict]]:
    cases = corpus._build_r3()
    fams = deal_r3(sorted({c["family"] for c in cases}), seed)
    counts = {s: {"families": 0, "cases": 0, "clusters": 0} for s in ("dev", "validation", "sealed")}
    for s in counts:
        sub = [c for c in cases if fams[c["family"]] == s]
        counts[s] = {"families": len({c["family"] for c in sub}), "cases": len(sub),
                     "clusters": len({c["source_case"] for c in sub})}
    return {"deal": {"seed": seed, "attempt": attempt, "rule": R3_DEAL_RULE},
            "families": {f: fams[f] for f in sorted(fams)}, "counts": counts}, cases


def r3_sealed_stats(doc: dict) -> dict:
    """Metadata-only sealed stats for the minimums check (no text is read)."""
    fams = doc["families"]
    cases = [c for c in corpus._build_r3() if fams[c["family"]] == "sealed"]
    return {"cases": len(cases), "clusters": len({c["source_case"] for c in cases}),
            "buried_en_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_buried" and c["language"] == "en"}),
            "buried_zh_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_buried" and c["language"] == "zh"}),
            "csv_args_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "csv_args"}),
            "superseded_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_superseded"}),
            "evidence_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "evidence"}),
            "s5_facts": sum(1 for c in cases if "fact" in c)}


def check_r3_minimums(doc: dict) -> list[str]:
    fams = doc["families"]
    n = {s: sum(1 for v in fams.values() if v == s) for s in ("dev", "validation", "sealed")}
    bad = []
    if n["dev"] < 6:
        bad.append(f"dev families {n['dev']} < 6")
    if n["validation"] < 6:
        bad.append(f"validation families {n['validation']} < 6")
    if doc.get("burn"):
        return bad
    if n["sealed"] < 24:
        bad.append(f"sealed families {n['sealed']} < 24")
    st = r3_sealed_stats(doc)
    for name, floor in (("cases", 400), ("clusters", 250), ("buried_en_clusters", 40),
                        ("buried_zh_clusters", 40), ("csv_args_clusters", 40),
                        ("superseded_clusters", 20), ("evidence_clusters", 80), ("s5_facts", 200)):
        if st[name] < floor:
            bad.append(f"sealed {name} {st[name]} < {floor}")
    return bad


def _main_r3(args) -> int:
    stored = json.loads(corpus.SPLITS_R3_FILE.read_text(encoding="utf-8")) if corpus.SPLITS_R3_FILE.exists() else None
    if args.check:
        assert stored, "splits_r3.json missing"
        doc, cases = r3_doc(stored["deal"]["seed"], stored["deal"]["attempt"])
        # The look-time sealed corpus hash is registered in SEALED-R3.sha256;
        # compute it before any burn replay moves those families to dev.
        digest = corpus.sealed_digest([c for c in cases if doc["families"][c["family"]] == "sealed"])
        burn = stored.get("burn")
        if burn:
            # A spent look burns its sealed families into dev — replay the
            # recorded burn(s) onto the fresh deal so the integrity check is
            # "corpus or deal changed", not "a look happened".
            for entry in burn:
                for f in entry["families"]:
                    doc["families"][f] = "dev"
            doc["burn"] = burn
            for s in doc["counts"]:
                sub = [c for c in cases if doc["families"][c["family"]] == s]
                doc["counts"][s] = {"families": len({c["family"] for c in sub}), "cases": len(sub),
                                    "clusters": len({c["source_case"] for c in sub})}
        # Semantic compare: a recorded burn is appended to the committed file
        # in the file's own key order, so byte equality with a fresh
        # sort_keys dump cannot hold. Content equality is the integrity check.
        ok = (json.loads(corpus.SPLITS_R3_FILE.read_text(encoding="utf-8")) == doc
              and corpus.SEALED_R3_HASH_FILE.read_text().split()[0] == digest)
        print("splits_r3.json and SEALED-R3.sha256 match" if ok else "MISMATCH: r3 corpus or deal changed")
        return 0 if ok else 1
    seed = args.seed or R3_SEED_DEFAULT
    attempt = args.attempt if args.attempt is not None else (stored["deal"]["attempt"] + 1 if stored else 1)
    doc, cases = r3_doc(seed, attempt)
    bad = check_r3_minimums(doc)
    if bad:
        print("sealed/split minimums violated:\n  " + "\n  ".join(bad))
        return 1
    corpus.SPLITS_R3_FILE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    digest = corpus.sealed_digest([c for c in cases if doc["families"][c["family"]] == "sealed"])
    corpus.SEALED_R3_HASH_FILE.write_text(f"{digest}  sealed-r3-cases(id,text_sha256,gold)\n", encoding="utf-8")
    if not corpus.SEALED_LOOKS_R3_FILE.exists():
        corpus.SEALED_LOOKS_R3_FILE.write_text("[]\n", encoding="utf-8")
    print(f"round 3 deal seed={seed} attempt={attempt}: {json.dumps(doc['counts'], sort_keys=True)}\n"
          f"sealed stats={r3_sealed_stats(doc)}\nSEALED-R3.sha256={digest}")
    return 0


# ---------------------------------------------------------------- round 4
R4_SEED_DEFAULT = "r4-deal-2026-11-25-a"
R4_DEAL_RULE = ("families ordered by sha256('<seed>:<family>'); first 6 -> dev, next 6 -> "
                "validation, rest -> sealed")


def deal_r4(families: list[str], seed: str) -> dict[str, str]:
    """Family-level deal for the round-4 split; seed-logged so a failed equivalence check re-deals."""
    order = sorted(families, key=lambda f: hashlib.sha256(f"{seed}:{f}".encode()).hexdigest())
    out = {}
    for i, f in enumerate(order):
        out[f] = "dev" if i < 6 else "validation" if i < 12 else "sealed"
    return out


def r4_doc(seed: str, attempt: int) -> tuple[dict, list[dict]]:
    cases = corpus._build_r4()
    fams = deal_r4(sorted({c["family"] for c in cases}), seed)
    counts = {s: {"families": 0, "cases": 0, "clusters": 0} for s in ("dev", "validation", "sealed")}
    for s in counts:
        sub = [c for c in cases if fams[c["family"]] == s]
        counts[s] = {"families": len({c["family"] for c in sub}), "cases": len(sub),
                     "clusters": len({c["source_case"] for c in sub})}
    return {"deal": {"seed": seed, "attempt": attempt, "rule": R4_DEAL_RULE},
            "families": {f: fams[f] for f in sorted(fams)}, "counts": counts}, cases


def r4_sealed_stats(doc: dict) -> dict:
    """Metadata-only sealed stats for the minimums check (no text is read)."""
    fams = doc["families"]
    cases = [c for c in corpus._build_r4() if fams[c["family"]] == "sealed"]
    return {"cases": len(cases), "clusters": len({c["source_case"] for c in cases}),
            "buried_en_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_buried" and c["language"] == "en"}),
            "buried_zh_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_buried" and c["language"] == "zh"}),
            "csv_args_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "csv_args"}),
            "superseded_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "s5_superseded"}),
            "evidence_clusters": len({c["source_case"] for c in cases if c["item_kind"] == "evidence"}),
            "s5_facts": sum(1 for c in cases if "fact" in c)}


def check_r4_minimums(doc: dict) -> list[str]:
    fams = doc["families"]
    n = {s: sum(1 for v in fams.values() if v == s) for s in ("dev", "validation", "sealed")}
    bad = []
    if n["dev"] < 6:
        bad.append(f"dev families {n['dev']} < 6")
    if n["validation"] < 6:
        bad.append(f"validation families {n['validation']} < 6")
    if doc.get("burn"):
        return bad
    if n["sealed"] < 24:
        bad.append(f"sealed families {n['sealed']} < 24")
    st = r4_sealed_stats(doc)
    for name, floor in (("cases", 400), ("clusters", 250), ("buried_en_clusters", 40),
                        ("buried_zh_clusters", 40), ("csv_args_clusters", 40),
                        ("superseded_clusters", 20), ("evidence_clusters", 80), ("s5_facts", 200)):
        if st[name] < floor:
            bad.append(f"sealed {name} {st[name]} < {floor}")
    return bad


def _main_r4(args) -> int:
    stored = json.loads(corpus.SPLITS_R4_FILE.read_text(encoding="utf-8")) if corpus.SPLITS_R4_FILE.exists() else None
    if args.check:
        assert stored, "splits_r4.json missing"
        doc, cases = r4_doc(stored["deal"]["seed"], stored["deal"]["attempt"])
        # The look-time sealed corpus hash is registered in SEALED-R4.sha256;
        # compute it before any burn replay moves those families to dev.
        digest = corpus.sealed_digest([c for c in cases if doc["families"][c["family"]] == "sealed"])
        burn = stored.get("burn")
        if burn:
            # A spent look burns its sealed families into dev — replay the
            # recorded burn(s) onto the fresh deal so the integrity check is
            # "corpus or deal changed", not "a look happened".
            for entry in burn:
                for f in entry["families"]:
                    doc["families"][f] = "dev"
            doc["burn"] = burn
            for s in doc["counts"]:
                sub = [c for c in cases if doc["families"][c["family"]] == s]
                doc["counts"][s] = {"families": len({c["family"] for c in sub}), "cases": len(sub),
                                    "clusters": len({c["source_case"] for c in sub})}
        # Semantic compare: a recorded burn is appended to the committed file
        # in the file's own key order, so byte equality with a fresh
        # sort_keys dump cannot hold. Content equality is the integrity check.
        ok = (json.loads(corpus.SPLITS_R4_FILE.read_text(encoding="utf-8")) == doc
              and corpus.SEALED_R4_HASH_FILE.read_text().split()[0] == digest)
        print("splits_r4.json and SEALED-R4.sha256 match" if ok else "MISMATCH: r4 corpus or deal changed")
        return 0 if ok else 1
    seed = args.seed or R4_SEED_DEFAULT
    attempt = args.attempt if args.attempt is not None else (stored["deal"]["attempt"] + 1 if stored else 1)
    doc, cases = r4_doc(seed, attempt)
    bad = check_r4_minimums(doc)
    if bad:
        print("sealed/split minimums violated:\n  " + "\n  ".join(bad))
        return 1
    corpus.SPLITS_R4_FILE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    digest = corpus.sealed_digest([c for c in cases if doc["families"][c["family"]] == "sealed"])
    corpus.SEALED_R4_HASH_FILE.write_text(f"{digest}  sealed-r4-cases(id,text_sha256,gold)\n", encoding="utf-8")
    if not corpus.SEALED_LOOKS_R4_FILE.exists():
        corpus.SEALED_LOOKS_R4_FILE.write_text("[]\n", encoding="utf-8")
    print(f"round 4 deal seed={seed} attempt={attempt}: {json.dumps(doc['counts'], sort_keys=True)}\n"
          f"sealed stats={r4_sealed_stats(doc)}\nSEALED-R4.sha256={digest}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--round", dest="round_", type=int, choices=(1, 2, 3, 4), default=1)
    ap.add_argument("--seed", help="round-2/3/4 deal seed")
    ap.add_argument("--attempt", type=int, default=None, help="round-2/3/4 deal attempt number")
    args = ap.parse_args(argv)
    if args.round_ == 2:
        return _main_r2(args)
    if args.round_ == 3:
        return _main_r3(args)
    if args.round_ == 4:
        return _main_r4(args)
    splits, digest, cases = build()
    blob = json.dumps(splits, indent=1, sort_keys=True) + "\n"
    if args.check:
        ok = corpus.SPLITS_FILE.read_text(encoding="utf-8") == blob and corpus.SEALED_HASH_FILE.read_text().split()[0] == digest
        print("splits.json and SEALED.sha256 match" if ok else "MISMATCH: corpus or split rule changed")
        return 0 if ok else 1
    corpus.SPLITS_FILE.write_text(blob, encoding="utf-8")
    corpus.SEALED_HASH_FILE.write_text(f"{digest}  sealed-cases(id,text_sha256,gold)\n", encoding="utf-8")
    counts = Counter(splits.values())
    clusters = {s: len({c["source_case"] for c in cases if splits[c["id"]] == s}) for s in counts}
    print(f"cases={len(cases)} {dict(counts)} clusters={clusters}\nSEALED.sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
