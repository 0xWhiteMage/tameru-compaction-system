# Session corpus: scenario schema

A host-neutral, deterministic corpus of multi-step agent sessions for the round-2 replays of both plugins (analysis plan
[`docs/ANALYSIS-PLAN-ROUND2.md`](../../docs/ANALYSIS-PLAN-ROUND2.md), section 2). Standard library only; no network, child
processes or environment reads. Generated scenarios are **not committed**; materialise them locally:

```
python -m benchmarks.session_corpus.build --split dev                     # build/session_corpus/dev/full/<id>.json
python -m benchmarks.session_corpus.build --split validation --window 252000
python -m benchmarks.session_corpus.build --split holdout --holdout --candidate NAME   # the one look; logged
```

Real outputs come from the two Squeez files (`canonical_test.jsonl`, sha256 `1ead3be1…0540`, and `canonical_train.jsonl`,
sha256 `8e64421b…22a3`; Apache-2.0), expected in `build/session_corpus/squeez/` (or `--squeez DIR`). They stay out of git.

## Committed files

| File | What |
|---|---|
| `families.py` | the 45 families (tools, filler templates en/zh, natural fact shapes, the S5 buried assignment shape, error blocks, sizes, task messages) |
| `generator.py` | plan pass (sizes, kinds, windows, facts, questions) and text pass (one step at a time) |
| `real.py`, `manifest.json` | the real-output pool and its manifest (origin, licence, id, sha256, size, gold spans as numbers, redaction, allowed splits); no text |
| `corpus.py`, `split.py`, `splits.json`, `SEALED-HOLDOUT.sha256` | the family deal (logged seed), export, canonical hashing, holdout guard |
| `holdout_looks.json` | one entry per holdout read (date, candidate, sealed hash, command) |
| `equivalence.py`, `equivalence-descriptors.jsonl`, `equivalence-result.json`, `equivalence-attempts.json` | the registered pre-tuning equivalence check (numbers only) |

## Scenario

```jsonc
{
  "schema": 1, "generator": "session-corpus-3",
  "id": "pytest-03", "family": "pytest", "index": 3, "seed": 123456789,   // seed = cluster (independent scenario)
  "language": "en" | "zh" | "mixed",      // zh: Chinese filler, fact lines, task and questions; mixed: English output, Chinese task/questions
  "task_style": "specific" | "vague",     // specific: the task names every fact key; vague: names none
  "task": "Run the pytest tests and report ...",   // the first user message (the engine query in the descriptors)
  "parameters": {"tool", "median_chars", "length_factor", "real_pool", "real_share_target", "scenarios_per_family", "chars_per_token"},
  "windows": {"128000": {"steps": 31, "chars": 1301234, "trigger_tokens": {"deepseek": 54464, "hermes": 96000}}, ...},
  "steps": [ <step>, ... ],
  "questions": [ <question>, ... ],
  "sliced_to_window": 252000              // only in a --window export
}
```

### Step

```jsonc
{
  "index": 12, "tool": "bash", "args": {"command": "pytest -q tests/cache -x --maxfail=50"},
  "kind": "filler" | "fact" | "error" | "real",
  "chars": 18342, "planned_chars": 18211,  // planned_chars drives the window table (actual >= planned - one line)
  "output_text": "...",                     // or "output_sha256" in the canonical hash form
  "source": "squeez:pydata__xarray-4094:2", // real steps only: manifest id
  "facts": [ {"id": "f04", "kind": "natural" | "error" | "buried" | "stale" | "real",
              "key": "example_suite", "value": "12", "line_index": 233, "superseded": true /* stale only */} ]
}
```

* **Deterministic recipe.** A synthetic step's text is `generator.step_text(plan(family, index, pool, split), i)`; it draws only
  from `random.Random(sha256(f"{id}:step:{i}"))`, so it never depends on the window or on other steps. A real step's text is the
  manifest output with that id, byte for byte.
* **Facts are natural**: failing test names, versions, error codes (TS/CS/SQLSTATE/HTTP/exit codes, k8s reasons), counts, config
  assignments in `k=v`, `k: v`, `k -> v` and JSON-`msg`-with-`=` shapes. The fact line always holds both key and value
  (`line_index`, 0-based, into `output_text.split("\n")`).
* **S5 buried singletons**: one per segment, a `cfgkey=value`-shaped line inside a step whose filler is ONE repetitive
  template (PASS / ok / CSV / JSON-log rows). Half of them have an earlier `stale` line of the same key (newest wins).
* **Real facts**: one per Squeez gold span, the span's longest line; `key` is the Squeez task query, `value` the line.

### Question

```jsonc
{"id": "q-f04", "text": "Which test failed in the example_suite suite?", "fact_ids": ["f04"],
 "stratum": "single" | "buried" | "superseded" | "aggregate" | "absent" | "real",
 "fact_kind": "natural" | "error" | "buried" | "pair" | "none" | "real",
 "first_window": 252000,                  // smallest window whose step slice holds every fact of the question
 "expected": "not present"}               // absent only
```

Strata follow S3: `single` (a natural or error fact), `buried` (S5 singleton), `superseded` (S5 singleton with a stale value
earlier), `aggregate` (two facts, both must be answered), `absent` (the key never occurs; catches fabrication), `real` (a Squeez
gold line). Whether a fact is verbatim in the prompt, only in a shortened original, or lost to compaction is decided by the
replay per arm, not here. Position strata (early / middle / late) are `step / steps(W)` at the replayed window.

## Lengths and windows

* Triggers (tokens, 4 chars per token): DeepSeek `floor(min(0.8W, W - 8000 - 65536))` (128K 54,464; 200K 126,464; 252K 178,464;
  500K 400,000; 1M 800,000); Hermes `0.75W`. Planning trigger = the larger of the two.
* Each scenario has a length factor `f` in [1.6, 2.1]; `steps(W)` = the fewest steps whose planned characters reach
  `f x 4 x planning trigger(W)`, so the unpruned total is >= 1.6x both hosts' triggers at every window. Sessions at different
  windows are prefixes of one step list (paired by step count). At 1M a session is about 200-300 steps and 5-7M characters.
* Step sizes: lognormal around the family median (sigma 0.8), clipped to 2K-60K. Real outputs keep their exact size and are
  size-matched: for each real step a target is drawn from the same distribution (capped at 40K) and the pool output with the
  closest log size is taken (+0.25 per earlier use of that output in the session). Only outputs of 2K-40K are used (kept from
  equivalence attempt 2, when the first two-repository pool had none above 40K).
* Facts are placed per segment `[steps(prev), steps(W))` for W in 128K, 252K, 500K, 1M, so every gated window has its own.

## Content

* 45 families x 11 scenarios. Language cycles within each family (en, zh, en, mixed, zh, en, en, zh, mixed, en, rotated per
  family): about 30% Chinese, 20% mixed. Task style alternates within each family (offset per family).
* Real outputs: a real step is next whenever the session's real characters are below 34% of its total, so every prefix is about
  one third real. Pools are by repository: 11 SWE-bench repositories (at most 120 outputs each) are dealt by a logged seed
  (`manifest.json` `repo_deal`) to holdout 5, dev 3, validation 3, so no repository straddles splits.
* The eight round-1 families (burned round-1 DeepSeek holdout `ac9e77dd…1489`: pytest-zh, maven-en, kubectl-zh, sql-en, jest-en,
  gotest-zh, cargo-en, metrics-zh) are reproduced as `pytest`, `maven`, `kubectl`, `sql`, `jest`, `gotest`, `cargo`, `metrics`
  and pinned to dev.

## Integrity

* `SEALED-HOLDOUT.sha256` = sha256 of the canonical JSON of the sorted `[id, scenario digest]` rows of the holdout, where a
  scenario digest is sha256 over its canonical head (task, questions, window table, parameters) and every step with
  `output_sha256` in place of the text. `python -m benchmarks.session_corpus.split --check` verifies it (about 45 s).
* `python -m benchmarks.session_corpus.real --check` proves `manifest.json` is byte-identical to a rebuild from the Squeez files.
* `corpus.scenarios("holdout")` and `build --split holdout` refuse without `--holdout --candidate NAME`; a permitted read
  checks the sealed hash first and appends to `holdout_looks.json`.
