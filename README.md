# Tameru (ためる)

<p align="center">
  <img src="assets/header.png" alt="The White Mage — Tameru Compaction System" width="100%"><br><br>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-v1.9.0-blue.svg" alt="Version 1.9.0"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python 3.10 and above"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/core-standard_library-orange.svg" alt="Standard-library core"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="Apache 2.0 licence"></a>
  <a href="#integrations"><img src="https://img.shields.io/badge/harness-agnostic-8A2BE2.svg" alt="Harness-agnostic engine"></a>
  <a href="https://x.com/0xWhiteMage"><img src="https://img.shields.io/badge/X-@0xWhiteMage-000000?logo=x&logoColor=white" alt="Follow 0xWhiteMage on X"></a>
  <a href="https://ko-fi.com/0xwhitemage"><img src="https://img.shields.io/badge/Ko--fi-support-FF5E5B?logo=ko-fi&logoColor=white" alt="Support on Ko-fi"></a>
</p>

**Deterministic, query-aware context compaction for long-running AI agents. Local, fail-open, with recoverable originals.**

Long agent sessions get expensive in a predictable way: bulky tool output (build logs, test runs, `grep` dumps, API responses) stays in the context and is paid for on every
later turn. Tameru shortens that output to the part the task needs, keeps every distinct error, and hands back the original text whenever it is unsure:

- **Shorten the bulk, keep the evidence.** An extract chosen against the question you are working on, not a blind head-and-tail cut. Every distinct error survives.
- **No new bill.** No LLM call, no GPU, nothing beyond Python's standard library. The default engine is deterministic: about 3 ms for a typical input, the same answer every run.
- **Fail open.** Ambiguous, malformed or low-saving input returns the exact original. Output that looks like a credential is never stored.
- **Recoverable.** A cut can point to its original (optional, off when you want no persistence), so a host can let the agent read any stretch back.

It is a Python function, a command-line tool and a transcript adapter. It has no dependency on any agent harness; harness plugins are separate repositories that vendor this
engine unchanged (see [Integrations](#integrations)).

![A terminal recording: tameru-compress turns a 200-line Gradle build log into 20 lines that keep the failing test, its assertion and the build result](assets/demo-cli.gif)

*Recorded output of the real engine (rendered by [`scripts/render_demo_gif.py`](scripts/render_demo_gif.py) from what `compress_context` returns): 200 lines in, 20 out, 93% fewer tokens, and the failing test, its assertion and the build result are all still there.*

[Why Tameru](#why-tameru) · [Use it](#use-it) · [Integrations](#integrations) · [Install](#install) · [Engine results](#engine-results) · [Recovery and limits](#recovery-and-limits) · [Documentation](#documentation)

## Why Tameru

| You want to… | Tameru gives you… |
|---|---|
| Stop re-paying for the same 600-line log on every turn | **Shortened tool output**: a query-aware extract that keeps every distinct error, with the original one call away. |
| Trust that nothing important was thrown away | **Recoverable originals** and per-call diagnostics (tokens, savings, risk, verifier result) so you can see what was kept and what was dropped. |
| Run it anywhere, offline | A pure-Python core with no model call, a CLI for any language, and a message-list adapter for any harness. |
| Read logs, diffs, reports and tables the way they are written | Structure-aware handling: SARIF, notebooks, Kubernetes, Git, LCOV, JUnit, unified diffs, grep output, shell and OS tool output. |
| Work in your language | Script-aware matching, tested across 20 script and language families, including Japanese, Chinese and Arabic. |

Safety defaults: output that looks like a credential is never stored, and when the engine is unsure it returns the original text.

## Use it

### Python

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
```

Supply the task's question alongside the source text. The example uses the default extractive strategy and disables recovery persistence: 5,342 characters in, 266 out
(95.0% fewer tokens), with the two linking facts (**Project Orion → warehouse Cedar → endpoint DB-EU-7**) intact. [API options and receipts →](docs/USAGE.md)

### Command line

`tameru-compress` is installed with the package and works from any language or shell:

```bash
tameru-compress build.log "Why did the build fail?" --no-ccr
tameru-compress build.log "Why did the build fail?" --no-ccr --stats    # JSON diagnostics, then ---, then the extract
cat build.log | tameru-compress - "Find the active error" --no-ccr        # read stdin
tameru-compress notes.md "What is the backup host?" --mode fixed --budget-ratio 0.3 --no-ccr   # ask for a smaller extract
```

| Option | What it does |
|---|---|
| `--no-ccr` / `--ccr` | Turn the reversible recovery store off or on (on by default). |
| `--citations` / `--no-citations` | Mark dropped blocks with a citation (on by default). |
| `--stats` | Print JSON diagnostics (tokens, savings, risk, verifier), then `---`, then the extract. |
| `--mode {adaptive,fixed,compiler,precision}` and `--budget-ratio R` | Ask for a smaller extract; lower ratios request less text. |
| `--strategy {clear,extract,summarise,auto}` | `extract` (default, no model), `clear` (drop tool payloads), `auto` (extract, escalate only if extraction fails open). |
| `--pin-recent N` | Always keep the first block and the newest N blocks. |
| `--min-savings-ratio R` | Return the original when the achieved savings fall below this ratio (0 disables). |
| `--derive-query` | On an empty or generic query, infer a conservative objective from recurring rare terms instead of failing open. |

### Message lists

For an OpenAI-style transcript, the generic adapter prunes old tool results in place and leaves everything else alone. The [integration guide](docs/INTEGRATION.md) covers
message lists, task-derived queries and keeping vendored copies current.

## Integrations

The engine is the same everywhere. A harness plugin adds what is specific to that harness: when to act, how to show it, where to keep state. Each plugin lives in its own
repository and vendors this engine unchanged.

| Harness | Plugin | State | What it adds |
|---|---|---|---|
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | [hermes-tameru-plugin](https://github.com/0xWhiteMage/hermes-tameru-plugin) | Released, **1.9.1**, listed in the Hermes plugin catalogue | Adaptive policy and self-tuning, pinned instructions, Keep and Restore, the Artifact Trail, a Desktop panel and `/tameru` commands |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | `dsh-tameru` (new) | In development, not released | Planned: the same functions on the Harness's own extension points |

Each plugin has its own version, independent of this engine's. The plugin README is the place for that harness's install steps, commands, screenshots and cost
measurements, which are measured against that harness's own stock behaviour and do not carry over to another harness. To integrate Tameru with another harness, see
[Writing a harness plugin](docs/INTEGRATION.md#4-writing-a-harness-plugin) and the [repository guide](docs/REPOSITORIES.md).

## Install

Requires **Python 3.10+**.

Install the verified **1.9.0** source, pinned to its commit:

```bash
python -m pip install "git+https://github.com/0xWhiteMage/tameru-compaction-system.git@9f1f1c4"
```

That commit is the engine code of 1.9.0 (later commits change documentation only). No release tag, GitHub Release page or PyPI package is published yet.

To use Tameru inside a harness, install that harness's plugin from the [Integrations](#integrations) table instead; it brings its own copy of the engine, so updating the plugin
updates the engine.

## Engine results

<!-- tameru:headline:start -->

| Mean characters saved | Required strings retained | Forbidden strings retained | Median wall time |
|:---:|:---:|:---:|:---:|
| **82.4%** | **25/25** | **0** | **3.05 ms** |

Measured on Tameru **1.9.0** on **16 shared task cases**, 2026-11-11 (Windows 11, Python 3.13, CPU only). These are source-evidence checks on Tameru's regression corpus; agent answer accuracy and model-token costs are outside this evaluation.

<!-- tameru:headline:end -->

<!-- tameru:comparison:start -->

**Same input. Same query. Same 16 tasks**, covering documents, configuration, Git/npm/YAML output, multilingual text, saturated grep, captured pytest and numbered-source cases (Windows 11, Python 3.13, 1 warmup and 5 timed calls per case):

| Method | Required strings kept | Forbidden strings ↓ | Clean cases | Mean chars saved ↑ | Median wall time ↓ |
|---|---:|---:|---:|---:|---:|
| **Tameru v1.9.0** | 25/25 | 0 | 16/16 | 82.4% | 3.05 ms |
| TF-IDF paragraph baseline | 22/25 | 5 | 9/16 | 53.4% | 0.10 ms |

**A clean case keeps every required string and excludes every planted forbidden string.** Savings are the arithmetic mean per case; wall time is the median of per-case medians.
Third-party methods (LCC, Headroom, Laya) were measured on an earlier release, have not been re-run for 1.9.0, and are reported separately in the [full comparison](benchmarks/COMPARISON.md).

[Complete comparison and per-task results →](benchmarks/COMPARISON.md) · [1.9.0 run, raw →](benchmarks/comparison-v1.9.0.json)

<details>
<summary><strong>Evaluation details: corpus, methods, timing and limits</strong></summary>

**Corpus.** All scored methods see identical text and task queries. The 16 cases include 25 required source strings plus planted stale, excluded or distracting strings. The large synthetic performance case and empty-query case belong to the separate release QA battery.

**Metrics.** Required strings must survive every output; a forbidden string in any output counts as a leak. Character savings measure text length, rather than model tokens or monetary cost. These checks cover specified fixture evidence and do not measure downstream agent answers or every possible semantic loss.

**Methods.** Tameru uses default extraction with `ccr=False`, `citations=True`. TF-IDF is a simple paragraph-retrieval baseline.

**Timing.** One untimed warmup and 5 timed complete calls per case. Parsing, scoring and rendering are inside the timer; imports are outside it. Hardware and scheduling affect latency. Tameru remembers analyses of repeated identical text, so this repeat-timing protocol flatters it.

**Runtime and provenance.** Python 3.13.17 on Windows 11 (AMD64, 16 logical CPUs), engine commit `cab2edc`; package versions and every timing sample are in `benchmarks/comparison-v1.9.0.json`.

**Interpretation.** This is Tameru's own regression corpus, including adversarial fixtures. Broader independent and live-agent evaluations are still needed to establish generality.

</details>

<!-- tameru:comparison:end -->

### Where the engine helps

| Your agent is reading… | Tameru focuses on… |
|---|---|
| Pages of logs around a failure | Error fingerprints, relevant messages, hosts and ports |
| Search results repeating the same name | Matching definitions and assignments, distinct matches and file context |
| A failed test with long captured output | The failure, recognised errors, warning-or-higher lines and section boundaries |
| Configuration containing an old value and a later override | The current value and its qualifier when supersession is explicit |
| A document with an answer spread across sections | Related entities and the source facts linking them |
| Git history, JSON, CSV or YAML dumps | Relevant records with enough structure to interpret them |

<details>
<summary><strong>Formats and languages</strong></summary>

| Input | Handling |
|---|---|
| Terminal and build logs | ANSI handling, repeated-template reduction, structured (logfmt/JSON) levels, error exemplars and last-occurrence retention |
| Numbered source reads | `cat -n` and common `read_file` gutters; code stays recognisable |
| Unified diffs and grep/rg | Hunk or file grouping, query matches, headers and saturated-query selection |
| Pytest (incl. quiet mode), Jest, Go, Cargo, Gradle, RSpec, PHPUnit, dotnet test, Maven Surefire | Failure evidence and summaries, with conservative handling of unknown surrounding lines |
| kubectl output | `describe`, `get events`, `get pods`, `top` and `rollout status` reducers; events collapsed and only abnormal node Conditions kept |
| Linux, macOS and Windows tool output | syslog/journal/dmesg, macOS unified log, `ps aux`, `top`, `vmstat`, `df`, `ping`, `traceroute`, `netstat`, `nmap`, `ipconfig /all`, `systeminfo`, PowerShell tables and error records, msiexec logs and `sysctl`/`pg_settings` listings: normal rows fold, outliers and failures stay |
| Build, package and container tools | Docker build, `docker ps`/`docker compose ps`, Terraform plans, Ansible, CMake, cargo, bundlers, pip/npm/yarn/composer installs, `npm ls`, `npm audit`, `pip freeze`, `apt`, lint and type checkers |
| Service logs | nginx, Apache, Redis, PHP, MySQL slow query, HAProxy, klog, web access logs and logfmt |
| Structured reports | SARIF findings, notebook cells, Kubernetes identity and status, whole Git log entries and patches, LCOV records, JUnit testcases: selected records keep their raw byte spans |
| JSON/NDJSON and CSV/TSV | Query-aware records, quote-aware framing, headers, and summaries (one example, unusual and matching records, a count) for large arrays, JSON Lines and tables |
| Markdown | Heading ancestry, fenced-code protection and outlier rows for large pipe tables |
| YAML, XML/HTML, SQL, INI/TOML-style sections | Conservative format-specific selection; ambiguous shapes can decline specialised reduction |
| Text extracted from OCR or vertical layouts | Matching in logical source order; text extraction happens upstream |

Script-aware matching has regression coverage across **20 script/language families**, including Japanese, Chinese and Arabic release cases. Matching uses a normalised shadow while extracts retain the source text. Accented query words stay whole, question words and generic asks count as filler in 20 languages besides English, and the opt-in no-query `prose_brief` splits sentences in Latin scripts, CJK, Thai, Devanagari and Arabic so templated repeats can fold. Coverage varies by language and task; Tameru accepts text and relies on upstream tools for OCR.

</details>

### Release QA battery

The separate **15-case release QA battery passes every case** on v1.9.0. All required answer strings survive, and no planted forbidden strings leak. These figures use **estimated tokens**, whereas the comparison above measures **characters**.

| Workload | Evidence checked | Estimated token savings |
|---|---|---:|
| **Documents and configuration** | | |
| Lexical distractor | Required backup host; distracting glossary excluded | **96.7%** |
| Multi-hop document | Endpoint linked through its warehouse | **95.0%** |
| Release evidence chain | Release alias, deployment identifier and checksum | **95.6%** |
| Current configuration | New timeout; explicitly superseded value excluded | **90.1%** |
| Negation and override | “Not enabled”; obsolete enabled state excluded | **92.5%** |
| Ambiguous configuration | Required value retained without an explicit supersession marker | **88.4%** |
| Excluded sample | Operational host; excluded example absent | **87.3%** |
| YAML configuration | Distro and language; excluded dependency absent | **76.0%** |
| **Agent tool outputs** | | |
| Git history | Required commit hash | **94.0%** |
| npm log | Requested Playwright version | **31.0%** |
| **Multilingual text** | | |
| Japanese document | Required layer count | **46.8%** |
| Chinese needle case | Required backup host | **90.9%** |
| Arabic needle case | Required backup host | **88.6%** |
| **Robustness** | | |
| Large synthetic document | Savings, repeatability and timing; no answer-string check | **99.9%** |
| Empty query | Original input returned | **0.0%** |

The 4,000-record synthetic document completed in about **140 ms wall time** (the gate is 1,200 ms). Its maximum saving is specific to that input. Token counts use Tameru's estimator; savings with a model's own tokenizer will vary. [Full release results →](benchmarks/production-qa-v3-results.json)

### Choose a context budget

Use `mode="fixed"` and `budget_ratio` to request a smaller extract. Lower ratios request a smaller budget for compressible content; pinned evidence can exceed that budget.

| `budget_ratio` | Mean character savings | Clean release cases |
|---:|---:|---:|
| 0.1 | **77.8%** | 15/15 |
| 0.2 | **69.9%** | 15/15 |
| 0.3 | **61.9%** | 15/15 |
| 0.5 | **41.7%** | 15/15 |
| 0.7 | **24.8%** | 15/15 |

Every operating point retained all required strings with no forbidden leaks in this corpus. Validate the evidence your own tasks need before choosing a ratio. [Replay the sweep →](benchmarks/threshold_sweep.py)

## Recovery and limits

**Recovery is optional.** The standalone API defaults to `ccr=True`; a successful store write can attach a pointer to the original context. Retrieval needs valid, unexpired records and a host that can follow that pointer. Set `ccr=False` when you do not want persistence or your host has no retrieval path.

**Evidence retention is task-dependent.** Extraction can miss relationships with no shared terms, and source lines impose a minimum output size. Weak queries, malformed input or insufficient savings can return the original text. Required-string checks measure fixture evidence, rather than an agent's final-answer accuracy.

<details>
<summary><strong>Storage, credentials and optional model paths</strong></summary>

Credential screening is heuristic. It gates recovery-cache writes; it does not redact returned text or encrypt the cache. A citation alone does not establish that an original was successfully stored.

The default `strategy="extract"` makes no LLM call. Optional `summarise`/`auto` strategies and semantic-model paths have separate dependencies and inference behaviour. Default extraction adds no LLM inference charge; local CPU work still consumes resources.

The [usage guide](docs/USAGE.md) explains budgets, recovery, receipts, host markers, optional models and known limits.

</details>

## Reproduce the checks

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python benchmarks/run_battery.py
python benchmarks/threshold_sweep.py
python benchmarks/compare.py --verify-against benchmarks/comparison-v1.9.0.json
```

Verification (2026-11-11): **2,016 tests passed / 4 skipped** (plus 146 subtests), **15/15 release QA cases**, and the comparison run reproducing its recorded output with **0 differing fields** over the 16 cases. Timing tests depend on hardware; the battery rewrites its JSON with your local timings.

`compare.py --verify-against` exits non-zero if any output hash, saving or retention result differs; timings are not compared. `--render-from` regenerates the figures and tables in this section from a completed report of the same engine version. The [comparison report](benchmarks/COMPARISON.md#reproduce) lists the pins and commands for the third-party methods.

## Documentation

| Start here | Find out how to… |
|---|---|
| [Integrations](#integrations) | Find the plugin for your harness: install steps, commands, screenshots and cost measurements live in each plugin's own README |
| [Usage and API](docs/USAGE.md) | Set budgets, inspect receipts, configure recovery and use advanced controls |
| [Repositories](docs/REPOSITORIES.md) | See what this engine repository owns and what each harness plugin repository owns |
| [Agent integration](docs/INTEGRATION.md) | Apply compaction in a host framework, write a harness plugin and keep vendored copies current |
| [Comparisons](benchmarks/COMPARISON.md) | Inspect every task, provider setting, timing sample and measurement limitation |
| [Release notes](docs/releases/v1.9.0.md) and [changelog](CHANGELOG.md) | Review this release's changes and the version history |
| [Red-team findings](benchmarks/redteam/FINDINGS-1.9.0.md) | Read what 228 adversarial cases found and what was fixed ([notes](benchmarks/redteam/NOTES-1.9.0.md)) |
| [Architecture](docs/ARCHITECTURE.md) | Understand the format adapters, Unicode handling and bounded-work limits |
| [Research digest](docs/RESEARCH.md) | Follow the research and ecosystem work behind the project |

## Credits and support

Built by **The White Mage**. Tameru (ためる) means “to store up”. Research and ecosystem acknowledgements, including LCC/JEV, Headroom, SelfCompact, PAACE, TPC, Compactor and ARC-style recovery, are recorded in the [research digest](docs/RESEARCH.md) and [changelog](CHANGELOG.md).

[Follow on X](https://x.com/0xWhiteMage) · [Support on Ko-fi](https://ko-fi.com/0xwhitemage) · [Report an issue](https://github.com/0xWhiteMage/tameru-compaction-system/issues) · [Contribute](https://github.com/0xWhiteMage/tameru-compaction-system/pulls)

Released under the [Apache License 2.0](LICENSE).
