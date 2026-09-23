#!/usr/bin/env python3
"""Tameru vs JEV-provider compaction comparison.

Same corpus as benchmarks/run_battery.py. Arms:
  tameru        — compress_context (deterministic extract)
  lcc-mech      — lcc compact_context(provider="mechanical") — free lexical fallback
  lcc-jev       — lcc compact_context(provider="jev") — TypeSafe System One

JEV requires a key: TYPESAFE_API_KEY env var or ~/.config/lcc/typesafe.key.
Cases that need an empty query or a 4,000-block document are excluded from
the JEV arm (lcc requires a non-empty objective; the big doc is kept for
the local arms only — ~500 scored blocks would burn API calls for no
information).

Metrics per arm×case: char savings %, gold-string recall, forbid-string
leaks, wall-clock latency, and determinism (a second run must emit
byte-identical text). Results land in jev-comparison-results.json and a
markdown table on stdout.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from run_battery import CASES  # noqa: E402
from tameru.compress_context import compress_context, estimate_tokens  # noqa: E402

try:
    from lcc.relevance.compactor import (  # noqa: E402
        RelevanceCompactionRequest,
        compact_context,
    )

    _LCC_OK = True
except ImportError:  # pragma: no cover - lcc optional
    _LCC_OK = False


def _jev_key_present() -> bool:
    import os

    if (os.environ.get("TYPESAFE_API_KEY") or "").strip():
        return True
    key_file = Path.home() / ".config" / "lcc" / "typesafe.key"
    return key_file.is_file() and bool(key_file.read_text().strip())


def _bridge_key_to_env() -> None:
    """lcc's provider availability check only reads the env var."""
    import os

    if (os.environ.get("TYPESAFE_API_KEY") or "").strip():
        return
    key_file = Path.home() / ".config" / "lcc" / "typesafe.key"
    if key_file.is_file():
        content = key_file.read_text(encoding="utf-8").strip()
        if content:
            os.environ["TYPESAFE_API_KEY"] = content


def _savings(before: str, after: str) -> float:
    return round((1 - len(after) / max(1, len(before))) * 100, 2)


def _gold(text: str, gold: list[str]) -> tuple[int, int]:
    return sum(1 for g in gold if g in text), len(gold)


def _leaks(text: str, forbid: list[str]) -> int:
    return sum(1 for f in forbid if f in text)


def run_tameru(case: dict) -> dict:
    t0 = time.perf_counter()
    out = compress_context(case["ctx"], case["q"], ccr=False, citations=True)
    ms = (time.perf_counter() - t0) * 1000
    again = compress_context(case["ctx"], case["q"], ccr=False, citations=True)
    hits, total = _gold(out.compressed_text, case.get("gold", []))
    return {
        "savings_pct": _savings(case["ctx"], out.compressed_text),
        "gold": f"{hits}/{total}",
        "gold_ok": hits == total,
        "forbid_leaks": _leaks(out.compressed_text, case.get("forbid", [])),
        "latency_ms": round(ms, 1),
        "deterministic": out.compressed_text == again.compressed_text,
        "fail_open": out.fail_open,
        "provider": "tameru-extract",
    }


def run_lcc(case: dict, provider: str) -> dict:
    req = RelevanceCompactionRequest(
        text=case["ctx"], question=case["q"], provider=provider, marker=False
    )
    t0 = time.perf_counter()
    res = compact_context(req)
    ms = (time.perf_counter() - t0) * 1000
    hits, total = _gold(res.compacted_text, case.get("gold", []))
    rep = res.report
    row = {
        "savings_pct": _savings(case["ctx"], res.compacted_text),
        "gold": f"{hits}/{total}",
        "gold_ok": hits == total,
        "forbid_leaks": _leaks(res.compacted_text, case.get("forbid", [])),
        "latency_ms": round(ms, 1),
        "provider": rep.provider_used,
        "degraded": rep.degraded,
        "guarantee": rep.semantic_guarantee,
        "jev_model": rep.jev_model_resolved,
        "calls": rep.calls,
    }
    again = compact_context(req)
    row["deterministic"] = res.compacted_text == again.compacted_text
    return row


def main() -> int:
    if not _LCC_OK:
        print("lcc not installed: pip install -e ../lcc", file=sys.stderr)
        return 2
    _bridge_key_to_env()
    have_jev = _jev_key_present() and bool((__import__("os").environ.get("TYPESAFE_API_KEY") or "").strip())

    # lcc requires a non-empty objective; JEV arm skips the 4k-block perf
    # doc (API cost for zero information gain).
    cases = [c for c in CASES if c["q"].strip()]
    jev_skip = {"large_doc_perf"}

    arms = ["tameru", "lcc-mech"] + (["lcc-jev"] if have_jev else [])
    if not have_jev:
        print("NOTE: no TYPESAFE_API_KEY — JEV arm skipped\n")

    results: dict[str, dict[str, dict]] = {}
    for case in cases:
        name = case["name"]
        results[name] = {"tameru": run_tameru(case), "lcc-mech": run_lcc(case, "mechanical")}
        if have_jev and name not in jev_skip:
            results[name]["lcc-jev"] = run_lcc(case, "jev")
        print(f"  {name} done", flush=True)

    out_path = Path(__file__).with_name("jev-comparison-results.json")
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # Per-case detail table.
    header = ["case", "arm", "saved%", "gold", "forbid", "ms", "det", "provider"]
    print("\n" + " | ".join(header))
    print("-" * 90)
    for name, arm_rows in results.items():
        for arm in arms:
            row = arm_rows.get(arm)
            if row is None:
                continue
            print(
                f"{name:<24} | {arm:<9} | {row['savings_pct']:>6} | {row['gold']:>5} "
                f"| {row['forbid_leaks']:>3} | {row['latency_ms']:>8} "
                f"| {'Y' if row['deterministic'] else 'n'} "
                f"| {row['provider']}{'*degraded' if row.get('degraded') else ''}"
            )

    # Aggregate per arm.
    print("\n== aggregate ==")
    for arm in arms:
        rows = [arm_rows[arm] for arm_rows in results.values() if arm in arm_rows]
        gold_ok = sum(1 for r in rows if r["gold_ok"])
        leaks = sum(r["forbid_leaks"] for r in rows)
        det = all(r["deterministic"] for r in rows)
        lat = statistics.median(r["latency_ms"] for r in rows)
        sav = statistics.mean(r["savings_pct"] for r in rows)
        print(
            f"{arm:<10} gold {gold_ok}/{len(rows)} | leaks {leaks} "
            f"| det {'Y' if det else 'n'} | median {lat:.0f} ms | mean saved {sav:.1f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
