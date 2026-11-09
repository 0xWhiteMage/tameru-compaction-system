"""Freeze inputs beside saved outputs for manual review of unknown transforms.

This does not run compression or recalculate the saved assessment. The corpus
bytes and each materialized input must match the original run's fingerprints.
Subsequent review reads transform-inspection.json instead of rebuilding inputs.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from corpus import build_corpus  # noqa: E402
from reviewed_checks import digest  # noqa: E402
from run_reviewed import materialise  # noqa: E402


def main() -> None:
    run = Path(sys.argv[1]).resolve()
    destination = run / "transform-inspection.json"
    if destination.exists():
        raise SystemExit("Already captured; read the existing inspection artifact.")
    report = json.loads((run / "results.json").read_text(encoding="utf-8"))
    corpus_path = "benchmarks/redteam/corpus.py"
    expected = report["source_files"][corpus_path]
    if hashlib.sha256((ROOT / corpus_path).read_bytes()).hexdigest() != expected:
        raise SystemExit("Corpus bytes differ from the recorded run.")
    corpus = {case["id"]: case for case in build_corpus()}
    inspected = []
    for result in report["results"]:
        primary = result["runs"][0]
        if not primary.get("audit", {}).get("unverified_lines"):
            continue
        job = json.loads(
            (run / "jobs" / f"{result['id']}-seed-{primary['seed']}.json").read_text(encoding="utf-8")
        )
        case = corpus[result["id"]]
        source = str(materialise(case["text"]) or "")
        if digest(source) != primary["input_sha256"]:
            raise SystemExit(f"Materialized input changed: {result['id']}")
        if digest(json.dumps(case["query"], ensure_ascii=True)) != primary["query_sha256"]:
            raise SystemExit(f"Query changed: {result['id']}")
        if digest(job["output"]) != primary["output_sha256"]:
            raise SystemExit(f"Saved output changed: {result['id']}")
        inspected.append({
            "id": result["id"], "source": source, "output": job["output"],
            "query": case["query"], "gold": case.get("gold") or [],
            "input_sha256": primary["input_sha256"], "output_sha256": primary["output_sha256"],
            "saved_audit": primary["audit"],
        })
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(
            {"run_id": report["run_id"], "corpus_sha256": expected, "cases": inspected},
            stream, ensure_ascii=True, indent=2,
        )
    print(destination)


if __name__ == "__main__":
    main()
