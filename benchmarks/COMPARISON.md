# Benchmark comparisons — results, methods and trade-offs

The offline [production battery](production-qa-v3-results.json) passes 15/15
on **v1.4.1**. The budget sweep is clean at all five tested ratios.
The comparison tables below retain their original **v1.2.0/v1.3.0** results;
external arms were not rerun for v1.4.1.

"Gold retention" means required answer strings present in compressed output.
"Forbidden strings" are planted stale, excluded or distracting source strings.
These checks measure evidence retention, not downstream agent accuracy or a
general defence against prompt injection. Savings and timings use the methods
specified for each run; the current battery reports estimated tokens and CPU
time, while the six-arm comparison reports characters and wall time.

## Head-to-head (same 17-case holdout, Aug 2026)

This is the earlier reported v1.2.0 holdout. The baseline labels and approximate
latency/cost figures describe that historical setup, not current product
capabilities or pricing. A per-case raw result file for this table is not
included here; the six-arm run below has inspectable raw results.

| Metric | **Tameru v1.2.0** | BM25 / Vector RAG Baseline | LLM summarise | LCM |
|---|---|---|---|---|
| Gold retention | **17/17** | 12/17 | 7/17 | 3–7/17 |
| Regression rate (right→wrong flips) | **0.0%** | ~8% | ~40% | n/a |
| Observed latency | **4–956 ms by workload; <1.2 s at 500 KB** | ~400 ms | ~2,000 ms | ~0 ms |
| Cost per call | **$0** | $0.02–0.05 | $$ | $0 |
| Deterministic | ✅ byte-identical | ❌ | ❌ | partial |
| Runs fully local | ✅ | ❌ (Vercel API; context leaves box) | varies | ✅ |
| Reversibility | citations + CCR store | CCR markers (strip on store failure) | none | none |
| Fail-open contract | original text on weak signal | collapsed view | hallucination risk | n/a |

## Six arms, one corpus (Sep 2026, `jev-1.13.0`)

Measured on the historical 12-case QA corpus via `benchmarks/jev_comparison.py`.
The [raw results](jev-comparison-results.json) contain per-case retention,
forbidden-string counts, character savings, wall time and repeat-output checks.
JEV runs through LCC's `compact_context` client (typed `noul`
keep-probability questions to System One, the same protocol
`fast-jev-compaction` uses); Laya is its local decision-model backend
(`convaiinnovations/laya-multilingual`, CPU); headroom is its Rust
`TextCrusher` (extractive BM25, `headroom-ai` 0.38.0); tfidf is a stdlib
paragraph-retrieval baseline. The JEV arm skipped the 4,000-block perf
case (API cost); Laya ran it — 3,379 s (~56 min) on CPU.

There are **14 required answer strings across 11 cases**. The large synthetic
case contains no required strings, so its `0/0` answer check passes without
testing answer retention. The case-pass row below includes that case for the
five arms that ran it. JEV's 11 cases cover all 14 required strings.

| Metric | **Tameru v1.3.0** | lcc → JEV | lcc → Laya (local) | lcc mechanical | headroom TextCrusher | TF-IDF baseline |
|---|---|---|---|---|---|---|
| Required answer strings kept | **14/14** | 14/14 † | 14/14 | 14/14 | 11/14 | 13/14 |
| Cases passing answer-string check | **12/12** | 11/11 † | 12/12 | 12/12 | 10/12 | 11/12 |
| Forbidden distractors kept | **0** | **5** | 5 | 5 | 4 | 5 |
| Deterministic | ✅ byte-identical | ❌ (output varied) | ✅ | ✅ | ✅ | ✅ |
| Median latency | **10.75 ms** | 591 ms † | 8,675 ms | 4.5 ms | 0.5 ms | <1 ms |
| Mean character savings | **81.0%** | 63.6% | 10.7% | 48.4% | 49.6% | 55.2% |
| Structured dumps (git/npm/yaml) | 30–95% saved | 0–12% | 0% | 0% | 49–56% | 0–61% |
| Cost per call | **$0** | API-priced input | $0 | $0 | $0 | $0 |
| Runs fully local | ✅ | ❌ (context leaves box) | ✅ | ✅ | ✅ | ✅ |
| `EXCLUDED-HOST` kept in excluded-sample case | **No** | Yes | Yes | Yes | Yes | Yes |

### What the arms actually showed

- **Keeping the answer is only one check.** JEV, Laya and mechanical also
  kept all 14 required strings, but each kept five forbidden strings.
  The planted cases include a superseded timeout, obsolete runbook,
  glossary decoy, excluded dependency and explicitly untrusted host sample.
  Tameru's trust, supersession and exclusion heuristics removed these in
  this corpus. That result does not establish universal containment.
- **Faster methods exist.** Mechanical, TextCrusher and TF-IDF had lower
  median wall times. Tameru combined a 10.75 ms median with the highest
  mean character savings and zero forbidden-string leaks in this run.
- **The structured-output case is revealing.** On `git_log`, Tameru kept
  the required commit hash with 95.38% character savings. JEV, Laya and
  mechanical kept the hash with 0% savings; TextCrusher saved 49.89% but
  dropped the hash. This tests TextCrusher directly, not Headroom's full
  content router or its other compressors.
- **The local model had a CPU trade-off.** Laya averaged 10.7% savings with
  an 8,675 ms median and took approximately 56 minutes on the large case.
  Hardware, model configuration and workload affect those timings.
- **Repeatability varied.** JEV's Japanese case differed between identical
  runs. The other five arms produced identical outputs in their repeat
  checks. This matters when an integration expects stable retained text.

† JEV ran 11 cases; `large_doc_perf` was skipped for API cost.
The current comparison runner uses the expanded 15-case battery and skips
the expensive large case for both JEV and Laya. Rerunning it therefore
produces a new corpus/run, not an exact replay of the historical JSON.
See the [research digest](../docs/RESEARCH.md) for ecosystem and paper links.

## Earlier regression probes

These probes motivated specific guards; they are not claims about every
current implementation of a retrieval or summarisation system.

- **Baseline RAG JSON cliff**: arrays >12 items keep only first 3 → gold at
  index 61 vanishes. Tameru crushes JSON with tail protection; battery case
  `weather_query_does_not_delete_json_tail` locks this.
- **Baseline RAG unrelated-query deletion**: generic queries deleted 99% of
  context in one probe. Tameru's saturation guard falls back to ranked-top keep.
- **CJK fail-open**: Baseline RAG refuses JP/KO without query overlap.
  Tameru tokenises Kana/Hangul/CJK/Arabic/Thai; i18n battery cases green.
- **Summariser fact loss**: LLM summaries drop config keys. The Hermes adapter
  historically used a `query_facts_lost` guard. That helper remains a
  deprecated transcript compatibility API; the maintained Hermes plugin
  has its own host-specific checks.

## Where Tameru honestly loses

- **Pure semantic paraphrase distractors** ("Operation Moonlight" ≡ "lunar
  warehouse", no shared tokens): lexical scoring can miss these. Mitigation is
  the bridge-entity graph closure + counterfactual guard; full fix needs an
  embedding/perplexity cross-check (future opt-in tier).
- **Abstractive compression**: extractive keeps verbatim lines, so minimum
  size ≈ sum of kept lines. For aggressive 10:1 prose summarisation a model wins.
- **Non-Latin savings %**: Tameru uses estimated token counts rather than a
  model-specific tokenizer. Savings can differ by script and actual model.

## Research grounding

Design choices track published results:

- **LongLLMLingua (ACL 2024)**: question-aware coarse-to-fine beats
  question-blind pruning — Tameru's core selector.
- **Lost in the Middle**: position bias — head/tail anchors + neighbour stitch.
- **NoLiMa (2025)**: lexical-distractor stress case — P0 fixed via counterfactual
  ambiguity guard (v0.5.18).
- **ARC-style addressing**: reversible citations by content hash.
- **Rate-distortion view**: recency ramp + novelty floor = H(Q)-aware floors.

## Reproduce

```bash
PYTHONPATH=src python -m pytest -q  # v1.4.1: 1172 passed, 3 skipped
python benchmarks/run_battery.py    # adversarial battery + timing table (15/15)
python benchmarks/jev_comparison.py # Tameru vs JEV-provider arms
                                    # (needs lcc + TYPESAFE_API_KEY for the JEV arm)
python benchmarks/threshold_sweep.py # operating-point replay across ratios
```
