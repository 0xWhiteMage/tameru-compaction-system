# Changelog

All notable changes to the **Tameru Compaction System** (`tameru`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] (1.4.1 candidate, local branch `locally/1.4.0-patches`)

Fixes for the two answers the 1.4.0 plugin report listed as lost, an opt-in
gap-marker change for hosts with long markers, and two small correctness items.
With default arguments (`gap_marker=None`, `inline_short_gaps=False`) output is
byte-identical to 1.4.0: `run_battery` 15/15 and `threshold_sweep`
77.3 / 68.4 / 61.2 / 41.5 / 24.9 % are unchanged.

### Added
- `compress_context(..., inline_short_gaps=False)` and `InliningGapMarker`: with a caller `gap_marker`, a dropped span whose marker would not be shorter than the span is kept verbatim (renderer and adapter cuts). Off by default.

### Changed
- pytest reduction: a `Captured log/stdout/stderr` section of more than 6 lines inside a failure block is collapsed to its first and last line (first 2 / last 2 in the first 1.4.1 cut) plus every error-fingerprint line and every WARNING/ERROR/CRITICAL/FATAL line (`[… N captured lines omitted …]` without a caller marker). Before, the whole section was kept and a long captured log made the run fail open.
- grep/rg adapter: when the query hits at least 80% of all matches (and there are more than `2 * per_file_cap`), it keeps per file the definition/assignment lines that hit, lines hitting the other query words, and distinct match texts (deduplicated across files, capped per file). Before, an all-matching `rg -n Name` kept everything and the definition line was lost in the plugin's brief.
- grep/rg adapter with a caller `gap_marker`: files whose matches are all omitted keep their `path  (N matches)` header but share one marker per consecutive run of such files, instead of one marker each. A host marker is ~100 chars, so a 25-file `rg` result spent ~2.5 KB on markers. Without a caller marker the per-file `[… N matches omitted …]` is unchanged.
- grep/rg adapter and pytest reduction honour `InliningGapMarker` (`inline_short_gaps=True`) like the renderer: an omitted run shorter than its marker is kept verbatim.
- Secrets screen also matches Google API keys (`AIza...`), Stripe live keys (`sk_live_`/`rk_live_`), bearer tokens and unquoted `KEY=value` assignments of 16+ chars.

### Fixed
- Command-line options in the query (`-n`, `--stat`, copied with the command, as the Hermes plugin does) are no longer adapter selectors. As "strong" selectors they crowded out the searched name: `rg -n Name` matched by `-n` alone selected nothing, so the saturated-query mode never ran and the plugin still fell to its brief and lost the definition line.
- A captured section ends at the next rule, test-block header or pytest section header, not at the first blank line: captured stdout with blank lines collapsed only up to its first blank line.
- Red-team round: the unquoted `KEY=value` secrets pattern flagged ordinary code (`password = get_password_from_vault()`, `api_key = agent._anthropic_api_key`, `api_key=fallback_api_key,`). On a Hermes checkout `contains_secret` was true for 141 of 2,372 non-test Python files (9 before 1.4.1), so a host that refuses to keep secret-bearing originals (the Hermes plugin's recovery store) dropped them. A value that is a call, an index, a `${...}`/`<...>` placeholder, an attribute chain or a lower-case snake_case name is no longer a match: 15 of 2,372 files now, all literal fixture keys. The exclusions are linear (a test pins 200K-char inputs under 2 s).
- `test_deep_malformed_cache_record_does_not_raise` failed on Python 3.12+ (a 1000-deep list now parses and is removed as a non-record; older versions raised RecursionError and kept it). The test now accepts either outcome and still requires no exception and no retrieval; `sweep_ccr_cache`'s docstring now says that parseable non-records are removed (that was already the behaviour other tests pin).

## [1.4.0] - 2026-10-06

Agent tool-output quality (Phase 1a/1b) and a plugin-facing API for
`hermes-tameru-plugin`. With default arguments, output for inputs that are not
affected by the fixes below is unchanged.

### Added
- `compress_context` kwargs: `gap_marker(omitted_chars, total_chars) -> str` (marks every cut, including adapter and CSV cuts), `recursion_markers` (caller-declared markers; input carrying one returns unchanged), and `content_hint` (skip detection: log/json/test/diff/grep/numbered_code/...).
- Public helpers: `error_fingerprints`, `brief_context`, `extract_evidence_lines`, `contains_secret`, `unwrap_tool_payload` / `rewrap_tool_payload` / `ToolPayload` (Hermes wrapper fields such as exit code survive a round trip), and `ENGINE_VERSION`. Exported from `tameru` (engine helpers lazily, so `python -m tameru.compress_context` still runs cleanly) together with `fold_lossless`.
- `tameru.agent_formats`: numbered-gutter detection (`cat -n`, Hermes `read_file` `N|`, `N: `), code detection, unified-diff adapter (whole hunks, per-file `+A -D in H hunks` stats, all hunk headers), grep/rg adapter (grouped by file), and pytest/jest/go test/cargo test reduction to failure blocks and summaries.
- `tameru.folding`: `fold_lossless` (terminal redraws, ANSI, trailing blanks, identical-line runs, pretty-printed JSON; idempotent), `mask_template` (one masking function shared by log templates and error fingerprints) and `json_brief` (valid-JSON brief of large arrays of objects with `_count`/`_omitted`).
- Log collapse keeps the last instance of each collapsed template as `[last] ...`; templates mask UUIDs, IPs, timestamps and durations.
- `tameru.transcript`: `text_of`, `task_query`; `scripts/sync_to_harness.py --check` verifies a vendored copy.
- Tests for all of the above, including `@pytest.mark.perf` linear-scaling tests.

### Changed
- Numbered reads and source code are no longer routed to CSV/TSV/YAML; `_looks_like_csv` and `detect_format` reject code (stable column counts, code keywords and line endings) and run diff/grep/gutter/code detectors before the table detectors. Python is no longer classified as YAML.
- Logs: one exemplar per ERROR/FAIL/FATAL/CRITICAL/PANIC fingerprint is exempt from the stale-error cap and the important-block exclusion, and survives floor-saturated reduction. Python traceback dumps with no query hit are still purged. Error lines restored by preprocessing return at their original relative positions, and already-collapsed `[xN]` duplicates are not re-added.
- A reduced pytest/jest/go/cargo run of at most 16 KB is final: block scoring no longer drops the failing test's file/name lines (receipt `adapter.name == "test_output"`).
- Filler queries ("continue", "thanks") no longer cause high-risk cuts.
- `trajectory_gate`: orphan tool calls no longer block compaction.
- Verifier: a bare line-leading timestamp no longer makes a line "critical".

### Fixed
- `_CRIT_LINE_RE` was compiled per call and invoked as `.search(line, re.IGNORECASE)`, passing the flag as `pos`; now module-level with `re.IGNORECASE`.
- Quadratic hot spots in critical-line recall, summary fact checks and backtracking path/token regexes (bounded): a generated 650 KB INFO/ERROR log through `compress_context(log, "why are requests failing?", ccr=False, citations=False)` went from 22.5 s to under 1 s; every error fingerprint is retained.
- Misdetection of code as CSV and numbered reads as two-column TSV.

### Fixed (QA round 2, same release)
- Test-runner reduction dropped errors printed around or inside a run: a `=====` rule in captured stdout ended the pytest FAILURES section (later failure bodies lost); compiler/`make`/tox `ERROR:` lines around a pytest run, cargo `error[E…]` / `could not compile`, and `npm ERR!` around jest were dropped. Unknown lines outside the recognised noise are now kept.
- Log templates masked every quoted value and path, merging distinct messages (`table "orders"` / `"payments"`, `a.db` / `b.db`) into one template and one error fingerprint; quoted values and paths are masked only when they hold a digit.
- Error lines that also report a zero count (`Failures: 2, Errors: 0 ... FAILURE!`, `FAILED (failures=2, errors=0)`) were treated as negated and lost exemplar protection.
- `recursion_markers` missed a marker opening a line inside a JSON tool payload (`rewrap_tool_payload` output was compressed twice).
- `fold_lossless` JSON minify re-serialised values (`1.10` → `1.1`, `-0` → `0`, lone surrogates, raw bidi overrides); it now removes only whitespace outside strings. `json_brief`/`brief_context` escape surrogates and bidi controls. Fold is idempotent on literal `[×N identical lines]` lines; a trailing CR run no longer erases a line.
- `content_hint="code"` on a numbered read split function bodies (now routed as numbered code).
- A 4300+ digit integer in tool JSON crashed the answer scan in `transcript`.

### Removed
- `integration/hermes` bundle (`context_engine/extractive`, `context_engine/tameru`) and the nine Hermes-gated tests; the integration now lives in [hermes-tameru-plugin](https://github.com/0xWhiteMage/hermes-tameru-plugin).

### Benchmarks
- Re-run 2026-10-06 on 1.4.0: `benchmarks/run_battery.py` 15/15 pass with savings identical to the checked-in 1.3.0 JSON; only per-case `ms` timings differ (machine noise, e.g. `large_doc_perf` 656 -> 819 ms), and `benchmarks/production-qa-v3-results.json` was updated accordingly. `benchmarks/threshold_sweep.py` (prints only): 15/15 clean at every `budget_ratio`, mean saved 77.3% / 68.4% / 61.2% / 41.5% / 24.9% at 0.1 / 0.2 / 0.3 / 0.5 / 0.7, 0 restorations, 0 leaks.
- Not re-run (need network or local models): the 17-case holdout and the jev_comparison arms (JEV, Laya, headroom, TF-IDF); their tables in `benchmarks/COMPARISON.md` and the README remain the 1.2.0/1.3.0 measurements and are labelled as such.
- Full suite: 1105 passed, 3 skipped (1125 passed, 3 skipped after QA round 2; battery and sweep unchanged).

---

## [1.3.0] - 2026-09-23

### Added
- Added typed-edge **dependency closure** (`_dependency_closure`): after selection, a dropped block that shares a rare term with a kept block AND carries a qualifier/negation cue (`except/unless/only/however/without/until/provided that/if`) or a definition cue (`is defined as/refers to/stands for/namely`) is restored — dropping it would change the meaning of what survives. lcc-style `QUALIFIES`/`DEPENDS_ON` edges, fully deterministic, capped at 8 restorations, never resurrects trust-risk or frozen-drop blocks, and supersession can still evict stale restorations. Fixed mode restores only within the caller's hard budget. Receipts report `sufficiency_restored: [block ids]`.
- Added **qualifier-aware trim refusal** in `_crush_value`: a long JSON string value whose truncated tail carries a qualifier cue is kept whole — a longer safe value beats a shorter misleading one.
- Added `trajectory_gate()` in `tameru.transcript` — SelfCompact-style timing rubric, deterministic version: compaction is suppressed when tool calls are pending (`pending-tool-calls`, mid-derivation) or when the last 3 assistant turns issued identical calls (`stuck-loop`, diagnose rather than erase evidence). Wired into `apply_extractive_tool_prune(..., timing_gate=True)`; the gate only ever suppresses, so it defaults on.
- Added **plan-aware multi-query**: `compress_context` accepts `query` as a string or an iterable of strings (current + next-k planned tasks); all query terms score as a union.
- Added `benchmarks/threshold_sweep.py`: Waxmell-style operating-point replay — sweeps `budget_ratio` across the QA corpus and reports gold retention, distractor leaks, savings, and restorations per ratio so operating points are chosen on evidence.
- Added multilingual battery cases `zh_needle` (Chinese) and `ar_needle` (Arabic) to `run_battery.py` — the Lost-in-Compression audit showed English-tuned compressors silently fail on CJK/RTL scripts.
- Added two more benchmark arms to `jev_comparison.py`: headroom-ai's Rust `TextCrusher` and a stdlib TF-IDF baseline, plus the Laya local-model arm (`convaiinnovations/laya-multilingual`).
- Added **context-calibrated ceiling** to `inspect_compressibility()` (Compactor-style): reports `guaranteed_savings_pct` — the duplicate-surplus share removable with zero judgement — and `ceiling_class` (`dedupe-heavy`/`moderate`/`sparse`) so callers see how much headroom a context actually has.
- Added opt-in **derived objective** (`derive_query=True`, CLI `--derive-query`): when the query is empty or generic, infers a conservative task descriptor from the document's recurring rare terms (deterministic frequency statistics over a bounded strided sample). Receipts mark `query_source: "derived"` + `derived_terms`, the compression-risk floor becomes `medium`, and documents with no stable term structure keep the normal empty-query fail-open. Propagates through `strategy="auto"`.

### Fixed
- None (verified `estimate_tokens` already prices CJK/no-space scripts correctly at ~1 token/char via `token_units` — the Headroom a35fe86 bug does not apply).

---

## [1.2.1] - 2026-09-23

### Added
- Added `tameru.transcript`: generic OpenAI-style transcript adapter (`apply_extractive_tool_prune`, `query_facts_lost`, `bulky_tools_dropped`). Harness-agnostic — works on any `role`/`content` message list. `hermes_extractive_engine` and `agent_extractive_engine` are now thin compatibility shims.
- Added `pin_recent`: unconditional positional pinning of the opening block and the newest N blocks, exempt from selection, freeze, supersession, and trust-filter paths.
- Added `min_savings_ratio` (default `0.10`): caller-configurable savings floor — compaction that shrinks less than the ratio fails open, and `0` disables the floor.
- Added opt-in `degraded_view`: on input size-limit breaches (`max_input_chars`, `max_lines`), blocks are scored on a bounded head+tail view while emitted output stays byte-exact. Safety limits (bidi controls, malformed surrogates, oversize query) remain hard failures; total work stays bounded by a 4× grace factor. Receipts report `degraded_view: true`.
- Added CLI flags `--pin-recent`, `--min-savings-ratio`, and `--degraded-view`.
- Added `strategy="auto"` progressive ladder: runs `extract` first and escalates to `summarise` only when extraction fails open (ambiguity, saturated floors, savings-floor undershoot). `summarise` still falls back to `extract` on any LLM failure. CLI: `--strategy auto`.
- Added a secrets screen before CCR archival: inputs containing probable credentials (private key blocks, `AKIA…`, GitHub/Slack/`sk-` tokens, JWTs, long quoted secret-style assignments) are never persisted to the CCR store. Compression proceeds normally; the result reports `ccr: None`, emits no `[CC-Retrieve:]` marker, and notes `ccr skipped: secret material detected` in `reasons`.
- Added a recursion guard: input already carrying Tameru output markers (`<compressed_context`, `[CC-Retrieve:`) returns unchanged with `policy_name="local-noop-recursion"`, preventing wrapper nesting and protecting the retrieval pointer that makes earlier drops recoverable.
- Added CCR recall tooling: `list_ccr(ccr_dir, offset=, limit=)` lists live records newest-first with hash/stored_at/ttl/chars/preview metadata, and `retrieve(hash, offset=, limit=)` paginates large originals.
- Added `selection` to every receipt: the selector path that decided the keep-set (`needle`, `floor`, `floor-saturated`, `line-records`, `fixed`, or a `*-failopen` variant), so silent degradation is visible to callers.
- Added `scripts/sync_to_harness.py`: one-command vendored sync — copies `src/tameru` modules (excluding `__init__.py`) into a harness plugin dir and stamps the plugin manifest version, so vendored integrations track releases without manual copying.
- Added `harnesses/README.md`: the integration contract for agent harnesses (pip API, CLI shell-out, vendored plugin) with file ownership rules.
- Added `benchmarks/jev_comparison.py`: live six-arm head-to-head on the production-QA corpus — Tameru vs LCC's mechanical scorer, real TypeSafe JEV (`jev-1.13.0`), LCC's local Laya decision model, headroom-ai's Rust TextCrusher, and a stdlib TF-IDF baseline. Measures gold retention, forbidden-distractor leakage, savings, latency, determinism, and provider degradation. Results in `benchmarks/COMPARISON.md`.
- Added `docs/RESEARCH.md`: curated digest of JEV-using and non-JEV compaction repos (lcc internals, Waxmell, Headroom, dsh-*, pi-lcm, SelfCompact) and 13 papers (Context Rot, LLMLingua-2, Provence, ACON, PAACE, TPC, CompactPrompt, Compactor, Lost-in-Compression, CompactionRL, memory surveys), each mapped to concrete Tameru takeaways with a ranked upgrade list.

### Changed
- In `mode="fixed"`, pinned blocks are now immovable and excluded from the `budget_ratio` base — the ratio governs compressible tokens only. Behavior is unchanged when no pins are present.

---

## [1.2.0] - 2026-08-31

### Added
- Added bounded industrial input profiles, configurable character/line/record/field/query/block/bidi limits, deterministic hashed receipts, and CLI controls.
- Added Unicode grapheme, script, direction, bidi-control, vertical-layout, and multilingual token accounting for 20 script/language families.
- Added exact extractive adapters for NDJSON, CSV, TSV, Markdown, YAML, line-oriented XML/HTML, SQL, INI/TOML-style sections, and vertical OCR columns.
- Added large-input SLOs, 20,000-record selection tests, multilingual adversarial fixtures, and an industrial architecture specification.

### Changed
- Modernized package licence metadata to an SPDX expression and raised the build-only setuptools floor to 77.
- Moved format-specific compaction and Unicode policy into dedicated modules while retaining the v1.1.1 scorer, verifier, CCR, and fail-open fallback.
- Upgraded non-ASCII token estimates and query matching without changing returned logical text order.
- Bounded large receipt ID sets with count/head/tail/SHA-256 manifests and added source/output/config hashes to every receipt path.
- Removed an O(gaps × Unicode-tokeniser) citation-accounting hotspot while preserving citation output.

### Security
- Added exact fail-open for malformed surrogates, oversized inputs, excessive bidi controls/overrides, malformed structured records, and adapter limit violations.

---

## [1.1.1] - 2026-08-30

### Added
- Added regression coverage for exact structured selectors, wrapped JSON, boolean polarity, per-tool evidence retention, cache maintenance, and public accounting.

### Fixed
- Preserved complete fenced code blocks, plain-text answer values, long JSON scalars, exact CSV selectors, and query-selected flat records.
- Made frozen supersession authoritative, deeply nested JSON fail open, and bounded CCR cleanup advance across repeated calls.
- Reused one factual-preservation gate for Hermes parent summaries, accepted retained facts in assistant/system summaries, and rejected total or partial loss of unrecoverable bulky tool evidence.
- Preserved scalar and boolean answer polarity from pure and wrapped JSON without substring collisions such as `widget-12` matching `widget-120`.
- Reported requested compiler mode and calculated token/savings diagnostics from the exact returned text, including wrappers and recovery markers.
- Rejected unsupported public modes and removed an unsupported Hermes activation command from the README.

### Changed
- Pure JSON now uses one full-document preprocessing path, while shared selector rules handle embedded and full JSON consistently.
- Hermes integration tests no longer depend on a profile-specific working directory.

---

## [1.1.0] - 2026-08-25

### Fixed
- Enforced freeze-on-first-sight keep/drop outcomes and bounded the decision cache to 4,096 blocks.
- Prevented fixed/adaptive head, tail, and neighbour stitching from re-admitting annotated blocks unless explicitly pinned.
- Recognised Docker `Step N/M` progress lines and preserved query-selected volatile log records during template collapse.
- Disabled CCR persistence for the Hermes live tool-pruning path; added expiry sweeping and owner-only cache permissions.
- Rejects invalid CCR timestamps/TTLs instead of retaining or serving records forever.
- Structurally unwraps escaped Hermes JSON strings without rewriting literal backslash bytes.
- Made the optional LLM summariser endpoint, model candidates, and total timeout budget configurable.
- Removed the duplicate `CompressResult.receipt` declaration.
- Made malformed structured-input scanning linear and persisted decision caches query-scoped and schema-safe.
- Made CCR writes atomic and owner-only, constrained recovery to validated records, bounded retention work, rejected future timestamps, and preserved exact caller bytes.
- Required factual validation for optional summaries and explicit opt-in for non-local summary endpoints.
- Made Hermes integration tests portable and canonicalised the `tameru` engine identifier.
- Added private atomic sidecar writes and disabled unrecoverable drop previews in the Hermes adapter.

### Tests
- Added regression coverage for every release finding, including explicit zero token readings, escaped JSON log selection, exact newline preservation, summary answer-value checks, and cache-schema compatibility.

### Release verification
- 195 pytest tests passed; 203 unittest tests passed.
- 12 Hermes integration tests passed and the production-QA battery passed 13/13 cases.
- Wheel: `tameru_compaction_system-1.1.0-py3-none-any.whl`.
- Wheel SHA-256: `335b9e1ccab3ba8af52ebbed493a41e3fde635e1eaa330767137af25cabdb676`.

---

## [0.10.0] - 2026-08-25

### Added
- **Adjacent-Family Hardening**: Added KVzip-style pinned sink regions, memorix-style compaction audit logs, and deterministic versioned context receipts.

### Changed
- Standardized context engine identifier from `extractive` to `tameru`.
- Upgraded test harness with 12 new adjacent-family validation suites (`tests/test_adjacent_v010.py`).

---

## [0.9.0] - 2026-08-25

### Added
- **NTK Layer-1 Filter Mechanisms**:
  - **Count-Preserving Template Deduplication**: Groups repeating log lines into compact `[A-N] exemplar` structures.
  - **Error-Signal Invariant**: Post-hoc validation preventing transformations from discarding active error traces.
  - **Progress-Bar Stripper**: Fast linear pass removing ANSI escape progress bars and spin markers.
  - **Multi-Language Frame-Run Collapsing**: Automatic collapse of repetitive Go and Java stack frames while preserving first and last frame anchors.
- **Lost-in-the-Middle Edge Reordering (`reorder_best`)**: Strategically places high-scoring evidence blocks at the extreme front and tail to maximize attention retention in decoder models.
- **Structural Verbatim Invariant**: Guarantees that kept fenced code blocks retain their enclosing syntax without truncation.
- **Inspect Compressibility Gate (`inspect_compressibility`)**: Pre-flight check measuring entropy and digit-normalized repetition ratio before committing to compaction.
- **Hermes Context-Engine Plugin**: Integrated support for `plugins/context_engine/tameru/`.

---

## [0.8.0] - 2026-08-24

### Added
- **Opt-in Local Semantic Tier**: Local bi-encoder and cross-encoder scoring (`tameru[semantic]`) via `sentence-transformers` for handling paraphrase distractors and subtle semantic ambiguities.
- Duck-typed fallback maintaining 100% zero-dependency stdlib operation when optional dependencies are absent.

---

## [0.7.0] - 2026-08-24

### Added
- **Old-Error Purging**: Stale historical error traces capped below the adaptive floor to prevent obsolete diagnostic data from polluting the context window.
- **Loss-Tolerance Routing**: Classification of tool payloads into zero, conditional, and high-loss tolerance tiers.

---

## [0.6.0] - 2026-08-23

### Added
- **Multi-Hop Bridge Expansion**: Graph closure using breadth-first traversal to rescue multi-hop entity alias chains ($A \to B \to C$).
- **Counterfactual Overlap Ambiguity Guard**: Protective fail-open defense against lexical distractor masking (NoLiMa findings).

---

## [0.5.0] - 2026-08-22

### Added
- **Temporal Supersession**: Automatic detection and pruning of superseded state statements (e.g., `"X is now Y"` overrides stale prior declarations of `"X is Z"`).

---

## [0.4.0] - 2026-08-21

### Added
- **Multilingual Tokenization**: Specialized tokenizers for Non-Latin scripts including CJK (Kana, Kanji, Hangul), Arabic right-to-left scripts, and syllabic Thai.

---

## [0.3.0] - 2026-08-20

### Added
- **Structural Tabular Compaction**:
  - CSV header-aware column pruning.
  - JSON structural array crushing with tail protection.
  - YAML configuration section isolation.

---

## [0.2.0] - 2026-08-19

### Added
- **Line-Record Log Mode**: Streaming parser and filter for Git commit logs, npm outputs, test traces, and ANSI terminal streams.
- **Reversible Citations**: ARC-style content-addressed hashes (`[A hash] "head"..."tail"`) for omitted segments.

---

## [0.1.0] - 2026-08-18

### Added
- Initial release of the Tameru byte-deterministic extractive compaction engine.
- Fast, local-only, zero-LLM context compaction.
- Fail-open safety contract.

[Unreleased]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v0.10.0...v1.1.0
