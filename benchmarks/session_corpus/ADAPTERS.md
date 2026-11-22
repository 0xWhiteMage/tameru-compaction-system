# Session corpus: what each plugin's replay must read (spec only)

The adapters themselves are a later task. This page fixes what they read so both replays judge the same sessions the same way.

## Input

* One JSON file per scenario from `python -m benchmarks.session_corpus.build --split <split> [--window W]`
  (`build/session_corpus/<split>/<full|wW>/<id>.json`, canonical JSON, UTF-8, LF) plus `index.json` (ids, family, language,
  style, window table). Field meanings: [`SCHEMA.md`](SCHEMA.md). A replay never generates text itself; it reads these files.
* Plugins are separate repositories: they read an exported directory by path (CLI flag), never import this package.
* The holdout directory exists only after the one logged look (`--holdout --candidate NAME`). A replay refuses to run on a
  holdout export whose recomputed per-scenario canonical hashes do not match the registration it was given, and refuses the
  burned round-1 hash `ac9e77dd…1489`.

## Per-window slicing

* At window W the session is `steps[0 : windows[str(W)].steps]` (export the full file and slice, or export with `--window W`;
  both give the same steps). Arms are paired on scenario id, seed and W.
* Gated windows: 128K, 252K (both hosts), 500K (DeepSeek). 1M is report-only; Hermes 500K is report-only. 200K is available
  for the DeepSeek 200K regression.
* The host trigger is the adapter's own formula (DeepSeek `floor(min(0.8W, W-8000-65536))`, Hermes its configured threshold);
  `trigger_tokens` in the window table is for reference and for the crossing report only. Token counts come from the host's own
  estimator; the corpus's 4 chars/token is a planning value.

## Session shape

* **DeepSeek Harness replay** (`scripts/replay`, `Scenario {id, family, seed, lang, style, task, steps[{tool, args, output}], needed}`):
  `task` = `task`; each step = `{tool, args, output: output_text}`; `lang` = `en` for `en`, `zh` for `zh` and `mixed`
  (record the corpus language as well); `style` = `task_style`.
* **Hermes replay** (`tests/eval`, `Turn / Round / ToolStep / GoldFact`): turn 1's user message is `task`; steps are grouped
  into rounds of one tool call each and turns of 6 steps; later user messages are the neutral `继续` (zh/mixed) or `continue`
  (en); `ToolStep.key` = `call_key(tool, args, nth)` with `nth` = the step index for repeated commands. The final question of a
  turn-limited run is the question set below.

## Facts and questions

* The questions answerable at W are those with `first_window <= W`. Their `fact_ids` resolve to step facts by id.
* **Fact held** (both replays): a fact is held at the end of the session when its full fact line
  (`output_text.split("\n")[line_index]`) is present in the final prompt, or, if the extract rewrote whitespace, when one line of
  the final prompt contains both `key` and `value` (real facts: the `value` line). Value-only presence is reported as a
  secondary column (`value_present`) because short values (counts, codes) occur by chance. For DSH, `needed` = the values of the
  questions' facts and the line check replaces `finalText.includes(v)`; for Hermes, `GoldFact.needle` = the fact line,
  `category` = `recall`, `source` = `tool`, `turn` = the turn holding the step, `needed` = true.
* A `superseded` question is held only if the newest line is present (a stale line alone does not count); an `aggregate`
  question needs every fact; an `absent` question has no fact and is scored only by S3 answer probes ("not present").
* Every replay row records: scenario id, family, language, task style, window, question stratum, fact kind, fact position
  (`step / steps(W)`, early / middle / late thirds), line-present and value-present, and, for each Tameru act and decline,
  the decline reason and the calibration stratum (basis x style), as the round-2 plan requires.

## Reporting

Per window and split: trigger crossings (>=1, >=2) measured by the replay itself (the corpus's `rho` model is a planning
check), facts held by stratum and language, worst family, and the real-output share of the slice.
