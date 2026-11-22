"""Run the engine benchmark: every case x host profile x query condition -> jsonl rows.

    python -m benchmarks.engine_bench.run --split dev --split validation --out results/x.jsonl
    python -m benchmarks.engine_bench.run --sealed --candidate NAME ...   # the ONE look per host

Host profiles (call settings only; no host code is imported):
  deepseek  compress_context(text, query, min_savings_ratio=0.25, ccr=False, citations=False, strategy="extract")
  hermes    the options of hermes_tameru_plugin/engine.py ``_compress`` (default settings): ccr=False,
            citations=False, gap_marker=Hermes' elision marker, inline_short_gaps=True, anchor_errors=True,
            prose_brief=True, recursion_markers=("[tameru:",), min_savings_ratio=0.10; the host then accepts the
            extract only when it is not fail-open, within max_risk ("high") and keeps an exemplar of every
            error fingerprint of the original, else the ORIGINAL text stays (saved 0).
Query conditions: task, tool_call, generic ("continue"), zh_user (cases whose language is zh or mixed).

Row = {"bench":"engine","engine","split","case","source_case","content_type","language","profile",
"query_condition", ...metrics}; one JSON object per line, sorted keys, ``wall_ms`` the only unstable field.
"""
from __future__ import annotations

import argparse
import datetime
import inspect
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from tameru import ENGINE_VERSION, error_fingerprints  # noqa: E402
from tameru.compress_context import compress_context  # noqa: E402
from tameru.contract_gates import query_has_distinctive_selectors  # noqa: E402

from . import corpus, ledger, report  # noqa: E402

PROFILES = ("deepseek", "hermes")
CONDITIONS = ("task", "tool_call", "generic", "zh_user")
CONDITIONS_R2 = ("task_specific", "task_vague", "build_specific", "build_vague", "tool_call", "generic", "zh_user")
_MARKER_PREFIX = "⟪HERMES-CONTEXT-COMPRESSION:"
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
HERMES_MAX_RISK = "high"
TAMERU_TAG = " [tameru:"


def _elision_marker(omitted: int, total: int) -> str:
    return f"{_MARKER_PREFIX} {omitted:,} of {total:,} chars omitted here by Hermes's context compressor.⟫"


def _call(profile: str, text: str, query, selector_query=None):
    sel_kw = {} if selector_query is None else {"selector_query": selector_query}
    if profile == "deepseek":
        return compress_context(text, query, min_savings_ratio=0.25, ccr=False, citations=False, strategy="extract", **sel_kw)
    return compress_context(text, query, ccr=False, citations=False, gap_marker=_elision_marker, inline_short_gaps=True,
                            anchor_errors=True, prose_brief=True, recursion_markers=(TAMERU_TAG.strip(),), min_savings_ratio=0.10, **sel_kw)


_SELECTOR_OK = "selector_query" in inspect.signature(compress_context).parameters
_BUILD_CONDS = ("build_specific", "build_vague")


def _selector_query_for(case: dict, condition: str):
    """The ``selector_query`` for an r2 ``build_*`` condition (``build_selector_query`` over the same
    synthetic transcript), or ``None`` when the engine under test does not accept the parameter
    (1.9.0, the stored 1.10.0 baseline) or the case carries none."""
    if not _SELECTOR_OK or condition not in _BUILD_CONDS:
        return None
    return (case.get("sel_queries") or {}).get(condition)


def _kept(strings, text):
    return [s in text for s in strings]


def measure(case: dict, profile: str, condition: str, split: str) -> dict:
    text, query = case["text"], case["queries"][condition]
    t0 = time.perf_counter()
    try:
        res = _call(profile, text, query, _selector_query_for(case, condition))
        raised = False
    except Exception:  # a raise is a fail-open for the host
        res, raised = None, True
    wall_ms = (time.perf_counter() - t0) * 1000.0
    fp_in = error_fingerprints(text, status_rows=False)
    if res is None:
        raw, fail_open, risk, conf, etype = text, True, None, None, None
    else:
        raw, fail_open, risk, conf, etype = res.compressed_text, bool(res.fail_open), res.compression_risk, res.confidence, res.content_type
    accepted = not fail_open
    if accepted and profile == "hermes":
        accepted = (_RISK_ORDER.get(risk or "", 2) <= _RISK_ORDER[HERMES_MAX_RISK]
                    and fp_in.keys() <= error_fingerprints(raw, status_rows=False).keys())
    effective = raw if accepted else text
    gold, forbidden = case["gold"], case["forbidden"]
    each_raw, each = _kept(gold, raw), _kept(gold, effective)
    fp_out = error_fingerprints(effective, status_rows=False)
    chars_in = len(text)
    row = {
        "bench": "engine", "engine": ENGINE_VERSION, "split": split, "case": case["id"], "source_case": case["source_case"],
        "content_type": case["content_type"], "shape": case["shape"], "language": case["language"],
        "profile": profile, "query_condition": condition,
        "chars_in": chars_in, "chars_out": len(effective), "raw_chars_out": len(raw),
        "saved_pct": round(100.0 * (1 - len(effective) / chars_in), 4) if chars_in else 0.0,
        "accepted": accepted, "fail_open": fail_open, "raised": raised, "compression_risk": risk,
        "confidence": None if conf is None else round(float(conf), 6), "engine_content_type": etype,
        "gold_total": len(gold), "gold_kept": round(sum(each) / len(gold), 6) if gold else None,
        "gold_kept_raw": round(sum(each_raw) / len(gold), 6) if gold else None,
        "gold_each": each, "all_gold_kept_raw": all(each_raw) if gold else None,
        "forbidden_kept": sum(_kept(forbidden, effective)), "forbidden_total": len(forbidden),
        "fingerprints_total": len(fp_in), "fingerprints_kept": len(fp_in.keys() & fp_out.keys()),
        # 1.10.0 (S5): protected fact lines of the original absent from the output (None on engines
        # without the field).
        "fact_lines_dropped": getattr(res, "fact_lines_dropped", None) if res is not None else None,
        # 1.10.0 (S5, E4): the text was fact-dense, the S5 machinery stayed off (receipt flag).
        "fact_dense": (res.receipt or {}).get("fact_dense") if res is not None else None,
        # S6 calibration features: what the confidence rests on, the engine's own specific/vague reading of the
        # objective (distinctive selectors, as its fact-drop confidence rule uses it) and the selection path.
        "confidence_basis": getattr(res, "confidence_basis", None) if res is not None else None,
        "query_specific": query_has_distinctive_selectors(query if isinstance(query, str) else " ".join(query)),
        "selection": (res.receipt or {}).get("selection") if res is not None else None,
        "industrial_applied": ((res.receipt or {}).get("industrial") or {}).get("applied") if res is not None else None,
        "wall_ms": round(wall_ms, 3),
    }
    if case.get("family") is not None:
        row["family"] = case["family"]
        row["item_kind"] = case["item_kind"]
    return row


def run(cases: list[dict], splits: dict[str, str], profiles=PROFILES, conditions=CONDITIONS) -> list[dict]:
    rows = []
    for case in cases:
        for profile in profiles:
            for cond in conditions:
                if cond in case["queries"]:
                    rows.append(measure(case, profile, cond, splits[case["id"]]))
    return rows


def dumps(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_rows(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")


def _log_sealed_look(candidate: str, command: str, path: Path = None) -> None:
    path = path or (HERE / "sealed_looks.json")
    looks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    looks.append({"date": datetime.date.today().isoformat(), "engine": ENGINE_VERSION, "candidate": candidate, "command": command})
    path.write_text(json.dumps(looks, indent=1) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", dest="round_", type=int, choices=(1, 2, 3), default=1,
                    help="benchmark round; 2/3 = the gen_cases_r2/r3 corpus and its own sealed guard")
    ap.add_argument("--split", action="append", choices=["dev", "validation", "sealed"],
                    help="repeatable; default: dev for round 2/3, dev + validation for round 1")
    ap.add_argument("--sealed", action="store_true", help="allow reading sealed texts (one look per host; logged)")
    ap.add_argument("--candidate", help="candidate name, required with --sealed")
    ap.add_argument("--setting", help="engine setting id in docs/SETTINGS-TRIED-LEDGER.json (required for round 2/3)")
    ap.add_argument("--reference", help="commit hash of a clean worktree reference run (round 2/3 alternative to --setting)")
    ap.add_argument("--out", type=Path, help="write rows to this jsonl file")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    r2 = args.round_ == 2
    r3 = args.round_ == 3
    if (r2 or r3) and "validation" in (args.split or []):
        print(f"refusing: round-{args.round_} validation is queried only through "
              "benchmarks/engine_bench/thresholdout.py", file=sys.stderr)
        return 2
    splits = args.split or (["dev"] if (r2 or r3) else ["dev", "validation"])
    try:
        prov = ledger.resolve_provenance(args.setting, args.reference, required=r2 or r3)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if "sealed" in splits and not args.sealed:
        print("refusing: the sealed split can only be read with --sealed (and --candidate)", file=sys.stderr)
        return 2
    if args.sealed and not args.candidate:
        print("--sealed requires --candidate NAME", file=sys.stderr)
        return 2
    assignment = corpus.r3_assignment() if r3 else (corpus.r2_assignment() if r2 else corpus.load_splits())
    if args.sealed:
        hash_file = corpus.SEALED_R3_HASH_FILE if r3 else (corpus.SEALED_R2_HASH_FILE if r2 else corpus.SEALED_HASH_FILE)
        builder = corpus._build_r3 if r3 else (corpus._build_r2 if r2 else corpus._build_all)
        if corpus.sealed_digest([c for c in builder() if assignment[c["id"]] == "sealed"]) != hash_file.read_text().split()[0]:
            print("refusing: sealed cases no longer match " + hash_file.name, file=sys.stderr)
            return 2
        _log_sealed_look(args.candidate, "python -m benchmarks.engine_bench.run " + " ".join(argv if argv is not None else sys.argv[1:]),
                         corpus.SEALED_LOOKS_R3_FILE if r3 else (corpus.SEALED_LOOKS_R2_FILE if r2 else None))
    loader = corpus.load_cases_r3 if r3 else (corpus.load_cases_r2 if r2 else corpus.load_cases)
    cases = loader(splits, sealed_ok=args.sealed)
    rows = run(cases, assignment, conditions=CONDITIONS_R2 if (r2 or r3) else CONDITIONS)
    for row in rows:
        row.update(prov)
    if args.out:
        write_rows(rows, args.out)
    if not args.quiet:
        print(report.headline(rows))
        print(report.callouts(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
