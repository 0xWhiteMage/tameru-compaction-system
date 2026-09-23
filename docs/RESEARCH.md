# Research digest — compaction systems, papers, and what Tameru takes from them

Continuously-updated study notes. Sources are grouped by kind; each entry lists
what it does and what maps onto Tameru's deterministic, extractive, local-first
design. For measured head-to-head numbers see `benchmarks/COMPARISON.md`.

## Ecosystem repos

### Direct JEV users (TypeSafe System One)

| Repo | What it does | Relationship to Tameru |
|---|---|---|
| `lucasmartins-ai/lcc` | Local Context Compiler. JEV `noul` keep-probability per block; `mechanical` lexical fallback; `laya` local decision model. Rich internals beyond its README: typed **context graph** (`SUPPORTS/QUALIFIES/CONTRADICTS/SUPERSEDES/DEPENDS_ON/DUPLICATES/DERIVED_FROM`) with `closure(kept)` pull-in; post-drop **sufficiency verification** ("was a dependency link severed?" → names missing evidence → restore); independent **tri-state semantic verifier** (PASS/REVIEW/FAIL, fail-closed→REVIEW); **four-axis block assessment** (relevance ≠ necessity ≠ dependency-risk ≠ semantic-risk); type-aware **safe trimming** (refuses to trim when the cut would straddle a qualifier/negation cue or break JSON/YAML/code structure); conservative boilerplate cleaner (whole-line matches only). | Benchmark arm (see COMPARISON.md). Typed-edge closure, sufficiency restore, and qualifier-aware trim refusal ported in v1.3.0. Two upstream issues filed: process-wide socket guard during token counting races concurrent JEV calls; `LayaClient` model reload per call. |
| `tamaratran/fast-jev-compaction` + ~20 forks | The original JEV compaction hook (Claude Code): two-question protocol (keep-call / keep-result), preserve first + recent messages, `minReductionRatio`, degrade to local path on API failure. | Ported: `pin_recent`, `min_savings_ratio`, `degraded_view`, `strategy="auto"` (v1.2.1). |
| `Waxmell114514/jev-compaction` | Score-only compactor, runs offline: frozen append-only prefix + work area; dropped segments move to a store with an `[[elided id=…]]` pointer; `expand()` returns original bytes. **Decision log + threshold replay**: replay the shadow log at different thresholds and count "still missed" = how often the agent had to call `expand()` — ground truth for tuning without re-running the agent. | Convergent with Tameru's CCR + `[CC-Retrieve:]`. Threshold-replay ported as `benchmarks/threshold_sweep.py` (v1.3.0). |
| `kerpopule/hermes-jev-skills` (682★) | JEV routing, memory filtering, turn selection for Hermes agents. | Evidence JEV is used as a *router/judge* — supports keeping JEV optional, not default. |
| `yoza10635/dsh-argp` | "LLM proposes, deterministic guards dispose": pure-predicate guard rejects proposed drops missing high-signal tokens; 0-LLM reference-graph prune (reverse-topological drop of in-degree-0 atoms); retention budget `compressible × ratio` (fixed overhead excluded); append-only log as source of truth; `recall_detail` paginated recall. | Ported: compressible-subset budgeting, `list_ccr`, paginated `retrieve` (v1.2.1). |
| `yangyu666/dsh-jev-prune` | Two-axis intersection gating (still-needed × did-mutate-state); relative quantiles degrading to a stricter absolute floor on small populations — never silently; `neverCompactTools` write-tool exclusion; deterministic receipts; fencing tokens. | Ported: `receipt["selection"]` path transparency. |
| `wjw66/dsh-jev-pre-compaction` | Lookahead pressure band (act at 70–80%, not at the cliff); secrets scanned before archiving; dedup by callId keeping newest. | Ported: secrets screen before CCR write. |
| `anneheartrecord/claude-code-docs` teardown | Three-tier progressive ladder (microcompact → session memory → full summary); evict stale tool results when re-run (`read→edit→read` makes first read dead); circuit breaker after 3 consecutive failures; compaction agent can't trigger compaction; transcript backup before replace. | Ported: recursion guard, `strategy="auto"` ladder. |

### Non-JEV compaction systems

| Repo | What it does | Relationship to Tameru |
|---|---|---|
| `headroomlabs-ai/headroom` (`headroom-ai` on PyPI) | **Closest production analog.** Local extractive middleware: `CacheAligner → ContentRouter → {SmartCrusher (JSON), TextCrusher (BM25 extractive), CodeCompressor (AST), LogCompressor, SearchCompressor, DiffCompressor} → CCR` (reversible cache + retrieve). Rust core (`headroom._core`) + Python mirror with parity tests; MCP tools `headroom_compress/retrieve/stats`; cross-agent memory store; CJK-aware ICU segmentation + CJK-priced token estimation (~1.5 chars/token vs 4.0 Latin). | Benchmark arm (`headroom` in jev_comparison). Its CJK token-pricing fix (PR a35fe86) prompted an audit — Tameru's `token_units` already prices no-space scripts at ~1 tok/char, so the same bug does not apply. |
| `codexstar69/pi-lcm` | SQLite+FTS5 memory; hierarchical DAG summaries (logarithmic depth); agent self-serve tools `lcm_grep/describe/expand`; static-prefix cache discipline. | CCR recall tooling ported (v1.2.1). Its DAG-of-pointers hierarchy is a possible CCR evolution. |
| `tianjianl/selfcompact` | Research scaffold: model invokes a compaction tool itself, gated by a four-question rubric — **C1 closed-unit** (not mid-derivation), **C2 summarizable**, **C3 progress since last compaction**, **N1 not-stuck** (stuck ⇒ diagnose, don't summarize). Probes reuse the KV prefix. +18.1pts math vs no-summarization at 30–70% lower cost. | Rubric ported deterministically as `tameru.transcript.trajectory_gate` (v1.3.0): suppress compaction on pending tool calls and stuck loops. |
| `microsoft/LLMLingua` family | Token-level extractive compression via LM perplexity/entropy. | Academic baseline; see papers below. |

## Papers

| Paper | Core idea | Takeaway for Tameru |
|---|---|---|
| **Context Rot** (Chroma technical report, Jul 2025) | 18 frontier models degrade as input grows — even on trivial tasks; distractors compound; low needle-question similarity degrades faster; shuffled haystacks paradoxically beat coherent ones. | The empirical reason this project exists. Validates: aggressive-but-safe compaction, distractor-heavy test cases (our `forbid` strings), and low-similarity needles in the corpus. |
| **LLMLingua-2** (ACL 2024) | Compression as **token classification** (preserve/discard) trained on GPT-4-distilled labels; extractive by construction; 3–6× faster than entropy methods. | Same family as our per-block keep/drop — validates the formulation; their training-data trick is the sanctioned way to add a learned tier later. |
| **Provence** (2025) | Sentence-level pruning = binary sequence labeling; **unifies pruning with reranking** so the pruner is free in a RAG pipeline; can output **0 sentences** ("nothing is relevant" is a legal answer). | Two takeaways: (a) ranking and pruning are one operation — our scorer already does both; (b) an explicit "nothing admissible" verdict is principled — maps to our fail-open/empty outcome. |
| **Lost in Compression** (audit, 2026) | Controlled cross-lingual audit of extractive compressors: English-tuned pruners collapse on CJK/non-English; only multilingual-supervised XProvence closes the gap; Headroom needed a dedicated CJK lane. | Drove the multilingual battery expansion (`zh_needle`, `ar_needle` alongside `jp_musubi`) and confirmed `token_units` already prices CJK correctly. |
| **ACON** (Oct 2025) | Agent Context Optimization: compress observations **and** interaction history with task-specific *guidelines*; optimize guidelines from failure pairs; distill the LLM compressor into a small model (>95% retention). | Validates per-content-type adapters (= "guidelines" made deterministic) and the distilled-small-model direction — the same bet as Laya. |
| **PAACE** (Dec 2025) | Plan-aware context engineering: keep what the **next k tasks** need, not just the current question; distilled plan-aware compressors keep 97% of teacher quality. | Ported: `compress_context(query=[...])` unions terms across current + planned tasks (v1.3.0). |
| **TPC** (Feb 2025) | Task-agnostic compression via a learned "task descriptor" when no explicit question exists. | Ported deterministically as `derive_query=True` (v1.3.0): infers a conservative objective from the document's recurring rare terms; receipts mark `query_source`/`derived_terms`; no stable term structure → normal fail-open. |
| **CompactPrompt** (Oct 2025) | Self-information scoring + dependency phrase grouping for token-level pruning; n-gram abbreviation for recurrent document patterns; numeric quantization for tables. | Self-information ≈ our rare-term IDF boost (convergent). |
| **Compactor** (Jul 2025) | KV-cache compression via leverage scores; **context-calibrated compression**: infer the *maximum* compression a given context supports before quality loss. | Ported: `inspect_compressibility` now reports `guaranteed_savings_pct` + `ceiling_class` — the deterministic bound a dedupe pass removes with zero judgement (v1.3.0). |
| **SelfCompact** (2026) | See repo entry above — rubric-gated self-compaction at trajectory boundaries. | Timing is as important as content; ported into the transcript adapter (v1.3.0). |
| **CompactionRL** (2026) | PPO trains task-execution + summary-generation jointly across compacted rollouts (+7pts SWE-bench Verified). | Training-side, out of scope — but proof the industry treats compaction policy as learnable; keeps our deterministic layer defensible as the *verifier/floor* under any learned policy. |
| **Memory-in-Agents surveys** (Dec 2025, 2505.00675, 2404.13501) | Memory ops taxonomy: consolidation, updating, indexing, **forgetting**, retrieval, **compression** — compression is one of six ops, not the whole story. | Positions Tameru correctly: we're the compression op; CCR is indexing+retrieval; TTL sweep is forgetting; `list_ccr`/paginate complete the op set. |

## Standing conclusions from the study

- **Relevance ≠ admissibility.** Every keep-score arm tested (JEV probability,
  Laya decision, BM25, TF-IDF) retained planted distractors; trust,
  supersession, and exclusion semantics have to be modelled separately —
  Tameru's core thesis, now measured.
- **Local semantic judges are possible but weak.** A ~1K-param decision model
  ran fully offline yet kept ~88% of everything at ~16 s/case on CPU.
- **Whole-block judges can't do line-record granularity.** Structured logs
  need record-level selection; per-block scoring gives ~0% savings there.
- **Deterministic beats clever at the boundary cases** that matter to agents:
  byte-identical output keeps prompt caches stable and makes every decision
  replayable after the fact.
