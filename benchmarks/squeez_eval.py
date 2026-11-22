# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Benjamin Ang
# SPDX-FileCopyrightText: Copyright 2026 KR Labs
# Modified by Benjamin Ang, 2026: extracted from three upstream files into this file
# alongside Tameru-specific code; docstring of compute_empty_accuracy shortened.

"""Tameru on the Squeez tool-output pruning benchmark (618-example held-out test set).

Benchmark: Kovacs, "Squeez: Task-Conditioned Tool-Output Pruning for Coding Agents", arXiv:2604.04979.
Data: huggingface.co/datasets/KRLabsOrg/tool-output-extraction-swebench, file ``canonical_test.jsonl``
(Apache-2.0; sha256 1ead3be111439266370fbcc8ffabeadd38fbd1526bbd981d23347da013b20540).

The metric functions and the naive baselines below are copied with minor modifications from the Squeez repository at
commit aa0bd37c4d32ade33f98e4b278801e4f139fbd9e (``squeez/training/evaluate.py``,
``squeez/data/canonical.py``, ``scripts/evaluate_baselines.py``; Apache License 2.0, Copyright 2026 KR Labs), so
the numbers are computed exactly as in the paper's Table 4. The naive baselines are re-run here as a check
that this scorer reproduces the published figures.

How Tameru is scored: ``compress_context(tool_output, query)`` with the focused ``query`` (what every Squeez
arm receives). The prediction is the set of output lines that are verbatim lines of the input; engine-made
lines (gap markers, adapter summaries) are not evidence and are dropped. When Tameru fails open it returns
the whole input, which counts as a full-recall, zero-compression prediction: that is what an agent would see.

    python benchmarks/squeez_eval.py --data <dir with canonical_test.jsonl> [--out results.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tameru.compress_context import ENGINE_VERSION, compress_context  # noqa: E402

DATA_SHA256 = "1ead3be111439266370fbcc8ffabeadd38fbd1526bbd981d23347da013b20540"

# Published Table 4 (arXiv:2604.04979v1): Prec., Recall, Strict F1, Exact, F1, Compression.
PUBLISHED = {
    "Squeez-2B": (0.80, 0.86, 0.79, 0.49, 0.80, 0.92),
    "Qwen 3.5 35B A3B": (0.74, 0.75, 0.70, 0.39, 0.73, 0.92),
    "Kimi K2": (0.61, 0.53, 0.53, 0.30, 0.68, 0.94),
    "Qwen 3.5 2B (base)": (0.42, 0.53, 0.41, 0.19, 0.55, 0.82),
    "BM25 (10%)": (0.13, 0.22, 0.13, 0.01, 0.23, 0.90),
    "First-N (10%)": (0.07, 0.14, 0.08, 0.02, 0.16, 0.91),
    "Random (10%)": (0.07, 0.10, 0.07, 0.01, 0.20, 0.91),
    "Last-N (10%)": (0.05, 0.05, 0.04, 0.01, 0.14, 0.91),
}


# ---- verbatim from squeez/data/canonical.py ---------------------------------------------------
def normalize_spans(spans: list[dict[str, Any]], total_lines: int) -> list[dict[str, int]]:
    """Clamp, sort, and merge line spans against a raw tool output."""
    if total_lines <= 0 or not spans:
        return []

    cleaned: list[tuple[int, int]] = []
    for span in spans:
        start = max(1, int(span.get("start_line", span.get("start", 1))))
        end = min(total_lines, int(span.get("end_line", span.get("end", start))))
        if start <= end:
            cleaned.append((start, end))

    if not cleaned:
        return []

    cleaned.sort()
    merged: list[tuple[int, int]] = [cleaned[0]]
    for start, end in cleaned[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    return [{"start_line": start, "end_line": end} for start, end in merged]


def extract_relevant_lines(tool_output: str, spans: list[dict[str, Any]]) -> list[str]:
    """Extract relevant lines from raw tool output using canonical spans."""
    lines = tool_output.split("\n")
    normalized = normalize_spans(spans, len(lines))
    result: list[str] = []
    for span in normalized:
        start = span["start_line"] - 1
        end = span["end_line"]
        result.extend(lines[start:end])
    return result


# ---- verbatim from squeez/training/evaluate.py ------------------------------------------------
def compute_span_metrics(predicted: list[str], reference: list[str]) -> dict[str, float]:
    """Compute span-level precision, recall, F1 using set overlap on normalized lines."""
    pred_set = set(predicted)
    ref_set = set(reference)

    if not ref_set and not pred_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "exact_match": 1.0}

    if not ref_set or not pred_set:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "exact_match": 0.0}

    tp = len(pred_set & ref_set)
    precision = tp / len(pred_set)
    recall = tp / len(ref_set)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    exact_match = 1.0 if pred_set == ref_set else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "exact_match": exact_match,
    }


def _line_overlap_score(pred_line: str, ref_line: str) -> float:
    """Compute a symmetric overlap score for two lines."""
    if not pred_line or not ref_line:
        return 0.0
    if pred_line == ref_line:
        return 1.0
    if pred_line in ref_line or ref_line in pred_line:
        return min(len(pred_line), len(ref_line)) / max(len(pred_line), len(ref_line))

    pred_bigrams = (
        {pred_line[i : i + 2] for i in range(len(pred_line) - 1)}
        if len(pred_line) > 1
        else {pred_line}
    )
    ref_bigrams = (
        {ref_line[i : i + 2] for i in range(len(ref_line) - 1)} if len(ref_line) > 1 else {ref_line}
    )
    if not pred_bigrams or not ref_bigrams:
        return 0.0

    overlap = len(pred_bigrams & ref_bigrams)
    precision = overlap / len(pred_bigrams)
    recall = overlap / len(ref_bigrams)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def compute_fuzzy_span_metrics(
    predicted: list[str],
    reference: list[str],
    threshold: float = 0.5,
) -> dict[str, float]:
    """Compute one-to-one fuzzy line overlap metrics at a fixed threshold."""
    if not reference and not predicted:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not reference or not predicted:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    candidate_pairs: list[tuple[float, int, int]] = []
    for pred_idx, pred_line in enumerate(predicted):
        for ref_idx, ref_line in enumerate(reference):
            score = _line_overlap_score(pred_line, ref_line)
            if score >= threshold:
                candidate_pairs.append((score, pred_idx, ref_idx))

    matched_pred: set[int] = set()
    matched_ref: set[int] = set()
    tp = 0

    for score, pred_idx, ref_idx in sorted(candidate_pairs, reverse=True):
        del score
        if pred_idx in matched_pred or ref_idx in matched_ref:
            continue
        matched_pred.add(pred_idx)
        matched_ref.add(ref_idx)
        tp += 1

    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(reference) if reference else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def compute_empty_accuracy(predicted: list[str], reference: list[str]) -> dict[str, float | str]:
    """Check if model correctly predicts empty vs non-empty."""
    ref_empty = len(reference) == 0
    pred_empty = len(predicted) == 0

    if ref_empty and pred_empty:
        return {"category": "true_negative", "correct": 1.0}
    elif ref_empty and not pred_empty:
        return {"category": "false_positive", "correct": 0.0}
    elif not ref_empty and pred_empty:
        return {"category": "false_negative", "correct": 0.0}
    else:
        return {"category": "true_positive", "correct": 1.0}


def compute_compression_ratio(original: str, filtered: str) -> float:
    """Compute compression ratio (1 - filtered/original)."""
    orig_lines = len(original.split("\n"))
    filt_lines = len(filtered.split("\n"))
    if orig_lines == 0:
        return 0.0
    return round(1.0 - filt_lines / orig_lines, 4)


# ---- verbatim from scripts/evaluate_baselines.py (first_n, last_n, bm25) ----------------------
def baseline_first_n(task: str, tool_output: str, target_ratio: float = 0.10) -> list[str]:
    """Keep the first ~10% of lines (naive truncation)."""
    lines = tool_output.split("\n")
    n_keep = max(1, int(len(lines) * target_ratio))
    return lines[:n_keep]


def baseline_last_n(task: str, tool_output: str, target_ratio: float = 0.10) -> list[str]:
    """Keep the last ~10% of lines."""
    lines = tool_output.split("\n")
    n_keep = max(1, int(len(lines) * target_ratio))
    return lines[-n_keep:]


def baseline_bm25(task: str, tool_output: str, target_ratio: float = 0.10) -> list[str]:
    """Rank lines by BM25 score against the task query, keep top ~10%."""
    lines = tool_output.split("\n")
    n_keep = max(1, int(len(lines) * target_ratio))

    # Simple BM25 implementation
    query_terms = set(task.lower().split())
    k1 = 1.5
    b = 0.75

    # Document frequency
    doc_freq: dict[str, int] = {}
    doc_lengths = []
    for line in lines:
        terms = set(line.lower().split())
        doc_lengths.append(len(line.lower().split()))
        for t in terms:
            doc_freq[t] = doc_freq.get(t, 0) + 1

    n_docs = len(lines)
    avg_dl = sum(doc_lengths) / max(n_docs, 1)

    scores = []
    for i, line in enumerate(lines):
        terms = line.lower().split()
        term_freq: dict[str, int] = {}
        for t in terms:
            term_freq[t] = term_freq.get(t, 0) + 1

        score = 0.0
        dl = doc_lengths[i]
        for qt in query_terms:
            if qt not in doc_freq:
                continue
            df = doc_freq[qt]
            tf = term_freq.get(qt, 0)
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avg_dl, 1)))
            score += idf * tf_norm
        scores.append((score, i))

    scores.sort(reverse=True)
    kept_indices = sorted([idx for _, idx in scores[:n_keep]])
    return [lines[i] for i in kept_indices]


# ---- Tameru arms -------------------------------------------------------------------------------
def _verbatim_lines(output: str, tool_output: str) -> list[str]:
    """Output lines that are verbatim input lines (drops engine-made markers and summaries)."""
    source = set(tool_output.split("\n"))
    return [line for line in output.split("\n") if line in source]


def tameru_arm(**kwargs: Any) -> Callable[[str, str], list[str]]:
    def predict(task: str, tool_output: str) -> list[str]:
        result = compress_context(tool_output, task, ccr=False, citations=False, **kwargs)
        predict.fail_open += int(result.fail_open)  # type: ignore[attr-defined]
        return _verbatim_lines(result.compressed_text, tool_output)

    predict.fail_open = 0  # type: ignore[attr-defined]
    return predict


ARMS: dict[str, Callable[[], Callable[[str, str], list[str]]]] = {
    # The engine's defaults.
    "tameru": lambda: tameru_arm(),
    # The Hermes plugin's engine settings (config.py defaults): error anchors and prose brief on.
    "tameru (plugin settings)": lambda: tameru_arm(anchor_errors=True, prose_brief=True),
    "BM25 (10%)": lambda: baseline_bm25,
    "First-N (10%)": lambda: baseline_first_n,
    "Last-N (10%)": lambda: baseline_last_n,
}


# ---- scoring -----------------------------------------------------------------------------------
def score(pred_lines: list[str], ref_lines: list[str], tool_output: str) -> dict[str, Any]:
    """The per-sample metrics of ``scripts/evaluate_baselines.py::_compute_metrics`` (ROUGE and partial
    overlap omitted: they are not in Table 4)."""
    span = compute_span_metrics(pred_lines, ref_lines)
    fuzzy = compute_fuzzy_span_metrics(pred_lines, ref_lines, threshold=0.5)
    empty = compute_empty_accuracy(pred_lines, ref_lines)
    return {
        "span_precision": span["precision"],
        "span_recall": span["recall"],
        "span_f1": span["f1"],
        "exact_match": span["exact_match"],
        "fuzzy_span_precision": fuzzy["precision"],
        "fuzzy_span_recall": fuzzy["recall"],
        "fuzzy_span_f1": fuzzy["f1"],
        "empty_category": empty["category"],
        "compression": compute_compression_ratio(tool_output, "\n".join(pred_lines)),
    }


_MEAN_KEYS = (
    "span_precision", "span_recall", "span_f1", "exact_match",
    "fuzzy_span_precision", "fuzzy_span_recall", "fuzzy_span_f1", "compression",
)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {k: round(statistics.mean(r[k] for r in rows), 4) for k in _MEAN_KEYS}
    confusion: dict[str, int] = defaultdict(int)
    for r in rows:
        confusion[r["empty_category"]] += 1
    out["empty_confusion"] = dict(confusion)
    out["n"] = len(rows)
    return out


def load(data_dir: Path) -> list[dict[str, Any]]:
    path = data_dir / "canonical_test.jsonl"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != DATA_SHA256:
        raise SystemExit(f"{path}: sha256 {digest} is not the pinned test set {DATA_SHA256}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(samples: list[dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name, make in ARMS.items():
        predict = make()
        per_sample, by_tool, latencies = [], defaultdict(list), []
        for sample in samples:
            tool_output = sample["tool_output"]
            ref_lines = [
                line.strip() for line in extract_relevant_lines(tool_output, sample["gold_spans"]) if line.strip()
            ]
            start = time.perf_counter()
            pred = predict(sample["query"], tool_output)
            latencies.append((time.perf_counter() - start) * 1000)
            pred_lines = [line.strip() for line in pred if line.strip()]
            row = score(pred_lines, ref_lines, tool_output)
            row["instance_id"], row["tool_type"] = sample["instance_id"], sample["tool_type"]
            per_sample.append(row)
            by_tool[sample["tool_type"]].append(row)
        summary = aggregate(per_sample)
        summary["median_ms"] = round(statistics.median(latencies), 2)
        summary["p95_ms"] = round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 2)
        if hasattr(predict, "fail_open"):
            summary["fail_open"] = predict.fail_open
        results[name] = {
            "summary": summary,
            "by_tool": {tool: aggregate(rows) for tool, rows in sorted(by_tool.items())},
            "per_sample": per_sample,
        }
    return results


def print_table(results: dict[str, Any]) -> None:
    head = ("Arm", "Prec", "Recall", "StrictF1", "Exact", "F1(fuzzy)", "FzPrec", "FzRec", "Compr", "ms(med)")
    print(" | ".join(head))
    for name, (p, r, sf1, em, f1, comp) in PUBLISHED.items():
        print(f"{name} [published] | {p:.2f} | {r:.2f} | {sf1:.2f} | {em:.2f} | {f1:.2f} | - | - | {comp:.2f} | -")
    for name, res in results.items():
        s = res["summary"]
        print(
            f"{name} [measured] | {s['span_precision']:.2f} | {s['span_recall']:.2f} | {s['span_f1']:.2f} | "
            f"{s['exact_match']:.2f} | {s['fuzzy_span_f1']:.2f} | {s['fuzzy_span_precision']:.2f} | "
            f"{s['fuzzy_span_recall']:.2f} | {s['compression']:.2f} | {s['median_ms']}"
            + (f" | fail_open={s['fail_open']}" if "fail_open" in s else "")
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True, help="directory holding canonical_test.jsonl")
    parser.add_argument("--out", type=Path, default=None, help="write full results JSON here")
    args = parser.parse_args()
    samples = load(args.data)
    results = run(samples)
    print(f"Tameru engine {ENGINE_VERSION}; {len(samples)} samples")
    print_table(results)
    if args.out:
        payload = {"engine_version": ENGINE_VERSION, "data_sha256": DATA_SHA256, "arms": results}
        args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
