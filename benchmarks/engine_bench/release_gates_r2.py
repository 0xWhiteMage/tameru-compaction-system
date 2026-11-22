"""Engine release gates on the round-2 sealed engine_bench split (P3 exit), computed from the look's rows.

    python -m benchmarks.engine_bench.release_gates_r2 --candidate C.jsonl --baseline B.jsonl [--out R.json]
    python -m benchmarks.engine_bench.release_gates_r2 --dry-run --candidate DEV_C.jsonl --baseline DEV_B.jsonl

C holds the candidate's rows and B the 1.10.0 engine's rows (the reference run taken in the same look) for the same
cases. ``--dry-run`` accepts dev rows so the code can be checked before the look; without it every row must be sealed.
Written before the look.

Intervals: one-sided percentile cluster bootstrap at alpha = 0.0125 (the engine's second look, ANALYSIS-PLAN-ROUND2
section 6), clusters = ``source_case``, 10,000 resamples, seed 20261122. Rows pair on (case, profile, query_condition).

S5 (strategy S5 and the P3 exit):
  vague         build_vague rows of the S5 kinds (s5_buried, s5_superseded, csv_args), per language (en, zh) x profile:
                all-gold-kept share >= 95 points and its lower bound >= 90.
  existing      evidence rows under tool_call, generic and zh_user, per profile x condition: all-gold-kept share >= 99.5.
  savings       per profile x condition: mean paired saved_pct (candidate - 1.10.0) >= -2.0 points.
Gate 9 (round-1 margins, ANALYSIS-PLAN-1.10):
  facts         per profile x condition: paired difference of gold kept (case mean, points), lower bound >= -1.0.
  fingerprints  per profile x condition, rows whose original has error fingerprints: paired difference of the share of
                fingerprints kept (points), lower bound >= -1.0.
  chinese       per profile, zh/mixed cases: gold kept under zh_user minus under task_vague (the conversational English
                condition of the same cases), lower bound >= -3.0.
S6 (ANALYSIS-PLAN-ROUND2, 2026-11-22 definitions), accepted candidate rows, the shipped calibration table:
  per stratum with n >= 50: ECE <= 0.05, and the reliability slope within 0.8-1.2 where p varies within the stratum;
  AUROC of p against "a fact-shaped line was dropped" >= 0.9; p < 0.99 and raw confidence < 1.0 on every row with
  fact_lines_dropped > 0; no vague or structural row at p >= 0.99 outside a stratum that lifts the cap.
Integrity: the candidate paired with itself gives exactly 0 on every paired metric.

Not computed here (the release report cites their commands and committed results): round-1 gates 1-4, 6 and 10-12
(determinism and idempotence, fail-open fuzz, host-rule and vendoring checks, red team, latency.py, memory.py, the
trace and CJK targets, claims).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from tameru import calibration  # noqa: E402

from . import calibrate, report  # noqa: E402

ALPHA = 0.0125
BOOT = 10_000
SEED = 20261122
S5_KINDS = ("s5_buried", "s5_superseded", "csv_args")
EXISTING_CONDS = ("tool_call", "generic", "zh_user")
PROFILES = ("deepseek", "hermes")


def _key(r: dict) -> tuple:
    return (r["case"], r["profile"], r["query_condition"])


def all_kept(r: dict) -> bool:
    return all(r["gold_each"]) if r.get("gold_total") else True


def lower_bound(pairs: list[tuple[str, float]], alpha: float = ALPHA, boot: int = BOOT, seed: int = SEED) -> dict:
    """Mean of ``pairs`` = [(cluster, value)] and its one-sided percentile cluster-bootstrap lower bound."""
    by: dict[str, list[float]] = defaultdict(list)
    for cluster, v in pairs:
        by[cluster].append(v)
    if not by:
        return {"mean": None, "lower": None, "n": 0, "clusters": 0}
    sums = [(sum(v), len(v)) for _k, v in sorted(by.items())]
    total, n = sum(s for s, _c in sums), sum(c for _s, c in sums)
    rng = random.Random(seed)
    means = []
    for _ in range(boot):
        picks = [sums[rng.randrange(len(sums))] for _ in sums]
        means.append(sum(s for s, _c in picks) / sum(c for _s, c in picks))
    means.sort()
    return {"mean": total / n, "lower": means[int(alpha * boot)], "n": n, "clusters": len(sums)}


def _paired(cand: list[dict], base: dict, value) -> list[tuple[str, float]]:
    out = []
    for r in cand:
        b = base.get(_key(r))
        if b is not None:
            v_c, v_b = value(r), value(b)
            if v_c is not None and v_b is not None:
                out.append((r["source_case"], v_c - v_b))
    return out


def _fp_share(r: dict) -> float | None:
    return 100.0 * r["fingerprints_kept"] / r["fingerprints_total"] if r.get("fingerprints_total") else None


def _check(name: str, ok: bool, **numbers) -> dict:
    return {"gate": name, "pass": bool(ok), **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in numbers.items()}}


def s5_gates(cand: list[dict], base_by_key: dict) -> list[dict]:
    out = []
    for lang in ("en", "zh"):
        for p in PROFILES:
            cell = [r for r in cand if r.get("item_kind") in S5_KINDS and r["query_condition"] == "build_vague"
                    and r["language"] == lang and r["profile"] == p]
            s = lower_bound([(r["source_case"], 100.0 if all_kept(r) else 0.0) for r in cell])
            ok = s["mean"] is not None and s["mean"] >= 95.0 and s["lower"] >= 90.0
            out.append(_check(f"S5 vague|{lang}|{p}", ok, share=s["mean"], lower=s["lower"], n=s["n"], clusters=s["clusters"]))
    for p in PROFILES:
        for c in EXISTING_CONDS:
            cell = [r for r in cand if r.get("item_kind") == "evidence" and r["profile"] == p and r["query_condition"] == c]
            if cell:
                share = 100.0 * sum(all_kept(r) for r in cell) / len(cell)
                out.append(_check(f"S5 existing gold|{p}|{c}", share >= 99.5, share=share, n=len(cell)))
    for p in PROFILES:
        for c in sorted({r["query_condition"] for r in cand}):
            pairs = _paired([r for r in cand if r["profile"] == p and r["query_condition"] == c], base_by_key,
                            lambda r: float(r["saved_pct"]))
            if pairs:
                s = lower_bound(pairs)
                out.append(_check(f"S5 savings|{p}|{c}", s["mean"] >= -2.0, mean_diff=s["mean"], lower=s["lower"], n=s["n"]))
    return out


def gate9(cand: list[dict], base_by_key: dict) -> list[dict]:
    out = []
    for p in PROFILES:
        for c in sorted({r["query_condition"] for r in cand}):
            sub = [r for r in cand if r["profile"] == p and r["query_condition"] == c]
            s = lower_bound(_paired(sub, base_by_key, lambda r: None if r["gold_kept"] is None else 100.0 * r["gold_kept"]))
            if s["n"]:
                out.append(_check(f"gate9 facts|{p}|{c}", s["lower"] >= -1.0, mean_diff=s["mean"], lower=s["lower"], n=s["n"]))
            s = lower_bound(_paired(sub, base_by_key, _fp_share))
            if s["n"]:
                out.append(_check(f"gate9 fingerprints|{p}|{c}", s["lower"] >= -1.0, mean_diff=s["mean"], lower=s["lower"], n=s["n"]))
    for p in PROFILES:
        zh = {r["case"]: r for r in cand if r["profile"] == p and r["query_condition"] == "zh_user"}
        pairs = [(r["source_case"], 100.0 * (zh[r["case"]]["gold_kept"] - r["gold_kept"]))
                 for r in cand if r["profile"] == p and r["query_condition"] == "task_vague" and r["case"] in zh
                 and r["gold_kept"] is not None and zh[r["case"]]["gold_kept"] is not None]
        s = lower_bound(pairs)
        if s["n"]:
            out.append(_check(f"gate9 chinese (zh_user - task_vague)|{p}", s["lower"] >= -3.0, mean_diff=s["mean"], lower=s["lower"], n=s["n"]))
    return out


def s6_gates(cand: list[dict], table_path: Path | None = None) -> tuple[list[dict], dict]:
    table = calibration.load() if table_path is None else calibration._parse(json.loads(table_path.read_text(encoding="utf-8")))
    acc = [r for r in cand if r["accepted"]]
    ps = [calibration.p_hat(r.get("confidence_basis"), bool(r.get("query_specific")), r.get("fact_lines_dropped") or 0,
                            r.get("confidence"), table=table) for r in acc]
    varying = {k for k, s in table.strata.items() if s.iso}
    lifted = {k for k, s in table.strata.items() if s.lifts_cap}
    m = calibrate.metrics(acc, ps, varying, lifted)
    out = []
    for k, s in m["strata"].items():
        if s["gated"]:
            out.append(_check(f"S6 ECE|{k}", s["ece"] <= 0.05, ece=s["ece"], n=s["n"], observed=s["observed"], mean_p=s["mean_p"]))
            if s["slope"] is not None:
                out.append(_check(f"S6 slope|{k}", 0.8 <= s["slope"] <= 1.2, slope=s["slope"], n=s["n"]))
    au = m["auroc_vs_fact_drop"]
    out.append(_check("S6 AUROC vs fact drop", au is not None and au >= 0.9, auroc=au, positives=m["fact_drop_positives"]))
    drops = [(p, r) for p, r in zip(ps, acc) if (r.get("fact_lines_dropped") or 0) > 0]
    out.append(_check("S6 p < 0.99 and raw confidence < 1.0 when a fact line was dropped",
                      all(p < 0.99 and (r.get("confidence") is None or r["confidence"] < 1.0) for p, r in drops), rows=len(drops)))
    out.append(_check("S6 no vague/structural p >= 0.99 outside a lifted stratum", m["p_ge_099_vague_or_structural"] == 0,
                      rows=m["p_ge_099_vague_or_structural"]))
    return out, {"method": table.method, "source": dict(table.source), "metrics": m}


def integrity(cand: list[dict]) -> list[dict]:
    me = {_key(r): r for r in cand}
    worst = 0.0
    for value in (lambda r: float(r["saved_pct"]), lambda r: None if r["gold_kept"] is None else 100.0 * r["gold_kept"], _fp_share):
        worst = max([worst] + [abs(d) for _c, d in _paired(cand, me, value)])
    return [_check("integrity: candidate vs itself is exactly 0", worst == 0.0, worst=worst)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true", help="accept dev rows (a check of this code, not the look)")
    ap.add_argument("--table", type=Path, help="dry runs only: a calibration table other than the shipped one")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    cand, base = report.load(args.candidate), report.load(args.baseline)
    want = {"dev"} if args.dry_run else {"sealed"}
    cand = [r for r in cand if r["split"] in want]
    base = [r for r in base if r["split"] in want]
    if not cand or not base:
        print(f"refusing: no {'/'.join(sorted(want))} rows in both files", file=sys.stderr)
        return 2
    missing = {_key(r) for r in cand} - {_key(r) for r in base}
    if missing:
        print(f"refusing: {len(missing)} candidate rows have no baseline row", file=sys.stderr)
        return 2
    if args.table and not args.dry_run:
        print("refusing: the look judges the shipped calibration table", file=sys.stderr)
        return 2
    base_by_key = {_key(r): r for r in base}
    s6, s6_info = s6_gates(cand, args.table)
    checks = integrity(cand) + s5_gates(cand, base_by_key) + gate9(cand, base_by_key) + s6
    failed = [c for c in checks if not c["pass"]]
    print(f"{'DRY RUN on dev rows' if args.dry_run else 'SEALED LOOK'}: candidate {sorted({str(r.get('engine_commit')) for r in cand})} "
          f"vs baseline {sorted({str(r.get('engine_commit') or r.get('reference')) for r in base})}; "
          f"{len({r['case'] for r in cand})} cases, {len({r['source_case'] for r in cand})} clusters; alpha {ALPHA}, {BOOT} resamples")
    for c in checks:
        nums = ", ".join(f"{k}={v}" for k, v in c.items() if k not in ("gate", "pass"))
        print(f"  {'PASS' if c['pass'] else 'FAIL'}  {c['gate']}  ({nums})")
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks pass")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"dry_run": args.dry_run, "alpha": ALPHA, "boot": BOOT, "seed": SEED, "checks": checks,
                                        "s6": s6_info}, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
