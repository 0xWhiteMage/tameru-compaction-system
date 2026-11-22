# S5 diagnosis on the round-2 dev+validation corpus (engine 1.10.0)

Stage-attribution run of `benchmarks/engine_bench/s5_diagnose.py` over all 380 r2 dev+validation
cases x 4 conditions (`build_vague`, `build_specific`, `tool_call`, `task_vague`) x 2 profiles
(deepseek, hermes) = 3,040 calls, each measured twice (unwrapped + wrapped). The wrappers
monkeypatch the seven traced stage functions in `tameru.compress_context` and only record which
gold lines are present before/after each stage call; every wrapped call produced a byte-identical
`CompressResult` (extract text and all metadata) to its unwrapped twin — 3,040/3,040 verified.
`_clear_memos()` was called before every measured call (clears `_preprocess_cached`,
`_segment_blocks_cached`, `_brief_scan_cached`, `_extract_critical_lines_cached`,
`_contains_secret_cached`, `_error_fingerprints_cached`, `_block_link_terms_cached`,
`_extract_entities_cached`, `_extract_terms_cached`, `_estimate_tokens_cached`, `_evidence_blob`,
`industrial._profile_input_cached`, `unicode_profile._search_units_cached`,
`contract_gates._distinctive_query_terms_cached`, `contract_gates._source_blob` and `_SCORED_MEMO`)
so no memoised stage was skipped. The sealed split was not read. No `src/` change.

Data: `benchmarks/engine_bench/results/r2-s5-diagnosis-1.10.0.json` (per-call rows + summary),
`build/s5-diagnosis-1.9.0.json` (same cells under 1.9.0, no tracing — build/ is ignored).

A "drop" is a case x condition x profile cell where the extract is accepted (not fail-open; for
hermes also within risk "high" and keeping every input error fingerprint) yet at least one gold
line is absent. Each drop is attributed to the first traced stage where a gold line went
present -> absent. Counts reconcile in every cell: drops = a + b + c + d.

## Verdicts on the plan's hypotheses

| hypothesis | verdict | numbers |
|---|---|---|
| (a) destructive pre-filter keyed on distinctive query terms deletes the fact line | **partly** | 15/287 drops (5.2%): `preprocess_csv` 8 (all in csv_args cells), `preprocess_flat_records` 7 (evidence cells, puppet). 11/15 of these drops have a matched selector term occurring in the tool-call args. For `s5_buried` — the bulk of the loss — **zero** pre-filter drops. |
| (b) fact line shares a log template with filler, collapse/exemplar choice drops it | **partly** | 8/287 drops (2.8%), all `preprocess_logs` on `s5_superseded` cases (dbt `max_workers: 4343` clusters). All 8 have the gold line's `_log_fingerprint` shared with another line — the stale superseded value's line, which is the same template with digits masked. For `s5_buried`: **zero**. |
| (c) value truncated or masked so the strict line check fails | **refuted** | 0 drops in every cell. |
| (d) gold survives all traced stages; selection/render leaves it out | (dominant) | 264/287 drops (92.0%). The fact line reaches block scoring intact and the selection does not keep it. |

## Stage table (S5 kinds x condition x language x profile)

n = cells, fo = fail-open, acc = accepted, drops = a+b+c+d, ret_acc = gold-lines kept among accepted.

| cell | n | fo | acc | drops | a | b | c | d | ret_all | ret_acc |
|---|---|---|---|---|---|---|---|---|---|---|
| s5_buried, build_vague, en, deepseek | 80 | 51 | 29 | 15 | 0 | 0 | 0 | 15 | 0.812 | 0.483 |
| s5_buried, build_vague, en, hermes | 80 | 48 | 32 | 9 | 0 | 0 | 0 | 9 | 0.888 | 0.719 |
| s5_buried, build_vague, zh, deepseek | 80 | 51 | 29 | 10 | 0 | 0 | 0 | 10 | 0.875 | 0.655 |
| s5_buried, build_vague, zh, hermes | 80 | 51 | 29 | 9 | 0 | 0 | 0 | 9 | 0.888 | 0.690 |
| s5_buried, build_specific, en, deepseek | 80 | 8 | 72 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| s5_buried, build_specific, en, hermes | 80 | 5 | 75 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| s5_buried, build_specific, zh, deepseek | 80 | 25 | 55 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| s5_buried, build_specific, zh, hermes | 80 | 25 | 55 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| s5_buried, tool_call, en, deepseek | 80 | 51 | 29 | 16 | 0 | 0 | 0 | 16 | 0.800 | 0.448 |
| s5_buried, tool_call, en, hermes | 80 | 49 | 31 | 10 | 0 | 0 | 0 | 10 | 0.875 | 0.677 |
| s5_buried, tool_call, zh, deepseek | 80 | 55 | 25 | 10 | 0 | 0 | 0 | 10 | 0.875 | 0.600 |
| s5_buried, tool_call, zh, hermes | 80 | 53 | 27 | 10 | 0 | 0 | 0 | 10 | 0.875 | 0.630 |
| s5_buried, task_vague, en, deepseek | 80 | 56 | 24 | 7 | 0 | 0 | 0 | 7 | 0.912 | 0.708 |
| s5_buried, task_vague, en, hermes | 80 | 55 | 25 | 6 | 0 | 0 | 0 | 6 | 0.925 | 0.760 |
| s5_buried, task_vague, zh, deepseek | 80 | 31 | 49 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| s5_buried, task_vague, zh, hermes | 80 | 30 | 50 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| s5_superseded, build_vague, en, deepseek | 20 | 11 | 9 | 3 | 0 | 2 | 0 | 1 | 0.850 | 0.667 |
| s5_superseded, build_vague, en, hermes | 20 | 11 | 9 | 3 | 0 | 2 | 0 | 1 | 0.850 | 0.667 |
| s5_superseded, build_specific, en, deepseek | 20 | 1 | 19 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| s5_superseded, build_specific, en, hermes | 20 | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| s5_superseded, tool_call, en, deepseek | 20 | 11 | 9 | 3 | 0 | 2 | 0 | 1 | 0.850 | 0.667 |
| s5_superseded, tool_call, en, hermes | 20 | 11 | 9 | 3 | 0 | 2 | 0 | 1 | 0.850 | 0.667 |
| s5_superseded, task_vague, en, deepseek | 20 | 12 | 8 | 2 | 0 | 0 | 0 | 2 | 0.900 | 0.750 |
| s5_superseded, task_vague, en, hermes | 20 | 12 | 8 | 2 | 0 | 0 | 0 | 2 | 0.900 | 0.750 |
| csv_args, build_vague, en, deepseek | 40 | 2 | 38 | 6 | 2 | 0 | 0 | 4 | 0.850 | 0.842 |
| csv_args, build_vague, en, hermes | 40 | 2 | 38 | 6 | 2 | 0 | 0 | 4 | 0.850 | 0.842 |
| csv_args, build_specific, en, deepseek | 40 | 0 | 40 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| csv_args, build_specific, en, hermes | 40 | 0 | 40 | 0 | 0 | 0 | 0 | 0 | 1.000 | 1.000 |
| csv_args, tool_call, en, deepseek | 40 | 2 | 38 | 6 | 2 | 0 | 0 | 4 | 0.850 | 0.842 |
| csv_args, tool_call, en, hermes | 40 | 2 | 38 | 6 | 2 | 0 | 0 | 4 | 0.850 | 0.842 |
| csv_args, task_vague, en, deepseek | 40 | 16 | 24 | 16 | 0 | 0 | 0 | 16 | 0.600 | 0.333 |
| csv_args, task_vague, en, hermes | 40 | 16 | 24 | 16 | 0 | 0 | 0 | 16 | 0.600 | 0.333 |

Evidence cells (multi-gold cases): drops are mostly (d) as well; `preprocess_flat_records` accounts
for 7 of 113 evidence drops (3 with tool-arg selectors, 4 with user-only selectors — all puppet
`task_vague`/hermes).

## 1.9.0 comparison (same cells, same query strings; 1.9.0 has no `build_query`)

Pooled over the S5 kinds (1,760 cells): 1.9.0 ret_all 0.8869, ret_acc 0.8092; 1.10.0 ret_all 0.9011,
ret_acc 0.8272. All kinds (3,040 cells): 1.9.0 ret_all 0.9130 / ret_acc 0.8429; 1.10.0 0.9206 / 0.8562.
The S5 loss is not a 1.10.0 regression: every `en` S5 cell has identical retention between the two
engines; `zh` cells improve slightly under 1.10.0 (e.g. s5_buried task_vague zh 0.95-0.96 -> 1.00,
build_vague zh 0.81-0.83 -> 0.87-0.89), partly via more fail-opens (accepted 1,043 -> 1,007 overall);
s5_superseded en build_vague/tool_call improves 0.80 -> 0.85 at equal accepted counts.

## What is not covered

- The sealed split (never read; the script refuses it).
- Stage functions outside the traced list: `_select_format_adapter` (test-runner/diff/grep/yaml/
  agent adapters), `_clear_tool_payloads`, block scoring, budget/render. All (d) drops happen in
  this untraced region — this run narrows them to "post-preprocessing", not further.
- Fail-open cells (1,344/3,040): the original text is what the host sees there, so nothing is lost;
  the cause of a fail-open is not classified.
- Partial multi-gold drops (evidence): attribution is per cell to the first stage losing any gold
  line; within a cell, different gold lines can be lost by selection at different points.
- `structural_log_pass` is not wrapped directly, but it is `preprocess_logs` with an empty query —
  its work is recorded under `preprocess_logs`.
