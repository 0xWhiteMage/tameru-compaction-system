"""Deal families to splits by a logged seed and seal the holdout.

    python -m benchmarks.session_corpus.split --seed SEED --attempt N   # (re)write splits.json + SEALED-HOLDOUT.sha256
    python -m benchmarks.session_corpus.split --check                   # verify both files, change nothing

Both need the Squeez file (default build/session_corpus/squeez/canonical_test.jsonl, or --squeez).  The sealed hash is
sha256 over the sorted [scenario id, scenario digest] rows of every holdout scenario, where a scenario digest covers
its full canonical export (every step's tool, args, kind, facts and the sha256 of its output text, the task, the
questions and the window table).  Only the digest is printed; no holdout text is shown.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import corpus
from . import real as realmod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", help="deal seed (logged in splits.json)")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--squeez", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        real = realmod.RealTexts(args.squeez)
    except realmod.SqueezMissing as e:
        print(f"skip: {e}", file=sys.stderr)
        return 3
    if args.check:
        doc = corpus.load_splits()
        want = corpus.splits_blob(corpus.splits_doc(doc["deal"]["seed"], doc["deal"]["attempt"]))
        ok_splits = corpus.SPLITS_FILE.read_text(encoding="utf-8") == want
        digest = corpus.split_digest(corpus._plans("holdout"), real)
        ok_hash = corpus.SEALED_HASH_FILE.read_text().split()[0] == digest
        print(f"splits.json {'matches' if ok_splits else 'MISMATCH'}; SEALED-HOLDOUT.sha256 {'matches' if ok_hash else 'MISMATCH'}")
        return 0 if ok_splits and ok_hash else 1
    if not args.seed:
        ap.error("--seed is required unless --check")
    doc = corpus.splits_doc(args.seed, args.attempt)
    corpus.SPLITS_FILE.write_text(corpus.splits_blob(doc), encoding="utf-8", newline="\n")
    digest = corpus.split_digest(corpus._plans("holdout", doc["families"]), real)
    n = doc["counts"]["holdout"]["scenarios"]
    corpus.SEALED_HASH_FILE.write_text(f"{digest}  holdout-scenarios({n}; id, scenario digest)\n", encoding="utf-8", newline="\n")
    print(f"counts={doc['counts']}\nSEALED-HOLDOUT.sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
