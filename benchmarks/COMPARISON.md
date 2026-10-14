# Tameru v1.4.1 — current comparisons

Freshly measured on **2026-10-12**, using **Tameru v1.4.1** and the same **16 task cases** for every scored method. The corpus includes evidence chains, stale configuration, Git/YAML/npm output, Japanese/Chinese/Arabic text, saturated grep, captured pytest logs with blank lines and numbered source reads.

| Method | Required strings kept | Forbidden strings ↓ | Clean cases | Mean chars saved ↑ | Median wall time ↓ | Repeat output identical |
|---|---:|---:|---:|---:|---:|---|
| **Tameru v1.4.1** | 25/25 | 0 | 16/16 | 81.9% | 12.83 ms | Yes |
| LCC mechanical | 25/25 | 5 | 11/16 | 36.3% | 6.97 ms | Yes |
| Headroom TextCrusher | 21/25 | 4 | 9/16 | 50.5% | 0.51 ms | Yes |
| TF-IDF paragraph baseline | 22/25 | 5 | 9/16 | 53.4% | 0.12 ms | Yes |
| LCC → Laya (CPU) | 25/25 | 5 | 11/16 | 8.0% | 8,091.08 ms | Yes |
| LCC → JEV — unmeasured | — | — | — | — | — | — |

**Status on v1.5.0.** This record was measured on Tameru v1.4.1 and is the only measurement of the competitor methods. Tameru v1.5.0 reproduces the Tameru column's outputs exactly (`python benchmarks/compare.py --verify-against benchmarks/comparison-v1.4.1.json`: same corpus hash, same output hashes, savings and retention on all 16 cases). Timings are not restated for v1.5.0, and no competitor was re-run.

All numeric cells are new measurements from this run. The earlier v1.2.0 holdout and v1.3.0 comparison have been retired from active documentation; their original records remain in Git history. No older score is relabelled as v1.4.1.

## What the measurements mean

- **Required strings:** specified source evidence found in every warmup/timed output. A loss in any repeat counts as a loss.
- **Forbidden strings:** planted stale, excluded or distracting strings seen in any repeat. This is a fixture check, not a general prompt-injection defence.
- **Clean cases:** all required strings retained with no forbidden leaks.
- **Savings:** arithmetic mean character savings per task case. Negative savings would indicate expansion. These are not model-token or monetary savings.
- **Timing:** one warmup and 3 complete calls per case. The aggregate is the median of per-case wall-time medians, including parsing, scoring and rendering. Imports, model load and warmup are excluded. TF-IDF includes its full scoring work.
- **Repeat output:** all four outputs are compared byte-for-byte after UTF-8 encoding. Repeated runs do not establish stability across every runtime or platform.

The 4,000-record synthetic performance case and empty-query fail-open case are outside the common answer corpus. They remain covered by the separate [15-case release battery](production-qa-v3-results.json), which uses CPU time and estimated token savings.

## Per-case character savings

| Case | **Tameru v1.4.1** | LCC mechanical | Headroom TextCrusher | TF-IDF paragraph baseline | LCC → Laya (CPU) |
|---|---:|---:|---:|---:|---:|
| lexical_distractor | 96.8% ✓ | 96.6% ‡ | 50.5% ‡ | 95.7% †‡ | 0.0% ‡ |
| multi_hop_chain | 95.0% ✓ | 98.4% ✓ | 49.8% ✓ | 96.8% ✓ | 6.5% ✓ |
| current_value | 91.1% ✓ | 93.1% ‡ | 47.2% ‡ | 88.5% ‡ | 18.5% ‡ |
| negation_override | 92.5% ✓ | 94.8% ‡ | 48.1% ‡ | 90.2% ‡ | 18.9% ‡ |
| no_marker_keeps_both | 89.4% ✓ | 94.4% ✓ | 47.8% ✓ | 89.7% ✓ | 84.8% ✓ |
| evidence_chain_holdout | 95.9% ✓ | 98.4% ✓ | 49.8% ✓ | 97.8% ✓ | 0.0% ✓ |
| git_log | 93.9% ✓ | 0.0% ✓ | 49.9% † | 0.0% ✓ | 0.0% ✓ |
| npm_log | 30.5% ✓ | 0.0% ✓ | 48.8% ✓ | 0.0% ✓ | 0.0% ✓ |
| jp_musubi | 35.3% ✓ | 5.6% ✓ | 49.8% ✓ | 42.6% ✓ | 0.0% ✓ |
| zh_needle | 89.3% ✓ | 0.0% ✓ | 48.1% ✓ | 95.7% † | 0.0% ✓ |
| ar_needle | 89.0% ✓ | 0.0% ✓ | 47.4% ✓ | 95.5% † | 0.0% ✓ |
| travis_yaml | 64.1% ✓ | 0.0% ‡ | 56.2% † | 61.1% ‡ | 0.0% ‡ |
| excluded_sample | 87.6% ✓ | 0.0% ‡ | 47.1% ‡ | 0.0% ‡ | 0.0% ‡ |
| grep_saturated_command | 79.8% ✓ | 0.0% ✓ | 68.0% ✓ | 0.0% ✓ | 0.0% ✓ |
| pytest_captured_blank_lines | 81.1% ✓ | 0.0% ✓ | 49.0% † | 0.0% ✓ | 0.0% ✓ |
| numbered_source | 98.5% ✓ | 0.0% ✓ | 50.2% ✓ | 0.0% ✓ | 0.0% ✓ |

✓ all required strings retained, no forbidden leaks; † required evidence lost; ‡ forbidden evidence retained. Savings alone do not establish success.

## Versions and settings

- Tameru **1.4.1**, source commit `13f9b51053776fefcb08f53afac8a52eea56ec7d`; default extraction, `ccr=False`, `citations=True`.
- LCC **1.0.0**, source `16f0ddf2b136154e5c80301237d3c860df42baac`; requested provider, `marker=False`, `max_workers=1`, remaining compaction options at defaults. A fallback is a failed provider measurement and receives no summary score.
- Headroom **0.40.0**, Rust `TextCrusher` at defaults. The full router, other compressors and recovery store are not exercised.
- TF-IDF: this runner's ASCII-term paragraph retrieval, original order and first paragraph retained. It is a deliberately simple baseline.
- Laya **0.4.4**, source `682ac6719faa5b1c04b529501feb93e58ee91f3d`, model `convaiinnovations/laya-multilingual` at `1720e3e3357cfe1e281542e223f8273b0890ca34`, CPU. LCC's model settings remain at defaults.
- Runtime: Python **3.12.14**, `x86_64`, INTEL(R) XEON(R) PLATINUM 8573C; CPU quota `800000 100000`, thread settings `{'OMP_NUM_THREADS': '8', 'MKL_NUM_THREADS': '8', 'RAYON_NUM_THREADS': '8'}`. Hardware and scheduling affect latency.

The [raw JSON](comparison-v1.4.1.json) records the corpus and input hashes, runner hash, source pins, package versions, output hashes, missing/leaked strings and individual timing samples.

Documentation and chart rendering can change after a measurement run. Recorded runner hashes identify the code used for those measurements, rather than necessarily matching the current documentation renderer.

Protected no-ops with zero scored blocks and zero calls are valid LCC policy results. They are flagged as `protected_noop`; they do not represent model inference. The run resumed after correcting this classification, with unchanged corpus, versions, settings and timing boundaries. Both runner hashes and the measured case lists are recorded in `execution_segments`.

## Provider availability

- **LCC → JEV:** RuntimeError: JEV requires --include-jev and an existing TYPESAFE_API_KEY

The old BM25/vector-RAG, LLM-summary and LCM table did not include sufficient implementation pins and replay inputs to reproduce those arms. It has no current scores. JEV needs an existing API credential and explicit opt-in; a local fallback is never shown as a JEV measurement.

## Reproduce

Install the engine's dev extra, Headroom 0.40.0 and the recorded LCC/Laya source pins in an isolated environment. Laya additionally needs CPU PyTorch, its runtime dependencies and the pinned public checkpoint. Full installed package versions are in the JSON.

```bash
python -m pip install -e '.[dev]'
python -m pip install headroom-ai==0.40.0
python -m pip install "git+https://github.com/lucasmartins-ai/lcc.git@16f0ddf2b136154e5c80301237d3c860df42baac"
python -m pip install "git+https://github.com/NandhaKishorM/laya.git@682ac6719faa5b1c04b529501feb93e58ee91f3d"
OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 RAYON_NUM_THREADS=8 USE_TF=0 \
  python benchmarks/compare.py --laya-revision 1720e3e3357cfe1e281542e223f8273b0890ca34 \
  --lcc-source-sha 16f0ddf2b136154e5c80301237d3c860df42baac \
  --laya-source-sha 682ac6719faa5b1c04b529501feb93e58ee91f3d
python benchmarks/compare.py --verify-against benchmarks/comparison-v1.4.1.json
```

The default command excludes paid JEV calls. Add `--include-jev` only when you have configured `TYPESAFE_API_KEY` and intend to run that provider. `--verify-against` re-runs only the Tameru arm and exits non-zero if any output hash, saving or retention result differs from the record (timings excluded). `--render-from` regenerates this page, the README blocks and the SVG chart from a report of the same engine version, so it needs a fresh full comparison on a later release.

## Limits and interpretation

This corpus belongs to Tameru's regression suite and includes deliberately adversarial examples. It is not an independent broad evaluation or a live-model answer-quality test. String retention cannot detect every semantic loss, and extractive output has a source-line size floor. Evaluate your workload and required evidence before choosing a compression budget.
