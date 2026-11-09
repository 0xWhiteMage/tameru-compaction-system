"""Capture second-pass counterexamples from a frozen reviewed run.

Reads saved first-pass output, not original inputs. Refuses changed engine or
corpus bytes, and checks each reproduction against the second-pass hash already
recorded by the run. Later presentation should read repeat-inspection.json.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from corpus import build_corpus  # noqa: E402
from reviewed_checks import digest  # noqa: E402
from tameru.compress_context import compress_context  # noqa: E402


def main() -> None:
    run = Path(sys.argv[1]).resolve()
    destination = run / "repeat-inspection.json"
    if destination.exists():
        raise SystemExit("Inspection already captured; read the existing artifact.")
    report = json.loads((run / "results.json").read_text(encoding="utf-8"))
    for relative, expected in report["source_files"].items():
        if relative.startswith("src/") or relative.endswith("/corpus.py"):
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            if actual != expected:
                raise SystemExit(f"Frozen input source changed: {relative}")
    corpus = {case["id"]: case for case in build_corpus()}
    inspected = []
    for row in report["results"]:
        primary = row["runs"][0]
        if primary.get("idempotence", {}).get("equal_bytes") is not False:
            continue
        job = json.loads((run / "jobs" / f"{row['id']}-seed-{primary['seed']}.json").read_text(encoding="utf-8"))
        first = job["output"]
        if digest(first) != primary["output_sha256"]:
            raise SystemExit("Saved first-pass output does not match its recorded hash.")
        case = corpus[row["id"]]
        if case.get("ccr"):
            raise SystemExit("CCR reproduction needs its original per-run storage protocol.")
        second = compress_context(first, case["query"], ccr=False, citations=False).compressed_text
        reproduced = digest(second) == primary["idempotence"]["second_output_sha256"]
        inspected.append({
            "id": row["id"], "first_sha256": digest(first), "second_sha256": digest(second),
            "matches_recorded_second_pass": reproduced, "second_output": second,
            "gold_indexes_missing_after_second_pass": [
                i for i, snippet in enumerate(case.get("gold") or []) if snippet and snippet not in second
            ],
            "diff": list(difflib.unified_diff(
                first.splitlines(keepends=True), second.splitlines(keepends=True),
                fromfile="first_pass", tofile="second_pass",
            )),
        })
    with destination.open("x", encoding="utf-8") as stream:
        json.dump({"run_id": report["run_id"], "cases": inspected}, stream, ensure_ascii=True, indent=2)
    print(destination)
    if not all(row["matches_recorded_second_pass"] for row in inspected):
        raise SystemExit("At least one counterexample did not reproduce the frozen hash.")


if __name__ == "__main__":
    main()
