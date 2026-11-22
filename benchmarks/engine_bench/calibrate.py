"""Fit and check the S6 calibrators on the round-2 dev split, leave-family-out.

    python -m benchmarks.engine_bench.calibrate --rows benchmarks/engine_bench/results/r2-candidate-e6-dev-s6.jsonl \
        [--write src/tameru/calibration.json] [--report build/s6/calibration-report.json]

Unit: one accepted row (the host profile accepted the extract). Label y = 1 when the row kept every gold line and
dropped no protected fact line (ANALYSIS-PLAN-ROUND2.md, 2026-11-22 clarification). A row with
``fact_lines_dropped > 0`` has y = 0 by definition and gets p = 0 at runtime; the strata are fit on the other rows.

Method ``family-beta-v1`` (``tameru/calibration.py``): per stratum (``confidence_basis`` x specific/vague) a Beta whose
units are families, on top of PRIOR_STRENGTH pseudo-families at the global family-mean rate. A stratum with >= 50
rows from >= 3 families and >= 10 losses from >= 3 families whose raw confidence ranks its losses (family-bootstrap
AUROC 5th percentile >= 0.65) also gets an isotonic step map of raw confidence, families weighted equally. Every prediction in the leave-family-out check
comes from a fit that never saw the row's family. Nothing here is tuned: the constants below are fixed a priori.

Metrics per stratum, over all accepted rows with the posterior-mean p: n, families, observed rate, mean p, ECE (10
equal-width bins), reliability slope (logistic regression of y on logit p, p clipped to [1e-3, 1 - 1e-3], over the
rows without a fact drop, in strata whose table maps raw confidence; None where p is constant within the stratum or
one class is absent), gated when n >= 50. Pooled: AUROC of
p against "a fact-shaped line was dropped" (``fact_lines_dropped > 0``, or an s5 item's gold fact lost), the count of
vague or structural rows with p >= 0.99 outside a stratum that lifts the cap, and observed vs predicted per language.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tameru.calibration import _parse, beta_ppf, p_hat, stratum_key  # noqa: E402

METHOD = "family-beta-v1"
PRIOR_STRENGTH = 2.0
CAP = 0.989          # strictly below 0.99: vague and structural rows never reach 0.99 unless their stratum lifts it
SUPPORT = 0.99       # a stratum lifts the cap when its Beta 5th percentile reaches this
ISO_AUROC_LB = 0.65
ISO_MIN_ROWS, ISO_MIN_FAMILIES = 50, 3
ISO_MIN_LOSSES, ISO_MIN_LOSS_FAMILIES = 10, 3   # a step map needs losses from several families
GATE_MIN_N = 50
BOOTSTRAP = 1000
SEED = 20261122
BINS = 10


def label(row: dict) -> int:
    kept = (not row["gold_total"]) or all(row["gold_each"])
    return int(kept and not (row.get("fact_lines_dropped") or 0) > 0)


def fact_drop_label(row: dict) -> int:
    s5_lost = str(row.get("item_kind", "")).startswith("s5") and row["gold_total"] and not all(row["gold_each"])
    return int((row.get("fact_lines_dropped") or 0) > 0 or bool(s5_lost))


def dropped(row: dict) -> bool:
    return (row.get("fact_lines_dropped") or 0) > 0


def key(row: dict) -> str:
    return stratum_key(row.get("confidence_basis"), bool(row.get("query_specific")))


def auroc(high: list[float], low: list[float]) -> float | None:
    """P(a score from ``high`` exceeds one from ``low``), ties counted half (Mann-Whitney U)."""
    if not high or not low:
        return None
    pooled = sorted([(v, 1) for v in high] + [(v, 0) for v in low])
    rank_high, i = 0.0, 0
    while i < len(pooled):
        j = i
        while j < len(pooled) and pooled[j][0] == pooled[i][0]:
            j += 1
        rank_high += (i + 1 + j) / 2.0 * sum(flag for _v, flag in pooled[i:j])
        i = j
    return (rank_high - len(high) * (len(high) + 1) / 2.0) / (len(high) * len(low))


def _by_family(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["family"]].append(r)
    return out


def _auroc_lb(rows: list[dict]) -> float | None:
    """5th percentile of the family-bootstrap AUROC of raw confidence (kept above lost); None when uninformative."""
    fams = _by_family(rows)
    names = sorted(fams)
    rng = random.Random(f"{SEED}:{len(rows)}:{names}")
    values = []
    for _ in range(BOOTSTRAP):
        sample = [r for name in (rng.choice(names) for _ in names) for r in fams[name]]
        a = auroc([r["confidence"] for r in sample if label(r)], [r["confidence"] for r in sample if not label(r)])
        if a is not None:
            values.append(a)
    if len(values) < BOOTSTRAP // 2:
        return None
    values.sort()
    return values[int(0.05 * len(values))]


def _isotonic(rows: list[dict]) -> list[list[float]]:
    """Weighted pool-adjacent-violators of y on raw confidence, each family's rows weighing 1 in all."""
    size = {name: len(group) for name, group in _by_family(rows).items()}
    levels: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        w = 1.0 / size[r["family"]]
        levels[float(r["confidence"])][0] += w
        levels[float(r["confidence"])][1] += w * label(r)
    blocks = []  # [upper edge, weight, weighted y]
    for conf in sorted(levels):
        w, wy = levels[conf]
        blocks.append([conf, w, wy])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][1] > blocks[-1][2] / blocks[-1][1]:
            edge, w2, wy2 = blocks.pop()
            blocks[-1] = [edge, blocks[-1][1] + w2, blocks[-1][2] + wy2]
    return [[edge, wy / w] for edge, w, wy in blocks]


def fit(rows: list[dict]) -> dict:
    """The calibration table (``tameru/calibration.py`` schema) for accepted ``rows``."""
    clean = [r for r in rows if not dropped(r)]
    family_rates = [sum(label(r) for r in g) / len(g) for g in _by_family(clean).values()]
    mu0 = min(1 - 1e-3, max(1e-3, statistics.fmean(family_rates)))
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in clean:
        groups[key(r)].append(r)
    strata = {}
    for k in sorted(groups):
        g = groups[k]
        rates = [sum(label(r) for r in fg) / len(fg) for fg in _by_family(g).values()]
        alpha = sum(rates) + PRIOR_STRENGTH * mu0
        beta = sum(1 - x for x in rates) + PRIOR_STRENGTH * (1 - mu0)
        losses = sum(1 - label(r) for r in g)
        lb, iso = None, []
        loss_families = len({r["family"] for r in g if not label(r)})
        if (len(g) >= ISO_MIN_ROWS and len(rates) >= ISO_MIN_FAMILIES and losses >= ISO_MIN_LOSSES
                and loss_families >= ISO_MIN_LOSS_FAMILIES):
            lb = _auroc_lb(g)
            if lb is not None and lb >= ISO_AUROC_LB:
                iso = _isotonic(g)
        strata[k] = {"alpha": round(alpha, 9), "beta": round(beta, 9), "families": len(rates), "rows": len(g),
                     "losses": losses, "lifts_cap": beta_ppf(0.05, alpha, beta) >= SUPPORT, "iso": iso,
                     "auroc_lb": None if lb is None else round(lb, 4)}
    return {
        "schema": 1, "method": METHOD,
        "label": "accepted extract kept every gold line and dropped no protected fact line",
        "prior": {"mean": round(mu0, 9), "strength": PRIOR_STRENGTH},
        "cap": {"value": CAP, "applies_to": "style vague or basis structural",
                "lifted_when": "the stratum's Beta 5th percentile >= 0.99"},
        "strata": strata,
    }


def predict(table: dict, rows: list[dict], quantile: float = 0.5) -> list[float]:
    cal = _parse(table)
    return [p_hat(r.get("confidence_basis"), bool(r.get("query_specific")), r.get("fact_lines_dropped") or 0,
                  r.get("confidence"), quantile=quantile, table=cal) for r in rows]


def ece(ps: list[float], ys: list[int]) -> float:
    bins: dict[int, list[int]] = defaultdict(list)
    for i, p in enumerate(ps):
        bins[min(BINS - 1, int(p * BINS))].append(i)
    return sum(len(ix) / len(ps) * abs(statistics.fmean(ps[i] for i in ix) - statistics.fmean(ys[i] for i in ix))
               for ix in bins.values())


def slope(ps: list[float], ys: list[int]) -> float | None:
    """Logistic regression of y on logit p (Newton); None where p is constant, one class is absent or it separates."""
    if len({round(p, 12) for p in ps}) < 2 or len(set(ys)) < 2:
        return None
    z = [math.log(p / (1 - p)) for p in (min(1 - 1e-3, max(1e-3, p)) for p in ps)]
    a = b = 0.0
    for _ in range(100):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for zi, yi in zip(z, ys):
            eta = max(-30.0, min(30.0, a + b * zi))
            mu = 1.0 / (1.0 + math.exp(-eta))
            w = mu * (1 - mu)
            g0, g1 = g0 + yi - mu, g1 + (yi - mu) * zi
            h00, h01, h11 = h00 + w, h01 + w * zi, h11 + w * zi * zi
        det = h00 * h11 - h01 * h01
        if det <= 1e-12:
            return None
        da, db = (h11 * g0 - h01 * g1) / det, (h00 * g1 - h01 * g0) / det
        a, b = a + da, b + db
        if abs(b) > 1e3:
            return None
        if abs(da) + abs(db) < 1e-10:
            break
    return b


def metrics(rows: list[dict], ps: list[float], varying: set[str], lifted: set[str]) -> dict:
    """``varying``: the strata whose shipped table maps raw confidence (isotonic); elsewhere p is constant within a
    stratum, so a slope over leave-family-out predictions would only measure fold-to-fold noise. ``lifted``: the
    strata whose table lifts the 0.99 cap; only rows outside them count against the vague/structural rule."""
    ys = [label(r) for r in rows]
    strata = {}
    for k in sorted({key(r) for r in rows}):
        ix = [i for i, r in enumerate(rows) if key(r) == k]
        clean = [i for i in ix if not dropped(rows[i])]
        strata[k] = {
            "n": len(ix), "families": len({rows[i]["family"] for i in ix}), "gated": len(ix) >= GATE_MIN_N,
            "fact_drop_rows": len(ix) - len(clean),
            "observed": round(statistics.fmean(ys[i] for i in ix), 4),
            "mean_p": round(statistics.fmean(ps[i] for i in ix), 4),
            "ece": round(ece([ps[i] for i in ix], [ys[i] for i in ix]), 4),
            "slope": None if k not in varying or (s := slope([ps[i] for i in clean], [ys[i] for i in clean])) is None
            else round(s, 3),
        }
    fd = [fact_drop_label(r) for r in rows]
    languages = {}
    for lang in sorted({r["language"] for r in rows}):
        ix = [i for i, r in enumerate(rows) if r["language"] == lang]
        languages[lang] = {"n": len(ix), "observed": round(statistics.fmean(ys[i] for i in ix), 4),
                           "mean_p": round(statistics.fmean(ps[i] for i in ix), 4)}
    vague_structural = [i for i, r in enumerate(rows) if key(r) not in lifted
                        and (not r.get("query_specific") or r.get("confidence_basis") == "structural")]
    a = auroc([p for p, f in zip(ps, fd) if not f], [p for p, f in zip(ps, fd) if f])
    return {
        "rows": len(rows), "observed": round(statistics.fmean(ys), 4), "mean_p": round(statistics.fmean(ps), 4),
        "ece": round(ece(ps, ys), 4), "strata": strata, "languages": languages,
        "auroc_vs_fact_drop": None if a is None else round(a, 4), "fact_drop_positives": sum(fd),
        "p_ge_099_vague_or_structural": sum(1 for i in vague_structural if ps[i] >= 0.99),
        "gated_failures": sorted(k for k, s in strata.items() if s["gated"] and (
            s["ece"] > 0.05 or (s["slope"] is not None and not 0.8 <= s["slope"] <= 1.2))),
    }


def leave_family_out(rows: list[dict]) -> list[float]:
    ps = [0.0] * len(rows)
    for fam in sorted({r["family"] for r in rows}):
        table = fit([r for r in rows if r["family"] != fam])
        ix = [i for i, r in enumerate(rows) if r["family"] == fam]
        for i, p in zip(ix, predict(table, [rows[i] for i in ix])):
            ps[i] = p
    return ps


def _print(title: str, m: dict) -> None:
    print(f"\n{title}: rows {m['rows']}  observed {m['observed']}  mean p {m['mean_p']}  ECE {m['ece']}  "
          f"AUROC vs fact drop {m['auroc_vs_fact_drop']} ({m['fact_drop_positives']} positives)  "
          f"p>=0.99 on vague/structural rows {m['p_ge_099_vague_or_structural']}")
    print(f"  {'stratum':22} {'n':>5} {'fam':>4} {'drop':>4} {'observed':>8} {'mean p':>7} {'ECE':>6} {'slope':>6}")
    for k, s in m["strata"].items():
        flag = "" if not s["gated"] else (" FAIL" if k in m["gated_failures"] else " pass")
        print(f"  {k:22} {s['n']:>5} {s['families']:>4} {s['fact_drop_rows']:>4} {s['observed']:>8} {s['mean_p']:>7} "
              f"{s['ece']:>6} {s['slope'] if s['slope'] is not None else '-':>6}{flag}")
    print("  languages: " + ", ".join(f"{k} n={v['n']} observed {v['observed']} mean p {v['mean_p']}" for k, v in m["languages"].items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--write", type=Path, help="write the table fit on every row here (src/tameru/calibration.json)")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args(argv)
    raw = args.rows.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if {r["split"] for r in rows} != {"dev"}:
        print("refusing: the calibrators are fit on the round-2 dev split only", file=sys.stderr)
        return 2
    accepted = [r for r in rows if r["accepted"]]
    if any(r.get("confidence_basis") is None or r.get("query_specific") is None for r in accepted):
        print("refusing: rows lack confidence_basis/query_specific (re-run engine_bench with the S6 fields)", file=sys.stderr)
        return 2
    table = fit(accepted)
    table["source"] = {
        "rows": args.rows.as_posix(), "rows_sha256": hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(),
        "split": "dev", "accepted_rows": len(accepted), "families": len({r["family"] for r in accepted}),
        "engine_commit": sorted({str(r.get("engine_commit")) for r in rows}),
    }
    varying = {k for k, s in table["strata"].items() if s["iso"]}
    lifted = {k for k, s in table["strata"].items() if s["lifts_cap"]}
    lfo = metrics(accepted, leave_family_out(accepted), varying, lifted)
    insample = metrics(accepted, predict(table, accepted), varying, lifted)
    _print("leave-family-out (dev)", lfo)
    _print("in-sample (dev, the shipped table)", insample)
    print("\n  table: " + "; ".join(
        f"{k} mean {s['alpha'] / (s['alpha'] + s['beta']):.4f} q10 {beta_ppf(0.1, s['alpha'], s['beta']):.4f}"
        f"{' iso' if s['iso'] else ''}{' lifts-cap' if s['lifts_cap'] else ''}" for k, s in table["strata"].items()))
    if args.write:
        args.write.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"leave_family_out": lfo, "in_sample": insample, "table": table}, indent=1) + "\n",
                               encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
