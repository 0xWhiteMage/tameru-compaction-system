# Changelog

All notable changes to the **Tameru Compaction System** (`tameru`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed
- Modernized package licence metadata to an SPDX expression and raised the build-only setuptools floor to 77.

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

[Unreleased]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/0xWhiteMage/tameru-compaction-system/compare/v0.10.0...v1.1.0
