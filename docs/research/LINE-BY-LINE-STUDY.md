# Line-by-Line Architecture Study — caveman-compression + NTK (2026-08-24)

Full source read: caveman (930 lines: NLP engine, MLM engine, SPEC.md,
benchmark harness) and NTK's compressor layer (`layer1_filter.rs` ~1300
lines, `spec_loader.rs`, RFC-0001 in full, fixtures).

---

## caveman-compression — mechanisms found

### C1. MLM predictability tier (`caveman_compress_mlm.py`)
Removes words where P(word|context) ≥ threshold using RoBERTa MLM probs.
Four documented thresholds with accuracy trade-offs (1e-3→16%/98%,
1e-5→32%/92%, 1e-6→54%/83%).
**Two refinements we'd want if we adopt this:**
- `no_adjacent_removal`: when two adjacent words both exceed the
  threshold, remove only the higher-probability one — prevents
  telegraphic ambiguity (their Anti-Pattern 1).
- `protect_ner`: never remove PERSON/ORG/GPE/DATE/MONEY/PERCENT/TIME/
  QUANTITY/CARDINAL/ORDINAL spans — facts are untouchable.
**Verdict:** real mechanism, but per-word forward passes = O(words)
model calls. Too slow for Tameru's hot path; belongs in a future
sentence-level "polish" strategy, opt-in like our semantic tier.
NOT adopted now — documented as roadmap.

### C2. Factual-preservation benchmark harness (`benchmark/`)
Their pattern: plant facts → compress → LLM Q&A per fact → score
preservation. Our battery does gold-string containment which is
stricter but narrower (no paraphrase QA).
**Verdict:** ADOPTED as idea — added a fact-QA mode note to the
battery docs for when we wire an LLM judge. Cheap to add later.

### C3. SPEC.md anti-patterns
Telegraphic ambiguity / over-compression / information addition as
named failure classes. Their validation algorithm: extract facts from
original and compressed, sets must be identical.
**Verdict:** our semantic-contract evaluator already implements a
stronger version (required_evidence + forbidden_distractors). No work.

## NTK — mechanisms found

### N1. Template dedup WITH COUNT + exemplar (`group_by_template`)
Normalize volatile fields (timestamps→<TS>, UUIDs, hex≥8, versions,
plain ints) to placeholders, group consecutive same-template lines,
emit `[×N] <first-line>` instead of silently dropping repeats 2+.
**Tameru gap confirmed:** our `_log_fingerprint` collapses repeats at
n≥2 SILENTLY — the count is lost. For an agent, "health check failed
2 times" vs "failed 340 times" is decision-relevant.
**ADOPTED:** count-preserving repeat collapse.

### N2. Idempotency guard (`is_already_processed_marker`)
Later-stage markers must pass through earlier stages untouched, else
re-running over-collapses (their invariant #5).
**Verdict:** applies to us the moment we emit `[×N]` markers — adopted
as part of N1 (markers contain digits, so the fingerprint normalizer
must skip marker lines).

### N3. Framework frame-run collapse with first-frame preservation
Runs of ≥3 consecutive *framework* frames collapse to first frame +
"N framework frames omitted". Classifier tables for 20+ languages.
**Tameru status:** our trace flush keeps first+last already — equivalent
for Python traces. Their multi-language classifier table is richer, but
our classify_line covers the common shapes. PARTIAL adopt: extend
trace-run detection to non-"File" indented frames (Go/Java style) —
cheap win inside preprocess_logs.

### N4. Progress-bar removal (`is_cargo_progress`, percent bars)
`Compiling crate v1.0.0` spam, `[===>] 45%` bars.
**Tameru gap confirmed:** no progress-bar stripping. Build logs carry
hundreds of these.
**ADOPTED:** line-match delete for progress bars.

### N5. Prefix/suffix factoring with cost check
If ≥80% of consecutive lines share a ≥8-char prefix AND saving beats
overhead → emit prefix once + stripped suffixes. They compute whether
the saving actually pays.
**Verdict:** real but niche for us (mostly hits cargo/npm output).
Deferred — record in STUDY-NOTES as available pattern.

### N6. Invariants as executable contract (`preserve_errors` etc.)
Rules declare invariants; runtime post-hoc regex-scans input vs output
and REJECTS a rule's output if error signal was dropped. This makes
community-contributed rules safe.
**Verdict:** STRONG idea, matches our fail-open philosophy. ADOPTED:
post-hoc error-signal check on our log preprocessing — if a transform
would drop every error line, keep them (never lose error signal).

### N7. Intent scope (`preserve_on: [debug_stack]`)
Rules can declare intents under which they must NOT fire. Query-shaped
compression gating.
**Verdict:** we already have this implicitly (query-aware everything;
trust-query regex). No new work.

### N8. YAML rule files as data (RFC-0001)
ESLint-for-context-garbage. Four primitives cover all their rules.
**Verdict:** beautiful design, wrong time for us — our rules live in
Python tests with full CI. Revisit if community contributions ever
become a goal. NOT adopted.

## Gap matrix vs Tameru v0.8.0

| Mechanism | Tameru before | Action |
|---|---|---|
| Count-preserving dedup | silent drop | ✅ ADOPT (N1+N2) |
| Progress-bar strip | none | ✅ ADOPT (N4) |
| Error-signal post-hoc invariant | implicit only | ✅ ADOPT (N6) |
| Go/Java-style frame runs | partial | ✅ ADOPT (N3-lite) |
| MLM predictability polish | none | documented, deferred (C1) |
| Fact-QA benchmark mode | containment only | noted (C2) |
| Prefix factor | none | deferred (N5) |
| YAML rule engine | n/a | declined (N8) |
