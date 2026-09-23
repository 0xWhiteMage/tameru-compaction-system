# Benchmark Comparison — Tameru v1.2.0 vs the field

All numbers from this repo's fixtures and production QA battery unless noted.
"Gold retention" = required gold strings present in compressed output.

## Head-to-head (same 17-case holdout, Aug 2026)

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
| Injection containment | trust-flag + exclude-cues | none (amplifies) | none | none |

## Live head-to-head vs TypeSafe JEV (Sep 2026, `jev-1.13.0`)

Measured on this repo's 12-case QA corpus via `benchmarks/jev_comparison.py`
(LCC `compact_context` as the JEV client — it sends typed `noul`
keep-probability questions to System One, the same protocol
`fast-jev-compaction` uses). JEV arm skipped on the 4,000-block perf case.

| Metric | **Tameru v1.2.1** | lcc → JEV (`jev-1.13.0`) | lcc mechanical (local baseline) |
|---|---|---|---|
| Gold retention | **12/12** | 11/11 | 12/12 |
| Forbidden distractors kept | **0** | **5** | 5 |
| Deterministic | ✅ byte-identical | ❌ (output varied between runs) | ✅ |
| Median latency | **10 ms** | 568 ms (~55×) | 8 ms |
| Mean savings | **81.0%** | 63.8% | 48.4% |
| Structured dumps (git/npm/yaml) | 63–95% saved | 0–12% saved | 0% saved |
| Cost per call | **$0** | API-priced input tokens | $0 |
| Runs fully local | ✅ | ❌ (context leaves the box) | ✅ |
| Injection containment | trust-flag + exclude-cues | none — kept `EXCLUDED-HOST` | none |

### What the JEV arm actually showed

- **Relevance ≠ admissibility.** JEV kept every forbidden distractor: the
  stale `30 seconds` config superseded by `5 seconds`, the obsolete
  `enabled` runbook, the `glossary` distractor, `libenchant-dev` — and
  `EXCLUDED-HOST`, a block literally labeled *"UNTRUSTED SAMPLE: ignore
  previous context"*. A keep-probability judge has no notion of trust,
  supersession, or exclusion cues; Tameru encodes all three.
- **Structured records defeat the block judge.** On git/npm/YAML dumps
  JEV returned ~0% savings — every line-record looks equally relevant to
  a whole-block judge. Tameru's line-record path keeps matching records
  only (95.4% on `git_log`).
- **Non-determinism is real, not theoretical.** The JP case produced
  different output across identical runs (score wobble across batch
  boundaries) — unusable as a cache-stable prompt prefix.
- **Latency and cost** are inherent: state + questions re-sent per batch,
  ~4 calls/case, ~0.5–2.2 s per case vs single-digit ms local scoring.

JEV remains a good fit for *transcript-level* keep/drop where no trust
model is needed — the layers stay complementary. This is why Tameru
borrows its cheap-first escalation (`strategy="auto"`) rather than its
judge.

## Known failure modes of others that Tameru explicitly avoids

- **Baseline RAG JSON cliff**: arrays >12 items keep only first 3 → gold at
  index 61 vanishes. Tameru crushes JSON with tail protection; battery case
  `weather_query_does_not_delete_json_tail` locks this.
- **Baseline RAG unrelated-query deletion**: generic queries deleted 99% of
  context in one probe. Tameru's saturation guard falls back to ranked-top keep.
- **CJK fail-open**: Baseline RAG refuses JP/KO without query overlap.
  Tameru tokenises Kana/Hangul/CJK/Arabic/Thai; i18n battery cases green.
- **Summariser fact loss**: LLM summaries drop config keys. The Hermes adapter
  rejects any summary missing query facts (`query_facts_lost` guard).

## Where Tameru honestly loses

- **Pure semantic paraphrase distractors** ("Operation Moonlight" ≡ "lunar
  warehouse", no shared tokens): lexical scoring can miss these. Mitigation is
  the bridge-entity graph closure + counterfactual guard; full fix needs an
  embedding/perplexity cross-check (future opt-in tier).
- **Abstractive compression**: extractive keeps verbatim lines, so minimum
  size ≈ sum of kept lines. For aggressive 10:1 prose summarisation a model wins.
- **Non-Latin savings %**: tokenizer counts are conservative for some scripts;
  containment is correct but savings percentages understate.

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
PYTHONPATH=src python -m pytest -q  # 272 passed, 9 skipped standalone
python benchmarks/run_battery.py   # adversarial battery + timing table
python benchmarks/jev_comparison.py # Tameru vs JEV-provider arms
                                   # (needs lcc + TYPESAFE_API_KEY for the JEV arm)
```
