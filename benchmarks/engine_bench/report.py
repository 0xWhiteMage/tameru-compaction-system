"""Analysis helpers for engine_bench rows (standard library only).

    python -m benchmarks.engine_bench.report FILE.jsonl [...]            # headline + call-outs per file
    python -m benchmarks.engine_bench.report --compare A.jsonl B.jsonl   # paired cluster-bootstrap B - A
    python -m benchmarks.engine_bench.report --selfcheck FILE.jsonl      # arm-vs-itself must be exactly 0

Intervals are percentile 95% intervals from a seeded cluster bootstrap: ``source_case`` clusters are
resampled with replacement and the statistic recomputed; the cluster count is printed next to every interval.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

SEED = 20261118
BOOT = 1000


def load(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------------ statistics
def cluster_mean(pairs: list[tuple[str, float]], boot: int = BOOT, seed: int = SEED) -> dict:
    """Mean of values with a cluster-bootstrap interval.  ``pairs`` = [(cluster, value)]."""
    by: dict[str, list[float]] = defaultdict(list)
    for cluster, v in pairs:
        by[cluster].append(v)
    if not by:
        return {"mean": None, "lo": None, "hi": None, "n": 0, "clusters": 0}
    keys = sorted(by)
    sums = [(sum(by[k]), len(by[k])) for k in keys]
    total, n = sum(s for s, _ in sums), sum(c for _, c in sums)
    mean = total / n
    rng = random.Random(seed)
    means = []
    for _ in range(boot):
        picks = [sums[rng.randrange(len(sums))] for _ in sums]
        cnt = sum(c for _, c in picks)
        means.append(sum(s for s, _ in picks) / cnt)
    means.sort()
    return {"mean": mean, "lo": means[int(0.025 * (boot - 1))], "hi": means[int(0.975 * (boot - 1))], "n": n, "clusters": len(keys)}


def auroc(scores: list[float], labels: list[bool]) -> float | None:
    """P(score of a positive > score of a negative), ties count 1/2 (Mann-Whitney), None if one class is empty."""
    pos = sum(1 for y in labels if y)
    neg = len(labels) - pos
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    rank_sum, i = 0.0, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        rank_sum += avg * sum(1 for k in order[i:j + 1] if labels[k])
        i = j + 1
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def _auroc_rows(rows):
    use = [r for r in rows if r["confidence"] is not None and not r["fail_open"] and r["all_gold_kept_raw"] is not None]
    return use, auroc([r["confidence"] for r in use], [bool(r["all_gold_kept_raw"]) for r in use])


def auroc_ci(rows, boot: int = 300, seed: int = SEED) -> dict:
    use, point = _auroc_rows(rows)
    by: dict[str, list[dict]] = defaultdict(list)
    for r in use:
        by[r["source_case"]].append(r)
    keys = sorted(by)
    rng = random.Random(seed)
    vals = []
    for _ in range(boot):
        sample = [r for k in (keys[rng.randrange(len(keys))] for _ in keys) for r in by[k]]
        a = auroc([r["confidence"] for r in sample], [bool(r["all_gold_kept_raw"]) for r in sample])
        if a is not None:
            vals.append(a)
    vals.sort()
    ok = bool(vals) and point is not None
    return {"auroc": point, "lo": vals[int(0.025 * (len(vals) - 1))] if ok else None,
            "hi": vals[int(0.975 * (len(vals) - 1))] if ok else None, "n": len(use), "clusters": len(keys)}


def calibration(rows, edges=(0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001)) -> list[dict]:
    """Bins of confidence vs fraction of rows whose output kept every gold string (non-fail-open rows)."""
    use, _ = _auroc_rows(rows)
    table = []
    for lo, hi in zip(edges, edges[1:]):
        b = [r for r in use if lo <= r["confidence"] < hi]
        table.append({"bin": f"[{lo:.1f},{min(hi, 1.0):.1f}{']' if hi > 1 else ')'}", "n": len(b),
                      "fully_kept": (sum(1 for r in b if r["all_gold_kept_raw"]) / len(b)) if b else None})
    return table


def paired_diff(a_rows, b_rows, metric: str, boot: int = BOOT) -> dict:
    """Cluster-bootstrap mean of (B - A) over rows matched by (case, profile, query_condition)."""
    key = lambda r: (r["case"], r["profile"], r["query_condition"])  # noqa: E731
    a = {key(r): r for r in a_rows}
    pairs = []
    for r in b_rows:
        m = a.get(key(r))
        if m is not None and r.get(metric) is not None and m.get(metric) is not None:
            pairs.append((r["source_case"], float(r[metric]) - float(m[metric])))
    return cluster_mean(pairs, boot)


# ------------------------------------------------------------------ tables
def _fmt(v, nd=1):
    return "-" if v is None else f"{v:.{nd}f}"


def _ci(s, scale=1.0, nd=1):
    if s["mean"] is None:
        return "-"
    return f"{s['mean'] * scale:.{nd}f} [{s['lo'] * scale:.{nd}f},{s['hi'] * scale:.{nd}f}]"


def summarize(rows, boot: int = 500) -> dict:
    gold_rows = [r for r in rows if r["gold_kept"] is not None]
    saved = cluster_mean([(r["source_case"], r["saved_pct"]) for r in rows], boot)
    kept = cluster_mean([(r["source_case"], 100.0 * r["gold_kept"]) for r in gold_rows], boot)
    fo = 100.0 * sum(1 for r in rows if r["fail_open"]) / len(rows) if rows else None
    pooled_in = sum(r["chars_in"] for r in rows)
    pooled = 100.0 * (1 - sum(r["chars_out"] for r in rows) / pooled_in) if pooled_in else None
    return {"n": len(rows), "clusters": len({r["source_case"] for r in rows}), "saved": saved, "kept": kept,
            "fail_open": fo, "pooled_saved": pooled, "auroc": auroc_ci(rows, 200)}


def _row_text(label, s):
    a = s["auroc"]
    au = "-" if a["auroc"] is None else f"{a['auroc']:.3f} [{_fmt(a['lo'], 3)},{_fmt(a['hi'], 3)}]"
    return (f"{label:<26} {s['n']:>4} {s['clusters']:>4}  {_ci(s['saved']):<20} {_fmt(s['pooled_saved']):>6}  "
            f"{_ci(s['kept']):<20} {_fmt(s['fail_open']):>5}  {au}")


HEAD = (f"{'profile x condition':<26} {'n':>4} {'clus':>4}  {'saved% (case mean, CI)':<20} {'pool%':>6}  "
        f"{'gold kept% (CI)':<20} {'fo%':>5}  AUROC(all gold kept | non-fail-open)")


def headline(rows, by_split: bool = True) -> str:
    out = []
    groups = [("ALL", rows)] if not by_split else [("ALL", rows)] + [(s, [r for r in rows if r["split"] == s]) for s in sorted({r["split"] for r in rows})]
    engine = sorted({r["engine"] for r in rows})
    for name, sub in groups:
        if not sub:
            continue
        out += [f"\n== engine {','.join(engine)} | split {name} | {len({r['case'] for r in sub})} cases, {len({r['source_case'] for r in sub})} clusters ==", HEAD]
        for p in sorted({r["profile"] for r in sub}):
            for c in sorted({r["query_condition"] for r in sub}):
                g = [r for r in sub if r["profile"] == p and r["query_condition"] == c]
                if g:
                    out.append(_row_text(f"{p} x {c}", summarize(g)))
    use = [r for r in rows if r["profile"] == "deepseek" and r["query_condition"] == "task"]
    out.append("\nCalibration (deepseek x task, non-fail-open rows: confidence bin -> fraction with ALL gold kept)")
    out.append("  " + "  ".join(f"{b['bin']} n={b['n']} {_fmt(None if b['fully_kept'] is None else 100 * b['fully_kept'], 0)}%" for b in calibration(use)))
    return "\n".join(out)


def _sel(rows, **kw):
    return [r for r in rows if all((r[k] == v if not callable(v) else v(r[k])) for k, v in kw.items())]


def callouts(rows) -> str:
    out = ["\n== call-outs =="]
    g = _sel(rows, profile="deepseek", query_condition="generic")
    if g:
        out.append("DeepSeek generic-query saved%:\n  " + _row_text("deepseek x generic", summarize(g)))
    for shape in ("trace-java", "trace-dotnet"):
        sub = [r for r in rows if r["shape"] == shape]
        out.append(f"{shape} saved% per profile x condition (clusters = source_case):")
        for p in sorted({r["profile"] for r in sub}):
            for c in sorted({r["query_condition"] for r in sub}):
                gg = [r for r in sub if r["profile"] == p and r["query_condition"] == c]
                if gg:
                    s = summarize(gg, 200)
                    out.append(f"  {p:<8} {c:<10} n={s['n']:>3} clusters={s['clusters']:>2} saved%={_ci(s['saved'])} gold kept%={_ci(s['kept'])}")
    for label, pred in (("uni-fullwidth", lambda r: r["shape"] == "uni-fullwidth"), ("jp_musubi-like (jp_musubi + ja/ko language cases)", lambda r: r["shape"] == "jp_musubi" or r["case"].startswith(("rt-lang-ja", "rt-lang-ko")))):
        sub = [r for r in rows if pred(r)]
        out.append(f"{label}:" + ("" if sub else " (no rows in this file's splits)"))
        for r in sorted(sub, key=lambda r: (r["case"], r["profile"], r["query_condition"])):
            out.append(f"  {r['case']:<28} {r['profile']:<8} {r['query_condition']:<9} saved={r['saved_pct']:6.1f}% gold={_fmt(None if r['gold_kept'] is None else 100 * r['gold_kept'], 0):>4}% conf={_fmt(r['confidence'], 3)} fo={int(r['fail_open'])}")
    zh = [r for r in rows if r["query_condition"] == "zh_user"]
    out.append(f"zh_user rows' confidence ({len(zh)} rows, {len({r['source_case'] for r in zh})} clusters):")
    for p in sorted({r["profile"] for r in zh}):
        for lang in ("zh", "mixed"):
            g = [r for r in zh if r["profile"] == p and r["language"] == lang]
            confs = [r["confidence"] for r in g if r["confidence"] is not None]
            if g:
                out.append(f"  {p:<8} {lang:<5} n={len(g):>3} clusters={len({r['source_case'] for r in g}):>2} confidence min/mean/max="
                           f"{min(confs):.3f}/{sum(confs) / len(confs):.3f}/{max(confs):.3f}  fail_open={sum(r['fail_open'] for r in g)}  "
                           f"gold kept%={_fmt(100 * sum(r['gold_kept'] for r in g) / len(g), 1)} saved%={_fmt(sum(r['saved_pct'] for r in g) / len(g), 1)}"
                           if confs else f"  {p} {lang} n={len(g)} no confidence")
    return "\n".join(out)


def compare_text(a_rows, b_rows, label="B - A") -> str:
    out = [f"== paired difference {label} (matched by case x profile x condition; cluster bootstrap) =="]
    for p in sorted({r["profile"] for r in b_rows}):
        for c in sorted({r["query_condition"] for r in b_rows}):
            sa, sb = _sel(a_rows, profile=p, query_condition=c), _sel(b_rows, profile=p, query_condition=c)
            for metric in ("saved_pct", "gold_kept", "fail_open"):
                for rs in (sa, sb):
                    for r in rs:
                        if metric == "fail_open":
                            r["_fo"] = 100.0 * bool(r["fail_open"])
                m = "_fo" if metric == "fail_open" else metric
                scale = 100.0 if metric == "gold_kept" else 1.0
                d = paired_diff(sa, sb, m)
                out.append(f"{p:<8} {c:<10} {metric:<10} diff={_ci(d, scale, 3)} pairs={d['n']} clusters={d['clusters']}")
    return "\n".join(out)


def selfcheck(rows) -> bool:
    """Arm-vs-itself: every paired difference must be exactly 0 (mean and both bounds)."""
    ok = True
    for metric in ("saved_pct", "gold_kept", "confidence", "chars_out"):
        d = paired_diff(rows, rows, metric)
        if d["n"] and (d["mean"] != 0 or d["lo"] != 0 or d["hi"] != 0):
            ok = False
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--selfcheck", metavar="FILE")
    args = ap.parse_args(argv)
    if args.selfcheck:
        ok = selfcheck(load(args.selfcheck))
        print("arm-vs-self difference is exactly 0" if ok else "FAIL: arm-vs-self difference is not 0")
        return 0 if ok else 1
    if args.compare:
        print(compare_text(load(args.compare[0]), load(args.compare[1])))
        return 0
    for f in args.files:
        rows = load(f)
        print(f"# {f}")
        print(headline(rows))
        print(callouts(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
