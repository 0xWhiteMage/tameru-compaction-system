# Research digest — compaction systems, papers, and what Tameru takes from them

Continuously-updated study notes. Sources are grouped by kind; each entry lists
what it does and what maps onto Tameru's deterministic, extractive, local-first
design. For measured head-to-head numbers see `benchmarks/COMPARISON.md`.

## Ecosystem repos

### Direct JEV users (TypeSafe System One)

| Repo | What it does | What we took / could take |
|---|---|---|
| `lucasmartins-ai/lcc` | Local Context Compiler. JEV `noul` keep-probability per block; `mechanical` lexical fallback; `laya` local decision model. Rich internals beyond its README: typed **context graph** (`SUPPORTS/QUALIFIES/CONTRADICTS/SUPERSEDES/DEPENDS_ON/DUPLICATES/DERIVED_FROM`) with `closure(kept)` pull-in; post-drop **sufficiency verification** ("was a dependency link severed?" → names missing evidence → restore); independent **tri-state semantic verifier** (PASS/REVIEW/FAIL, fail-closed→REVIEW); **four-axis block assessment** (relevance ≠ necessity ≠ dependency-risk ≠ semantic-risk); type-aware **safe trimming** (refuses to trim when the cut would straddle a qualifier/negation cue or break JSON/YAML/code structure); conservative boilerplate cleaner (whole-line matches only). | Benchmarked (see COMPARISON.md). Candidate imports: graph-closure rescue, sufficiency restore pass, qualifier-aware trim refusal, 4-axis receipt vocabulary. |
| `tamaratran/fast-jev-compaction` + ~20 forks | The original JEV compaction hook (Claude Code): two-question protocol (keep-call / keep-result), preserve first + recent messages, `minReductionRatio`, degrade to local path on API failure. | Already ported: `pin_recent`, `min_savings_ratio`, `degraded_view`, `strategy="auto"` (v1.2.1). |
| `Waxmell114514/jev-compaction` | Score-only compactor, runs offline: frozen append-only prefix + work area; dropped segments move to a store with an `[[elided id=…]]` pointer; `expand()` returns original bytes. **Decision log + threshold replay**: replay the shadow log at different thresholds and count "still missed" = how often the agent had to call `expand()` — ground truth for tuning the threshold without re-running the agent. | Convergent design with Tameru's CCR + `[CC-Retrieve:]`. **Importable**: threshold-replay tuning over `log_dir` receipts — measure "agent came back for it" as a calibration signal for `min_savings_ratio`/floor. |
| `kerpopule/hermes-jev-skills` (682★) | JEV routing, memory filtering, turn selection for Hermes agents. | Evidence JEV is being used as a *router/judge* everywhere — supports keeping JEV optional, not default. |
| `yoza10635/dsh-argp` | "LLM proposes, deterministic guards dispose": pure-predicate guard rejects proposed drops missing high-signal tokens; 0-LLM reference-graph prune (reverse-topological drop of in-degree-0 atoms); retention budget `compressible × ratio` (fixed overhead excluded); append-only log as source of truth; `recall_detail` paginated recall. | Ported: compressible-subset budgeting, `list_ccr`, paginated `retrieve` (v1.2.1). |
| `yangyu666/dsh-jev-prune` | Two-axis intersection gating (still-needed × did-mutate-state); relative quantiles degrading to a stricter absolute floor on small populations — never silently; `neverCompactTools` write-tool exclusion; deterministic receipts; fencing tokens. | Ported: `receipt["selection"]` path transparency. |
| `wjw66/dsh-jev-pre-compaction` | Lookahead pressure band (act at 70–80%, not at the cliff); secrets scanned before archiving; dedup by callId keeping newest. | Ported: secrets screen before CCR write. |
| `anneheartrecord/claude-code-docs` teardown | Three-tier progressive ladder (microcompact → session memory → full summary); evict stale tool results when re-run (`read→edit→read` makes first read dead); circuit breaker after 3 consecutive failures; compaction agent can't trigger compaction; transcript backup before replace. | Ported: recursion guard, `strategy="auto"` ladder. |

### Non-JEV compaction systems

| Repo | What it does | Relevance |
|---|---|---|
| `headroomlabs-ai/headroom` (`headroom-ai` on PyPI) | **Closest production analog.** Local extractive middleware: `CacheAligner → ContentRouter → {SmartCrusher (JSON), TextCrusher (BM25 extractive), CodeCompressor (AST), LogCompressor, SearchCompressor, DiffCompressor} → CCR` (reversible cache + retrieve). Rust core (`headroom._core`) + Python mirror with parity tests; MCP tools `headroom_compress/retrieve/stats`; cross-agent memory store; `headroom learn` mines failed sessions into CLAUDE.md corrections; CJK-aware ICU segmentation + CJK-priced token estimation (~1.5 chars/token vs 4.0 Latin). | Benchmark arm (`headroom` in jev_comparison). **Imports worth making**: (a) CJK-aware token estimate — our `_approx_tokens` divides chars/4, which under-counts CJK ~4–6× (they hit the same bug: headroom PR a35fe86); (b) per-content-type specialized crushers beyond our format adapters; (c) Rust/Python parity-test methodology if a native port ever ships; (d) `learn` feedback loop ≈ our `log_dir` tuning hook. |
| `codexstar69/pi-lcm` | SQLite+FTS5 memory; hierarchical DAG summaries (logarithmic depth); agent self-serve tools `lcm_grep/describe/expand`; static-prefix cache discipline. | Ported: CCR recall tooling. DAG-of-pointers is a possible CCR evolution (hierarchical originals). |
| `tianjianl/selfcompact` | Research scaffold: model invokes a compaction tool itself, gated by a four-question rubric — **C1 closed-unit** (not mid-derivation), **C2 summarizable**, **C3 progress since last compaction**, **N1 not-stuck** (stuck ⇒ diagnose, don't summarize). Probes reuse the KV prefix. +18.1pts math vs no-summarization at 30–70% lower cost. | Rubric is implementable as a deterministic gate in `tameru.transcript`: suppress compaction when the trajectory is mid-task / no-progress / stuck-looping. "Compaction at unit boundaries" is a real result, not a guess. |
| `microsoft/LLMLingua` family | Token-level extractive compression via LM perplexity/entropy. | Academic baseline; see papers below. |

## Papers

| Paper | Core idea | Takeaway for Tameru |
|---|---|---|
| **Context Rot** (Chroma technical report, Jul 2025) | 18 frontier models degrade as input grows — even on trivial tasks; distractors compound; low needle-question similarity degrades faster; shuffled haystacks paradoxically beat coherent ones. | The empirical reason this project exists. Validates: aggressive-but-safe compaction, distractor-heavy test cases (our `forbid` strings), and low-similarity needles in the corpus. |
| **LLMLingua-2** (ACL 2024) | Compression as **token classification** (preserve/discard) trained on GPT-4-distilled labels; extractive by construction; 3–6× faster than entropy methods. | Same family as our per-block keep/drop — validates the formulation; their training-data trick is the sanctioned way to add a learned tier later. |
| **Provence** (2025) | Sentence-level pruning = binary sequence labeling; **unifies pruning with reranking** so the pruner is free in a RAG pipeline; can output **0 sentences** ("nothing is relevant" is a legal answer). | Two takeaways: (a) ranking and pruning are one operation — our scorer already does both; (b) an explicit "nothing admissible" verdict is principled — maps to our fail-open/empty outcome. |
| **Lost in Compression** (audit, 2026) | Controlled cross-lingual audit of extractive compressors: English-tuned pruners collapse on CJK/non-English; only multilingual-supervised XProvence closes the gap; Headroom needed a dedicated CJK lane. | We already handle Japanese (jp_musubi case) — but this argues for (i) more CJK/multilingual cases in the battery, (ii) the CJK token-pricing fix, (iii) never assuming whitespace tokenization. |
| **ACON** (Oct 2025) | Agent Context Optimization: compress observations **and** interaction history with task-specific *guidelines*; optimize guidelines from failure pairs; distill the LLM compressor into a small model (>95% retention). | Validates per-content-type adapters (= "guidelines" made deterministic) and the distilled-small-model direction — the same bet as Laya. |
| **PAACE** (Dec 2025) | Plan-aware context engineering: keep what the **next k tasks** need, not just the current question; distilled plan-aware compressors keep 97% of teacher quality. | Suggests `query` should accept a *plan list* — union of current + next-step needs — rather than a single string. Medium-term design idea. |
| **TPC** (Feb 2025) | Task-agnostic compression via a learned "task descriptor" when no explicit question exists. | Motivation for a conservative *derived-objective* path when `query` is empty — today we fail open; a descriptor could replace that with cautious ranking. Care needed: derived objectives must stay deterministic. |
| **CompactPrompt** (Oct 2025) | Self-information scoring + dependency phrase grouping for token-level pruning; n-gram abbreviation for recurrent document patterns; numeric quantization for tables. | Self-information ≈ our rare-term IDF boost (convergent). Numeric quantization is a candidate CSV/TSV adapter upgrade (lossy — would need opt-in `lossy_ok`). |
| **Compactor** (Jul 2025) | KV-cache compression via leverage scores; **context-calibrated compression**: infer the *maximum* compression a given context supports before quality loss. | Direct upgrade for `inspect_compressibility`: estimate a per-context compression ceiling rather than only flagging "compressible Y/N". |
| **SelfCompact** (2026) | See repo entry above — rubric-gated self-compaction at trajectory boundaries. | Timing is as important as content; ported into the transcript-adapter candidate list. |
| **CompactionRL** (2026) | PPO trains task-execution + summary-generation jointly across compacted rollouts (+7pts SWE-bench Verified). | Training-side, out of scope — but proof the industry treats compaction policy as learnable; keeps our deterministic layer defensible as the *verifier/floor* under any learned policy. |
| **Memory-in-Agents surveys** (Dec 2025, 2505.00675, 2404.13501) | Memory ops taxonomy: consolidation, updating, indexing, **forgetting**, retrieval, **compression** — compression is one of six ops, not the whole story. | Positions Tameru correctly: we're the compression op; CCR is indexing+retrieval; TTL sweep is forgetting; `list_ccr`/paginate complete the op set. |

## Ranked candidate upgrades — status after the second round (v1.3.0)

Shipped or verified:

1. ~~**CJK-aware token pricing**~~ — **already correct**: `estimate_tokens` uses `token_units`, which emits one unit per no-space-script char (~1 tok/char, matching cl100k 1.0–1.7 and conservative vs Qwen 0.6–0.8). The Headroom a35fe86 bug does not apply to us. Verified 2026-09-23.
2. ~~**Graph-closure rescue + sufficiency restore**~~ — **shipped** as `_dependency_closure`: rare-term shared entity + qualifier/definition cue → restore. Cap 8, never trust-risk/frozen-drop, budget-bound in fixed mode. `receipt["sufficiency_restored"]`.
3. ~~**Qualifier-aware trim refusal**~~ — **shipped** in `_crush_value` (the only emission-side cut): tails containing qualifier cues keep the value whole. `degraded_view` needed no change — it only bounds the *scoring* view; emitted spans are always full.
4. ~~**Threshold-replay tuner**~~ — **shipped** as `benchmarks/threshold_sweep.py` (budget_ratio sweep → gold/leaks/savings frontier).
5. ~~**Compaction-timing gate**~~ — **shipped** as `tameru.transcript.trajectory_gate` + `timing_gate` param on `apply_extractive_tool_prune` (pending-tool-calls / stuck-loop suppression).
6. ~~**Plan-aware multi-query**~~ — **shipped**: `compress_context(query=[...])` unions terms across planned tasks.
7. ~~**Multilingual battery expansion**~~ — **shipped**: `zh_needle` + `ar_needle` cases, battery now 15/15.

Still deferred:

8. **Numeric quantization adapter** (CompactPrompt) — lossy CSV/table crusher behind `lossy_ok`; wait for a real use-case.
9. **CCR hierarchy** (pi-lcm DAG) — chained/hierarchical originals; bigger lift.
10. **Context-calibrated ceiling** (Compactor paper) — `inspect_compressibility` could estimate a per-context max-compression bound; research-y, defer.
11. **Derived-objective path** (TPC paper) — when `query` is empty, derive a conservative task descriptor instead of failing open. Delicate: must stay deterministic and not weaken the empty-query contract. Defer.

Deliberately skipped: KV-cache methods (different layer), RL/fine-tuned compressors (breaks zero-dep determinism — revisit only as opt-in extra like `summarise`), soft-prompt/GIST methods (non-extractive, loses byte-exactness).
