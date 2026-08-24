# Adjacent-Family Red Team — learning from non-extractive compaction (2026-08-25)

Families studied code-first this pass: **KV-cache eviction** (KVzip,
NeurIPS'25 Oral), **agent memory layers** (memorix, ⭐682), and the
**NAACL'25 prompt-compression survey taxonomy** (hard/soft, filtering/
paraphrasing/gist/embedding families) as the completeness checklist.

---

## What each family does differently from us

### KVzip (KV-cache eviction)
Compresses the *attention cache*, not text. Its transferable ideas:

1. **Context-reconstruction scoring** — score every token's importance by
   asking "can the model reconstruct this chunk given everything else?"
   Attention mass during a reconstruction task IS the importance signal.
2. **Query-agnostic compression** — compress once, serve many queries
   (3–4× cache reduction, 2× latency win). They explicitly optimise for
   the multi-query case; we re-score per query.
3. **Sink tokens** — system-prompt tokens are never evicted (protected
   prefix), separate from content scoring.
4. **Head-level precomputed scores** — a context-independent fallback
   (ratio 0.6) when runtime scoring is too expensive: precompute once,
   reuse everywhere.

### memorix (agent memory layer)
1. **Compaction checkpoints** — every compaction event is recorded as a
   queryable row (reason, tokens_before, first_kept_entry_id, status).
   Compaction becomes *auditable infrastructure*, not a side effect.
2. **Bounded context receipts** — schema-versioned machine-readable summary
   of what context was assembled and why (`schemaVersion: '1'`).
3. **Freshness gating** — semantic indexes carry explicit freshness state;
   stale indexes are refused, not silently used.

### Survey taxonomy (completeness check against all of hard+soft)
Hard/filtering ✅ (us), hard/paraphrasing ❌, soft/gist ❌, soft/embedding ❌
(we have an opt-in bi-encoder tier but no soft-token path). RL-enhanced
selection (TACO-RL) ❌. The survey's own future-directions list: hybrid
hard+soft, encoder optimisation, multimodality.

---

## Red-team gap register (Tameru v0.9.0 vs these)

| # | Gap | Source | Severity | Verdict |
|---|---|---|---|---|
| G1 | **No compaction event log** — our CompressResult is returned but never persisted; no way to audit what was dropped last week | memorix | MED-HIGH | **ADOPT** |
| G2 | **No sink/pinned region** — head/tail are heuristics inside scoring; a caller cannot declare "never drop lines matching X" (e.g., an AGENTS.md excerpt embedded mid-dump) | KVzip sinks + memorix policies | MED | **ADOPT** |
| G3 | **No reconstruction-based self-test** — we verify entity recall lexically; KVzip's "can the content be reconstructed?" is stronger. Cheap proxy: after compression, ask the local Qwen one binary question per dropped high-score block ("is the answer to `<query>` present?") only when risk=high | KVzip | MED | **ADAPT (opt-in, gated)** |
| G4 | **Per-query rescoring cost** on repeated identical contexts (multi-turn same dump) — KVzip's query-agnostic lesson says: cache selection by context fingerprint | KVzip | LOW-MED | Partially exists (decision_cache); **document + test it** |
| G5 | **No receipt artifact** — callers get CompressResult fields but no versioned machine-readable provenance block they can store alongside the compacted view | memorix | LOW-MED | **ADOPT** (cheap: serialise verifier+kept_ids+policy as `receipt`) |
| G6 | Soft-token / gist path | survey | LOW | **REJECT for now** — breaks model-agnostic contract |
| G7 | RL-optimised keep/drop policy | survey (TACO-RL) | LOW | **DEFER** — needs training infra + risks determinism |

## Adopted plan (this pass)

- **G1**: `compaction_log` — append-only JSONL next to CCR store; one line per
  compression: ts, query-hash, policy, kept/total, savings, risk, top_dropped.
  Opt-in via `log_dir` param; default off (light contract).
- **G2**: `pin_patterns` parameter — list of regexes; matching blocks are
  exempt from dropping in every selector path (sink semantics).
- **G5**: `result.receipt` — dict {schema_version, policy, kept_ids, dropped_ids,
  verifier, query_hash, engine_version}. Pure function of existing data.
- **G3**: documented as future opt-in (needs local model call in the loop;
  conflicts with fast/light until gated properly behind `verify_model_url`).

Not adopted: soft tokens (G6), RL policy (G7) — rejected with reasons above.
