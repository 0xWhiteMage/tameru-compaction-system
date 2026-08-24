# Changelog

All notable changes to the **Tameru Compaction System** (`tameru`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.10.0] - 2026-08-25

### Added
- **Compaction Audit Log (Memorix)**: Structured audit entries detailing compaction decisions, pruned token counts, and entity retention telemetry.
- **Pinned Sink Regions (KVzip)**: High-priority sink preservation protecting critical initial and terminal token anchors during high-pressure compaction.
- **Versioned Context Receipts (Memorix)**: Deterministic, content-addressed receipt hashes accompanying compacted output blocks.
- **Adjacent-Family Research Register**: Comprehensive technical documentation added to `docs/research/ADJACENT-FAMILIES-STUDY.md`.

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
