# Benchmark Comparison — Tameru v0.6.0 vs the field

All numbers from this repo's fixtures and production QA battery unless noted.
"Gold retention" = required gold strings present in compressed output.

## Head-to-head (same 17-case holdout, Aug 2026)

| Metric | **Tameru v0.6.0** | SuperCompress (hosted) | LLM summarise | LCM |
|---|---|---|---|---|
| Gold retention | **17/17** | 12/17 | 7/17 | 3–7/17 |
| Regression rate (right→wrong flips) | **0.0%** | ~8% | ~40% | n/a |
| Median latency | **~5 ms** | ~400 ms | ~2,000 ms | ~0 ms |
| Cost per call | **$0** | $0.02–0.05 | $$ | $0 |
| Deterministic | ✅ byte-identical | ❌ | ❌ | partial |
| Runs fully local | ✅ | ❌ (Vercel API; context leaves box) | varies | ✅ |
| Reversibility | citations + CCR store | CCR markers (strip on store failure) | none | none |
| Fail-open contract | original text on weak signal | collapsed view | hallucination risk | n/a |
| Injection containment | trust-flag + exclude-cues | none (amplifies) | none | none |

## Known failure modes of others that Tameru explicitly avoids

- **SuperCompress JSON cliff**: arrays >12 items keep only first 3 → gold at
  index 61 vanishes. Tameru crushes JSON with tail protection; battery case
  `weather_query_does_not_delete_json_tail` locks this.
- **SuperCompress unrelated-query deletion**: generic queries deleted 99% of
  context in one probe. Tameru's saturation guard falls back to ranked-top keep.
- **CJK fail-open**: SuperCompress refuses JP/KO without query overlap.
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
pytest tests/ -q          # 121 passed, 5 skipped (Hermes-specific)
python benchmarks/run_battery.py   # adversarial battery + timing table
```
