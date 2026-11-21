"""S5 stage-attribution diagnosis (plan S5, hypotheses a-c): WHERE the gold fact line is lost.

    python -m benchmarks.engine_bench.s5_diagnose --engine-src src --label 1.10.0 \
        --out benchmarks/engine_bench/results/r2-s5-diagnosis-1.10.0.json
    python -m benchmarks.engine_bench.s5_diagnose --engine-src <1.9.0-worktree>/src --label 1.9.0 \
        --no-trace --out build/s5-diagnosis-1.9.0.json

Round-2 dev + validation ONLY -- the script refuses the sealed split.

Cells: item_kind x condition x language x profile for item kinds s5_buried / s5_superseded /
csv_args / evidence, conditions build_vague / build_specific / tool_call / task_vague, profiles
deepseek / hermes with run.py's exact ``_call`` settings and its Hermes host acceptance rule
(run.py is imported AFTER the engine under test is loaded, so its tameru symbols bind to it).

Tracing: the module-level stage functions of ``tameru.compress_context`` listed in TRACED_* are
monkeypatched with wrappers that record, per call, which gold lines are present in the input and
in the output (the bench's own gold check, ``gold in text``). The wrappers only observe; for every
measured call the un-wrapped call is run too and its CompressResult is verified byte-identical
(extract text and all metadata), else the run stops. ``compress_context._clear_memos()`` is called
before every measured call so no memoised stage is skipped. Caches cleared: _contains_secret_cached,
_error_fingerprints_cached, _extract_critical_lines_cached, _preprocess_cached,
_segment_blocks_cached, _brief_scan_cached, _block_link_terms_cached, _extract_entities_cached,
_extract_terms_cached, _estimate_tokens_cached, _evidence_blob, industrial._profile_input_cached,
unicode_profile._search_units_cached, contract_gates._distinctive_query_terms_cached,
contract_gates._source_blob and the _SCORED_MEMO dict.

Drop classes (first match wins, per case x condition x profile with accepted=True and gold lost):
  a  first traced pre-filter / crush where a gold line goes present -> absent:
     _preprocess_json, preprocess_csv, preprocess_filler_comments, preprocess_flat_records,
     preprocess_json
  b  preprocess_logs or _fold_repeated_sentences (template collapse); records whether the gold
     line's _log_fingerprint is shared by at least one other line of the text
  c  gold survives every traced stage, but the extract holds a line with the gold key and not the
     gold value (untouched / truncated / masked)
  d  everything else: gold survived preprocessing unaltered; selection/render left it out
"""
from __future__ import annotations

import argparse
import dataclasses
import functools
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from benchmarks.session_corpus.equivalence import _engine  # noqa: E402
from benchmarks.engine_bench import corpus, ledger  # noqa: E402

KINDS = ("s5_buried", "s5_superseded", "csv_args", "evidence")
CONDITIONS = ("build_vague", "build_specific", "tool_call", "task_vague")
PROFILES = ("deepseek", "hermes")
TRACED = {  # stage -> class
    "_preprocess_json": "a", "preprocess_csv": "a", "preprocess_filler_comments": "a",
    "preprocess_flat_records": "a", "preprocess_json": "a",
    "preprocess_logs": "b", "_fold_repeated_sentences": "b",
}
ELLIPSIS_MARKERS = ("…", "...", "⟪", "⟫", "[tameru:", "[×")
CACHES_CLEARED = ["_contains_secret_cached", "_error_fingerprints_cached",
                  "_extract_critical_lines_cached", "_preprocess_cached", "_segment_blocks_cached",
                  "_brief_scan_cached", "_block_link_terms_cached", "_extract_entities_cached",
                  "_extract_terms_cached", "_estimate_tokens_cached", "_evidence_blob",
                  "industrial._profile_input_cached", "unicode_profile._search_units_cached",
                  "contract_gates._distinctive_query_terms_cached", "contract_gates._source_blob",
                  "_SCORED_MEMO"]


def _as_text(x):
    return x if isinstance(x, str) else "\n".join(x)


class Tracer:
    """Wrap the traced stage functions; record which gold indices go present -> absent per call."""

    def __init__(self, cc, gold):
        self.cc, self.gold, self.events, self.originals = cc, gold, [], {}

    def install(self):
        for name, fn in ((n, getattr(self.cc, n)) for n in TRACED):
            self.originals[name] = fn
            setattr(self.cc, name, self._wrap(name, fn))

    def restore(self):
        for name, fn in self.originals.items():
            setattr(self.cc, name, fn)
        self.originals = {}

    def _wrap(self, name, fn):
        gold, events = self.gold, self.events

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            before = _as_text(args[0]) if args else ""
            out = fn(*args, **kwargs)
            after = _as_text(out)
            events.append({"stage": name, "cls": TRACED[name],
                           "dropped": [i for i, g in enumerate(gold) if g in before and g not in after]})
            return out
        return wrapper


def _result_dump(res) -> str:
    """Comparable view of a CompressResult (extract text + all metadata)."""
    return json.dumps(dataclasses.asdict(res), ensure_ascii=False, sort_keys=True, default=str)


def _value_altered(raw: str, key: str, value: str) -> str | None:
    """Class (c): a line in the extract holds the gold key but not the full gold value."""
    if not key or not value:
        return None
    for ln in raw.splitlines():
        if key not in ln or value in ln:
            continue
        head = value[: max(8, len(value) // 3)]
        if head in ln and any(m in ln for m in ELLIPSIS_MARKERS):
            return "value_truncated"
        if "<" in ln or "***" in ln:
            return "value_masked"
        return "key_without_value"
    return None


def _shared_template(cc, text: str, gold_line: str) -> bool | None:
    fp = cc._log_fingerprint(gold_line)
    if fp is None:
        return None
    return sum(1 for ln in text.splitlines() if ln != gold_line and cc._log_fingerprint(ln) == fp) > 0


def _selector_origin(contract_gates, case, cond, query) -> dict:
    """For each distinctive selector term: does it occur in the tool-call args, the user message, both?"""
    task_key = "task_specific" if cond in ("build_specific", "task_specific") else "task_vague"
    task = (case["queries"].get(task_key) or "").casefold()
    tool = (case["queries"].get("tool_call") or "").casefold()
    origin = {}
    for t in contract_gates.distinctive_query_terms(query):
        if t.startswith("script:"):
            continue
        in_args, in_user = t in tool, t in task
        origin[t] = "both" if in_args and in_user else ("args" if in_args else
                                                      ("user" if in_user else "neither"))
    return origin


def _classify(eng, case, raw, query, each, events, cond) -> dict:
    dropped = [i for i, k in enumerate(each) if not k]
    gold = case["gold"]
    for ev in events:
        if any(i in dropped for i in ev["dropped"]):
            out = {"cls": ev["cls"], "stage": ev["stage"], "gold": gold[min(dropped)]}
            if ev["cls"] == "a":
                out["selector_origin"] = _selector_origin(eng.contract_gates, case, cond, query)
            else:
                out["shared_template"] = _shared_template(eng.cc, case["text"], gold[min(dropped)])
            return out
    fact = case.get("fact") or {}
    altered = _value_altered(raw, fact.get("key", ""), fact.get("value", ""))
    if altered:
        return {"cls": "c", "kind": altered, "gold": gold[min(dropped)]}
    return {"cls": "d", "gold": gold[min(dropped)]}


def diagnose_cell(eng, case, profile, cond, *, trace: bool) -> dict:
    """One case x profile x condition."""
    text, query, gold = case["text"], case["queries"][cond], case["gold"]
    sel_query = eng.selector_query(case, cond) if eng.selector_query else None

    def run_call():
        if eng.clear:
            eng.clear()
        try:
            return eng.call(profile, text, query, sel_query), False
        except Exception:
            return None, True

    res, raised = run_call()
    events = []
    if trace:
        tracer = Tracer(eng.cc, gold)
        tracer.install()
        try:
            res_traced, raised_traced = run_call()
            events = tracer.events
        finally:
            tracer.restore()
        neutral = (raised == raised_traced
                   and (res is None and res_traced is None
                        or res is not None and res_traced is not None
                        and _result_dump(res) == _result_dump(res_traced)))
        if not neutral:
            raise SystemExit(f"wrapper changed output on {case['id']} {profile} {cond} — stopping")
    raw = text if res is None else res.compressed_text
    fail_open = res is None or bool(res.fail_open)
    accepted = not fail_open
    if accepted and profile == "hermes":
        accepted = (eng.RISK_ORDER.get(res.compression_risk or "", 2) <= eng.RISK_ORDER[eng.HERMES_MAX_RISK]
                    and eng.error_fingerprints(text, status_rows=False).keys()
                    <= eng.error_fingerprints(raw, status_rows=False).keys())
    each = [g in raw for g in gold]
    row = {"case": case["id"], "family": case["family"], "source_case": case["source_case"],
           "split": case["_split"], "item_kind": case["item_kind"], "language": case["language"],
           "profile": profile, "condition": cond, "fail_open": fail_open, "raised": res is None,
           "accepted": accepted, "gold_total": len(gold),
           "gold_lines_kept_raw": sum(each), "query": query,
           "gold_kept": round(sum(each) / len(gold), 6) if gold else None,
           "all_gold_kept": all(each) if gold else None}
    if accepted and gold and not all(each):
        row["drop"] = _classify(eng, case, raw, query, each, events, cond) if trace else {"cls": "untraced"}
    return row


class _Eng:
    pass


def load_engine(engine_src: Path, label: str) -> _Eng:
    version, _ = _engine(engine_src)  # puts engine_src on sys.path and sanity-checks the import
    if version != label:
        raise SystemExit(f"engine at {engine_src} is {version}, not {label}")
    import tameru  # noqa: PLC0415
    import tameru.compress_context as cc  # noqa: PLC0415
    import tameru.contract_gates as cg  # noqa: PLC0415
    from benchmarks.engine_bench import run  # noqa: PLC0415

    eng = _Eng()
    eng.version, eng.cc, eng.contract_gates = version, cc, cg
    eng.call = run._call  # run.py's exact per-profile compress_context settings
    # run.py's build_* selector-query rule: None keeps the call unchanged (e.g. 1.9.0).
    eng.selector_query = getattr(run, "_selector_query_for", None)
    eng.RISK_ORDER, eng.HERMES_MAX_RISK = run._RISK_ORDER, run.HERMES_MAX_RISK
    eng.error_fingerprints = tameru.error_fingerprints
    eng.clear = getattr(cc, "_clear_memos", None)
    return eng


def run_cells(eng, cases, *, trace: bool) -> list[dict]:
    return [diagnose_cell(eng, case, profile, cond, trace=trace)
            for case in cases for profile in PROFILES for cond in CONDITIONS
            if cond in case["queries"]]


def _gold_effective(row) -> int:
    return row["gold_total"] if not row["accepted"] else row["gold_lines_kept_raw"]


def summarise(rows: list[dict], *, traced: bool) -> dict:
    cells, examples = {}, {}
    for r in rows:
        key = "|".join((r["item_kind"], r["condition"], r["language"], r["profile"]))
        c = cells.setdefault(key, {"n": 0, "fail_open": 0, "accepted": 0, "gold_kept_lines": 0,
                                   "gold_total_lines": 0, "acc_gold_kept_lines": 0,
                                   "acc_gold_total_lines": 0, "drops": 0,
                                   "a": {}, "b": {}, "c": {}, "d": 0, "a_tool_args": 0,
                                   "b_shared_template": 0})
        c["n"] += 1
        c["fail_open"] += r["fail_open"]
        c["accepted"] += r["accepted"]
        c["gold_kept_lines"] += _gold_effective(r)
        c["gold_total_lines"] += r["gold_total"]
        if r["accepted"]:
            c["acc_gold_kept_lines"] += r["gold_lines_kept_raw"]
            c["acc_gold_total_lines"] += r["gold_total"]
        d = r.get("drop")
        if not d or d.get("cls") == "untraced":
            continue
        c["drops"] += 1
        cls = d["cls"]
        if cls == "a":
            c["a"][d["stage"]] = c["a"].get(d["stage"], 0) + 1
            if any(o in ("args", "both") for o in (d.get("selector_origin") or {}).values()):
                c["a_tool_args"] += 1
        elif cls == "b":
            c["b"][d["stage"]] = c["b"].get(d["stage"], 0) + 1
            c["b_shared_template"] += bool(d.get("shared_template"))
        elif cls == "c":
            c["c"][d["kind"]] = c["c"].get(d["kind"], 0) + 1
        else:
            c["d"] += 1
        ex_key = f"{cls}|{r['profile']}"
        if r["split"] == "dev" and len(examples.setdefault(ex_key, [])) < 5:
            examples[ex_key].append({"case": r["case"], "condition": r["condition"],
                                     "stage": d.get("stage"), "query": r["query"],
                                     "gold": d.get("gold"), "detail": d})
    for c in cells.values():
        if traced:
            c["a_total"], c["b_total"], c["c_total"] = sum(c["a"].values()), sum(c["b"].values()), sum(c["c"].values())
            recon = c["a_total"] + c["b_total"] + c["c_total"] + c["d"]
            assert recon == c["drops"], f"cell does not reconcile: {recon} != {c['drops']}"
        c["retention_all"] = round(c["gold_kept_lines"] / c["gold_total_lines"], 4) \
            if c["gold_total_lines"] else None
        c["retention_accepted"] = round(c["acc_gold_kept_lines"] / c["acc_gold_total_lines"], 4) \
            if c["acc_gold_total_lines"] else None
    return {"cells": cells, "examples": examples}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine-src", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--no-trace", action="store_true", help="plain run, no stage wrappers (1.9.0)")
    ap.add_argument("--split", action="append", choices=["dev", "validation", "sealed"],
                    help="repeatable; default dev; 'validation' and 'sealed' are refused")
    ap.add_argument("--setting", help="engine setting id in docs/SETTINGS-TRIED-LEDGER.json (required)")
    ap.add_argument("--reference", help="commit hash of a clean worktree reference run")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None, help="debug: first N cases only")
    args = ap.parse_args(argv)
    splits = args.split or ["dev"]
    if "sealed" in splits:
        print("refusing: the sealed split is never read by the diagnosis", file=sys.stderr)
        return 2
    if "validation" in splits:
        print("refusing: round-2 validation is queried only through "
              "benchmarks/engine_bench/thresholdout.py", file=sys.stderr)
        return 2
    try:
        prov = ledger.resolve_provenance(args.setting, args.reference, required=True)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    eng = load_engine(Path(args.engine_src), args.label)
    assignment = corpus.r2_assignment()
    cases = [dict(c, _split=assignment[c["id"]]) for c in corpus._build_r2()
             if assignment[c["id"]] in splits and c["item_kind"] in KINDS]
    if args.limit:
        cases = cases[: args.limit]
    rows = run_cells(eng, cases, trace=not args.no_trace)
    data = {"engine": eng.version, "traced": not args.no_trace, "calls": len(rows), **prov,
            "splits": splits, "caches_cleared": CACHES_CLEARED if not args.no_trace else [],
            "neutrality": ("verified per call: unwrapped vs wrapped CompressResult byte-identical, else abort"
                           if not args.no_trace else None),
            "summary": summarise(rows, traced=not args.no_trace), "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"{data['calls']} calls, engine {data['engine']}, traced={data['traced']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
