"""Materialise a split of the session corpus as JSON files (one per scenario) under an ignored build/ directory.

    python -m benchmarks.session_corpus.build --split dev                       # full sessions (up to the 1M slice)
    python -m benchmarks.session_corpus.build --split validation --window 252000  # sliced to the 252K window
    python -m benchmarks.session_corpus.build --split holdout --holdout --candidate NAME   # the ONE look; logged

Output: build/session_corpus/<split>/<window or full>/<scenario id>.json and index.json (ids, family, language, style,
window table).  The Squeez files are read from build/session_corpus/squeez/ unless --squeez DIR is given.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import corpus
from . import generator as g
from . import real as realmod

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "build" / "session_corpus"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", required=True, choices=corpus.SPLITS)
    ap.add_argument("--window", type=int, choices=g.WINDOWS)
    ap.add_argument("--holdout", action="store_true", help="allow reading the holdout (one look; logged)")
    ap.add_argument("--candidate", help="candidate name, required with --holdout")
    ap.add_argument("--squeez", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, help="first N scenarios only (smoke runs)")
    args = ap.parse_args(argv)
    if args.split == "holdout" and not (args.holdout and args.candidate):
        print("refusing: the holdout can only be read with --holdout --candidate NAME", file=sys.stderr)
        return 2
    if args.holdout and args.split != "holdout":
        print("--holdout is only for --split holdout", file=sys.stderr)
        return 2
    command = "python -m benchmarks.session_corpus.build " + " ".join(argv if argv is not None else sys.argv[1:])
    out = args.out / args.split / (f"w{args.window}" if args.window else "full")
    out.mkdir(parents=True, exist_ok=True)
    index = []
    try:
        it = corpus.scenarios(args.split, holdout=args.holdout, candidate=args.candidate, squeez=args.squeez,
                              window=args.window, command=command)
        for k, sc in enumerate(it):
            if args.limit is not None and k >= args.limit:
                break
            (out / f"{sc['id']}.json").write_text(corpus.canonical(sc) + "\n", encoding="utf-8", newline="\n")
            index.append({"id": sc["id"], "family": sc["family"], "language": sc["language"], "task_style": sc["task_style"],
                          "steps": len(sc["steps"]), "questions": len(sc["questions"]), "windows": sc["windows"]})
    except realmod.SqueezMissing as e:
        print(f"cannot build: {e}", file=sys.stderr)
        return 3
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(index)} scenarios to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
