# Tameru Architecture: format adapters, Unicode and bounded work

**Status:** Living implementation specification (original design written 2026-08-31; the module names below are current)
**Constraints:** deterministic, local-first, stdlib-only core, extractive, fail-open, reversible where CCR is enabled

## 1. Goal

Tameru is a bounded, format-aware, multilingual compaction engine suitable for multi-megabyte production context. The design must improve recall and compression without changing the core safety contract: if structure, query intent, Unicode semantics, or complexity cannot be handled confidently, return the exact caller input.

## 2. Non-negotiable contracts

1. **Logical Unicode order is canonical.** Bidirectional and vertical writing affect presentation, not stored text order. Tameru never visually reorders code points.
2. **Grapheme atomicity.** Compaction and query matching must not split base characters from combining marks, variation selectors, emoji modifiers, join controls, or ZWJ sequences.
3. **Original bytes survive fail-open.** Matching may use normalised shadow text, but returned extracts use original substrings.
4. **Format validity is preserved.** An adapter may emit only structurally valid extracts of the detected format; otherwise it declines and the generic engine handles or fails open.
5. **Bounded work.** Parsers and profilers have explicit character, line, record, nesting, field and scan limits.
6. **Deterministic decisions.** Same text, query, options and Unicode runtime produce byte-identical output and metadata.
7. **No implicit network or model dependency.** The industrial core remains Python stdlib only.

## 3. Unicode profile

A new `tameru.unicode_profile` module owns:

- approximate extended grapheme iteration using Unicode general categories, variation selectors, emoji modifiers, regional-indicator pairs, ZWJ/ZWNJ and join chains;
- script-family classification for Latin, Greek, Cyrillic, Armenian, Georgian, Hebrew, Arabic, Indic, Southeast Asian, Han, Kana, Hangul, Ethiopic and other letters;
- direction analysis from Unicode bidi classes (`L`, `R`, `AL`) with `ltr`, `rtl`, `mixed`, `neutral` outcomes;
- explicit bidi-control accounting, with overrides (`LRO`, `RLO`) flagged separately from isolates/marks;
- logical-order search normalisation that strips presentation-only bidi controls for matching while retaining join controls;
- search units tailored by script: words for spaced scripts, graphemes plus bounded n-grams for Han/Kana/Hangul and space-free Southeast Asian scripts;
- vertical-layout hints from markup/CSS and one-grapheme-per-line OCR shapes. Vertical hints never trigger reordering.

The implementation is a documented **UAX #29 tailoring**, not a claim of full dictionary segmentation. Thai, Lao, Khmer, Myanmar, Chinese and Japanese require locale dictionaries for linguistically exact words; v1.2 uses deterministic grapheme n-grams and fails open when evidence is ambiguous.

## 4. Format adapter architecture

A new `tameru.format_adapters` module provides `FormatResult` objects containing:

- detected format and confidence;
- exact extracted text or a decline result;
- total/kept record counts;
- structural validity and truncation flags;
- deterministic reasons for receipts and diagnostics.

Priority adapters:

1. **NDJSON / JSON Lines** — validate each non-empty line as RFC 8259 JSON; retain exact matching records; never insert non-JSON comments.
2. **Delimited records** — CSV and TSV record framing respects quoted delimiters, escaped quotes and quoted newlines; retain the exact header and original record bytes.
3. **Markdown** — headings establish sections, fenced/indented code remains atomic, and retained content carries its ancestor heading chain.
4. **YAML-like streams** — indentation-aware mapping/list sections retain exact parent keys and document markers. No attempt is made to resolve tags, aliases or arbitrary schemas.
5. **XML / HTML** — detect and profile safely; destructive extraction is allowed only where exact balanced element spans can be proven. DTD/entity expansion is never performed.
6. **Line records** — Git, package-manager, test, stack-trace and generic key/value records use exact record boundaries.
7. **Vertical/OCR text** — one-grapheme-per-line columns may be grouped for matching, but extracts retain source line order.

Adapters are ordered, bounded and independently testable. A declined adapter is not an error.

## 5. Industrial limits and scale profile

A new `tameru.industrial` module defines `IndustrialLimits` and `InputProfile`.

Default limits:

| Limit | Default | Behaviour when exceeded |
| --- | ---: | --- |
| Input characters | 8,000,000 | Exact fail-open |
| Lines | 250,000 | Exact fail-open |
| Structured records | 100,000 | Adapter declines or exact fail-open |
| JSON nesting | 64 | JSON adapter declines |
| Record characters | 1,000,000 | Adapter declines |
| Fields per delimited row | 4,096 | Adapter declines |
| Profile sample | 32,768 characters, balanced head/tail | Deterministic bounded analysis |
| Query characters | 32,768 | Exact fail-open |
| Scored blocks | 20,000 | Exact fail-open before scoring |
| Receipt IDs | 512 | Bounded head/tail manifest plus SHA-256 |

The public API accepts an optional `limits` argument. Existing callers receive defaults and remain source-compatible. Limits must be serialisable into receipts.

In 1.10.0 an outer size guard runs before this pipeline: over 2,000,000 characters it analyses a bounded head/tail and error-line sample (`huge_sampled`, basis `partial`, confidence at most 0.5); over 8,000,000 it returns the exact original with `too_large`. The sample path does not verify or store the full original. These thresholds are independent of custom `IndustrialLimits`; see [usage](USAGE.md#1100-results-and-bounded-analysis).

Scale SLOs on the reference host:

- existing 4,000-record battery: under 1.2 seconds median CPU;
- 1 MiB NDJSON/TSV fixtures: under 1.5 seconds median CPU;
- 4 MiB multilingual text: under 4 seconds median CPU;
- doubling-input CPU ratio below 3.2 for supported record formats;
- fail-open limit checks under 100 ms after the input string already exists;
- no recursion errors, unbounded regex backtracking, or parser network/entity access.

## 6. Integration seam

`compress_context()` performs the following before legacy destructive preprocessing:

1. validate public mode/options;
2. build a bounded `InputProfile` from the caller text;
3. exact fail-open on hard input limits or malformed surrogate data;
4. invoke the ordered industrial adapter registry when the query is distinctive;
5. pass accepted extracts into the existing scorer, verifier, CCR and accounting pipeline;
6. attach format/profile/limit metadata to the receipt;
7. use the generic engine's behaviour when adapters decline.

On the normal, unsampled path, the original caller text remains the CCR source and fail-open return value.

## 6a. Interface layer (1.10.0)

Additive modules let a host keep its acceptance rule, option set and worker schema as data instead of code. These helpers do not themselves change extraction. The full 1.10.0 release also changes extraction and result metadata; its golden record was regenerated (see the historical [build notes](1.10.0-BUILD-NOTES.md#golden-regeneration-review-1100-done-once-after-steps-2a-and-2b)).

- `decide.py`: `decide(result, policy)` returns `Decision(accept, reason, basis)` with the closed reasons `fail_open`, `sanitized`,
  `risk`, `lost_fingerprint`, `no_gain`, `low_confidence`, `not_enough_tokens`, `negative_ev`, `ok`. `HERMES_POLICY` and
  `DSH_POLICY` express the two 1.9.x host rules. Lines the engine's trust screen flags never count as a surviving error
  fingerprint. An optional `Policy.ev` (`EVPolicy`: price profile, loss profile, strength, conservatism quantile,
  calibrator callable) replaces the confidence check with the expected-value rule `p_hat·V − (1 − p_hat)·L > 0`; the hard vetoes run
  first, unchanged.
- `calibration.py` + `calibration.json`: a shipped development-fit, family-stratified Beta table. `p_hat(basis, specific, fact_lines_dropped=0, raw_confidence=None, *, quantile=0.5, table=None)` returns a probability estimate (0 when protected facts were dropped); unknown strata use the prior. An EV caller must explicitly supply a `calibrator` callable to use it: `EVPolicy.quantile` alone does not connect the table, and the default EV path still uses raw confidence. No live answer-quality guarantee follows from the fit.
- `loss.py` + `loss_profiles.json`: dated, sourced loss profiles for the EV rule (`p_needed`, `p_recovered`,
  `recovery_output_tokens`, `lambda_base`, strength multipliers), each figure flagged `unverified` where it is an
  assumption. Plain data read with `pathlib`, same style as `prices.py`.
- `plan.py`: `plan(PlanInput) -> Plan`, a pure planner (no I/O, no clock, deterministic, O(n log n), no host constants —
  trigger formulas, stock actions and engine candidates all arrive as inputs). Gating: it acts on the cache-broken events
  (`trigger`, `cache_cold`, `prefix_rewritten`), on a warm `step` only inside a caller-set forecast horizon, and never inside
  the hysteresis window `K` unless the event is `trigger`. Prune mode covers every stock-cut item — `extract` when the
  candidate passes vetoes and EV and fits the stock cut, `stub` otherwise — and never touches a non-cut item. Compact mode
  allocates the retained budget over the stock-demote set by fact rows first, then EV per retained character, then recency,
  and commits `superseded` only when the successor covers the item's facts. The output carries per-item action, reason and
  EV numbers plus totals.
- `presets.json` + `presets.py`: `tool-result@1` and `dsh-tool-result@1` are the exact option sets the two plugins pass today;
  `resolve_preset(name, overrides)` returns explicit keyword arguments. The file is plain data, read with `pathlib`.
- `protocol.py`: `PROTOCOL_VERSION = 3`, the worker request fields with types, ranges and closed enums, `pin_patterns` limits and a
  conservative backtracking check, `validate_request`, `result_to_dict`, `version_info`. v3 adds `selector_query` and
  `derive_selector_query` on `compress` plus the `plan` request (`validate_plan_request` → `PlanInput`, `plan_to_dict`
  → reply); earlier clients validate unchanged. Errors are fixed codes and never echo request text.
- `compress_context(redact_secrets=True)` replaces the engine's own credential patterns in the output with `[tameru:redacted]`
  (opt-in; a fail-open returns the original unredacted). A `gap_marker` that declares a parameter named `kind` is told what the
  dropped span is (`markers.GAP_KINDS`); 2-argument markers are called as before (`gap_kind.py`).
- `unwrap_tool_payload` is the neutral name; `unwrap_hermes_tool` stays as a deprecated alias.

## 7. Test matrix

### Unicode and direction

- NFC/NFD-equivalent Latin, Greek, Cyrillic, Arabic, Hebrew and Indic queries;
- combining marks, ZWJ emoji, variation selectors and regional indicators;
- Arabic/Hebrew mixed with Latin identifiers and left-to-right digits;
- bidi isolates/marks preserved; bidi overrides detected without reordering;
- Thai, Lao, Khmer and Myanmar no-space queries via grapheme n-grams;
- Mongolian/vertical CSS and CJK one-grapheme-per-line OCR fixtures;
- malformed surrogates exact fail-open.

### Formats

- NDJSON CRLF/LF, empty-line policy, malformed line fail-open;
- CSV/TSV quoted delimiters, doubled quotes and embedded newlines;
- Markdown nested headings, lists, blockquotes and fenced code;
- YAML document streams, anchors/tags treated conservatively;
- XML/HTML balanced structures, CDATA, comments and entity declarations;
- SQL, logs, stack traces, diffs and test output regression coverage.

### Scale and adversarial safety

- deeply nested JSON/XML;
- giant single records and delimiter floods;
- unmatched quotes/fences/tags;
- bidi-control injection and confusable identifiers;
- deterministic output across hash seeds;
- property tests asserting extractiveness, non-expansion, exact fail-open and bounded completion.

## 8. Delivery phases

1. Unicode profile and query units.
2. Limits/profile API and receipt metadata.
3. NDJSON and CSV/TSV adapters.
4. Markdown/YAML/markup/vertical adapters.
5. Scale fixtures, adversarial tests and benchmark SLOs.
6. Documentation, package release, vendored-copy parity in the harness plugins and independent review.

## 9. Primary references

- Unicode Bidirectional Algorithm, UAX #9: https://www.unicode.org/reports/tr9/
- Unicode Line Breaking Algorithm, UAX #14: https://www.unicode.org/reports/tr14/
- Unicode Text Segmentation, UAX #29: https://www.unicode.org/reports/tr29/
- CSS Writing Modes Level 4: https://www.w3.org/TR/css-writing-modes-4/
- JSON, RFC 8259: https://www.rfc-editor.org/rfc/rfc8259
- CSV, RFC 4180: https://www.rfc-editor.org/rfc/rfc4180
- NDJSON 1.0: https://github.com/ndjson/ndjson-spec
- YAML 1.2.2: https://yaml.org/spec/1.2.2/
- CommonMark 0.31.2: https://spec.commonmark.org/0.31.2/
- XML 1.0 Fifth Edition: https://www.w3.org/TR/xml/
