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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
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
