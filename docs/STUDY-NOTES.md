# Comparative Architecture Study — 2026-08-24 (v0.6.0 → v0.7.0 candidates)

Four repos studied hands-on. Verdicts: what to adopt, what to skip, and why.

## 1. leanctx (⭐317, LLMLingua-2 production wrapper)

**Adopt — A: Old-error purge.** Failed tool calls are useful for ~4 turns,
then dead weight. Replace content of errored messages older than N turns with
`[errored output purged for compaction]` — the *fact* of the error survives,
the bulk doesn't. Fits our block model perfectly: a `trust_risk`-adjacent flag
on error blocks with a turn counter.

**Adopt — B: Structural verbatim invariant.** Content containing fenced code
blocks or tracebacks must survive byte-for-byte — "a coding agent must see
exact tokens". We protect traces in scoring but do not enforce verbatim
survival through the JSON-crush preprocessor. Worth a hard invariant.

**Adopt — C: Structural-integrity invariants as test schema.** Their bench
declares explicit invariants per workload (e.g. "tool_use_id unchanged",
"code fence intact"). Our battery checks gold strings; adding structural
invariants (JSON still parses, fences balanced) would harden the crush paths.

**Skip:** their LLMLingua-2 core (model-based; violates our zero-dep contract)
and loss-tolerance routing classes (our trust-risk + fail-open already covers).

## 2. twotrim (⭐31, LongLLMLingua-inspired middleware)

**Adopt — Lost-in-the-Middle reordering.** Keep best sentence at FRONT,
second-best at END, remainder chronological. LLMs attend hardest to window
edges. We keep head/tail blocks but never reorder within the kept set.
Cheap, deterministic, no deps — directly applicable to `_render`.

**Skip:** sentence-transformer semantic scoring (deps + latency), proxy-server
packaging (out of scope).

## 3. clipforge-PAKT (lossless-first structural compression)

**Adopt — A: Pre-compression inspect gate.** `pakt_inspect` tells you whether
a payload is worth compressing BEFORE committing. They honestly document that
small nested configs EXPAND +25% and prose passes through unchanged. Our cost
gate catches this after compression; a cheap pre-check (repetition ratio,
nesting depth) could skip work entirely and avoid pathological cases.

**Adopt — B: Pipe-aligned dictionary form for repetitive records.**
`users [2]{name|role}: Alice|$a Bob|$a` — column-dictionary encoding for
repeated keys. 27–57% savings LOSSLESS on tabular data. This is a genuinely
different lever than ours (we drop rows; they shrink syntax). Could be a
preprocess stage for wide CSV/repetitive JSON before our extractive pass.
Measured model-comprehension parity (36/36 vs 35/36 on raw JSON).

**Skip:** full PAKT format (big surface area, TS core); we'd take only the
repetitive-record encoder if we take it at all.

## 4. post_compact_reminder (⭐54)

**Adopt — Compaction-amnesia hook pattern.** After ANY compaction event,
inject a one-line reminder to re-read project rules (AGENTS.md). The failure
is real (post-compaction rule amnesia) and Hermes has the same shape: after
Tameru prunes, the agent may forget skill constraints. A tiny post-compaction
footer ("[N blocks compacted; re-check AGENTS.md/skills if behaviour drifts]")
costs ~20 tokens. Candidate for the Hermes engine wrapper, not the library.

**Skip:** Claude Code hook plumbing itself.

## Priority ranking for v0.7.0

1. **Old-error purge** (leanctx) — small, safe, big win on long agent sessions
2. **Lost-in-the-middle reorder** (twotrim) — ~15 lines in _render, deterministic
3. **Structural verbatim invariant + tests** (leanctx) — correctness hardening
4. **Inspect gate** (PAKT) — cheap pre-check, avoids expansion pathologies
5. **Record-dictionary encoder** (PAKT) — bigger lift, new preprocess layer;
   only for wide CSV/repetitive JSON, behind a flag
6. **Compaction-amnesia footer** (pcr) — Hermes wrapper, not library

All six preserve the contract: local, deterministic, stdlib-only, fail-open.
