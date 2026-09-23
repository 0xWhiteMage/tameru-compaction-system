#!/usr/bin/env python3
"""Operating-point sweep — Waxmell-style threshold replay for Tameru.

Sweeps ``budget_ratio`` in fixed mode across the production-QA corpus and
reports gold retention / forbidden-distractor leaks / savings at each
operating point. The point of the exercise (Waxmell's insight): the knob's
default should be *chosen on evidence* — "at ratio X we save N% and miss
nothing the agent came back for" — not inherited.

Pure deterministic arms, no dependencies, no API calls. Runs in seconds.

Usage: python benchmarks/threshold_sweep.py [0.1 0.2 0.3 0.5 0.7]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from run_battery import CASES  # noqa: E402
from tameru.compress_context import compress_context  # noqa: E402


def run_point(case: dict, ratio: float) -> dict:
    out = compress_context(
        case["ctx"], case["q"], mode="fixed", budget_ratio=ratio,
        ccr=False, citations=True,
    )
    gold = case.get("gold", [])
    hits = sum(1 for g in gold if g in out.compressed_text)
    leaks = sum(1 for f in case.get("forbid", []) if f in out.compressed_text)
    return {
        "savings_pct": round((1 - len(out.compressed_text) / max(1, len(case["ctx"]))) * 100, 1),
        "gold": f"{hits}/{len(gold)}",
        "gold_ok": hits == len(gold),
        "leaks": leaks,
        "fail_open": out.fail_open,
        "selection": out.receipt.get("selection"),
        "restored": len(out.receipt.get("sufficiency_restored") or []),
    }


def main() -> int:
    ratios = [float(a) for a in sys.argv[1:]] or [0.1, 0.2, 0.3, 0.5, 0.7]
    header = ["case", *[f"r={r:g}" for r in ratios]]
    print(" | ".join(f"{h:<22}" for h in header))
    print("-" * (24 * len(header)))
    for case in CASES:
        row = [case["name"]]
        for ratio in ratios:
            r = run_point(case, ratio)
            mark = "ok" if r["gold_ok"] and not r["leaks"] else ("MISS" if not r["gold_ok"] else "LEAK")
            cell = f"{r['savings_pct']:>5}% g:{r['gold']} l:{r['leaks']}"
            if r["fail_open"]:
                cell = "FO " + cell
            if r["restored"]:
                cell += f" +{r['restored']}r"
            row.append(f"{cell:<20} {mark}")
        print(" | ".join(f"{c:<22}" for c in row))

    print("\n== per-ratio summary (cases where gold intact AND no leaks) ==")
    for ratio in ratios:
        rows = [run_point(c, ratio) for c in CASES]
        clean = sum(1 for r in rows if r["gold_ok"] and not r["leaks"])
        print(f"  ratio={ratio:<4} clean {clean}/{len(rows)} "
              f"| mean saved {sum(r['savings_pct'] for r in rows) / len(rows):.1f}% "
              f"| restored {sum(r['restored'] for r in rows)} blocks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
