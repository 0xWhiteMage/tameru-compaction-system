"""Reviewed synthetic checks; never overwrites the exploratory 1.6.0 artifacts.

Run: python benchmarks/redteam/run_reviewed.py [--case ID ...]
Optional serial timing protocol: --timing-repeats 3 (one discarded warmup per
scaling fixture, then at least three fresh-process first-pass measurements).

All selected cases run under BOTH hash seeds. Timing from the functional checks
is observational, not a benchmark claim. Literal substring gold assertions and
the conservative transform audit do not establish general semantic correctness.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from reviewed_checks import audit_output, compare_seed_records, digest, self_test  # noqa: E402

SEEDS = (0, 12345)
WORKER_TIMEOUT_SECONDS = 30
SCHEMA_VERSION = 2


def materialise(value):
    if not isinstance(value, dict):
        return value
    if value["kind"] == "const":
        return value["value"]
    if value["kind"] == "repeat":
        lines = [value["line"]] * value["n"]
        midpoint = value["n"] // 2
        return "\n".join(lines[:midpoint] + list(value.get("extra") or []) + lines[midpoint:])
    if value["kind"] == "scale":
        return value["base"] * value["mult"]
    raise ValueError("Unknown fixture materialization")


def string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from string_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from string_values(child)


def evaluate(case: dict, *, timing_only: bool = False) -> dict:
    from tameru.compress_context import ENGINE_VERSION, compress_context

    raw = materialise(case["text"])
    # This is the API's documented/coercion path, including None/0 -> "".
    source = str(raw or "")
    record = {
        "id": case["id"], "status": "ok", "engine_version": ENGINE_VERSION,
        "input_type": type(raw).__name__, "input_sha256": digest(source),
        "query_sha256": digest(json.dumps(case["query"], ensure_ascii=True)),
        "flags": {"ccr": bool(case.get("ccr")), "citations": False},
        "violations": [], "observations": {},
    }
    with tempfile.TemporaryDirectory(prefix="tameru-reviewed-") as ccr_dir:
        kwargs = {"ccr": bool(case.get("ccr")), "citations": False, "ccr_dir": ccr_dir}
        started = time.perf_counter()
        try:
            result = compress_context(raw, case["query"], **kwargs)
        except Exception as exc:
            return {**record, "status": "engine_error", "error_type": type(exc).__name__}
        elapsed = (time.perf_counter() - started) * 1000
        output = result.compressed_text
        if not isinstance(output, str):
            return {**record, "status": "invalid_result", "error_type": "non_text_output"}
        record.update(output_sha256=digest(output), first_pass_ms=elapsed, output=output)
        if timing_only:
            return record
        violations = record["violations"]
        record["metrics"] = {
            "input_chars": len(source), "output_chars": len(output),
            "removed_chars": len(source) - len(output),
            "character_savings_pct": 100 * (1 - len(output) / len(source)) if source else None,
            "reported_original_tokens": result.original_tokens,
            "reported_kept_tokens": result.kept_tokens,
            "reported_estimated_token_savings_pct": result.tokens_saved_pct,
            "output_changed": source != output, "output_is_blank": not output.strip(),
            "fail_open": result.fail_open, "risk": result.compression_risk,
            "adapter": (result.receipt or {}).get("adapter"),
        }
        if result.fail_open and output != source:
            violations.append({"check": "fail_open_identity"})
        record["observations"]["character_growth"] = len(output) > len(source)
        record["observations"]["first_pass_above_5_seconds"] = elapsed > 5000
        record["audit"] = audit_output(source, output)
        required = case.get("gold") or []
        invalid_gold = [i for i, snippet in enumerate(required) if snippet and snippet not in source]
        missing_gold = [i for i, snippet in enumerate(required) if snippet and snippet in source and snippet not in output]
        record["gold"] = {
            "kind": "literal_substring_presence_only", "total": len(required),
            "missing_indexes": missing_gold, "invalid_fixture_indexes": invalid_gold,
        }
        if invalid_gold:
            violations.append({"check": "invalid_gold_fixture", "indexes": invalid_gold})
        if missing_gold:
            violations.append({"check": "gold_missing", "indexes": missing_gold})
        # An explicitly historical value may correctly coexist with a current
        # value. Presence alone is not a leak or a supersession failure.
        record["observations"]["historical_or_forbidden_snippet_indexes"] = [
            i for i, snippet in enumerate(case.get("forbidden") or []) if snippet and snippet in output
        ]
        record["observations"]["input_marker_indexes_retained"] = [
            i for i, marker in enumerate(case.get("forged_markers") or []) if marker in output
        ]
        try:
            second = compress_context(output, case["query"], **kwargs)
            identical = second.compressed_text == output
            record["idempotence"] = {
                "equal_bytes": identical, "second_output_sha256": digest(second.compressed_text),
                "second_output_chars": len(second.compressed_text),
            }
            if not identical:
                violations.append({"check": "idempotence_byte_equality"})
        except Exception as exc:
            violations.append({"check": "idempotence_exception", "error_type": type(exc).__name__})
        try:
            repeated = compress_context(raw, case["query"], **kwargs)
            record["same_input_repeat_equal"] = repeated.compressed_text == output
            if not record["same_input_repeat_equal"]:
                violations.append({"check": "same_input_repeat"})
        except Exception as exc:
            violations.append({"check": "repeat_exception", "error_type": type(exc).__name__})
        if any(0xD800 <= ord(char) <= 0xDFFF for char in output) and not any(
            0xD800 <= ord(char) <= 0xDFFF for char in source
        ):
            violations.append({"check": "new_lone_surrogate"})
        if case.get("ccr"):
            files = sorted(Path(ccr_dir).glob("*.json"))
            leaks = unreadable = 0
            for file in files:
                try:
                    stored = json.loads(file.read_text(encoding="utf-8"))
                    if case.get("secret") and any(case["secret"] in part for part in string_values(stored)):
                        leaks += 1
                except (OSError, ValueError, RecursionError):
                    unreadable += 1
            record["ccr"] = {"records": len(files), "planted_secret_records": leaks, "unreadable_records": unreadable}
            if leaks:
                violations.append({"check": "ccr_planted_secret", "records": leaks})
            if unreadable:
                violations.append({"check": "ccr_scan_incomplete", "records": unreadable})
    return record


def source_manifest() -> dict:
    files = sorted((ROOT / "src" / "tameru").glob("*.py"))
    files += [HERE / name for name in ("corpus.py", "reviewed_checks.py", "run_reviewed.py")]
    import hashlib
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def run_child(case_id: str, seed: int, *, timing_only: bool = False) -> dict:
    mode = "--timing-worker" if timing_only else "--worker"
    env = {**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONIOENCODING": "utf-8"}
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), mode, case_id],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env,
    )
    started = time.perf_counter()
    try:
        stdout, stderr = process.communicate(timeout=WORKER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        # communicate waits for termination: requesting kill alone is not proof.
        process.communicate(timeout=5)
        return {
            "id": case_id, "status": "worker_timeout", "seed": seed,
            "terminated": process.poll() is not None, "returncode": process.returncode,
            "timeout_seconds": WORKER_TIMEOUT_SECONDS,
        }
    if process.returncode:
        return {
            "id": case_id, "status": "worker_error", "seed": seed,
            "returncode": process.returncode, "stderr_sha256": digest(stderr),
        }
    try:
        record = json.loads(stdout)
        if record.get("id") != case_id:
            raise ValueError("wrong worker result")
    except (ValueError, AttributeError):
        return {"id": case_id, "status": "invalid_worker_output", "seed": seed}
    record.update(seed=seed, worker_wall_ms=(time.perf_counter() - started) * 1000)
    return record


def main() -> int:
    from corpus import build_corpus

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--timing-repeats", type=int, default=0)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--worker")
    parser.add_argument("--timing-worker")
    args = parser.parse_args()
    if args.worker or args.timing_worker:
        case_id = args.worker or args.timing_worker
        case = next(case for case in build_corpus() if case["id"] == case_id)
        print(json.dumps(evaluate(case, timing_only=bool(args.timing_worker)), ensure_ascii=True))
        return 0
    self_test()
    if args.self_test:
        print("Reviewed checker self-tests passed.")
        return 0
    if args.timing_repeats and not 3 <= args.timing_repeats <= 10:
        parser.error("--timing-repeats must be 0 or between 3 and 10")
    cases = build_corpus()
    unknown = set(args.case) - {case["id"] for case in cases}
    if unknown:
        parser.error("Unknown case id")
    if args.case:
        cases = [case for case in cases if case["id"] in args.case]
    manifest = source_manifest()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    destination = runs / run_id
    destination.mkdir()
    jobs = destination / "jobs"
    jobs.mkdir()
    records = []
    timing = []
    for index, case in enumerate(cases, 1):
        seeds = []
        for seed in SEEDS:
            record = run_child(case["id"], seed)
            (jobs / f"{case['id']}-seed-{seed}.json").write_text(
                json.dumps(record, ensure_ascii=True, indent=2), encoding="utf-8",
            )
            seeds.append({key: value for key, value in record.items() if key != "output"})
        row = {
            **{key: case[key] for key in ("id", "family", "format", "lang", "attack")},
            "hash_seeds": compare_seed_records(seeds), "runs": seeds,
        }
        records.append(row)
        print(f"[{index}/{len(cases)}] {case['id']}: " + ", ".join(record["status"] for record in seeds), flush=True)
        if args.timing_repeats and case["family"] == "perf-scaling":
            samples = [run_child(case["id"], 0, timing_only=True) for _ in range(args.timing_repeats + 1)]
            (jobs / f"{case['id']}-timing.json").write_text(
                json.dumps(samples, ensure_ascii=True, indent=2), encoding="utf-8",
            )
            verified = all(
                sample.get("status") == "ok" and sample.get("input_sha256") == seeds[0].get("input_sha256")
                for sample in samples
            )
            values = [sample["first_pass_ms"] for sample in samples[1:]] if verified else []
            timing.append({
                "id": case["id"], "verified": verified, "discarded_warmups": 1,
                "samples_ms": values, "median_ms": statistics.median(values) if values else None,
            })
    engine_violations = [
        {"case": row["id"], "seed": run["seed"], **violation}
        for row in records for run in row["runs"] for violation in run.get("violations", [])
    ]
    manifest_after = source_manifest()
    source_stable = manifest_after == manifest
    payload = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id, "source_files": manifest,
        "source_unchanged_during_run": source_stable,
        "source_files_after": manifest_after if not source_stable else None,
        "environment": {
            "python": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "protocol": {
            "functional_workers": 1, "hash_seeds": list(SEEDS), "hash_coverage": "every selected case",
            "worker_timeout_seconds": WORKER_TIMEOUT_SECONDS, "output_comparison": "UTF-8 with surrogatepass",
            "timing": "fresh process, first compression call; startup excluded; external machine load uncontrolled",
            "timing_repeats": args.timing_repeats,
            "limits": [
                "Gold checks assert literal presence, not association or general semantic correctness.",
                "Unverified transforms are review work, not demonstrated fabrication.",
                "Recognized marker grammars do not verify their numeric counts.",
                "Historical values and source-provided markers are observations, not vulnerability verdicts.",
                "Functional-run times alone do not establish scaling or comparative speed.",
            ],
        },
        "coverage": {field: dict(Counter(case[field] for case in cases)) for field in ("family", "format", "lang", "attack")},
        "selected_cases": len(cases), "total_corpus_cases": len(build_corpus()),
        "results": records, "violations": engine_violations, "timing_samples": timing,
        "transform_review_required": [
            row["id"] for row in records
            if any(run.get("audit", {}).get("unverified_lines", 0) for run in row["runs"])
        ],
        "release_readiness": "not_asserted",
    }
    (destination / "results.json").write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(destination / "results.json")
    incomplete = any(not row["hash_seeds"]["verified"] for row in records)
    return 1 if engine_violations or incomplete or not source_stable else 0


if __name__ == "__main__":
    raise SystemExit(main())
