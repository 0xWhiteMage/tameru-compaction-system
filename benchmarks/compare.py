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
from html import escape
from math import ceil, floor
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


def comparison_table(report: dict, *, include_repeats: bool = True) -> str:
    lines = [
        "| Method | Required strings kept | Forbidden strings ↓ | Clean cases | Mean chars saved ↑ | Median wall time ↓ |"
        + (" Repeat output identical |" if include_repeats else ""),
        "|---|---:|---:|---:|---:|---:|" + ("---|" if include_repeats else ""),
    ]
    for arm in ARMS:
        item = report["arms"].get(arm, {})
        summary = item.get("common_summary") if item.get("status") == "complete" else None
        if summary is None:
            lines.append(f"| {LABELS[arm]} — unmeasured | — | — | — | — | — |"
                         + (" — |" if include_repeats else ""))
            continue
        repeat = "Yes" if summary["deterministic"] else "No"
        lines.append(
            f"| {LABELS[arm]} | {summary['gold_kept']}/{summary['gold_total']} | "
            f"{summary['forbid_leaks']} | {summary['clean_cases']}/{summary['cases']} | "
            f"{summary['mean_character_savings_pct']:.1f}% | "
            f"{summary['median_wall_ms']:,.2f} ms |"
            + (f" {repeat} |" if include_repeats else "")
        )
    return "\n".join(lines)


def comparison_svg(report: dict) -> str:
    """Render an accessible, theme-aware chart directly from measured summaries."""
    measured = [a for a in ARMS if report["arms"].get(a, {}).get("status") == "complete"]
    summaries = [report["arms"][a]["common_summary"] for a in measured]
    count = len(report["protocol"]["common_cases"])
    height = 220 + 46 * len(measured)
    low = min(0, floor(min(s["mean_character_savings_pct"] for s in summaries) / 25) * 25)
    high = max(100, ceil(max(s["mean_character_savings_pct"] for s in summaries) / 25) * 25)

    def x(value: float) -> float:
        return 330 + (value - low) / (high - low) * 280

    def text(px: float, py: float, value: str, cls: str = "label", anchor: str = "start") -> str:
        return (f'<text x="{px:.2f}" y="{py:.2f}" class="{cls}" '
                f'text-anchor="{anchor}">{escape(value)}</text>')

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1120 {height}" '
        f'width="1120" height="{height}" role="img" aria-labelledby="title description">',
        '<title id="title">Tameru v' + escape(report["tameru_version"]) + ' comparison: savings and evidence retention</title>',
        f'<desc id="description">{count} common tasks, identical inputs and queries. '
        + escape("; ".join(
            f"{LABELS[a].strip('*')}: {s['mean_character_savings_pct']:.1f}% mean character savings, "
            f"{s['clean_cases']}/{s['cases']} clean cases" for a, s in zip(measured, summaries, strict=True)
        )) + '.</desc>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:#24292f}'
        '.title{font-size:26px;font-weight:700}.subtitle{font-size:15px;fill:#57606a}'
        '.heading{font-size:13px;font-weight:700;letter-spacing:1px}.label{font-size:16px}'
        '.value{font-size:17px;font-weight:600}.tick,.note{font-size:13px;fill:#57606a}'
        '.background{fill:#f6f8fa}.track{fill:#e5e9ef}.bar{fill:#8294ad}'
        '.tameru{fill:#7355cc}.clean{fill:#25806c}.rule{stroke:#d0d7de}'
        '@media(prefers-color-scheme:dark){text{fill:#e6edf3}.subtitle,.tick,.note{fill:#a5b3c4}'
        '.background{fill:#111827}.track{fill:#253145}.bar{fill:#8497b2}.tameru{fill:#b29aff}'
        '.clean{fill:#67cdb6}.rule{stroke:#39465a}}</style>',
        f'<rect class="background" width="1120" height="{height}" rx="16"/>',
        text(30, 42, "Same tasks. Less context.", "title"),
        text(30, 70, f"Tameru v{report['tameru_version']} · {count} matched tasks · "
             f"{len(measured)} measured methods · {report['run_at_utc'].split('T')[0]}", "subtitle"),
        text(330, 112, "MEAN CHARACTER SAVINGS", "heading"),
        text(790, 112, "CLEAN CASES", "heading"),
    ]
    for tick in range(low, high + 1, 25):
        svg.append(text(x(tick), 136, f"{tick}%", "tick", "middle"))
    for tick in (0, count // 2, count):
        svg.append(text(790 + tick / max(1, count) * 190, 136, str(tick), "tick", "middle"))
    for i, (arm, summary) in enumerate(zip(measured, summaries, strict=True)):
        y = 160 + i * 46
        savings = summary["mean_character_savings_pct"]
        clean = summary["clean_cases"]
        svg.extend([
            text(30, y + 19, LABELS[arm].strip("*")),
            f'<rect x="330" y="{y}" width="280" height="26" rx="5" class="track"/>',
            f'<rect x="{min(x(0), x(savings)):.2f}" y="{y}" '
            f'width="{abs(x(savings) - x(0)):.2f}" height="26" rx="5" '
            f'class="{"tameru" if arm == "tameru" else "bar"}"/>',
            text(685, y + 19, f"{savings:.1f}%", "value", "end"),
            f'<rect x="790" y="{y}" width="190" height="26" rx="5" class="track"/>',
            f'<rect x="790" y="{y}" width="{clean / max(1, count) * 190:.2f}" '
            f'height="26" rx="5" class="{"clean" if arm == "tameru" else "bar"}"/>',
            text(1075, y + 19, f"{clean}/{count}", "value", "end"),
        ])
    svg.extend([
        f'<path d="M30 {height - 65}H1090" class="rule"/>',
        text(30, height - 41, "Savings are averaged per task. Clean = every required string kept, no planted forbidden strings retained.", "note"),
        text(30, height - 20, "Source: benchmarks/comparison-v" + report["tameru_version"]
             + ".json · Tameru regression corpus; downstream agent accuracy is not measured.", "note"),
        '</svg>\n',
    ])
    return "\n".join(svg)


def replace_readme_block(readme: str, name: str, content: str) -> str:
    start_marker = f"<!-- tameru:{name}:start -->"
    end_marker = f"<!-- tameru:{name}:end -->"
    if readme.count(start_marker) != 1 or readme.count(end_marker) != 1:
        raise ValueError(f"README requires one complete {name} marker pair")
    start = readme.index(start_marker) + len(start_marker)
    end = readme.index(end_marker, start)
    return readme[:start] + "\n\n" + content.rstrip() + "\n\n" + readme[end:]


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
    measured = [arm for arm in ARMS if report["arms"].get(arm, {}).get("status") == "complete"]
    env = report["environment"]
    packages = env["packages"]
    jev = report["arms"].get("lcc-jev", {})
    availability_note = ""
    if jev.get("status") != "complete":
        availability_note = (
            "JEV was unmeasured because its API credential was unavailable. "
            if "TYPESAFE_API_KEY" in jev.get("reason", "") else
            "JEV has no score because this provider did not complete the corpus. "
        )
    headline = (
        "| Mean characters saved | Required strings retained | Forbidden strings retained | Median wall time |\n"
        "|:---:|:---:|:---:|:---:|\n"
        f"| **{tameru['mean_character_savings_pct']:.1f}%** | "
        f"**{tameru['gold_kept']}/{tameru['gold_total']}** | **{tameru['forbid_leaks']}** | "
        f"**{tameru['median_wall_ms']:,.2f} ms** |\n\n"
        f"Measured on **{count} shared task cases**, with {len(measured)} runnable methods on CPU, "
        f"**{date}**. These are source-evidence checks on Tameru's regression corpus; "
        "agent answer accuracy and model-token costs are outside this evaluation.\n"
    )
    repeat_text = (
        f"All {len(measured)} scored methods produced identical output across the warmup "
        "and timed repeats. " if all(report["arms"][a]["common_summary"]["deterministic"]
                                    for a in measured) else
        "Repeat-output checks for each method are in the detailed report. "
    )
    short = (
        f"**Same input. Same query. Same {count} tasks.** The current comparison covers "
        "documents, configuration, Git/npm/YAML output, multilingual text and v1.4.1's "
        "grep, pytest and numbered-source cases.\n\n"
        f"![v{__version__} comparison of mean character savings and clean cases across measured methods]"
        f"(assets/comparison-v{__version__}.svg)\n\n"
        + comparison_table(report, include_repeats=False) + "\n\n"
        "**A clean case keeps every required string and excludes every planted forbidden string.** "
        "Savings are the arithmetic mean per case; wall time is the median of per-case medians. "
        "Headroom's row measures the **TextCrusher component**. "
        + availability_note.rstrip() + "\n\n"
        "[Complete comparison and per-task results →](benchmarks/COMPARISON.md) · "
        f"[Raw measurements →](benchmarks/comparison-v{__version__}.json)\n\n"
        "<details>\n<summary><strong>Evaluation details: corpus, methods, timing and limits</strong></summary>\n\n"
        "**Corpus.** All scored methods see identical text and task queries. "
        f"The {count} cases include {tameru['gold_total']} required source strings plus "
        "planted stale, excluded or distracting strings. The large synthetic performance case "
        "and empty-query case belong to the separate release QA battery.\n\n"
        "**Metrics.** Required strings must survive every output; a forbidden string in any "
        "output counts as a leak. Character savings measure text length, rather than model "
        "tokens or monetary cost. These checks cover specified fixture evidence and do not "
        "measure downstream agent answers or every possible semantic loss.\n\n"
        "**Methods.** Tameru uses default extraction with `ccr=False`, `citations=True`. "
        f"LCC {packages.get('local-context-compiler', 'not installed')} uses one scoring worker "
        f"and no marker; Headroom {packages.get('headroom-ai', 'not installed')} uses Rust TextCrusher "
        "at defaults, without the full router or recovery store. TF-IDF is a simple "
        f"paragraph-retrieval baseline. Laya {packages.get('laya', 'not installed')} runs "
        "its pinned multilingual model on CPU. "
        "LCC's protected no-ops are valid policy outcomes; model fallbacks receive no score.\n\n"
        f"**Timing.** One untimed warmup and {repeats} timed complete calls per case. "
        "Parsing, scoring and rendering are inside the timer; imports and model loading are "
        "outside it. " + repeat_text + "Hardware and scheduling affect latency.\n\n"
        f"**Runtime and provenance.** Python {env['python']} on "
        f"{env.get('cpu_model', 'the recorded CPU')}, with CPU-quota and thread settings "
        "in the JSON. Source/model pins, input/output "
        "hashes, package versions and individual timing samples are recorded in the raw JSON. "
        "The resumed Laya measurements retain the same corpus and settings; execution segments "
        "record the protected-no-op classification correction.\n\n"
        "**Interpretation.** This is Tameru's own regression corpus, including adversarial "
        "fixtures. Broader independent and live-agent evaluations are still needed to establish "
        "generality. An unmeasured provider has no score carried forward from an earlier release.\n\n"
        "</details>\n"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme = replace_readme_block(readme, "headline", headline)
    readme = replace_readme_block(readme, "comparison", short)
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    (assets / f"comparison-v{__version__}.svg").write_text(comparison_svg(report), encoding="utf-8")

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
        "Documentation and chart rendering can change after a measurement run. "
        "Recorded runner hashes identify the code used for those measurements, "
        "rather than necessarily matching the current documentation renderer.\n\n"
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
        "`--render-from` regenerates this page, the README headline/comparison blocks "
        "and the theme-aware SVG chart from the JSON. It preserves the rest of the README.\n\n"
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
