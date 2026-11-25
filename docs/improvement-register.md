# Tameru engine improvement register

Tracking ID | Status | Lens | Area | Finding / Improvement
--- | --- | --- | --- | ---
R-0001 | done | red | harness | `atk-forged-markers` flagged although engine correctly noops (fail_open identity); forged-marker violation should only fire when the engine actually compacted.
R-0002 | done | red | harness | `fmt-csv`, `fmt-tsv`, `fmt-md-table`: `... N of M rows omitted` emitted without parens; `markers.py` `rows_omitted` regex required ` \(.*\)` — allow-list gap.
R-0003 | done | red | harness | `fmt-lcov`, `fmt-sarif`, `run-junit`, `fmt-ipynb`: `[tameru:report … kept N/M …]` headers not in `markers.py` allow-list — allow-list gap.
R-0004 | done | red | harness | `fmt-ipynb`, `fmt-sarif`: short JSON junction lines `},{`, `}]` flagged fabricated though they are ws-free substrings of input — checker gap.
R-0005 | done | purple | harness | no invariant catches "non-empty input → empty output without fail_open" (redos-tabs silently produced "").
R-0006 | done | purple | harness | low-savings check fires on whitespace-only inputs (hostile-only-newlines, redos-tabs) where empty output is correct.
R-0007 | found | red | engine | `atk-superseded`: `connect_timeout_ms = 30000` survives though later block reassigns the same key; supersession only fires on explicit staleness markers, not reassignment.
R-0008 | found | red | engine | `atk-forged-markers` regression vs 1.6.0: one forged `[… 10 chars omitted …]` line triggers the recursion noop → whole doc uncompacted (compactability DoS); forged marker lines should be stripped, not disable compaction.
R-0009 | found | purple | engine | `pin_recent=float('inf')` → OverflowError crash; `pin_recent='abc'` → ugly ValueError. Validate as finite non-negative int.
R-0010 | found | purple | engine | `query=42` (non-str, non-iterable) → TypeError crash; coerce scalars via str().
R-0011 | found | purple | engine | `gap_marker` callback exception propagates (ZeroDivisionError) — a buggy callback crashes compaction; wrap and fall back to default marker.
R-0012 | found | purple | engine | `limits='x'` → AttributeError; validate `IndustrialLimits` type early.
R-0013 | found | red | engine | `hostile-1mb-line`: a kept line of 1MB is emitted whole (0% saved, fail_open=False). `_render` never bounds kept-line length; window around query hits.
R-0014 | rejected | purple | engine | `gap_marker` longer than the gap: intended semantics — plain markers emit regardless of length (test_gap_marker_inline asserts it); `inline_short_gaps` is the documented opt-in for span-verbatim fallback.
R-0015 | fixed | blue | engine | `[CC-Retrieve: <hash>]` noop now requires the record to exist in ccr_dir — forged pointers are plain input. [PR#23]
R-0016 | fixed | purple | tests | adaptiveness invariants pinned: keep-ratio non-increasing vs doc size, specific > weak query, saturation bounds or fails open. [PR#24]
R-0017 | verified | red | engine | low savings resolved: trace-java 94%, trace-dotnet 94%, uni-fullwidth 96% on current v1.10.0 — earlier numbers were pre-fix baseline.
R-0018 | verified | blue | engine | `gap_marker` callback fires once per compression (widest-span probe) — no per-gap repeat calls. [verified]
- R-0019 [fix, PR#19] estimator: `_TOKEN_RE` counted a 1MB word run as 1 token → false fail-open via net-negative gate. Added `_ASCII_WORD_RUN_RE` len/4 term (≥32 chars). [verified: hostile-1mb-line clean]
- R-0020 [fix, PR#19] render: kept lines >8KiB now windowed (head+tail+hit windows + omitted markers) via `_window_oversized_line`; query plumbed to `_render`. [verified]
- R-0021 [fix, PR#19] floors: `_bound_fact_line` + `_fact_variant_present` stop fact/err/outcome floors re-appending oversized lines over their bounded variants. [verified]
- R-0022 [fix, PR#17] supersession: order-gated reassignment (`newer_is_later`), § scope separator, INI/YAML parent scoping, split-block wildcard matching, header normalization, full-coverage drop rule. [5 review rounds resolved]
- R-0023 [red] atk-forged-markers: forged engine markers in input survive as kept lines (fabrication). OPEN — strip/neutralize `ENGINE_MARKERS` in input text.
- R-0024 [red] hostile-only-newlines: 5000 newline input → 0.0% saved (est floor max(1,·)). OPEN.
- R-0025 [red] redos-tabs: 200KB tabs → 0.0% saved. OPEN.
- R-0026 [fix, PR#20] forged-marker guard reworked to a contamination-aware model: dominant-marker inputs noop, sparse markers strip from an analysis copy only (fail-open keeps caller_text byte-for-byte); marker-only line anchoring, ANSI-aware match, JSON-envelope coverage, noise-free pin/preflight inputs, hard limits still judge the true input. [13 tests]
- R-0027 [fix, PR#19] hit-window folding hardened: lazy fold map only when fold lengths change (1MB line now ~1MB peak), combining-mark strip for İ-style folds, cancel-drift safe identity check, budget-filling clip advances cursor, verbatim (raw-case) hits preferred over folded-only windows, over-budget folded windows clip when nothing preferred follows, must-span compare NFKC-only (case is a real difference). [11 tests]
- R-0028 [fix, PR#16→checker] hostile-only-newlines + redos-tabs were checker artifacts: whitespace-only inputs estimate ~0 tokens so 0.0% saved is correct. pending: min original_tokens floor on the low-savings invariant.
- R-0029 [fix, PR#21] API validation: pin_recent finite check, scalar/generator query coercion, gap_marker exception → default marker, limits type check. [8 tests]
- R-0030 [fix, PR#20 rounds 5-7] envelope recovery hardening: metadata unwrap falls back to cleaned text only when it wraps (never discards an applied industrial transform); degraded line cap judged on the true input's profile; protected_source decodes a recovered envelope; recovered body re-screened for recursion markers. [18 tests]
- R-0031 [fix, PR#19 round 10] duplicate-term windows: per-span term coverage tracked; a non-preferred span with only already-emitted terms yields budget to later windows carrying missing terms. [14 tests]
- R-0032 [fix, PR#26] API validation round 2: `limits` dicts coerce to FormatLimits/IndustrialLimits at every entry (adapt_format, adapt_report, industrial_preprocess, profile_input); FormatLimits `__post_init__` enforces positive-int non-bool fields; non-str `strategy`/`mode`/`selector_query` TypeErrors; `budget_ratio` float() OverflowError maps to +inf → domain ValueError; `recursion_markers` scalar names the option in its TypeError. [34 tests]
- R-0033 [fix, PR#27] marker guard short-payload gap: `_marker_in_tool_payload` used the public 200-char unwrap floor, so a re-wrapped compacted output under 200 chars lost its marker and recompressed; the escaped-marker precheck already gates, so the guard unwraps with min_field_chars=0. Round 2: judge every envelope field — a short `content` can no longer shadow a marked `output`. [2 tests]
- R-0034 [verified, purple] decision_cache poisoning: forged keep/restore entries are ignored and empty output unchanged — no crash, no content injection. [probe, no fix needed]
- R-0035 [verified, purple] `plan(42)` → AttributeError is duck-type-acceptable; `pin_patterns=[non-str]` fail-open is designed; `summary_timeout` non-numeric falls back inside `_summarise_with_llm`; `' extract '` mode normalization is genuinely invalid (validated). [probes, no fix needed]
- R-0036 [ops] #17 merged (bf48b54); #20/#19 rebased onto post-merge v1.10.0 — merges combined `marked`-hoist + `orig_index`-gate + `_bound_fact_line`/`_fact_variant_present` semantics; all tests green.

- R-0037 [blue] PR #19: `_bounded_orig_index` quadratic scan on ANSI-rewritten logs — short-circuits when no oversized originals; ambiguous shared-prefix matches map to none.
- R-0038 [blue] PR #20: JSON-envelope inner lines lack orig_index positions — tri-state `newer_is_later` (unknown order: prose-marker vetoes yes, bare reassignment no).
- R-0039 [blue] PR #20: `_line_scopes` restores section context — same-named keys in different INI/YAML sections can no longer veto each other's restores.
- R-0040 [blue] PR #28: `preprocess_json` / `content_key` TypeError on non-str args (was AttributeError).

- R-0041 [blue] PR #29: `mode` non-str AttributeError → TypeError; `summary_timeout` non-numeric/non-positive/non-finite → ValueError at entry.
- R-0042 [blue] PR #20 round 4: restores re-emit `[section]` headers (INI/TOML reopen semantics) so scoped lines can't misattribute; `_line_scopes` last-occurrence aligns with `orig_index`.
- R-0043 | #20 round-4 | `_restored_block` rework: scoped restores insert into surviving sections (plain `[a]` appends before next section head; `[[a]]` restores as own entry before the next surviving entry by orig_index); `line_headers` carries each line's exact header text so case-distinct `[Foo]`/`[foo]` tables never cross. Fixes duplicate-table, phantom-array-entry, and case-collapse findings. [PR #20, c6daf3a→squashed 5b1b67a]
- R-0044 | brief_context budget_chars | `TypeError` non-numeric (bool excluded), `ValueError` non-finite/non-positive; `int(nan)` crash and `True`→budget-1 misread closed. [PR #31]
- R-0045 | yaml_requires_original | `None` arg TypeError → coerces `text or ""`, returns False (fail-open convention). [PR #31]
- R-0046 | #20 round-6 | `_restored_block` boundary scan skipped `[`-lines inside TOML multiline strings (`_toml_code_part` + unescaped-triple-quote parity mask, escaped `\"\"\"` stays masked); `_PARENT_RE` accepts `]` inside quoted dotted names via char-level alternation (also kills `(a+)+`-style exponential backtracking on unclosed lines); `_resolve` disambiguates shared-prefix bounded lines by 32-char tail. [PR #20, 8730aa5]
- R-0047 | decide() malformed fields | non-str compressed_text → `malformed`; non-numeric token counts → `malformed`; non-numeric confidence → `low_confidence`; non-numeric tokens_saved → `not_enough_tokens`; non-Mapping fingerprints fall back to original's fingerprints; EV saved float() guarded. [PR #32]
- R-0048 | plan domain fields | negative chars/tokens/stock_kept_chars/compressed_chars made min(kept, chars) negative → phantom savings, predicted_chars_after < 0, negative margin_steps inflated replace target; __post_init__ ValueErrors on PlanItem/Candidate/CacheState/PlanInput + candidate isinstance. [PR #33]
- R-0049 | #20 round-7 | `['90s]` unmatched-quote strip collided with `[90]` (ini[1:-1] ate the last char) — fold now requires matched quotes; `_toml_code_part` blanks closed same-line triple-quoted spans so `#` inside `"""a"b#c"""` stays content. [PR #20, b4be0a9]
- R-0050 | adapt_format entry | `limits=42` → AttributeError inside adapters; `format_name=42` echoed non-str format. `_coerce_limits` (dict→FormatLimits, else TypeError) + format_name TypeError on adapt_format and adapt_report. [PR #34]
- R-0051 | industrial limits args | profile_input/industrial_preprocess `limits` int/dict → AttributeError; `_coerce_limits` dict→IndustrialLimits + TypeError. [PR #35]
- R-0052 | preset overrides type | resolve_preset non-Mapping overrides → AttributeError on .items(); now TypeError. [PR #36]
- R-0053 | grep adapter arg type | detect/adapt_grep_lines non-str → AttributeError; now TypeError. [PR #37]
- R-0054 | cache max_bytes domain | ContentCache(max_bytes) junk stored silently → first-set TypeError / always-evict; now ValueError at init. [PR #38]
- R-0055 | api-validation | diff adapters (detect/adapt/apply) tolerated None or crashed deep on non-str text → TypeError naming expected type | PR #41
- R-0056 | supersession | kept-line veto missing — head-of-doc stale assignment shadowed later reassignment | PR #43
- R-0057 | markers | guillemet-wrapped ALL-CAPS foreign banners survived as kept lines | PR #43
- R-0058 | api-validation | artifact_markers=42 TypeError named recursion_markers (wrong option) | PR #47
- R-0059 | cache | ContentCache get/set accepted non-str keys — silent never-matching entries | PR #48
- R-0060 | veto polish | kept-line veto narrowed: eq-shape, single-occurrence, pinned/triple-quote mask, key precount | PR #43
- R-0061 | api-validation | unwrap/rewrap_tool_payload non-str/non-payload args → int inner or AttributeError; now TypeError | PR #61
- R-0062 | probe-closed-no-bug | adaptiveness: budget_ratio appears near-inert in extract strategy — all-fact input gives identical output at ratio 0.1/0.5/0.9 (fixed+adaptive); large mixed input varies only 3974 vs 4066 chars. Unclear if ceiling-only semantics intended or cap fails to bind. Empty-query all-fact input EXPANDED 14289→17692 chars (fail-open plus receipt?). Needs decisive investigation: does ratio cap ever bind, and is expansion-with-receipt a net-negative gate miss?
- R-0063 | probe-closed-no-bug | budget_ratio verified adaptive: unique low-score filler keeps 30/150/300 lines at ratio 0.1/0.5/0.9 exactly proportional; fail-open returns byte-identical original (len match, zero divergence). Early flat readings were correct: all-fact inputs hit keep floors, self-similar noise dedupes before selection. Not a gap.
- R-0064 | inspect_compressibility | non-str text/query crashed mid-estimate; now entry TypeError (None query stays tolerated) | PR #65
- R-0065 | milestone | red-team 228/228 clean, zero findings on v1.10.0 1afc770 — first fully-green baseline since harness inception
- R-0066 | release hygiene | CHANGELOG.md on v1.10.0 had committed nested merge-conflict markers around token_units entries; resolved keeping final wording | PR #66
- R-0067 | option validation | min_savings_ratio skipped type check — str/list/dict crashed with bare float() error; now TypeError naming the option | PR #67
- R-0068 | probe-open | TOML multiline basic string ending in backslash before closing quotes: reviewer hypothesizes _UNESCAPED_TRIPLE_DQ (compress_context.py:1765, used at 1959-1963 in _restored_block masking) miscounts escapes, so lines before the next quotes are misread as string content and fact-restore places them inside the value. Verify with a compressing (non-fail-open) input; fix masking at the root. Surfaced on dsh#26 vendored copy — fix belongs engine-side, then re-vendor.
| R-0069a-evidence: probe shows query-hit line `step3` hoisted BEFORE the `[tasks]` header — parses as root-table key, wrong scope; needs determination whether hit-hoisting is intentional vs mis-scoping (probe: TOML with [tasks] step1/note-multiline/step2/step3 + noise, query step3) |
| R-0069 | open | engine | restore-ordering | multiline extract keeps string opener + earlier steps: `_restored_block` inserts a dropped later step BEFORE them, reordering instructions (hermes#29 review finding 1; engine-side fix needed in compress_context.py ~2056) — CONCRETE REPRO (gamma-repro): `[tasks]/alpha/beta/gamma + 50 noise` query "gamma" yields exactly `[…]\ngamma = 3\n[…]\n[tasks]\nalpha = 1\nbeta = 2` — gamma parses in the ROOT table, mis-scoped; hit lines are reordered ahead of their section header, breaking TOML semantics the restore machinery elsewhere protects |
