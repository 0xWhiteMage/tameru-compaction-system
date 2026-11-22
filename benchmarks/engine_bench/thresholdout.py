"""Round-2/3 validation is queried ONLY through this gate (plan section 7): a noisy
pass/fail answer on a fixed gate, never the numbers.

    python -m benchmarks.engine_bench.thresholdout --setting E4 --gate s5_vague_en
    python -m benchmarks.engine_bench.thresholdout --setting E12 --gate s5_vague_en --round 3

Each query: refuses when ``validation_queries.engine`` has reached the budget (20),
otherwise runs the gate on the r2 validation rows of THIS tree's engine, adds Laplace
noise (scale 0.2 points, derived from the ledger's ``noise_seed``) to each bound,
increments the counter, logs the query and prints exactly ``PASS`` or ``FAIL``.

Gates:
  s5_vague_en / s5_vague_zh   S5 kinds under build_vague: gold kept over all cases >=
                              95 points and cluster-bootstrap one-sided lower bound >=
                              90 points, in the named language, for BOTH profiles.
  existing_gold               evidence cases under the round-1 conditions (tool_call,
                              generic, zh_user): gold kept >= 99.5 in every
                              profile x condition cell.
  savings                     round-1 dev+validation: mean paired saved ratio per
                              profile x condition >= stored 1.10.0 baseline - 2 points.
  s6_calibration              calibrate.py's table fit on this engine's r2 dev rows, applied
                              to the accepted r2 validation rows: in every stratum with
                              n >= 50, ECE <= 0.05 and, where p varies within the stratum,
                              reliability slope within 0.8-1.2; AUROC of p against "a
                              fact-shaped line was dropped" >= 0.9; no vague or structural
                              row at p >= 0.99 outside a stratum that lifts the cap.

Testing seams: ``--ledger PATH`` points at a ledger copy; ``--r2-rows``/``--r1-rows``/``--r2-dev-rows``
feed precomputed rows instead of running the engine.
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import sys
from pathlib import Path

from . import corpus, ledger, report, run as bench_run

NOISE_SCALE = 0.2  # Laplace scale, in points
S5_KINDS = ("s5_buried", "s5_superseded", "csv_args")
R1_CONDS_IN_R2 = ("tool_call", "generic", "zh_user")
R1_BASELINE = Path(__file__).resolve().parent / "results" / "r1-baseline-1.10.0-dev-validation.jsonl"


def _laplace(rng: random.Random, scale: float) -> float:
    u = rng.random() - 0.5
    import math
    return -scale * (1 if u >= 0 else -1) * math.log(1 - 2 * abs(u))


def _all_kept(row) -> bool:
    """Every gold line survived. ``gold_kept`` is the kept FRACTION and ``gold_total`` a count, so comparing the two
    (as before 2026-11-22) only held for single-line gold; ``gold_each`` is per line, with the fraction as fallback."""
    each = row.get("gold_each")
    return all(each) if each is not None else row["gold_kept"] >= 1.0


def _gold_share(rows) -> float:
    """100 * share of cases whose gold lines all survived the effective text."""
    use = [r for r in rows if r.get("gold_total")]
    if not use:
        return float("nan")
    return 100.0 * sum(1 for r in use if _all_kept(r)) / len(use)


def _gold_share_bound(rows) -> float:
    """One-sided cluster-bootstrap lower bound of the full-kept share, in points."""
    use = [r for r in rows if r.get("gold_total")]
    if not use:
        return float("nan")
    pairs = [(r["source_case"], 1.0 if _all_kept(r) else 0.0) for r in use]
    return 100.0 * report.cluster_mean(pairs)["lo"]


def _checks(gate: str, r2_rows, r1_rows, r1_base, r2_dev_rows=()) -> list[tuple[str, float, float]]:
    """(label, value-in-points, bound) per sub-check; a check passes when value >= bound + noise."""
    checks: list[tuple[str, float, float]] = []
    if gate in ("s5_vague_en", "s5_vague_zh"):
        lang = gate.rsplit("_", 1)[1]
        rows = [r for r in r2_rows
                if r.get("item_kind") in S5_KINDS and r["query_condition"] == "build_vague"
                and r["language"] == lang and r["split"] == "validation"]
        for profile in bench_run.PROFILES:
            cell = [r for r in rows if r["profile"] == profile]
            checks.append((f"{gate}|{profile}|point", _gold_share(cell), 95.0))
            checks.append((f"{gate}|{profile}|bound", _gold_share_bound(cell), 90.0))
    elif gate == "existing_gold":
        rows = [r for r in r2_rows
                if r.get("item_kind") == "evidence" and r["split"] == "validation"
                and r["query_condition"] in R1_CONDS_IN_R2]
        for profile in bench_run.PROFILES:
            for cond in R1_CONDS_IN_R2:
                cell = [r for r in rows if r["profile"] == profile and r["query_condition"] == cond]
                if cell:
                    checks.append((f"existing_gold|{profile}|{cond}", _gold_share(cell), 99.5))
    elif gate == "savings":
        key = lambda r: (r["case"], r["profile"], r["query_condition"])  # noqa: E731
        base = {key(r): r for r in r1_base}
        for profile in bench_run.PROFILES:
            for cond in bench_run.CONDITIONS:
                cand = [r for r in r1_rows
                        if r["profile"] == profile and r["query_condition"] == cond]
                diffs = [r["saved_pct"] - base[key(r)]["saved_pct"] for r in cand if key(r) in base]
                if diffs:
                    checks.append((f"savings|{profile}|{cond}", sum(diffs) / len(diffs), -2.0))
    elif gate == "s6_calibration":
        from . import calibrate
        table = calibrate.fit([r for r in r2_dev_rows if r["accepted"] and r["split"] == "dev"])
        val = [r for r in r2_rows if r["accepted"] and r["split"] == "validation"]
        if not val:
            return checks
        varying = {k for k, s in table["strata"].items() if s["iso"]}
        lifted = {k for k, s in table["strata"].items() if s["lifts_cap"]}
        m = calibrate.metrics(val, calibrate.predict(table, val), varying, lifted)
        for k, s in m["strata"].items():
            if s["gated"]:
                checks.append((f"s6|{k}|ece", -100.0 * s["ece"], -5.0))
                if s["slope"] is not None:
                    checks.append((f"s6|{k}|slope_low", 100.0 * s["slope"], 80.0))
                    checks.append((f"s6|{k}|slope_high", -100.0 * s["slope"], -120.0))
        if m["auroc_vs_fact_drop"] is not None:
            checks.append(("s6|auroc_vs_fact_drop", 100.0 * m["auroc_vs_fact_drop"], 90.0))
        checks.append(("s6|p_ge_099_vague_or_structural", -float(m["p_ge_099_vague_or_structural"]), -0.5))
    return checks


def _r2_validation_rows() -> list[dict]:
    assignment = corpus.r2_assignment()
    cases = corpus.load_cases_r2(["validation"], sealed_ok=False)
    rows = bench_run.run(cases, assignment, conditions=bench_run.CONDITIONS_R2)
    return [r for r in rows if r["split"] == "validation"]


def _r2_dev_rows() -> list[dict]:
    assignment = corpus.r2_assignment()
    rows = bench_run.run(corpus.load_cases_r2(["dev"], sealed_ok=False), assignment, conditions=bench_run.CONDITIONS_R2)
    return [r for r in rows if r["split"] == "dev"]


def _r3_validation_rows() -> list[dict]:
    assignment = corpus.r3_assignment()
    cases = corpus.load_cases_r3(["validation"], sealed_ok=False)
    rows = bench_run.run(cases, assignment, conditions=bench_run.CONDITIONS_R2)
    return [r for r in rows if r["split"] == "validation"]


def _r3_dev_rows() -> list[dict]:
    assignment = corpus.r3_assignment()
    rows = bench_run.run(corpus.load_cases_r3(["dev"], sealed_ok=False), assignment, conditions=bench_run.CONDITIONS_R2)
    return [r for r in rows if r["split"] == "dev"]


def _r4_validation_rows() -> list[dict]:
    assignment = corpus.r4_assignment()
    cases = corpus.load_cases_r4(["validation"], sealed_ok=False)
    rows = bench_run.run(cases, assignment, conditions=bench_run.CONDITIONS_R2)
    return [r for r in rows if r["split"] == "validation"]


def _r4_dev_rows() -> list[dict]:
    assignment = corpus.r4_assignment()
    rows = bench_run.run(corpus.load_cases_r4(["dev"], sealed_ok=False), assignment, conditions=bench_run.CONDITIONS_R2)
    return [r for r in rows if r["split"] == "dev"]


_VALIDATION_ROWS = {2: _r2_validation_rows, 3: _r3_validation_rows, 4: _r4_validation_rows}
_DEV_ROWS = {2: _r2_dev_rows, 3: _r3_dev_rows, 4: _r4_dev_rows}


def _r1_rows() -> list[dict]:
    assignment = corpus.load_splits()
    cases = corpus.load_cases(["dev", "validation"], sealed_ok=False)
    return bench_run.run(cases, assignment)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setting", required=True, help="engine setting id in the ledger")
    ap.add_argument("--gate", required=True, choices=("s5_vague_en", "s5_vague_zh", "existing_gold", "savings", "s6_calibration"))
    ap.add_argument("--round", dest="round_", type=int, choices=(2, 3, 4), default=2,
                    help="which round's validation/dev corpus the gate queries (r3/r4 post-burn)")
    ap.add_argument("--ledger", type=Path, default=None, help="ledger path (tests use a copy)")
    ap.add_argument("--r2-rows", type=Path, default=None, help="precomputed validation rows for the selected round (tests)")
    ap.add_argument("--r1-rows", type=Path, default=None, help="precomputed r1 rows (tests)")
    ap.add_argument("--r2-dev-rows", type=Path, default=None, help="precomputed dev rows for the selected round (tests; s6_calibration)")
    ap.add_argument("--r1-baseline", type=Path, default=R1_BASELINE, help="stored 1.10.0 r1 rows")
    args = ap.parse_args(argv)

    led = ledger.load_ledger(args.ledger)
    ledger_path = args.ledger or ledger.LEDGER_PATH
    if args.setting not in ledger.engine_setting_ids(led):
        print("refusing: setting is not an engine setting in the ledger", file=sys.stderr)
        return 2
    used = led.get("validation_queries", {}).get("engine", 0)
    budget = led.get("validation_query_budget", 20)
    if used >= budget:
        print("refusing: engine validation query budget exhausted", file=sys.stderr)
        return 2

    r2_rows = report.load(args.r2_rows) if args.r2_rows else _VALIDATION_ROWS[args.round_]()
    r1_rows, r1_base = [], []
    if args.gate == "savings":
        r1_rows = report.load(args.r1_rows) if args.r1_rows else _r1_rows()
        r1_base = report.load(args.r1_baseline)
    r2_dev_rows = []
    if args.gate == "s6_calibration":
        r2_dev_rows = report.load(args.r2_dev_rows) if args.r2_dev_rows else _DEV_ROWS[args.round_]()

    checks = _checks(args.gate, r2_rows, r1_rows, r1_base, r2_dev_rows)
    if not checks:
        print("refusing: gate matched no rows", file=sys.stderr)
        return 2
    rng = random.Random(f"{led.get('noise_seed', 0)}:{used}:{args.gate}")
    ok = all(value >= bound + _laplace(rng, NOISE_SCALE) for _label, value, bound in checks)

    led.setdefault("validation_queries", {})["engine"] = used + 1
    led.setdefault("validation_query_log", []).append({
        "date": datetime.date.today().isoformat(), "target": "engine",
        "setting": args.setting, "gate": args.gate, "query_index": used,
        "noise_seed": led.get("noise_seed", 0), "checks": len(checks),
    })
    ledger_path.write_text(json.dumps(led, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8", newline="\n")
    print("PASS" if ok else "FAIL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
