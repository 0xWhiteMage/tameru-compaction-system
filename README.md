# Tameru (貯める) — Context compaction for LLM agents

<p align="center">
  <img src="assets/header.png" alt="Tameru Compaction System (貯める)" width="100%"><br><br>
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-v1.4.1-blue.svg" alt="Version 1.4.1"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT licence"></a>
  <a href="tests/"><img src="https://img.shields.io/badge/tests-1172%20passed-success.svg" alt="1172 tests passed"></a>
  <a href="benchmarks/run_battery.py"><img src="https://img.shields.io/badge/QA-15%2F15-brightgreen.svg" alt="15 of 15 QA cases passed"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/core-Python%20stdlib-orange.svg" alt="Python standard library core"></a>
</p>

**Tameru (貯める) — Japanese for “to store up”.** Reduce bulky agent context while keeping the evidence needed for the current task.

The default extraction path runs locally, uses no LLM and adds **$0 in LLM inference charges**. It retains task-relevant source text, collapses repetitive noise and returns the original input when its safety gates decline compaction. Optional recovery storage lets an integration retrieve omitted content later.

- **Keep useful evidence:** query-aware selection, error retention and restoration of related definitions and qualifiers.
- **Spend less context:** successful cases in the release QA battery save **31–99.5% estimated tokens**, depending on workload.
- **Stay reproducible:** extraction is deterministic for identical inputs and configuration; stored recovery metadata may include timestamps.
- **Run without a GPU or runtime dependencies:** Python **3.10+**, standard library only for the default path.

**Source version: v1.4.1. The GitHub tag and Release are pending publication.**

**v1.4.1** improves saturated grep results, long pytest captured logs, host omission-marker overhead and credential screening. See [what changed](#whats-new-in-v141) and the [full changelog](CHANGELOG.md).

## Quickstart

Install the reviewed v1.4.1 source commit from GitHub while the tag is pending:

```bash
python -m pip install "git+https://github.com/0xWhiteMage/tameru-compaction-system.git@dbe40619b9ebcb1595269809dd9f963b1c246015"
```

Or install from a checkout:

```bash
git clone https://github.com/0xWhiteMage/tameru-compaction-system.git
cd tameru-compaction-system
git checkout dbe40619b9ebcb1595269809dd9f963b1c246015
python -m pip install -e .
```

### Python

```python
from tameru.compress_context import compress_context

context = (
    "[INFO] Routine worker heartbeat.\n" * 500
    + "[ERROR] DB connection failed on db-prod-01: port 5432 unreachable.\n"
)
result = compress_context(
    context,
    "Why did the database connection fail?",
    ccr=False,  # no recovery-store writes for this example
)
print(result.compressed_text)
print(f"Estimated token savings: {result.tokens_saved_pct:.1f}%")
print(f"Returned original input: {result.fail_open}")
```

### CLI

```bash
tameru-compress context.txt "Why did the database connection fail?" --no-ccr --stats
cat context.txt | tameru-compress - "Find the active error" --no-ccr --stats
```

The CLI writes compacted text to stdout. With `--stats`, it prints JSON diagnostics first, followed by `---` and the compacted text. Use a task-specific query: “continue” often provides too little signal.

## What's new in v1.4.1

| Improvement | What it changes |
|---|---|
| **Saturated grep/rg results** | When the query hits at least 80% of matches and the result is large enough, selection prioritises matching definitions and assignments, other query words and distinct match text. This addresses definition loss in a host's shortened view. |
| **Command-aware selectors** | Flags such as `-n` and `--stat` no longer crowd out the searched name when a host includes the command in its query. |
| **Pytest captured output** | Long captured log/stdout/stderr sections retain their first and last lines, recognised error fingerprints and WARNING/ERROR/CRITICAL/FATAL lines. Blank lines no longer terminate sections prematurely. |
| **Smaller host-marker overhead** | Consecutive fully omitted grep files share one caller-supplied omission marker while retaining their file headers. |
| **Opt-in short-gap inlining** | `inline_short_gaps=True` keeps a dropped span verbatim when its marker would be at least as long. Applies to extraction and grep/pytest cuts; `brief_context` accepts an `InliningGapMarker` wrapper. Off by default. |
| **Credential-screen hardening** | Adds Google API keys, Stripe live keys, bearer tokens and whole-line env/YAML credential assignments; avoids common code-expression false positives. Screens recovery persistence, not output redaction. |
| **BOM-tolerant file reads** | CLI context, decision-cache and recovery-cache files accept BOM-prefixed UTF-8 from Windows tools. String API input and stored originals retain their text. |
| **Integration maintenance** | Behaviour-neutral Ruff changes for Hermes vendoring and a portable deep-malformed-cache regression test. |

The release battery and budget sweep retain the previous savings. Affected grep and pytest cases intentionally change; unchanged benchmark output is not a guarantee that every v1.4.0 input produces identical output in v1.4.1.

## Release verification and measured results

The v1.4.1 release checks cover **1,172 passed / 3 skipped** pytest tests and **15/15** production-QA cases. The battery checks required answer strings, forbidden distractors, repeat-output determinism, savings, fail-open behaviour and a large-input timing gate. These are fixture-level checks, not a guarantee of downstream model accuracy.

Selected measurements from the [release battery](benchmarks/production-qa-v3-results.json):

| Workload | Estimated token savings |
|---|---:|
| Large synthetic document | 99.5% |
| Multi-hop evidence chain | 95.0% |
| Git history | 94.0% |
| Chinese needle case | 90.9% |
| Arabic needle case | 88.6% |
| YAML configuration | 64.7% |
| Japanese document | 57.5% |
| npm log | 31.0% |
| Empty query, fail-open | 0.0% |

Latency depends on workload and hardware. The battery enforces a **1,200 ms CPU-time** budget for its 4,000-record synthetic document; per-case timings are in the JSON. Savings use Tameru's token estimator, not a model-specific tokenizer.

The [budget sweep](benchmarks/threshold_sweep.py) retains all required gold strings with zero forbidden-distractor leaks at every tested operating point:

| `budget_ratio` | Mean character savings | Clean cases |
|---:|---:|---:|
| 0.1 | 77.3% | 15/15 |
| 0.2 | 68.4% | 15/15 |
| 0.3 | 61.2% | 15/15 |
| 0.5 | 41.5% | 15/15 |
| 0.7 | 24.9% | 15/15 |

The sweep measures **characters**, whereas the battery reports **estimated tokens**. Neither is a universal compression ratio.

### Historical comparisons

The six-arm comparison was measured on **Tameru v1.3.0**, not v1.4.1. On that 12-case corpus, Tameru retained 12/12 gold cases, kept zero forbidden distractors, averaged 81.0% savings and had a 10.75 ms median latency. JEV ran 11 cases because the large case was skipped for API cost.

The older 17-case holdout was measured on **v1.2.0**. External comparison arms have **not** been rerun for this release. See [COMPARISON.md](benchmarks/COMPARISON.md) for original tables, versions, methodology and limitations.

## Formats and language coverage

Tameru operates on **text**, including text extracted upstream from other media. It does not perform image recognition or OCR itself.

| Input | Handling |
|---|---|
| Terminal/build logs | ANSI handling, template deduplication, error exemplars and last-occurrence retention |
| Numbered source reads | Recognises `cat -n` and common `read_file` gutters; avoids treating code as tabular data |
| Unified diffs | Whole-hunk selection, hunk headers and per-file change summaries |
| Grep/rg output | File grouping, query matches and saturated-query handling |
| Pytest, Jest, Go and Cargo output | Failure evidence and summaries, with conservative retention of unknown surrounding lines |
| JSON and NDJSON | Query-aware structured processing; exact raw-record selection where applicable; JSON briefs for large object arrays |
| CSV/TSV | Quote-aware records, header retention and embedded-newline handling |
| Markdown | Heading ancestry and fenced-code protection |
| YAML, XML/HTML, SQL, INI/TOML-style sections | Conservative format-specific selection; ambiguous or unsafe shapes decline specialised reduction |
| Vertical-source OCR text | Logical-source-order matching and column framing on already extracted text |

Script-aware matching and profiling cover 20 script/language families, with multilingual regression fixtures and Japanese, Chinese and Arabic release-battery cases. This is **tested coverage**, not complete semantic support for every language or writing system.

Matching uses a separate normalised shadow. Unicode handling preserves logical source order rather than applying visual bidi reordering. Direction profiles, grapheme handling and configurable bidi limits are described in the [industrial specification](docs/industrial-compaction-v1.2.md).

## Safety, recovery and limitations

### Fail-open and evidence checks

Weak query signal, ambiguity and insufficient savings can cause extraction to return the original input. Industrial preflight bounds input size, lines, records, fields, query size and bidi controls. Malformed or unsafe inputs can also fail open. Receipts expose selection paths, diagnostic risk, evidence checks and dependency restorations.

These checks address known failure modes; they do not prove that every fact needed for a future task survives. Extraction can miss semantic connections without shared terms. Query changes, unusual formats and aggressive budgets can reduce usefulness. Inspect receipts and validate the evidence your integration requires.

### Recovery storage (CCR)

The standalone API defaults to `ccr=True`. When storage succeeds, a recovery pointer allows retrieval of the original context. Omission citations and retrieval markers are distinct: a citation alone is not proof that recoverable content was stored.

```python
from tameru.compress_context import retrieve

# Use a real hash returned by your recovery store:
# original = retrieve(record_hash)
# page = retrieve(record_hash, offset=0, limit=2000)
```

`list_ccr(ccr_dir, offset=..., limit=...)` lists live records; `sweep_ccr_cache()` performs bounded cleanup. Recovery requires enabled storage, a successful write, unexpired valid records and a usable retrieval path. The secrets screen skips CCR writes for probable credentials. Files use owner-only permissions where POSIX modes are supported and writes are atomic. Use `ccr=False` when the host has no recovery path or persistence is unwanted.

**Credential screening is heuristic.** It does not redact returned text, guarantee detection of every secret or encrypt the cache. Code-shaped values such as `password = settings_default_password` are a documented detection gap.

### Optional model-backed paths

`strategy="extract"` is the default and uses no LLM. `strategy="summarise"` can invoke a configured model; `strategy="auto"` tries extraction first and may escalate when extraction fails open. LLM failure falls back to extraction.

Configure `summary_endpoint`, `summary_models` and `summary_timeout` per call, or `TAMERU_SUMMARY_ENDPOINT`, `TAMERU_SUMMARY_MODELS` and `TAMERU_SUMMARY_TIMEOUT`. The timeout is one total retry budget across models. Endpoints are loopback-only by default; remote endpoints require `summary_allow_remote=True` or `TAMERU_SUMMARY_ALLOW_REMOTE=1` and may incur inference charges and transmit context.

An optional semantic extra installs `sentence-transformers`; it is outside the standard-library dependency claim:

```bash
python -m pip install -e '.[semantic]'
```

## Agent integration

Use the Python API for individual tool results, the CLI for non-Python hosts, or the generic transcript adapter for OpenAI-style message lists:

```python
from tameru.transcript import apply_extractive_tool_prune

messages, n_changed = apply_extractive_tool_prune(
    messages,
    query="Diagnose the deployment failure",
    min_chars=800,
    protect_last_tool=2,
)
```

The transcript adapter disables CCR and citations, skips failed/non-shrinking results and protects recent tools. Its timing gate suppresses this prune step during pending tool calls or repeated-call loops; it does not control other compaction performed by the host.

### Hermes

Use the maintained [hermes-tameru-plugin](https://github.com/0xWhiteMage/hermes-tameru-plugin). Follow its installation and recovery-store instructions, then select:

```yaml
context:
  engine: tameru
```

The engine and plugin are separate repositories. An engine release does not automatically update an installed or vendored plugin. See [harness integration](harnesses/README.md) for API/CLI contracts, task-derived queries and vendored-copy synchronisation.

### Host controls

```python
from tameru import unwrap_tool_payload, rewrap_tool_payload
from tameru.compress_context import compress_context

payload = unwrap_tool_payload(tool_result_text)
result = compress_context(
    payload.inner, query,
    ccr=False,
    citations=False,
    content_hint="grep",
    gap_marker=lambda omitted, total: f"[... {omitted} of {total} chars omitted ...]",
    inline_short_gaps=True,
    recursion_markers=("[my-plugin: compacted",),
)
out = rewrap_tool_payload(payload, result.compressed_text)
```

Envelope fields such as exit codes survive rewrapping. `gap_marker` replaces cut markers when citations are disabled. `brief_context` accepts an `InliningGapMarker` wrapper directly; the Boolean convenience flag belongs to `compress_context`.

## Advanced controls and architecture

| Control | Purpose |
|---|---|
| `mode="fixed"`, `budget_ratio` | Budget the compressible portion; pinned evidence remains protected |
| `pin_recent=N` | Retain the opening block and newest N blocks |
| `min_savings_ratio` | Decline reductions below the savings floor; default 0.10 |
| Multiple query strings | Score against the union of current and planned tasks |
| `derive_query=True` | Infer a bounded lexical objective for empty/generic queries; reports derived terms and raises the risk floor |
| `decision_cache` | Freeze first-sight block decisions; bounded to 4,096 entries; frozen keeps may exceed a later requested ratio |
| `degraded_view=True` | Opt-in bounded head/tail scoring for certain oversized inputs; preserves safety limits and raises the risk floor |
| `IndustrialLimits` | Configure character, line, record, field, query and bidi limits |

The default pipeline combines bounded preflight, format adapters, lexical/entity/structural scoring, graph and dependency rescue, emission and diagnostic verification. Dependency rescue can restore related definitions or qualifiers; trust and supersession rules address known distractor and stale-state patterns. These are deterministic heuristics, not a semantic judge or a general prompt-injection defence.

The recursion guard avoids compacting recognised Tameru output again. `inspect_compressibility()` estimates duplicate-removal headroom. `fold_lossless`, `error_fingerprints`, `brief_context` and `extract_evidence_lines` are available for host-specific reduction.

For implementation details, see [the source](src/tameru/), [industrial architecture](docs/industrial-compaction-v1.2.md) and [research digest](docs/RESEARCH.md). Research inspiration is documented separately from implemented mechanisms.

## Reproduce the release checks

From the reviewed v1.4.1 source checkout:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m pytest -q -m 'not perf'  # optional: omit timing-ratio scaling tests
python benchmarks/run_battery.py
python benchmarks/threshold_sweep.py
python scripts/sync_to_harness.py <plugin>/tameru --manifest ../plugin.yaml --check
```

The battery rewrites its results JSON with local timings. Timing tests depend on hardware and runtime conditions. The external comparison requires additional dependencies/models and, for JEV, provider access; it is outside this release's offline verification.

## Credits and support

Built by **The White Mage**. Research and ecosystem acknowledgements, including LCC/JEV, Headroom, SelfCompact, PAACE, TPC, Compactor and ARC-style recovery, are recorded in [RESEARCH.md](docs/RESEARCH.md) and [CHANGELOG.md](CHANGELOG.md).

- [Follow @0xWhiteMage on X](https://x.com/0xWhiteMage)
- [Support on Ko-fi](https://ko-fi.com/0xwhitemage)
- [Report an issue or contribute](https://github.com/0xWhiteMage/tameru-compaction-system/issues)

Released under the [MIT licence](LICENSE).
