# Engine 1.10.0: results (replay only)

All numbers come from `benchmarks/engine_bench`, a replay of recorded and generated tool outputs through the engine under each host's call settings.
None of them is a measurement against a real model, an answer-quality check or a bill. Plan, margins and rules: [`ANALYSIS-PLAN-1.10.md`](ANALYSIS-PLAN-1.10.md).
Result files are committed under `benchmarks/engine_bench/results/`.

This page records the historical look on `99db5bd`, not a fresh evaluation of every later 1.10.0 commit. Later development changes (fact-line protection, bounded caches and the shipped calibration table) are described in the [changelog](../CHANGELOG.md#1100---unreleased). Do not rebuild or rerun the sealed split or corpus holdout to reproduce this page during routine checks.

## The sealed look (one, on commit 99db5bd, taken 2026-11-19)

94 cases in 62 source clusters that were not used for building or checking. Paired against engine 1.9.0 on the same cases
(`sealed-baseline-1.9.0.jsonl`, run once for comparison), cluster bootstrap by source case.

| Host settings × question | Saved, 1.10.0 | Difference from 1.9.0 (95% interval) | Evidence kept | Falls back to the original |
|---|---|---|---|---|
| DeepSeek, generic | 76.9% | +63.7 points [+52.1, +73.0] | 100% | 13.8% (1.9.0: 83%) |
| DeepSeek, tool-call-shaped | 76.6% | +17.0 [+8.5, +26.2] | 99.5% | 13.8% |
| DeepSeek, task | 86.6% | +21.7 [+12.9, +31.7] | 100% | 2.1% |
| Hermes, generic | 80.2% | +13.7 [+5.3, +22.7] | 98.9% | 7.4% |
| Hermes, tool-call-shaped | 76.7% | +11.2 [+4.4, +20.2] | 99.5% | 13.8% |
| Hermes, task | 86.0% | +6.5 [+1.8, +12.2] | 98.9% | 2.1% |
| Chinese user message, either host | about 90% | +0.9 [0.0, +2.7] | 100% | 5.6% |

Evidence kept did not fall in any cell (the paired difference is 0.0 or positive everywhere).

**Stack traces** (sealed): Java chains 89% saved and .NET chains 84 to 87% saved, under all three question types and both hosts' settings, with all evidence kept.

**Confidence** (DeepSeek, tool-call-shaped question, sealed): AUROC 0.988 [0.969, 1.000] for "all evidence kept"; in the calibration table every bin from 0.7 up kept all evidence.
The Hermes plugin does not use confidence. For the generic question under Hermes settings the AUROC is 0.355 [0.287, 0.411], from two rows that lose evidence at the flat structural confidence of 0.95; it is reported, not tuned.

## What is not met or not measured

- **`uni-fullwidth` and `jp_musubi` are in the development split, not the sealed split.** On dev and validation `uni-fullwidth` saves 97.6% (target 90%). `jp_musubi` saves 41.6% on a specific question and falls back to the
  original otherwise; the target for unstructured prose was amended (see the amendment in the analysis plan), so the sealed split holds no row for these two gates.
- **Whole-session cost for either host is not measured here.** The Hermes replay (`effective_real`) and the DeepSeek whole-session replay are run in the plugins' repositories; no cost or saving claim is made.
- **No real model has run.** Answer quality, the provider's cache behaviour and billing are unverified.
- **Calls with `pin_patterns` or `pin_recent`** keep 1.9.0 behaviour for the structural features.
- **Squeez** (618 SWE-bench outputs, 1.9.0): the engine compresses about 39% of the input and falls open on 200 samples, with span precision 0.09 and recall 0.74. It is not a span extractor.
- At this look, the speed budgets in `benchmarks/latency.py`: the `--quick` run passed all 84 cells (200K inputs about 0.2 to 0.3 s); the full run including 2M inputs had not been repeated. The changelog records a later development run including 2M and 4M classes; it is not a rerun of this sealed evaluation.

## The DeepSeek plugin's whole-session replay (gate 8): not met

The DeepSeek plugin measures the engine in whole sessions with a priced cache (read 0.1, write 1.0; write 1.25 as a sensitivity), replay only, in its own repository (`docs/REPLAY-1.10.0.md`).
26 settings were tried on 60 development scenarios (36 development, 24 validation), declared in [`ANALYSIS-PLAN-1.10.md`](ANALYSIS-PLAN-1.10.md) before they ran; round 1 found nothing inside the margins, round 2 fixed a defect in
the "act only where the Harness would cut" policy and froze that policy with no confidence gate (T-0). The one look at the fresh holdout (48 scenarios, hash registered in the plan before any tuning) gave:

| Quantity (T-0, 48 clusters) | Result | Margin | Met |
|---|---|---|---|
| Cost vs the 1.9.0-era plugin | -0.03% (one-sided upper +0.36) | upper <= +1.0 | yes |
| Facts kept vs the 1.9.0-era plugin | -0.50 points (one-sided lower -2.27) | lower >= -1.0 | no |
| Accepted extracts keep their facts | 90.2% (one-sided lower 82.5) | lower >= 85 | no |
| Cost vs stock | -1.27% (upper -0.85) | reported | |
| Facts kept vs stock | +5.00 points (lower +2.74) | reported | |

Gate 8 is therefore **not met**, and the look is spent; a further change of setting needs a new sealed holdout. The engine's own results above do not depend on this gate. No real model ran.

## Sealed-look log

`benchmarks/engine_bench/sealed_looks.json` records one look at the candidate. The 1.9.0 baseline was run once over the same cases for comparison only.
