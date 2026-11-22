"""Pre-tuning equivalence check of the session-corpus splits (descriptors only; no candidate setting is ever used).

    # per engine (run once with this checkout's src, once with a scratch worktree of the 1.9.0 engine); shardable
    python -m benchmarks.session_corpus.equivalence engine --engine-src src --label 1.10.0 --part 0/4 --out DIR
    # engine-free descriptors (structure)
    python -m benchmarks.session_corpus.equivalence structure --out DIR
    # classifier + acceptance gaps -> equivalence-result.json (registered, hashed) and equivalence-attempts.json
    python -m benchmarks.session_corpus.equivalence check --dir DIR

Descriptors per scenario (computed for every family under every real-output pool group, so any deal can be checked;
holdout texts are read only to compute these numbers):
  * engine (1.10.0 and 1.9.0) x host call settings (deepseek, hermes; exactly the profiles of
    benchmarks/engine_bench/run.py): acceptance rate, characters saved (share of sampled output characters) and
    fail-open rate over SAMPLE_STEPS steps per scenario (the steps with the lowest sha256("eq:"+id+":"+i), any window),
    query = the scenario's task message.  A stock-arm "facts held after compaction" descriptor needs a replay and is
    not computed here.
  * structure: mean fact step position (step / steps at 252K) and mean fact line position (line / lines) of the
    natural, error and buried facts inside the 252K slice; output-size histogram (5 bins) of the 252K slice; CJK share
    of the sampled steps; trigger crossings at 128K/252K/500K/1M for both hosts (retention model rho = 0.3); real-output
    share of the 252K slice and of the full session.
Classifier: L2 logistic regression (lambda 1, standardised features, Newton steps), own implementation.  Registered
primary statistic: out-of-fold AUC with folds grouped BY FAMILY (the unit the deal randomises), 5 folds, mean of 10
fold seeds; the scenario-level stratified 5-fold AUC is reported next to it.  Pass: grouped AUC <= 0.65 for dev vs
validation and dev vs holdout, and pooled step acceptance within 10 points across the three splits for every engine x
host.  The 1.9.0-vs-stock facts sign needs a replay (adapters, later task) and is recorded as not computed here.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import sys
import time
from pathlib import Path

from . import corpus
from . import generator as g
from . import families
from . import real as realmod

HERE = Path(__file__).resolve().parent
RESULT_FILE = HERE / "equivalence-result.json"
ATTEMPTS_FILE = HERE / "equivalence-attempts.json"
DESCRIPTORS_FILE = HERE / "equivalence-descriptors.jsonl"
SAMPLE_STEPS = 24
RHO = 0.3
CROSS_WINDOWS = (128_000, 252_000, 500_000, 1_000_000)
SIZE_BINS = (5000, 10000, 20000, 40000)
AUC_MAX, ACCEPT_GAP_MAX = 0.65, 10.0
PROFILES = ("deepseek", "hermes")
_MARKER_PREFIX = "⟪HERMES-CONTEXT-COMPRESSION:"
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def sample_steps(p: g.Plan) -> list[int]:
    return sorted(sorted(range(len(p.chars)), key=lambda i: hashlib.sha256(f"eq:{p.id}:{i}".encode()).hexdigest())[:SAMPLE_STEPS])


def pool_groups() -> dict[str, list[dict]]:
    """Real-output pools by the splits that share them, e.g. {"dev+validation": [...], "holdout": [...]}."""
    m = realmod.load_manifest()
    by_ids: dict[tuple, list[str]] = {}
    pools: dict[tuple, list[dict]] = {}
    for split in corpus.SPLITS:
        pool = realmod.pool_for(split, m)
        key = tuple(sorted(o["id"] for o in pool))
        by_ids.setdefault(key, []).append(split)
        pools[key] = pool
    return {"+".join(splits): pools[key] for key, splits in by_ids.items()}


def group_of_split() -> dict[str, str]:
    return {split: name for name in pool_groups() for split in name.split("+")}


def all_plans() -> list[tuple[str, g.Plan]]:
    """Every family under every real-output pool group: a scenario's content depends only on (family, index, pool), so
    descriptors computed once serve any deal of families to splits."""
    out = []
    for name, pool in pool_groups().items():
        out.extend((name, g.plan(f.id, i, pool, name)) for f in families.FAMILIES for i in range(g.SCENARIOS_PER_FAMILY))
    return out


# ------------------------------------------------------------------------------------------------ engine descriptors
def _engine(src: Path):
    sys.path.insert(0, str(src.resolve()))
    import tameru  # noqa: PLC0415
    from tameru.compress_context import compress_context  # noqa: PLC0415
    if not str(Path(tameru.__file__).resolve()).startswith(str(src.resolve())):
        raise RuntimeError(f"tameru imported from {tameru.__file__}, not {src}")

    def marker(omitted: int, total: int) -> str:
        return f"{_MARKER_PREFIX} {omitted:,} of {total:,} chars omitted here by Hermes's context compressor.⟫"

    def call(profile: str, text: str, query: str):
        """-> (accepted, saved_chars, fail_open); the call settings of benchmarks/engine_bench/run.py."""
        try:
            if profile == "deepseek":
                res = compress_context(text, query, min_savings_ratio=0.25, ccr=False, citations=False, strategy="extract")
            else:
                res = compress_context(text, query, ccr=False, citations=False, gap_marker=marker, inline_short_gaps=True,
                                       anchor_errors=True, prose_brief=True, recursion_markers=("[tameru:",), min_savings_ratio=0.10)
        except Exception:
            return False, 0, True
        if res.fail_open:
            return False, 0, True
        out = res.compressed_text
        ok = True
        if profile == "hermes":
            ok = (_RISK_ORDER.get(res.compression_risk or "", 2) <= _RISK_ORDER["high"]
                  and tameru.error_fingerprints(text, status_rows=False).keys() <= tameru.error_fingerprints(out, status_rows=False).keys())
        return ok, (len(text) - len(out)) if ok else 0, False

    return tameru.ENGINE_VERSION, call


def cmd_engine(args) -> int:
    version, call = _engine(Path(args.engine_src))
    if version != args.label:
        print(f"engine at {args.engine_src} is {version}, not {args.label}", file=sys.stderr)
        return 2
    k, n = (int(x) for x in args.part.split("/"))
    real = realmod.RealTexts(args.squeez)
    rows = []
    t0 = time.time()
    for j, (group, p) in enumerate(all_plans()):
        if j % n != k:
            continue
        q = g.task_text(p)
        acc = {pr: [0, 0, 0, 0] for pr in PROFILES}  # accepted, saved chars, fail-open, chars
        for i in sample_steps(p):
            text, _ = g.step_text(p, i, real)
            for pr in PROFILES:
                ok, saved, fo = call(pr, text, q)
                a = acc[pr]
                a[0] += ok
                a[1] += saved
                a[2] += fo
                a[3] += len(text)
        row = {"id": p.id, "family": p.family.id, "pool_group": group, "engine": version, "steps": SAMPLE_STEPS}
        for pr, (a, s, fo, c) in acc.items():
            row[f"{pr}_accept"] = round(a / SAMPLE_STEPS, 6)
            row[f"{pr}_saved"] = round(s / c, 6)
            row[f"{pr}_failopen"] = round(fo / SAMPLE_STEPS, 6)
        rows.append(row)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"engine-{version}-part{k}of{n}.jsonl").write_text("".join(corpus.canonical(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    print(f"{len(rows)} scenarios, {time.time() - t0:.0f}s")
    return 0


# ------------------------------------------------------------------------------------------------ structure descriptors
def crossings(chars: list[int], trigger_tokens: int, rho: float = RHO) -> int:
    ctx, n = 0.0, 0
    for c in chars:
        ctx += c / g.CHARS_PER_TOKEN
        if ctx >= trigger_tokens:
            n += 1
            ctx = rho * trigger_tokens
    return n


def _cjk(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿" or "　" <= ch <= "〿" or "＀" <= ch <= "￯")


def structure_row(group: str, p: g.Plan, real) -> dict:
    n252 = p.windows[252_000]
    sl = p.chars[:n252]
    row = {"id": p.id, "family": p.family.id, "pool_group": group, "language": p.language, "task_style": p.style}
    pos_step, pos_line = [], []
    by_step: dict[int, list] = {}
    for f in p.facts:
        if f.kind in ("natural", "error", "buried") and f.step < n252:
            by_step.setdefault(f.step, []).append(f)
    for i in sorted(by_step):
        text, facts = g.step_text(p, i, real)
        nl = text.count("\n") + 1
        for fd in facts:
            if fd["kind"] in ("natural", "error", "buried"):
                pos_step.append(i / n252)
                pos_line.append(fd["line_index"] / nl)
    row["fact_step_pos"] = round(sum(pos_step) / len(pos_step), 6)
    row["fact_line_pos"] = round(sum(pos_line) / len(pos_line), 6)
    edges = (0,) + SIZE_BINS + (10 ** 9,)
    for b in range(len(edges) - 1):
        row[f"size_bin{b}"] = round(sum(1 for c in sl if edges[b] <= c < edges[b + 1]) / len(sl), 6)
    cjk = tot = 0
    for i in sample_steps(p):
        text, _ = g.step_text(p, i, real)
        cjk += _cjk(text)
        tot += len(text)
    row["cjk_share"] = round(cjk / tot, 6)
    for w in CROSS_WINDOWS:
        n = p.windows[w]
        for host, trig in (("deepseek", g.ds_trigger(w)), ("hermes", g.hermes_trigger(w))):
            for rho in (0.1, 0.3, 0.5):
                row[f"cross_{host}_{w // 1000}k_rho{int(rho * 10)}"] = crossings(p.chars[:n], trig, rho)
    real_c = sum(c for c, k in zip(sl, p.kinds) if k == "real")
    row["real_share_252k"] = round(real_c / sum(sl), 6)
    row["real_share_full"] = round(sum(c for c, k in zip(p.chars, p.kinds) if k == "real") / sum(p.chars), 6)
    row["total_chars_full"] = sum(p.chars)
    row["steps"] = {str(w): p.windows[w] for w in g.WINDOWS}
    return row


def cmd_structure(args) -> int:
    real = realmod.RealTexts(args.squeez)
    rows = [structure_row(group, p, real) for group, p in all_plans()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "structure.jsonl").write_text("".join(corpus.canonical(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    print(f"{len(rows)} scenarios")
    return 0


# ------------------------------------------------------------------------------------------------ classifier
def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        d = m[c][c]
        for r in range(n):
            if r != c and m[r][c] != 0.0:
                f = m[r][c] / d
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_logistic(x: list[list[float]], y: list[int], lam: float = 1.0, iters: int = 30) -> tuple[list[float], list[float], list[float]]:
    d = len(x[0])
    mu = [sum(r[j] for r in x) / len(x) for j in range(d)]
    sd = [math.sqrt(sum((r[j] - mu[j]) ** 2 for r in x) / len(x)) or 1.0 for j in range(d)]
    z = [[1.0] + [(r[j] - mu[j]) / sd[j] for j in range(d)] for r in x]
    w = [0.0] * (d + 1)
    m = d + 1
    for _ in range(iters):
        grad = [lam * w[j] if j else 0.0 for j in range(m)]
        hess = [[(lam if j == k and j else 0.0) + (1e-9 if j == k else 0.0) for k in range(m)] for j in range(m)]
        for row, yi in zip(z, y):
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, sum(wi * zi for wi, zi in zip(w, row))))))
            e, v = p - yi, p * (1.0 - p)
            for j in range(m):
                rj = row[j]
                grad[j] += e * rj
                if rj:
                    vr = v * rj
                    hj = hess[j]
                    for k in range(j, m):
                        hj[k] += vr * row[k]
        for j in range(m):
            for k in range(j):
                hess[j][k] = hess[k][j]
        step = _solve(hess, grad)
        w = [wi - si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return w, mu, sd


def predict(model, row: list[float]) -> float:
    w, mu, sd = model
    s = w[0] + sum(wj * (v - m) / s_ for wj, v, m, s_ in zip(w[1:], row, mu, sd))
    return s


def auc(scores: list[float], y: list[int]) -> float:
    pairs = sorted(zip(scores, y))
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        i = j + 1
    n1 = sum(y)
    n0 = len(y) - n1
    r1 = sum(r for r, (_, lab) in zip(ranks, pairs) if lab == 1)
    return (r1 - n1 * (n1 + 1) / 2) / (n1 * n0)


def cv_auc(x, y, groups, *, by_group: bool, folds: int = 5, repeats: int = 10) -> float:
    vals = []
    for rep in range(repeats):
        fold_of = {}
        for lab in (0, 1):
            units = sorted({(groups[i] if by_group else i) for i in range(len(y)) if y[i] == lab},
                           key=lambda u: hashlib.sha256(f"fold:{rep}:{u}".encode()).hexdigest())
            for k, u in enumerate(units):
                fold_of[u] = k % folds
        scores = [0.0] * len(y)
        for f in range(folds):
            tr = [i for i in range(len(y)) if fold_of[groups[i] if by_group else i] != f]
            te = [i for i in range(len(y)) if fold_of[groups[i] if by_group else i] == f]
            if not te:
                continue
            model = fit_logistic([x[i] for i in tr], [y[i] for i in tr])
            for i in te:
                scores[i] = predict(model, x[i])
        vals.append(auc(scores, y))
    return round(sum(vals) / len(vals), 4)


ENGINE_FEATURES = [f"{e}_{pr}_{m}" for e in ("1.10.0", "1.9.0") for pr in PROFILES for m in ("accept", "saved", "failopen")]
STRUCT_FEATURES = (["fact_step_pos", "fact_line_pos"] + [f"size_bin{b}" for b in range(len(SIZE_BINS) + 1)] + ["cjk_share"]
                   + [f"cross_{h}_{w // 1000}k_rho3" for w in CROSS_WINDOWS for h in PROFILES] + ["real_share_252k", "real_share_full"])


def load_descriptors(d: Path) -> dict[str, dict]:
    """Rows of the current deal: each scenario's descriptors under the pool group of its family's split."""
    allrows: dict[tuple, dict] = {}
    for line in (d / "structure.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        allrows[(r["id"], r["pool_group"])] = r
    for f in sorted(d.glob("engine-*-part*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            for pr in PROFILES:
                for m in ("accept", "saved", "failopen"):
                    allrows[(r["id"], r["pool_group"])][f"{r['engine']}_{pr}_{m}"] = r[f"{pr}_{m}"]
    assignment, groups = corpus.family_split(), group_of_split()
    rows = {}
    for (sid, group), r in allrows.items():
        split = assignment[r["family"]]
        if groups[split] == group:
            rows[sid] = dict(r, split=split)
    missing = [i for i, r in rows.items() if any(k not in r for k in ENGINE_FEATURES)]
    if missing or len(rows) != len(families.FAMILIES) * g.SCENARIOS_PER_FAMILY:
        raise SystemExit(f"{len(missing)} scenarios lack engine descriptors (run the engine step for both engines, all parts)")
    return rows


def _pooled_accept(rows: list[dict], key: str) -> float:
    return round(100.0 * sum(r[key] for r in rows) / len(rows), 3)


def cmd_check(args) -> int:
    d = Path(args.dir)
    rows = load_descriptors(d)
    by_split = {s: [r for r in rows.values() if r["split"] == s] for s in corpus.SPLITS}
    feats = ENGINE_FEATURES + STRUCT_FEATURES
    comparisons = {}
    for other in ("validation", "holdout"):
        sel = by_split["dev"] + by_split[other]
        x = [[float(r[f]) for f in feats] for r in sel]
        y = [0] * len(by_split["dev"]) + [1] * len(by_split[other])
        fam = [r["family"] for r in sel]
        comparisons[f"dev_vs_{other}"] = {"auc_family_grouped": cv_auc(x, y, fam, by_group=True),
                                          "auc_scenario_level": cv_auc(x, y, fam, by_group=False),
                                          "n": [len(by_split["dev"]), len(by_split[other])]}
    accept = {}
    for e in ("1.10.0", "1.9.0"):
        for pr in PROFILES:
            key = f"{e}_{pr}_accept"
            per = {s: _pooled_accept(by_split[s], key) for s in corpus.SPLITS}
            accept[key] = {"per_split": per, "gap_points": round(max(per.values()) - min(per.values()), 3)}
            skey = f"{e}_{pr}_saved"
            accept[key]["saved_pct_per_split"] = {s: _pooled_accept(by_split[s], skey) for s in corpus.SPLITS}
            fkey = f"{e}_{pr}_failopen"
            accept[key]["failopen_pct_per_split"] = {s: _pooled_accept(by_split[s], fkey) for s in corpus.SPLITS}
    crossing = {}
    for s in corpus.SPLITS:
        rs = by_split[s]
        crossing[s] = {}
        for w in CROSS_WINDOWS:
            for h in PROFILES:
                for rho in (1, 3, 5):
                    k = f"cross_{h}_{w // 1000}k_rho{rho}"
                    crossing[s][k] = {"ge1_pct": round(100.0 * sum(r[k] >= 1 for r in rs) / len(rs), 1),
                                      "ge2_pct": round(100.0 * sum(r[k] >= 2 for r in rs) / len(rs), 1)}
    shares = {s: {"zh_scenarios_pct": round(100.0 * sum(r["language"] == "zh" for r in by_split[s]) / len(by_split[s]), 1),
                  "mixed_scenarios_pct": round(100.0 * sum(r["language"] == "mixed" for r in by_split[s]) / len(by_split[s]), 1),
                  "vague_pct": round(100.0 * sum(r["task_style"] == "vague" for r in by_split[s]) / len(by_split[s]), 1),
                  "real_chars_pct_full": round(100.0 * sum(r["real_share_full"] * r["total_chars_full"] for r in by_split[s])
                                               / sum(r["total_chars_full"] for r in by_split[s]), 2),
                  "scenarios": len(by_split[s]), "families": len({r["family"] for r in by_split[s]})} for s in corpus.SPLITS}
    passed = (all(c["auc_family_grouped"] <= AUC_MAX for c in comparisons.values())
              and all(a["gap_points"] <= ACCEPT_GAP_MAX for a in accept.values()))
    splits_doc = corpus.load_splits()
    desc_blob = "".join(corpus.canonical(rows[k]) + "\n" for k in sorted(rows))
    result = {
        "registered": datetime.date.today().isoformat(),
        "generator": g.GENERATOR_VERSION,
        "deal": splits_doc["deal"],
        "sealed_holdout_sha256": corpus.SEALED_HASH_FILE.read_text().split()[0],
        "descriptors_sha256": hashlib.sha256(desc_blob.encode("utf-8")).hexdigest(),
        "sample_steps_per_scenario": SAMPLE_STEPS,
        "engines": ["1.10.0 (this checkout)", "1.9.0 (commit 3bc2978, scratch worktree)"],
        "classifier": "L2 logistic regression (lambda 1, standardised, Newton), 5-fold CV x 10 fold seeds; primary = folds grouped by family",
        "features": feats,
        "gates": {"auc_max": AUC_MAX, "acceptance_gap_max_points": ACCEPT_GAP_MAX},
        "comparisons": comparisons,
        "acceptance": accept,
        "not_computed_here": "1.9.0-vs-stock facts sign (needs a replay; checked by the adapters' first dev run)",
        "trigger_crossing_pct": crossing,
        "content_shares": shares,
        "pass": passed,
    }
    result["result_sha256"] = hashlib.sha256(corpus.canonical(result).encode("utf-8")).hexdigest()
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    DESCRIPTORS_FILE.write_text(desc_blob, encoding="utf-8", newline="\n")
    attempts = json.loads(ATTEMPTS_FILE.read_text(encoding="utf-8")) if ATTEMPTS_FILE.exists() else []
    attempts.append({"date": result["registered"], "generator": g.GENERATOR_VERSION, "deal": splits_doc["deal"], "note": args.note,
                     "sealed_holdout_sha256": result["sealed_holdout_sha256"], "comparisons": comparisons,
                     "acceptance_gaps": {k: v["gap_points"] for k, v in accept.items()}, "pass": passed,
                     "result_sha256": result["result_sha256"]})
    ATTEMPTS_FILE.write_text(json.dumps(attempts, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"comparisons": comparisons, "acceptance_gaps": {k: v["gap_points"] for k, v in accept.items()}, "pass": passed}, indent=1))
    return 0 if passed else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("engine")
    e.add_argument("--engine-src", required=True)
    e.add_argument("--label", required=True)
    e.add_argument("--part", default="0/1")
    e.add_argument("--out", required=True)
    e.add_argument("--squeez", type=Path)
    s = sub.add_parser("structure")
    s.add_argument("--out", required=True)
    s.add_argument("--squeez", type=Path)
    c = sub.add_parser("check")
    c.add_argument("--dir", required=True)
    c.add_argument("--note", default="", help="why this attempt (logged in equivalence-attempts.json)")
    args = ap.parse_args(argv)
    return {"engine": cmd_engine, "structure": cmd_structure, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
