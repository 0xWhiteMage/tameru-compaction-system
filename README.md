# Tameru (貯める) — Context compaction for LLM agents

<p align="center">
  <img src="assets/header.png" alt="Tameru Compaction System (貯める)" width="100%"><br><br>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-v1.4.1-blue.svg" alt="Version 1.4.1"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT licence"></a>
  <a href="tests/"><img src="https://img.shields.io/badge/tests-1179%20passed-success.svg" alt="1179 tests passed"></a>
  <a href="benchmarks/run_battery.py"><img src="https://img.shields.io/badge/QA-15%2F15-brightgreen.svg" alt="15 of 15 QA cases passed"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/core-Python%20stdlib-orange.svg" alt="Python standard library core"></a>
</p>

**Give your agent more room to work. Keep the evidence that matters.**

Tameru (貯める, Japanese for “to store up”) reduces bulky logs, search results, documents and tool outputs before they fill an agent's context window. It selects task-relevant source text, collapses repetition and restores related evidence such as definitions, identifiers and qualifiers.

- **Less context to send:** successful cases in the v1.4.1 QA battery save **31–99.5% estimated tokens**, depending on the input.
- **No extra model call:** default extraction runs locally, uses no LLM or GPU and adds **$0 in LLM inference charges**.
- **Repeatable decisions:** identical input and configuration produce deterministic extraction; weak signal can return the original input.
- **Retrieve more when needed:** optional recovery storage lets a host retrieve omitted context after a successful store write.

Python **3.10+** · Standard-library core · MIT licence · **v1.4.1 source**

[See it work](#see-it-work) · [Compare approaches](#comparison-with-other-approaches) · [Install](#quickstart) · [Hermes](#hermes) · [What's new](#whats-new-in-v141)

## Where Tameru helps

| What your agent is reading | What is useful to keep |
|---|---|
| Hundreds of routine log lines around a failure | Error fingerprints, relevant messages and source details such as hosts and ports |
| A search result that repeats the same name everywhere | Matching definitions and assignments, distinct matches and file context |
| A failed test with pages of captured output | The failure, recognised errors, warning-or-higher lines and section boundaries |
| Configuration with an old value and a later override | The current value and its qualifier when the supersession is explicit |
| A document where the answer spans several sections | Related entities and the links connecting the question to its answer |
| Git history, JSON, CSV or YAML dumps | Relevant records with the structure needed to interpret them |

These mechanisms target real sources of context waste. They preserve selected source evidence; they do not guarantee a model's final answer.

## See it work

**Question:** “Which database endpoint does Project Orion use?”

In the [multi-hop fixture](benchmarks/run_battery.py), 60 routine archive paragraphs surround two facts. The endpoint line does not name Project Orion, so retaining the connecting fact matters.

Input excerpt:

```text
Routine archive section 0: ordinary status record with no relevant operational facts.
... 29 more routine archive paragraphs ...

Project Orion uses warehouse Cedar.

Cedar routes writes through endpoint DB-EU-7.

... 30 more routine archive paragraphs ...
```

Actual v1.4.1 output with recovery storage and citations disabled:

```text
Routine archive section 0: ordinary status record with no relevant operational facts.
[…]
Project Orion uses warehouse Cedar.
[…]
Cedar routes writes through endpoint DB-EU-7.
[…]
Routine archive section 29: ordinary status record with no relevant operational facts.
```

**5,342 → 266 characters; 95.0% estimated token savings.** Both the endpoint and the Project Orion → Cedar relationship survive. Run this example in the [quickstart](#quickstart).

## Comparison with other approaches

Freshly measured on **2026-10-12**, using **Tameru v1.4.1** and the same **16 task cases** for every scored method. The corpus includes evidence chains, stale configuration, Git/YAML/npm output, Japanese/Chinese/Arabic text, saturated grep, captured pytest logs with blank lines and numbered source reads.

| Tested method | Required strings kept | Forbidden strings ↓ | Clean cases | Mean character savings | Median wall time | Repeat output identical |
|---|---:|---:|---:|---:|---:|---|
| **Tameru v1.4.1** | 25/25 | 0 | 16/16 | 81.9% | 12.83 ms | Yes |
| LCC mechanical | 25/25 | 5 | 11/16 | 36.3% | 6.97 ms | Yes |
| Headroom TextCrusher | 21/25 | 4 | 9/16 | 50.5% | 0.51 ms | Yes |
| TF-IDF paragraph baseline | 22/25 | 5 | 9/16 | 53.4% | 0.12 ms | Yes |
| LCC → Laya (CPU) | 25/25 | 5 | 11/16 | 8.0% | 8091.08 ms | Yes |
| LCC → JEV — unmeasured | — | — | — | — | — | — |

Tameru retained **25/25 required strings**, with **0 forbidden leaks** and **81.9% mean character savings**. A clean case keeps every required string and excludes every planted forbidden string. Faster methods and different savings are shown alongside these retention checks.

Each case gets one untimed warmup and 3 timed complete calls. Retention is checked across all 4 outputs; the timing column is the median of per-case wall-time medians. Imports and model loading are outside the timer. Character savings are separate from the estimated token savings in the release battery.

This is Tameru's regression corpus, not an independent downstream-agent evaluation. Headroom's row tests its Rust TextCrusher, not its full content router; LCC rows use the recorded provider and one scoring worker.

LCC's Laya path includes protected no-ops: inputs that need no model scoring are kept by its deterministic policy. These are recorded separately from failed or degraded model calls.

Unmeasured providers have no scores carried forward from earlier releases:

- **LCC → JEV:** RuntimeError: JEV requires --include-jev and an existing TYPESAFE_API_KEY

See [the complete v1.4.1 comparison](benchmarks/COMPARISON.md) and [raw results, pins and timing samples](benchmarks/comparison-v1.4.1.json).

## v1.4.1 measured results

The current release passes **15/15 production-QA cases**, keeping all required answer strings with zero forbidden-distractor leaks. Selected results from the [v1.4.1 battery](benchmarks/production-qa-v3-results.json):

| Workload | Evidence checked | Estimated token savings |
|---|---|---:|
| Git history | Required commit hash | **94.0%** |
| Multi-hop document | Database endpoint reached through a related entity | **95.0%** |
| Release evidence chain | Alias, deployment identifier and checksum | **95.6%** |
| Current configuration | New timeout retained; superseded config excluded | **90.1%** |
| YAML configuration | Distro and language retained; excluded dependency absent | **64.7%** |
| npm log | Requested Playwright version | **31.0%** |
| Japanese document | Required layer count | **57.5%** |
| Chinese needle case | Required backup host | **90.9%** |
| Arabic needle case | Required backup host | **88.6%** |
| Large synthetic document | Savings, determinism and timing; no answer-string check | **99.5%** |
| Empty query | Original input returned | **0.0%** |

The large synthetic case contains 4,000 records and completed in **822.9 ms CPU time** on the recorded runner, within its **1,200 ms** gate. Per-case timings are in the JSON and vary with hardware. Savings use Tameru's token estimator, so actual model-token savings vary. The synthetic maximum is a workload result, not an expected saving for every input.

### Choose a context budget

The [budget sweep](benchmarks/threshold_sweep.py) shows how the savings change in `mode="fixed"`. Lower ratios request a smaller budget for compressible content; pinned evidence can exceed that budget.

| `budget_ratio` | Mean character savings | Cases with required strings retained and no forbidden leaks |
|---:|---:|---:|
| 0.1 | **77.3%** | 15/15 |
| 0.2 | **68.4%** | 15/15 |
| 0.3 | **61.2%** | 15/15 |
| 0.5 | **41.5%** | 15/15 |
| 0.7 | **24.9%** | 15/15 |

These are fixture-level operating points. Character savings and estimated token savings are separate measurements; validate the retained evidence for your own tasks.

## Quickstart

The source and metadata identify **v1.4.1**. The GitHub tag and Release are pending publication; this command pins the verified engine source:

```bash
python -m pip install "git+https://github.com/0xWhiteMage/tameru-compaction-system.git@976f7a5049c2a32410a112a8748dd245cf7c464c"
```

### Python

Reproduce the example above without disk writes or model calls:

```python
from tameru.compress_context import compress_context

archive = "\n\n".join(
    f"Routine archive section {i}: ordinary status record with no relevant operational facts."
    for i in range(30)
)
context = (
    archive
    + "\n\nProject Orion uses warehouse Cedar.\n\n"
    + "Cedar routes writes through endpoint DB-EU-7.\n\n"
    + archive
)
result = compress_context(
    context,
    "Which database endpoint does Project Orion use?",
    ccr=False,
    citations=False,
)
print(result.compressed_text)
print(f"Estimated token savings: {result.tokens_saved_pct:.1f}%")
print(f"Returned original input: {result.fail_open}")
```

### CLI

```bash
tameru-compress context.txt "Why did the database connection fail?" --no-ccr --stats
cat context.txt | tameru-compress - "Find the active error" --no-ccr
```

The CLI accepts a file or stdin and writes compacted text to stdout. `--stats` adds JSON diagnostics first, followed by `---` and the text. Use a task-specific query: “continue” often provides too little signal.

### Hermes

Use the maintained [hermes-tameru-plugin](https://github.com/0xWhiteMage/hermes-tameru-plugin), follow its installation instructions and select:

```yaml
context:
  engine: tameru
```

The plugin supplies the Hermes integration and recovery path. Engine and plugin releases are separate; update the plugin to receive its vendored engine changes. The plugin's catalogue submission is [Hermes PR #94102](https://github.com/NousResearch/hermes-agent/pull/94102).

For another agent framework, use the Python API, CLI or generic transcript adapter. See the [agent integration guide](docs/INTEGRATION.md) for message-list pruning, task-derived queries and vendored-copy synchronisation.

## What's new in v1.4.1

| Improvement | Why it matters |
|---|---|
| **Better saturated grep/rg selection** | A search matching nearly every line can still retain the definition or assignment your agent needs. Command flags such as `-n` no longer crowd out the searched name. |
| **Shorter noisy pytest failures** | Long captured sections keep boundary lines, recognised error fingerprints and warning-or-higher evidence. Blank lines no longer end a section early. |
| **Less omission-marker overhead** | Consecutive fully omitted grep files share a caller-supplied marker while retaining file headers. |
| **Opt-in short-gap inlining** | `inline_short_gaps=True` keeps a span verbatim when its marker would be at least as long. Off by default. |
| **Broader credential screening** | Recovery persistence recognises additional API keys, bearer tokens and env/YAML assignments while avoiding common code-expression false positives. This does not redact returned output. |
| **Windows-friendly file inputs** | CLI, decision-cache and recovery-cache reads accept BOM-prefixed UTF-8. |

The full [changelog](CHANGELOG.md) and [v1.4.1 notes](docs/releases/v1.4.1.md) cover conditions and maintenance changes. Affected grep and pytest inputs intentionally change; unchanged battery savings are not a blanket promise of identical output to v1.4.0.

## Formats and languages

| Input | Handling |
|---|---|
| Terminal/build logs | ANSI handling, template deduplication, error exemplars and last-occurrence retention |
| Numbered source reads | Recognises `cat -n` and common `read_file` gutters; avoids treating code as a table |
| Unified diffs and grep/rg | Hunk or file grouping, query matches, headers and saturated-query selection |
| Pytest, Jest, Go and Cargo output | Failure evidence and summaries, with conservative retention of unknown surrounding lines |
| JSON/NDJSON and CSV/TSV | Query-aware records; quote-aware framing and headers; JSON briefs for large object arrays |
| Markdown | Heading ancestry and fenced-code protection |
| YAML, XML/HTML, SQL, INI/TOML-style sections | Conservative format-specific selection; ambiguous shapes decline specialised reduction |
| Extracted vertical/OCR text | Logical-source-order matching on text already extracted upstream |

Script-aware matching has regression coverage across **20 script/language families**, including Japanese, Chinese and Arabic release cases. Matching uses a normalised shadow while extracts retain source text and logical order. This is tested coverage, not complete semantic support for every language. Tameru operates on text; it does not perform OCR or image recognition.

## Recovery and limits

The standalone API defaults to `ccr=True`. When storage succeeds, a recovery pointer can retrieve the original context. Recovery depends on a successful write, valid unexpired records and a host retrieval path. Use `ccr=False` when persistence is unwanted or the host cannot retrieve omitted content.

Credential screening is heuristic: it gates cache writes, does not encrypt the cache and does not redact returned text. A citation by itself is not proof that recoverable content was stored.

Extraction can miss relationships with no shared terms, and retained source lines impose a minimum output size. Weak queries, malformed inputs or insufficient savings can return the original. The default `strategy="extract"` uses no LLM; optional `summarise`/`auto` and semantic-model paths have their own dependencies and inference behaviour.

See [usage, recovery and advanced controls](docs/USAGE.md) for budgets, receipts, host markers, optional models and known limits, or the [industrial architecture](docs/industrial-compaction-v1.2.md) for format and Unicode design.

## Reproduce the checks

From a checkout of this repository:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python benchmarks/run_battery.py
python benchmarks/threshold_sweep.py
```

Release verification: **1,179 tests passed / 3 skipped**, wheel/source builds and installed-wheel Python/CLI smoke checks. Timing tests depend on hardware and runtime conditions; `python -m pytest -q -m 'not perf'` omits the marked scaling tests. The battery rewrites its results JSON with local timings. Historical external comparison setup is documented in [COMPARISON.md](benchmarks/COMPARISON.md).

## Credits and support

Built by **The White Mage**. Research and ecosystem acknowledgements, including LCC/JEV, Headroom, SelfCompact, PAACE, TPC, Compactor and ARC-style recovery, are recorded in the [research digest](docs/RESEARCH.md) and [changelog](CHANGELOG.md).

- [Follow @0xWhiteMage on X](https://x.com/0xWhiteMage)
- [Support on Ko-fi](https://ko-fi.com/0xwhitemage)
- [Report an issue or contribute](https://github.com/0xWhiteMage/tameru-compaction-system/issues)

Released under the [MIT licence](LICENSE).
