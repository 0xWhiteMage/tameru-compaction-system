"""Round-3 split equivalence check (descriptors only; no candidate setting is ever used).

    # engine descriptors, once per engine (this checkout's src, and a scratch worktree of 1.9.0); shardable
    python -m benchmarks.engine_bench.equivalence_r3 engine --engine-src src --label 1.10.0 --part 0/1 --out DIR
    python -m benchmarks.engine_bench.equivalence_r3 engine --engine-src <worktree>/src --label 1.9.0 --part 0/1 --out DIR
    # engine-free descriptors
    python -m benchmarks.engine_bench.equivalence_r3 structure --out DIR
    # classifier + gates -> equivalence-r3-result.json; every check logs to equivalence-r3-attempts.json
    python -m benchmarks.engine_bench.equivalence_r3 check --dir DIR

Descriptors per case (computed for every generated case, so any deal can be checked; sealed r3 texts are read only
to compute these numbers):
  * engine (1.10.0 and 1.9.0) x host call settings (deepseek, hermes; exactly the profiles of run.py): acceptance
    share, pooled saved-chars share and fail-open share over the case's query conditions.  Gold kept is NOT used.
  * structure: mean gold-line position (line index / lines), char/line counts, size-bin histogram (5 bins), CJK
    share, language and item-kind indicators.
Classifier: the session corpus's L2 logistic regression (benchmarks/session_corpus/equivalence.py), out-of-fold AUC
with folds grouped BY FAMILY (the unit the deal randomises).  Gates: grouped AUC sealed vs dev <= 0.65 (validation vs
dev is reported), pooled acceptance within 10 points of dev for every engine x host, and the 1.10.0-minus-1.9.0
saved-ratio difference with the same sign on sealed as on dev.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path

from benchmarks.session_corpus.equivalence import PROFILES, _engine, cv_auc

from . import corpus

HERE = Path(__file__).resolve().parent
RESULT_FILE = HERE / "equivalence-r3-result.json"
ATTEMPTS_FILE = HERE / "equivalence-r3-attempts.json"
DESCRIPTORS_FILE = HERE / "equivalence-r3-descriptors.jsonl"
SIZE_BINS = (1500, 3000, 6000, 12000)
AUC_MAX, ACCEPT_GAP_MAX = 0.65, 10.0
ENGINES = ("1.10.0", "1.9.0")


def canonical(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ------------------------------------------------------------------------------------------------ engine descriptors
def case_queries(case: dict) -> list[str]:
    return [case["queries"][c] for c in
            ("task_specific", "task_vague", "build_specific", "build_vague", "tool_call", "generic", "zh_user")
            if c in case["queries"]]


def cmd_engine(args) -> int:
    version, call = _engine(Path(args.engine_src))
    if version != args.label:
        print(f"engine at {args.engine_src} is {version}, not {args.label}", file=sys.stderr)
        return 2
    k, n = (int(x) for x in args.part.split("/"))
    cases = corpus._build_r3()
    rows = []
    for j, case in enumerate(cases):
        if j % n != k:
            continue
        row = {"id": case["id"], "family": case["family"], "engine": version}
        for pr in PROFILES:
            acc = saved = fo = chars = 0
            queries = case_queries(case)
            for q in queries:
                ok, s, f = call(pr, case["text"], q)
                acc += ok
                saved += s
                fo += f
                chars += len(case["text"])
            row[f"{pr}_accept"] = round(acc / len(queries), 6)
            row[f"{pr}_saved"] = round(saved / chars, 6) if chars else 0.0
            row[f"{pr}_failopen"] = round(fo / len(queries), 6)
        rows.append(row)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"engine-{version}-part{k}of{n}.jsonl").write_text(
        "".join(canonical(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    print(f"{len(rows)} cases -> {out}")
    return 0


# ------------------------------------------------------------------------------------------------ structure descriptors
def _cjk(text: str) -> int:
    return sum(1 for ch in text if "一" <= ch <= "鿿" or "　" <= ch <= "〿" or "＀" <= ch <= "￯")


def structure_row(case: dict) -> dict:
    lines = case["text"].splitlines()
    nl = max(1, len(lines))
    gold_pos = []
    idx = {ln: i for i, ln in enumerate(lines)}
    for g in case["gold"]:
        hits = [i for i, ln in enumerate(lines) if ln == g]
        if hits:
            gold_pos.append(hits[0] / nl)
    size = len(case["text"])
    edges = (0,) + SIZE_BINS + (10 ** 12,)
    row = {"id": case["id"], "family": case["family"],
           "gold_line_pos": round(sum(gold_pos) / len(gold_pos), 6) if gold_pos else 0.0,
           "log_chars": round(math.log10(max(1, size)), 6), "n_lines": nl,
           "cjk_share": round(_cjk(case["text"]) / size, 6) if size else 0.0,
           "lang_zh": int(case["language"] == "zh"), "lang_mixed": int(case["language"] == "mixed"),
           "kind_s5_buried": int(case["item_kind"] == "s5_buried"),
           "kind_s5_superseded": int(case["item_kind"] == "s5_superseded"),
           "kind_csv_args": int(case["item_kind"] == "csv_args")}
    for b in range(len(edges) - 1):
        row[f"size_bin{b}"] = float(edges[b] <= size < edges[b + 1])
    return row


def cmd_structure(args) -> int:
    rows = [structure_row(c) for c in corpus._build_r3()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "structure.jsonl").write_text("".join(canonical(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    print(f"{len(rows)} cases -> {out}")
    return 0


# ------------------------------------------------------------------------------------------------ check
ENGINE_FEATURES = [f"{e}_{pr}_{m}" for e in ENGINES for pr in PROFILES for m in ("accept", "saved", "failopen")]
STRUCT_FEATURES = (["gold_line_pos", "log_chars", "n_lines", "cjk_share", "lang_zh", "lang_mixed",
                    "kind_s5_buried", "kind_s5_superseded", "kind_csv_args"]
                   + [f"size_bin{b}" for b in range(len(SIZE_BINS) + 1)])


def load_descriptors(d: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in (d / "structure.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        rows[r["id"]] = r
    for f in sorted(d.glob("engine-*-part*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            for pr in PROFILES:
                for m in ("accept", "saved", "failopen"):
                    rows[r["id"]][f"{r['engine']}_{pr}_{m}"] = r[f"{pr}_{m}"]
    missing = [i for i, r in rows.items() if any(k not in r for k in ENGINE_FEATURES)]
    cases = {c["id"]: c for c in corpus._build_r3()}
    if missing or len(rows) != len(cases):
        raise SystemExit(f"{len(missing)} cases lack engine descriptors (run the engine step for both engines, all parts)")
    return rows


def _pooled(rows: list[dict], key: str) -> float:
    return round(100.0 * sum(r[key] for r in rows) / len(rows), 3) if rows else None


def cmd_check(args) -> int:
    d = Path(args.dir)
    rows = load_descriptors(d)
    assignment = corpus.r3_assignment()
    for cid, r in rows.items():
        r["split"] = assignment[cid]
    by_split = {s: [r for r in rows.values() if r["split"] == s] for s in ("dev", "validation", "sealed")}
    feats = ENGINE_FEATURES + STRUCT_FEATURES
    comparisons = {}
    for other, gate in (("sealed", True), ("validation", False)):
        sel = by_split["dev"] + by_split[other]
        x = [[float(r[f]) for f in feats] for r in sel]
        y = [0] * len(by_split["dev"]) + [1] * len(by_split[other])
        fam = [r["family"] for r in sel]
        comparisons[f"dev_vs_{other}"] = {"auc_family_grouped": cv_auc(x, y, fam, by_group=True),
                                          "auc_case_level": cv_auc(x, y, fam, by_group=False),
                                          "n": [len(by_split["dev"]), len(by_split[other])], "gated": gate}
    accept = {}
    for e in ENGINES:
        for pr in PROFILES:
            key = f"{e}_{pr}_accept"
            per = {s: _pooled(by_split[s], key) for s in by_split}
            accept[key] = {"per_split": per,
                           "gap_points_vs_dev": {s: round(abs(per[s] - per["dev"]), 3) for s in ("validation", "sealed")}}
    saved = {}
    for e in ENGINES:
        for pr in PROFILES:
            saved[f"{e}_{pr}_saved_pct"] = {s: _pooled(by_split[s], f"{e}_{pr}_saved") for s in by_split}
    sign = {}
    for pr in PROFILES + ("pooled",):
        if pr == "pooled":
            diff = {}
            for s, rs in by_split.items():
                tot = sum(r[f"1.10.0_{p}_saved"] - r[f"1.9.0_{p}_saved"] for r in rs for p in PROFILES)
                diff[s] = round(100.0 * tot / (len(rs) * len(PROFILES)), 4) if rs else None
        else:
            diff = {s: round(_pooled(by_split[s], f"1.10.0_{pr}_saved") - _pooled(by_split[s], f"1.9.0_{pr}_saved"), 4)
                    for s in by_split}
        sign[pr] = {"diff_points_per_split": diff,
                    "same_sign_sealed_dev": (diff["sealed"] == 0) == (diff["dev"] == 0) and
                                          (diff["sealed"] > 0) == (diff["dev"] > 0)}
    passed = (comparisons["dev_vs_sealed"]["auc_family_grouped"] <= AUC_MAX
              and all(a["gap_points_vs_dev"]["sealed"] <= ACCEPT_GAP_MAX for a in accept.values())
              and sign["pooled"]["same_sign_sealed_dev"])
    splits_doc = corpus.load_splits_r3()
    desc_blob = "".join(canonical(rows[k]) + "\n" for k in sorted(rows))
    result = {
        "registered": datetime.date.today().isoformat(),
        "deal": splits_doc["deal"],
        "sealed_r3_sha256": corpus.SEALED_R3_HASH_FILE.read_text().split()[0],
        "descriptors_sha256": hashlib.sha256(desc_blob.encode("utf-8")).hexdigest(),
        "engines": ["1.10.0 (this checkout)", "1.9.0 (commit 3bc2978, scratch worktree)"],
        "classifier": "session-corpus L2 logistic regression, 5-fold CV x 10 fold seeds; primary = folds grouped by family",
        "features": feats,
        "gates": {"auc_max": AUC_MAX, "acceptance_gap_max_points": ACCEPT_GAP_MAX,
                  "saved_sign": "sign(1.10.0 - 1.9.0 saved) equal on sealed and dev"},
        "comparisons": comparisons,
        "acceptance": accept,
        "saved_pct_per_split": saved,
        "saved_sign": sign,
        "pass": passed,
    }
    result["result_sha256"] = hashlib.sha256(canonical(result).encode("utf-8")).hexdigest()
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    DESCRIPTORS_FILE.write_text(desc_blob, encoding="utf-8", newline="\n")
    attempts = json.loads(ATTEMPTS_FILE.read_text(encoding="utf-8")) if ATTEMPTS_FILE.exists() else []
    attempts.append({"date": result["registered"], "deal": splits_doc["deal"],
                     "auc": {k: v["auc_family_grouped"] for k, v in comparisons.items()},
                     "accept_gaps_vs_dev": {k: v["gap_points_vs_dev"] for k, v in accept.items()},
                     "saved_sign": {k: v["same_sign_sealed_dev"] for k, v in sign.items()},
                     "pass": passed})
    ATTEMPTS_FILE.write_text(json.dumps(attempts, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8", newline="\n")
    print(f"dev_vs_sealed grouped AUC {comparisons['dev_vs_sealed']['auc_family_grouped']} (gate {AUC_MAX}); "
          f"dev_vs_validation {comparisons['dev_vs_validation']['auc_family_grouped']}")
    print("accept gaps vs dev:", {k: v["gap_points_vs_dev"] for k, v in accept.items()})
    print("saved sign:", {k: v["diff_points_per_split"] for k, v in sign.items()})
    print("PASS" if passed else "FAIL — re-deal with a new seed and re-run check")
    return 0 if passed else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("engine")
    pe.add_argument("--engine-src", required=True)
    pe.add_argument("--label", required=True)
    pe.add_argument("--part", default="0/1")
    pe.add_argument("--out", required=True)
    ps = sub.add_parser("structure")
    ps.add_argument("--out", required=True)
    pc = sub.add_parser("check")
    pc.add_argument("--dir", required=True)
    args = ap.parse_args(argv)
    return {"engine": cmd_engine, "structure": cmd_structure, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
