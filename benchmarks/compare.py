#!/usr/bin/env python3
"""Versioned, same-input comparison with full-call wall-time measurements.

Default runs are local. JEV requires both --include-jev and an existing
TYPESAFE_API_KEY. Optional dependencies that cannot run are reported without
scores. No historical measurements are copied into the new report.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))

from run_battery import CASES as RELEASE_CASES  # noqa: E402

from tameru import __version__  # noqa: E402
from tameru.compress_context import compress_context  # noqa: E402

ARMS = ("tameru", "lcc-mech", "headroom", "tfidf", "lcc-laya", "lcc-jev")
MODEL = "convaiinnovations/laya-multilingual"
Runner = Callable[[dict], tuple[str, dict]]
LABELS = {
    "tameru": f"**Tameru v{__version__}**", "lcc-mech": "LCC mechanical",
    "headroom": "Headroom TextCrusher", "tfidf": "TF-IDF paragraph baseline",
    "lcc-laya": "LCC → Laya (CPU)", "lcc-jev": "LCC → JEV",
}


def current_cases() -> list[dict]:
    """Release cases plus reproducible agent-output coverage for this release."""
    grep = []
    bodies = (
        "raise InsufficientStock('no stock')",
        "except InsufficientStock as exc:",
        "log.error('InsufficientStock: %s', exc)",
        "assert isinstance(exc, InsufficientStock)",
        "return InsufficientStock()",
    )
    for file in range(25):
        for line in range(6):
            body = bodies[(file + line) % len(bodies)]
            if file == 12 and line == 3:
                body = "class InsufficientStock(RuntimeError):"
            grep.append(f"src/pkg{file:02d}/mod.py:{10 + line}:{body}")

    captured = [
        "============================= test session starts ==============================",
        "collected 1 item",
        "tests/test_orders.py F [100%]",
        "=================================== FAILURES ===================================",
        "___________________________________ test_order ___________________________________",
        ">       assert order.status == 'paid'",
        "E       AssertionError: assert 'pending' == 'paid'",
        "tests/test_orders.py:41: AssertionError",
        "------------------------------ Captured stdout call -------------------------------",
    ]
    for i in range(1, 61):
        captured.append(f"INFO app.order message number {i} with padding for the captured section")
        if i == 10:
            captured.append("")
        if i == 30:
            captured.append("ERROR app.order payment rejected by gateway DB-PAY-17")
        if i == 40:
            captured.append("WARNING app.order retry budget exhausted")
    captured += [
        "=========================== short test summary info ============================",
        "FAILED tests/test_orders.py::test_order - AssertionError",
        "============================== 1 failed in 0.01s ===============================",
    ]

    source = ["import os", ""]
    for i in range(80):
        source += [
            f"def handler_{i}(request, context=None):",
            f"    value = request.get('key_{i}', {i}), context",
            "    if context is None:",
            f"        return value[0] + {i}",
            f"    return value, context, 'handler_{i}-done'",
            "",
        ]
    numbered = "\n".join(f"{i + 1}|{line}" for i, line in enumerate(source))
    return [dict(case) for case in RELEASE_CASES] + [
        dict(name="grep_saturated_command", ctx="\n".join(grep),
             q="rg -n InsufficientStock; where is InsufficientStock defined?",
             gold=["class InsufficientStock(RuntimeError):"], forbid=[]),
        dict(name="pytest_captured_blank_lines", ctx="\n".join(captured),
             q="Why did test_order fail?",
             gold=["assert 'pending' == 'paid'", "DB-PAY-17",
                   "WARNING app.order retry budget exhausted",
                   "FAILED tests/test_orders.py::test_order"], forbid=[]),
        dict(name="numbered_source", ctx=numbered, q="what does handler_60 do?",
             gold=["def handler_60(request, context=None):",
                   "value = request.get('key_60', 60), context",
                   "return value[0] + 60", "handler_60-done"], forbid=[]),
    ]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest(case: dict) -> dict:
    return {
        "name": case["name"], "input_chars": len(case["ctx"]),
        "input_sha256": digest(case["ctx"]), "query": case["q"],
        "gold": case.get("gold", []), "forbid": case.get("forbid", []),
        "scope": "answer" if case.get("gold") else "robustness",
    }


def tfidf_text(text: str, query: str) -> str:
    """The whole retrieval calculation is inside the caller's timing boundary."""
    import math

    def terms(value: str) -> Counter:
        return Counter(re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_.\-/]{2,}", value.lower()))

    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    q = terms(query)
    tfs = [terms(b) for b in blocks]
    df: Counter = Counter(t for tf in tfs for t in tf)
    n = max(1, len(blocks))
    kept = [
        block for i, (block, tf) in enumerate(zip(blocks, tfs, strict=True))
        if i == 0 or sum(qc * math.log(1 + n / (1 + df[t])) * tf[t]
                         for t, qc in q.items()) > 0
    ]
    return "\n\n".join(kept)


def make_runner(arm: str, args: argparse.Namespace) -> Runner:
    if arm == "tameru":
        def tameru(case):
            out = compress_context(case["ctx"], case["q"], ccr=False, citations=True)
            return out.compressed_text, {"provider": "tameru-extract", "fail_open": out.fail_open}
        return tameru
    if arm == "tfidf":
        return lambda case: (tfidf_text(case["ctx"], case["q"]), {"provider": "tfidf"})
    if arm == "headroom":
        from headroom._core import TextCrusher
        crusher = TextCrusher()
        return lambda case: (crusher.compress(case["ctx"], case["q"]).compressed,
                             {"provider": "headroom-textcrusher"})
    if arm == "lcc-jev" and not (args.include_jev and os.environ.get("TYPESAFE_API_KEY")):
        raise RuntimeError("JEV requires --include-jev and an existing TYPESAFE_API_KEY")
    if arm == "lcc-laya":
        import laya  # noqa: F401
        if not args.laya_revision:
            raise RuntimeError("Laya requires --laya-revision for a recorded model pin")
        os.environ["LAYA_REVISION"] = args.laya_revision
    from lcc.relevance.compactor import RelevanceCompactionRequest, compact_context
    provider = {"lcc-mech": "mechanical", "lcc-laya": "laya", "lcc-jev": "jev"}[arm]

    def lcc(case):
        request = RelevanceCompactionRequest(
            text=case["ctx"], question=case["q"], provider=provider,
            marker=False, max_workers=1, laya_model=MODEL, laya_device="cpu",
        )
        result = compact_context(request)
        report = result.report
        policy_only = (
            not report.degraded and report.provider_used == "mechanical"
            and getattr(report, "calls", None) == 0
            and getattr(report, "blocks_scored", None) == 0
            and getattr(report, "blocks_total", 0) > 0
            and report.blocks_protected == report.blocks_total
            and result.compacted_text == case["ctx"]
        )
        if report.degraded or (report.provider_used != provider and not policy_only):
            raise RuntimeError(f"Requested {provider}; received {report.provider_used}, degraded={report.degraded}")
        return result.compacted_text, {
            "provider": report.provider_used, "degraded": report.degraded,
            "protected_noop": policy_only, "scoring_calls": getattr(report, "calls", None),
            "model": report.jev_model_resolved if provider == "jev" else None,
        }
    return lcc


def measure(runner: Runner, case: dict, repeats: int) -> dict:
    warm_text, _ = runner(case)
    samples = []
    outputs = []
    metadata = {}
    for _ in range(repeats):
        start = time.perf_counter()
        text, metadata = runner(case)
        samples.append((time.perf_counter() - start) * 1000)
        outputs.append(text)
    text = outputs[0]
    checked = [warm_text, *outputs]
    missing = [g for g in case.get("gold", []) if any(g not in out for out in checked)]
    leaked = [f for f in case.get("forbid", []) if any(f in out for out in checked)]
    return {
        "status": "measured", "output_chars": len(text), "output_sha256": digest(text),
        "savings_pct": round((1 - len(text) / max(1, len(case["ctx"]))) * 100, 4),
        "gold_kept": len(case.get("gold", [])) - len(missing),
        "gold_total": len(case.get("gold", [])), "missing_gold": missing,
        "forbid_leaks": len(leaked), "leaked_forbid": leaked,
        "latency_ms": round(statistics.median(samples), 4),
        "latency_samples_ms": [round(t, 4) for t in samples],
        "deterministic": all(out == warm_text for out in outputs),
        "output_samples_sha256": [digest(out) for out in checked],
        "returned_original": text == case["ctx"], **metadata,
    }


def aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {}
    return {
        "cases": len(rows), "gold_kept": sum(r["gold_kept"] for r in rows),
        "gold_total": sum(r["gold_total"] for r in rows),
        "clean_cases": sum(not r["missing_gold"] and not r["forbid_leaks"] for r in rows),
        "forbid_leaks": sum(r["forbid_leaks"] for r in rows),
        "mean_character_savings_pct": round(statistics.mean(r["savings_pct"] for r in rows), 4),
        "median_wall_ms": round(statistics.median(r["latency_ms"] for r in rows), 4),
        "deterministic": all(r["deterministic"] for r in rows),
    }


def comparison_table(report: dict) -> str:
    lines = [
        "| Tested method | Required strings kept | Forbidden strings ↓ | Clean cases | Mean character savings | Median wall time | Repeat output identical |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for arm in ARMS:
        item = report["arms"].get(arm, {})
        summary = item.get("common_summary") if item.get("status") == "complete" else None
        if summary is None:
            lines.append(f"| {LABELS[arm]} — unmeasured | — | — | — | — | — | — |")
            continue
        repeat = "Yes" if summary["deterministic"] else "No"
        lines.append(
            f"| {LABELS[arm]} | {summary['gold_kept']}/{summary['gold_total']} | "
            f"{summary['forbid_leaks']} | {summary['clean_cases']}/{summary['cases']} | "
            f"{summary['mean_character_savings_pct']:.1f}% | "
            f"{summary['median_wall_ms']:.2f} ms | {repeat} |"
        )
    return "\n".join(lines)


def render_report(report: dict) -> None:
    if report["tameru_version"] != __version__:
        raise ValueError("The report must match this checkout's engine version")
    count = len(report["protocol"]["common_cases"])
    repeats = report["protocol"]["timed_runs_per_case"]
    table = comparison_table(report)
    date = report["run_at_utc"].split("T", 1)[0]
    intro = (
        f"Freshly measured on **{date}**, using **Tameru v{__version__}** and the same "
        f"**{count} task cases** for every scored method. The corpus includes evidence chains, "
        "stale configuration, Git/YAML/npm output, Japanese/Chinese/Arabic text, saturated "
        "grep, captured pytest logs with blank lines and numbered source reads.\n\n"
    )
    unavailable = []
    for arm in ARMS:
        item = report["arms"].get(arm, {})
        if item.get("status") != "complete":
            reason = item.get("reason") or next(
                (r.get("reason") for r in item.get("results", {}).values()
                 if r.get("status") == "failed"), "not run")
            unavailable.append(f"- **{LABELS[arm]}:** {reason}")
    unavailable_text = "\n".join(unavailable)
    tameru = report["arms"]["tameru"]["common_summary"]
    short = (
        "## Comparison with other approaches\n\n" + intro + table + "\n\n"
        f"Tameru retained **{tameru['gold_kept']}/{tameru['gold_total']} required strings**, "
        f"with **{tameru['forbid_leaks']} forbidden leaks** and "
        f"**{tameru['mean_character_savings_pct']:.1f}% mean character savings**. "
        "A clean case keeps every required string and excludes every planted forbidden string. "
        "Faster methods and different savings are shown alongside these retention checks.\n\n"
        f"Each case gets one untimed warmup and {repeats} timed complete calls. Retention is checked "
        f"across all {repeats + 1} outputs; the timing column is the median of per-case wall-time medians. "
        "Imports and model loading are outside the timer. Character savings are separate from "
        "the estimated token savings in the release battery.\n\n"
        "This is Tameru's regression corpus, not an independent downstream-agent evaluation. "
        "Headroom's row tests its Rust TextCrusher, not its full content router; "
        "LCC rows use the recorded provider and one scoring worker.\n\n"
    )
    short += (
        "LCC's Laya path includes protected no-ops: inputs that need no model scoring "
        "are kept by its deterministic policy. These are recorded separately from "
        "failed or degraded model calls.\n\n"
    )
    if unavailable:
        short += "Unmeasured providers have no scores carried forward from earlier releases:\n\n" + unavailable_text + "\n\n"
    short += (
        "See [the complete v1.4.1 comparison](benchmarks/COMPARISON.md) and "
        "[raw results, pins and timing samples](benchmarks/comparison-v1.4.1.json).\n\n"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start = readme.index("## Comparison with other approaches\n")
    end = readme.index("## v1.4.1 measured results\n", start)
    (ROOT / "README.md").write_text(readme[:start] + short + readme[end:], encoding="utf-8")

    measured = [arm for arm in ARMS if report["arms"].get(arm, {}).get("status") == "complete"]
    per_case = ["| Case | " + " | ".join(LABELS[a] for a in measured) + " |",
                "|---|" + "---:|" * len(measured)]
    for name in report["protocol"]["common_cases"]:
        cells = []
        for arm in measured:
            row = report["arms"][arm]["results"][name]
            marks = ("†" if row["missing_gold"] else "") + ("‡" if row["forbid_leaks"] else "")
            cells.append(f"{row['savings_pct']:.1f}% {marks or '✓'}")
        per_case.append("| " + name + " | " + " | ".join(cells) + " |")
    env = report["environment"]
    pins = report["source_pins"]
    full = (
        f"# Tameru v{__version__} — current comparisons\n\n" + intro + table + "\n\n"
        "All numeric cells are new measurements from this run. The earlier v1.2.0 holdout "
        "and v1.3.0 comparison have been retired from active documentation; their original "
        "records remain in Git history. No older score is relabelled as v1.4.1.\n\n"
        "## What the measurements mean\n\n"
        "- **Required strings:** specified source evidence found in every warmup/timed output. "
        "A loss in any repeat counts as a loss.\n"
        "- **Forbidden strings:** planted stale, excluded or distracting strings seen in any "
        "repeat. This is a fixture check, not a general prompt-injection defence.\n"
        "- **Clean cases:** all required strings retained with no forbidden leaks.\n"
        "- **Savings:** arithmetic mean character savings per task case. Negative savings "
        "would indicate expansion. These are not model-token or monetary savings.\n"
        f"- **Timing:** one warmup and {repeats} complete calls per case. The aggregate is the "
        "median of per-case wall-time medians, including parsing, scoring and rendering. "
        "Imports, model load and warmup are excluded. TF-IDF includes its full scoring work.\n"
        "- **Repeat output:** all four outputs are compared byte-for-byte after UTF-8 encoding. "
        "Repeated runs do not establish stability across every runtime or platform.\n\n"
        "The 4,000-record synthetic performance case and empty-query fail-open case are "
        "outside the common answer corpus. They remain covered by the separate "
        "[15-case release battery](production-qa-v3-results.json), which uses CPU time "
        "and estimated token savings.\n\n"
        "## Per-case character savings\n\n" + "\n".join(per_case) + "\n\n"
        "✓ all required strings retained, no forbidden leaks; † required evidence lost; "
        "‡ forbidden evidence retained. Savings alone do not establish success.\n\n"
        "## Versions and settings\n\n"
        f"- Tameru **{__version__}**, source commit `{report['source_commit']}`; "
        "default extraction, `ccr=False`, `citations=True`.\n"
        f"- LCC **{env['packages'].get('local-context-compiler', 'not installed')}**, "
        f"source `{pins.get('lcc')}`; requested provider, `marker=False`, "
        "`max_workers=1`, remaining compaction options at defaults. A fallback is "
        "a failed provider measurement and receives no summary score.\n"
        f"- Headroom **{env['packages'].get('headroom-ai', 'not installed')}**, "
        "Rust `TextCrusher` at defaults. The full router, other compressors and "
        "recovery store are not exercised.\n"
        "- TF-IDF: this runner's ASCII-term paragraph retrieval, original order and "
        "first paragraph retained. It is a deliberately simple baseline.\n"
        f"- Laya **{env['packages'].get('laya', 'not installed')}**, source "
        f"`{pins.get('laya')}`, model `{MODEL}` at "
        f"`{report['protocol']['laya']['revision']}`, CPU. LCC's model settings remain at defaults.\n"
        f"- Runtime: Python **{env['python']}**, `{env['machine']}`, "
        f"{env.get('cpu_model', 'CPU model unavailable')}; CPU quota "
        f"`{env.get('cpu_quota', 'not recorded')}`, thread settings "
        f"`{env.get('thread_settings')}`. Hardware and scheduling affect latency.\n\n"
        "The [raw JSON](comparison-v1.4.1.json) records the corpus and input hashes, "
        "runner hash, source pins, package versions, output hashes, missing/leaked "
        "strings and individual timing samples.\n\n"
        "Protected no-ops with zero scored blocks and zero calls are valid LCC policy "
        "results. They are flagged as `protected_noop`; they do not represent model inference. "
        "The run resumed after correcting this classification, with unchanged corpus, "
        "versions, settings and timing boundaries. Both runner hashes and the measured "
        "case lists are recorded in `execution_segments`.\n\n"
        "## Provider availability\n\n" + (unavailable_text or "Every requested provider completed the common corpus.") + "\n\n"
        "The old BM25/vector-RAG, LLM-summary and LCM table did not include sufficient "
        "implementation pins and replay inputs to reproduce those arms. It has no "
        "current scores. JEV needs an existing API credential and explicit opt-in; "
        "a local fallback is never shown as a JEV measurement.\n\n"
        "## Reproduce\n\n"
        "Install the engine's dev extra, Headroom 0.40.0 and the recorded LCC/Laya "
        "source pins in an isolated environment. Laya additionally needs CPU PyTorch, "
        "its runtime dependencies and the pinned public checkpoint. Full installed "
        "package versions are in the JSON.\n\n"
        "```bash\npython -m pip install -e '.[dev]'\n"
        "python -m pip install headroom-ai==0.40.0\n"
        f'python -m pip install "git+https://github.com/lucasmartins-ai/lcc.git@{pins.get("lcc")}"\n'
        f'python -m pip install "git+https://github.com/NandhaKishorM/laya.git@{pins.get("laya")}"\n'
        "OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 RAYON_NUM_THREADS=8 USE_TF=0 \\\n"
        f"  python benchmarks/compare.py --laya-revision {report['protocol']['laya']['revision']} \\\n"
        f"  --lcc-source-sha {pins.get('lcc')} \\\n"
        f"  --laya-source-sha {pins.get('laya')}\n"
        "python benchmarks/compare.py --render-from benchmarks/comparison-v1.4.1.json\n```\n\n"
        "The default command excludes paid JEV calls. Add `--include-jev` only when "
        "you have configured `TYPESAFE_API_KEY` and intend to run that provider. "
        "`--render-from` regenerates this page and the README comparison from the JSON.\n\n"
        "## Limits and interpretation\n\n"
        "This corpus belongs to Tameru's regression suite and includes deliberately "
        "adversarial examples. It is not an independent broad evaluation or a live-model "
        "answer-quality test. String retention cannot detect every semantic loss, and "
        "extractive output has a source-line size floor. Evaluate your workload and "
        "required evidence before choosing a compression budget.\n"
    )
    (ROOT / "benchmarks/COMPARISON.md").write_text(full, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=list(ARMS))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT / f"benchmarks/comparison-v{__version__}.json")
    parser.add_argument("--include-jev", action="store_true")
    parser.add_argument("--laya-revision")
    parser.add_argument("--lcc-source-sha")
    parser.add_argument("--laya-source-sha")
    parser.add_argument("--resume", action="store_true", help="resume matching inputs/settings without repeating completed measurements")
    parser.add_argument("--render-from", type=Path, help="render current docs from a completed JSON report")
    args = parser.parse_args(argv)
    if args.render_from:
        render_report(json.loads(args.render_from.read_text(encoding="utf-8")))
        print("Updated README and COMPARISON.md from the recorded results")
        return 0
    if args.repeats < 2:
        parser.error("--repeats must be at least 2 to check repeat output")
    cases = current_cases()
    manifests = [manifest(c) for c in cases]
    common = [m["name"] for m in manifests if m["scope"] == "answer"]
    report = {
        "schema": "tameru-comparison/2", "tameru_version": __version__,
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "corpus_sha256": digest(json.dumps(manifests, ensure_ascii=False, sort_keys=True)),
        "protocol": {
            "common_cases": common, "warmups_per_case": 1, "timed_runs_per_case": args.repeats,
            "timing": "median wall time of complete calls; imports/model load and warmup excluded",
            "savings": "arithmetic mean character savings per common answer case",
            "tameru": {"ccr": False, "citations": True, "strategy": "extract"},
            "lcc": {"marker": False, "max_workers": 1, "other_options": "defaults"},
            "headroom": "Rust TextCrusher defaults; full Headroom router not tested",
            "tfidf": "ASCII paragraph retrieval, first paragraph retained; full scoring timed",
            "laya": {"model": MODEL, "revision": args.laya_revision, "device": "cpu"},
        },
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "machine": platform.machine(), "cpu_count": os.cpu_count(),
                        "packages": dict(sorted((d.metadata["Name"], d.version)
                                                for d in importlib.metadata.distributions()
                                                if d.metadata.get("Name")))},
        "source_pins": {"lcc": args.lcc_source_sha, "laya": args.laya_source_sha},
        "cases": manifests, "arms": {},
    }
    cpu_info = Path("/proc/cpuinfo")
    if cpu_info.is_file():
        match = re.search(r"^model name\s*:\s*(.+)$", cpu_info.read_text(), re.M)
        report["environment"]["cpu_model"] = match.group(1) if match else "unknown"
    cpu_quota = Path("/sys/fs/cgroup/cpu.max")
    if cpu_quota.is_file():
        report["environment"]["cpu_quota"] = cpu_quota.read_text().strip()
    report["environment"]["thread_settings"] = {
        name: os.environ.get(name) for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "RAYON_NUM_THREADS")
    }
    report["protocol"]["retention"] = "worst required/forbidden string result across warmup and all timed outputs"
    if args.resume:
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        for key in ("tameru_version", "corpus_sha256", "protocol", "environment", "source_pins"):
            if previous[key] != report[key]:
                raise ValueError(f"Cannot resume: {key} changed")
        segments = previous.get("execution_segments", [{
            "runner_sha256": previous["runner_sha256"], "started_at_utc": previous["run_at_utc"],
            "measured_cases": {arm: [name for name, row in data.get("results", {}).items()
                                    if row.get("status") == "measured"]
                               for arm, data in previous["arms"].items()},
        }])
        report["arms"] = previous["arms"]
        report["run_at_utc"] = previous["run_at_utc"]
        report["execution_segments"] = [*segments, {
            "runner_sha256": report["runner_sha256"], "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": "resume after protected-noop classification fix; timing/corpus/provider settings unchanged",
            "measured_cases": {},
        }]
    else:
        report["execution_segments"] = [{
            "runner_sha256": report["runner_sha256"], "started_at_utc": report["run_at_utc"],
            "measured_cases": {},
        }]
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for arm in args.arms:
        arm_report = report["arms"].get(arm, {"status": "pending", "results": {}})
        if arm_report.get("status") == "complete":
            continue
        arm_report["status"] = "pending"
        report["arms"][arm] = arm_report
        try:
            runner = make_runner(arm, args)
        except Exception as exc:
            arm_report.update(status="unavailable", reason=f"{type(exc).__name__}: {exc}")
            print(f"{arm}: unavailable ({type(exc).__name__})", flush=True)
            save()
            continue
        for case in cases:
            if arm_report["results"].get(case["name"], {}).get("status") == "measured":
                continue
            if case["name"] not in common:
                arm_report["results"][case["name"]] = {"status": "skipped", "reason": "robustness/performance covered separately by release battery"}
                continue
            try:
                row = measure(runner, case, args.repeats)
            except Exception as exc:
                row = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
            arm_report["results"][case["name"]] = row
            if row["status"] == "measured":
                report["execution_segments"][-1]["measured_cases"].setdefault(arm, []).append(case["name"])
            print(f"{arm}/{case['name']}: {row['status']}", flush=True)
            save()
            if row["status"] == "failed" and arm == "lcc-jev":
                break
        rows = [arm_report["results"].get(name, {}) for name in common]
        complete = all(r.get("status") == "measured" for r in rows)
        arm_report["status"] = "complete" if complete else "incomplete"
        if complete:
            arm_report["common_summary"] = aggregate(rows)
            print(f"{arm}: {json.dumps(arm_report['common_summary'])}", flush=True)
        save()
    return 0 if report["arms"].get("tameru", {}).get("status") == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
