# Deep Research — Deterministic & Extractive Compaction Landscape (2026-08-24)

Scope: deterministic-path compaction systems, extractive models, and the
embedding/perplexity tier design. Sources: GitHub (star-sorted search across
five query families), arXiv, engineering blogs. Every claim below is from
the linked repo's own README/benchmarks.

## The field, mapped

| System | Path | Deterministic? | Semantic paraphrase? | Key mechanism adopted |
|---|---|---|---|---|
| **Tameru** (ours) | extractive block selection | ✅ byte-exact | ❌ (this doc) | query-aware floor + supersession + closure BFS |
| **zettel-compress** ⭐small | zettel memory + BM25 recall | ✅ "byte-identical" | synonym expansion only | **BM25+synonym+date-proximity recall**; LoCoMo 41.6 F1 zero-model |
| **agent-knowledge** | claims/compiled-truth memory | ✅ | ❌ ("zero vector dependencies") | **96.6% R@5 LongMemEval-S with BM25+KG+RRF only** |
| **ogham** (Rust) | 6 content-type compressors + CCR | ✅ fail-closed | optional server embeds | degradation cascade compress→summarize→drop; derived from Headroom |
| **distill** (Go) ⭐ | dedup→extract→decay | ✅ ~12ms | via pre-computed embeddings or OpenAI | **hierarchical decay** full→summary→keywords→evict |
| **NTK** (Rust) | 4-layer tool-output pipeline | L1/L2 ✅, L3 neural opt-in | L3 via Ollama/Phi-3 | **YAML rule engine with `preserve_errors` invariant** — rules that would lose error signal auto-drop |
| **caveman-compression** ⭐1014 | grammar-strip semantic compression | NLP path ✅ <100ms | no | MLM predictability tier: remove top-k most *predictable* tokens (RoBERTa), 3-tier ladder NLP→MLM→LLM |
| **ReFind** (arXiv 2608.12888) | agent-controlled BM25 search over raw logs | index ✅ | no structure at all | beats graph/tree memory systems (58.2 vs 53.2 mean acc) with zero structure — validates our minimal-structure bet |

## Key findings

1. **Our positioning is validated by the strongest new evidence.** ReFind
   (arXiv, Aug 2026): agent-controlled lexical search over raw history
   beats HippoRAG 2 and other structured-memory systems on precise
   retrieval. Structure-before-query loses to retrieval-at-query-time.
   Tameru's philosophy (keep raw blocks, select per query) is the same bet.

2. **The paraphrase gap has a standard, boring fix: hybrid fusion.**
   agent-memory-challenge (leaderboard submission): BM25 + frozen
   `bge-small-en-v1.5` (33M params, CPU) fused by weighted RRF. Fully
   deterministic, zero network, `EMBED_ENABLED=false` runs pure-BM25 with
   no code change. zettel-compress measured GloVe-blend spike at only
   +0.4 points on LoCoMo — embeddings help most exactly where we're weak:
   *distractor discrimination*, not gold recall.

3. **Hard-negative fine-tuning is the multiplier.** adaptmem: raw MiniLM
   R@5 0.965 → **0.995 after one epoch of contrastive FT on mined hard
   negatives**, CPU, single epoch, 90MB encoder. This is how the semantic
   tier gets *domain-tuned to our distractor cases* rather than generic.

4. **Cross-encoders are for rerank, not first pass.** MiniLM-L6-v2 CE
   scores ~20 pairs in ~33ms. Perfect shape for our need: rerank the top-N
   ambiguous candidates only when the CFA guard fires — not every block.

5. **Predictability-aware removal is a distinct axis.** caveman's MLM tier
   removes tokens a RoBERTa finds *predictable* (grammar/filler) — keeps
   facts. Orthogonal to our block-level selection; would be a v0.9
   sentence-level polish, not now.

6. **Rule engines need an error-preservation invariant.** NTK's RFC-0001:
   any transform that would lose error signal is dropped at runtime,
   worst-case pass-through. Same spirit as our trust-risk filter; worth
   adopting as a formal invariant name in docs.

## Design: Tameru semantic tier (v0.8.0)

Principles: **opt-in, local-only, graceful fallback, never breaks the
zero-dep contract, deterministic given a pinned model.**

```
compress_context(text, query, semantic_tier=None)
                     │
                     ├─ None (default): pure lexical, byte-deterministic, zero deps
                     │
                     └─ SemanticTier object:
                          encode(block_texts) → vectors      # bge-small / MiniLM, CPU
                          cross_scores(query, texts) → floats # optional CE rerank
```

Integration points (all behind `if semantic_tier is not None`):
1. **CFA upgrade** — `_counterfactual_overlap_ambiguity`: when the lexical
   chain check is inconclusive but candidates exist, score
   cos(query, dropped_block) vs cos(query, winner). Ambiguous iff
   margin < ε (default 0.05). This is the Operation-Moonlight kill shot.
2. **Bridge rescue** — `_graph_path_closure`: admit semantic neighbours of
   kept seeds into the candidate budget (cos ≥ τ_bridge, default 0.55).
3. **CE rerank** — optional second stage on ≤32 candidates when CFA fired.

Fallback contract: any exception in the tier → log once, set
`semantic_available=False`, continue lexical. Battery must pass identically
with tier disabled (regression gate).
