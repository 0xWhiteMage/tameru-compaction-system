# ⚡ Tameru (貯める) — Industrial Extractive Context Compaction for LLM Agents

<p align="center">
  <img src="assets/header.png" alt="Tameru Compaction System (貯める)" width="100%"><br><br>
  <a href="LICENSE"><img src="https://img.shields.io/badge/release-v1.2.0-blue.svg?style=for-the-badge" alt="Version 1.2.0"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=for-the-badge" alt="License: MIT"></a>
  <a href="tests/"><img src="https://img.shields.io/badge/tests-272%20passed-success.svg?style=for-the-badge" alt="Test Suite"></a>
  <a href="benchmarks/run_battery.py"><img src="https://img.shields.io/badge/production_QA_v3-13%2F13_green-brightgreen.svg?style=for-the-badge" alt="Production QA v3"></a>
  <a href="#-head-to-head-competitive-benchmark"><img src="https://img.shields.io/badge/large_case-%3C1.2s-purple.svg?style=for-the-badge" alt="Large-case latency"></a>
  <a href="#-core-design-tenets"><img src="https://img.shields.io/badge/determinism-100%25_reproducible-blueviolet.svg?style=for-the-badge" alt="Determinism"></a>
  <a href="#-why-tameru-the-problem-with-abstractive-summarization"><img src="https://img.shields.io/badge/dependencies-stdlib_only-orange.svg?style=for-the-badge" alt="Zero Dependencies"></a><br><br>
  <a href="https://x.com/0xWhiteMage" target="_blank"><img src="https://img.shields.io/badge/Follow_on_X-@0xWhiteMage-000000?style=for-the-badge&logo=x&logoColor=white" alt="Follow on X"></a>&nbsp;&nbsp;•&nbsp;&nbsp;
  <a href="https://ko-fi.com/0xwhitemage" target="_blank"><img src="https://img.shields.io/badge/Kofi-Buy_me_a_coffee-1A9642?style=for-the-badge&logo=buymeacoffee&logoColor=white" alt="Ko-fi"></a>
</p>

> **Named from 貯める (*tameru*) — Japanese for *"to save, store up, or accumulate."***  
> Tameru is a query-aware, deterministic, purely extractive context compaction engine for autonomous LLM agents. v1.2 adds bounded industrial preflight, Unicode-aware logical-order matching across 20 script/language families, exact format adapters, direction/security profiles, and configurable scale limits—without external LLM calls, GPU dependencies, or runtime dependencies.

---

## 📑 Table of Contents

- [💡 Why Tameru? (The Problem with Abstractive Summarization)](#-why-tameru-the-problem-with-abstractive-summarization)
- [🎯 Core Design Tenets](#-core-design-tenets)
- [🏗️ Architectural Blueprint & Data Flow](#️-architectural-blueprint--data-flow)
- [📐 Mathematical Formulation & Scoring Engine](#-mathematical-formulation--scoring-engine)
- [🛡️ 6-Stage Defensive Pipeline](#️-6-stage-defensive-pipeline)
- [🧩 Supported Modalities & Preprocessing Engine](#-supported-modalities--preprocessing-engine)
- [🌍 Unicode, Direction & Vertical Text](#-unicode-direction--vertical-text)
- [🏭 Industrial Limits & Format Contracts](#-industrial-limits--format-contracts)
- [📊 Head-to-Head Competitive Benchmark](#-head-to-head-competitive-benchmark)
- [🧪 The Production QA Battery (v3)](#-the-production-qa-battery-v3)
- [🔄 Reversible Compaction & ARC Citations (CCR Store)](#-reversible-compaction--arc-citations-ccr-store)
- [🔌 Hermes Context-Engine Plugin Integration](#-hermes-context-engine-plugin-integration)
- [🚀 Quickstart & Installation](#-quickstart--installation)
- [💻 Python API & Agent Integration](#-python-api--agent-integration)
- [📜 Changelog](#-changelog)
- [🙏 Credits & Research Lineage](#-credits--research-lineage)
- [🤝 Community & Support](#-community--support)
- [📄 License](#-license)

---

## 💡 Why Tameru? (The Problem with Abstractive Summarization)

Modern autonomous coding and research agents rapidly saturate their context windows (32k–128k+) with bulky tool outputs: `git log`, `npm test` traces, JSON API responses, database schemas, and multi-file diffs.

Traditional context reduction approaches fail in mission-critical agent workflows:

1. **Abstractive LLM Summarizers (e.g., secondary LLM calls)**:
   - **Slow & Expensive**: Adds 2–5 seconds of latency and doubles API costs per turn.
   - **Hallucinatory & Lossy**: Paraphrases lose critical hex hashes, line numbers, variable names, and exact error traces.
   - **Context Window Pressure**: Compressing a 100k context requires an auxiliary model with at least a 100k window.

2. **Naive Sliding Windows / Head-Tail Truncation**:
   - **Lost in the Middle**: Drops critical intermediate facts, configurations, and multi-hop clues located in the middle turns.

### The Extractive Alternative

**Tameru operates purely extractively.** Instead of generating new summary prose, it scores, filters, and retains original, verbatim text blocks while eliminating noise, repetition, and dead weight.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             RAW CONTEXT (500 KB)                            │
│  [Build Logs (80k)]  [Git History (40k)]  [JSON (120k)]  [Diffs (60k)] ...   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                        ⚡ TAMERU ENGINE (<1.2s at 500 KB, $0)
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      COMPACTED EXTRACTIVE VIEW (12 KB)                      │
│  ✓ Exact error trace (Lines 42-45 preserved verbatim)                       │
│  ✓ Active query entity references retained                                  │
│  ✓ Structural JSON/YAML skeleton preserved                                  │
│  ✓ 97.6% token reduction | 0 hallucinations | 100% byte-deterministic       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Core Design Tenets

Tameru adheres to a strict engineering contract:

- **Query-Aware Precision**: Scored against the user's active intent using sublinear BM25-IDF weighting, alphanumeric identifier extraction, and non-Latin script tokenization.
- **Strictly Deterministic**: Given the exact same context string and query, Tameru produces **byte-identical output** every single time, verified across arbitrary `PYTHONHASHSEED` values.
- **Fail-Open Contract**: If query signal is ambiguous, low-confidence, or zero-overlap, Tameru safely returns the original context rather than risking data corruption.
- **Reversible by Design**: Omitted sections are replaced with content-addressed ARC citation anchors (`[A hash] "head"..."tail"`), backed by a local Content-Centric Retrieval (CCR) store.
- **Zero External Dependencies**: Pure Python standard library (`re`, `json`, `difflib`, `math`, `typing`). No PyTorch, no HuggingFace, no network required for core operations.
- **Multi-Hop & Temporal Integrity**: Solves graph closure ($A \to B \to C$) across isolated tool outputs and prunes superseded obsolete statements.
- **Logical-Order Unicode Safety**: Profiles LTR, RTL, mixed and vertical-source text without visually reordering or rewriting caller bytes.
- **Bounded Industrial Work**: Enforces input, line, record, field, profile and bidi-control limits before expensive transforms.

---

## 🏗️ Architectural Blueprint & Data Flow

```
                                  USER QUERY
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │ 1. INDUSTRIAL PREFLIGHT       │
                      │    • Size / Line / Bidi Limits│
                      │    • Script / Direction Profile│
                      │    • Format Detection         │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │ 2. EXACT FORMAT ADAPTERS      │
                      │    • JSON/NDJSON / CSV / TSV  │
                      │    • Markdown / YAML / XML    │
                      │    • HTML / SQL / INI / OCR   │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │ 3. MULTI-SIGNAL SCORING       │
                      │    • Sublinear BM25-IDF       │
                      │    • Entity Density Anchoring │
                      │    • Temporal Supersession    │
                      │    • Trust & Injection Flags  │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │ 4. GRAPH CLOSURE & RESCUE     │
                      │    • Multi-Hop BFS Expansion  │
                      │    • Counterfactual Overlap   │
                      │    • Error-Signal Invariant   │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │ 5. REVERSIBLE ARC CITATIONS   │
                      │    • Content-Addressed Hashes │
                      │    • Lost-in-Middle Reorder   │
                      │    • Local CCR Persistence    │
                      └───────────────┬───────────────┘
                                      │
                                      ▼
                             COMPACTED CONTEXT
```

---

## 📐 Mathematical Formulation & Scoring Engine

Each discrete text block $b_i \in B$ is evaluated through a composite scoring function balancing lexical overlap, entity density, structural importance, and recency:

$$\mathcal{S}(b_i \mid q) = \mathcal{S}_{\text{lex}}(b_i, q) + \mathcal{S}_{\text{ent}}(b_i, q) + \mathcal{S}_{\text{struct}}(b_i) + \mathcal{S}_{\text{recency}}(b_i) - \mathcal{P}_{\text{trust}}(b_i) - \mathcal{P}_{\text{stale}}(b_i)$$

### 1. Sublinear Lexical BM25-IDF Overlap
To prevent repetitive term spamming from dominating relevance:

$$\mathcal{S}_{\text{lex}}(b_i, q) = \sum_{t \in b_i \cap q} \text{IDF}(t) \cdot \left(1 + \ln(1 + \text{tf}(t, b_i))\right)$$

Where $\text{IDF}(t) = \ln\left(1 + \frac{|B| - n(t) + 0.5}{n(t) + 0.5}\right)$.

### 2. Multi-Hop Graph Closure (BFS Bridge Expansion)
For multi-hop reasoning chains ($A \to B \to C$), if an evidence block $b_j$ shares a bridge entity $e$ with a high-scoring block $b_k$, its score is boosted proportional to graph distance:

$$\mathcal{S}_{\text{graph}}(b_j) = \max_{b_k \in B_{\text{kept}}} \left( \mathcal{S}(b_k \mid q) \cdot \gamma^{\text{hop-distance}(b_j, b_k)} \right), \quad \gamma = 0.65$$

### 3. Adaptive Selection Threshold
The selection floor $\theta_{\text{adaptive}}$ dynamically scales based on candidate distribution:

$$\theta_{\text{adaptive}} = \max\left(2.2, \min\left(11.5, 0.38 \cdot \max_{b \in B} \mathcal{S}(b \mid q)\right)\right)$$

---

## 🛡️ 6-Stage Defensive Pipeline

1. **Pre-Flight Gate**: Evaluates `inspect_compressibility()`. If repetition ratio is low or input is already compact, passes through unchanged.
2. **Log & Structural Preprocessing**: Performs count-preserving template deduplication (`[A-N] exemplar`), ANSI stripping, and JSON array flattening.
3. **Multi-Signal Scoring & Graph Closure**: Computes lexical, entity, structural, and graph-expansion scores.
4. **Defensive Invariant Checks**: Verifies that active errors, stack traces, and code fences are preserved intact (`error-signal invariant`).
5. **Lost-in-the-Middle Reordering (`reorder_best`)**: Places top-ranked evidence at the front and second-best at the tail to optimize LLM decoder attention.
6. **Self-Check Diagnostic Verifier**: Performs post-compaction validation:

$$\text{Confidence Score} = 0.50 \cdot \text{Recall(ent)} + 0.30 \cdot \text{Recall(kw)} + 0.20 \cdot \text{CriticalLineRatio}$$

---

## 🧩 Supported Modalities & Preprocessing Engine

| Modality | Specialized Processing | Typical Reduction |
|---|---|---|
| **Terminal & Build Logs** | Count-preserving deduplication, ANSI stripping, stack frame collapse | **90–96%** |
| **JSON Schemas & APIs** | Key-preserving array crushing, bounded nesting, exact selector matching | **75–88%** |
| **NDJSON / JSONL** | Per-record validation and exact raw-line selection | **80–99%** |
| **CSV / TSV** | Quote-aware record framing, header retention, embedded-newline safety | **70–95%** |
| **Markdown** | Heading ancestry and atomic fenced-code sections | **60–90%** |
| **YAML** | Parent-key plus matching-subtree retention; conservative decline on ambiguous prose | **60–90%** |
| **XML / HTML** | Exact line-oriented child selection with preserved wrappers; unsafe multiline shapes decline | **50–90%** |
| **SQL** | Quote/comment/dollar-string-aware statement selection | **60–95%** |
| **INI / TOML-style sections** | Complete matching-section retention | **60–95%** |
| **Git Dumps & Commit Logs** | Commit hash retention, author/subject line-record filtering | **80–92%** |
| **Code Diffs & Patches** | Structural fence invariant, changed-line hunk isolation | **65–80%** |
| **Multilingual / Mixed Direction** | Grapheme-safe logical-order matching across 20 script/language families | **60–95%** |
| **Vertical OCR Columns** | Blank-column framing with logical-source-order matching | **50–90%** |

---

## 🌍 Unicode, Direction & Vertical Text

Tameru never applies visual bidi reordering and never rewrites output into a
different normalisation form. Original substrings remain the source of truth.
A separate NFKC/case-folded matching shadow is used only for search.

- Extended grapheme tailoring keeps combining marks, variation selectors,
  emoji modifiers, flags, Indic virama sequences and ZWJ/ZWNJ sequences atomic.
- Direction profiles report `ltr`, `rtl`, `mixed`, or `neutral` using Unicode
  bidi classes. Explicit controls and overrides are counted separately.
- Script-aware query units cover Arabic, Hebrew, Persian/Urdu, Devanagari,
  Bengali, Tamil, Telugu, Thai, Lao, Khmer, Myanmar, Han, Kana, Hangul,
  Greek, Cyrillic, Armenian, Georgian, Ethiopic and Mongolian families.
- Space-free scripts use bounded grapheme n-grams; spaced scripts use logical
  word runs. ASCII keeps the original compiled-regex fast path.
- CSS `writing-mode` and one/two-grapheme OCR columns are metadata hints only;
  they never reverse or rotate source text.

See [`docs/industrial-compaction-v1.2.md`](docs/industrial-compaction-v1.2.md)
for the standards, tailoring decisions and invariants.

---

## 🏭 Industrial Limits & Format Contracts

Default limits are deliberately conservative and configurable per call:

| Limit | Default |
|---|---:|
| Input characters | 8,000,000 |
| Logical lines | 250,000 |
| Structured records | 100,000 |
| Characters per record | 1,000,000 |
| Fields per structured record | 4,096 |
| Unicode profile sample | 16,384 chars at each edge |
| Bidi controls | 10,000 |
| Bidi overrides | 128 |

If a hard limit, malformed surrogate, parser invariant, or structure check
fails, Tameru returns the caller's exact text before CCR writes or lossy work.
Adapters only activate when they produce a shorter structurally valid exact
subset; otherwise the v1.1 scorer remains the fallback.

```python
from tameru import IndustrialLimits
from tameru.compress_context import compress_context

limits = IndustrialLimits(
    max_input_chars=4_000_000,
    max_records=50_000,
    max_bidi_overrides=16,
)
result = compress_context(context_data, query, limits=limits)
profile = result.receipt["industrial"]["profile"]
```

Equivalent CLI controls are available as `--max-input-chars`, `--max-lines`,
`--max-records`, `--max-record-chars`, `--max-fields`,
`--max-profile-chars`, `--max-bidi-controls`, and `--max-bidi-overrides`.

---

## 📊 Head-to-Head Competitive Benchmark

Tested across 17 standardized production-QA fixtures containing multi-hop reasoning, temporal overrides, noisy logs, and structured sample text:

| Compaction System | Gold Fact Recall | Latency (avg) | Cost / 1k Ops | Deterministic | Dependencies |
|---|---|---|---|---|---|
| **⚡ Tameru (v1.2.0)** | **17 / 17 (100%)** | **4–956 ms observed; <1.2 s at 500 KB** | **$0.00** | **100% Yes** | **Python stdlib** |
| **BM25 / Vector RAG Baseline** | 12 / 17 (70.6%) | ~400 ms | $0.02–$0.05 | No | Vector DB + Embeddings |
| **Abstractive LLM Summarizer** | 7 / 17 (41.2%) | ~2,500 ms | $1.50–$3.00 | No (Stochastic) | Auxiliary LLM API |
| **Uncompressed Baseline** | 17 / 17 (100%) | 0 ms | Full Tokens | Yes | None |

---

## 🧪 The Production QA Battery (v3)

The `tests/` directory contains an exhaustive production-QA suite:

- `test_arabic_and_sql_sink.py`: Non-Latin script preservation and SQL tabular sink compaction.
- `test_adjacent_v010.py`: Compaction audit logging, pinned sink regions, and versioned context receipts.
- `test_hardening_pass_v09.py`: NTK template deduplication, progress-bar stripping, and stack frame collapse.
- `test_semantic_gates.py`: Counterfactual distractor masking and graph closure validation.
- `test_production_qa_v3.py`: Cross-seed determinism validation (`PYTHONHASHSEED=0` vs `PYTHONHASHSEED=1`).

Run the full battery:
```bash
python -m unittest discover -s tests
```

Current v1.2.0 release verification:

- **272 passed, 9 skipped** with pytest; **281 passed, 9 skipped** with unittest discovery.
- **13/13** production-QA cases passed; the 500 KB citation case saved **99.5%** under the **1.2 s** gate (**675–956 ms** observed across independent runs).
- **53/53** dedicated industrial Unicode, language, format, property, pipeline and scale tests passed.
- Vendored Hermes package: **53/53** industrial tests plus **15/15** explicit rollout tests passed through actual plugin discovery.
- Independent final GPT-5.4 release review: **PASS**, with no must-fix blockers.

---

## 🔄 Reversible Compaction & ARC Citations (CCR Store)

When Tameru drops content blocks, it emits content-addressed **ARC Citations**:

```
[A 7f8a9b] "2026-08-25 02:00:00 [INFO] Worker started"...[48 lines omitted]..."2026-08-25 02:05:00 [INFO] Complete"
```

If an agent subsequently determines that it needs the omitted content, it can query the local Content-Centric Retrieval (CCR) store:

```python
from tameru.compress_context import retrieve

full_context = retrieve("7f8a9b2c4d6e8f0011223344")
```

CCR is opt-in per integration path. The standalone API keeps its reversible
default, while the Hermes live tool-pruning adapter disables CCR because it has
no retrieval path and tool payloads may contain secrets. Expired valid records
are swept whenever a new CCR record is written; operators can also call
`sweep_ccr_cache()` directly. CCR directories and records are created with
owner-only permissions where the platform supports POSIX modes.

---

## 🔌 Hermes Context-Engine Plugin Integration

Tameru integrates directly into **Hermes Agent** as a pluggable context engine:

1. Shipped under `plugins/context_engine/tameru/`.
2. Activated in `config.yaml`:
   ```yaml
   context:
     engine: tameru
   ```

---

## 🚀 Quickstart & Installation

### Option 1: Standard Installation (Zero Dependencies)
```bash
pip install -e .
```

### Option 2: With Opt-in Semantic Embeddings
```bash
pip install -e '.[semantic]'
```

### Option 3: LLM / Agent Prompt Setup
To equip an autonomous agent with Tameru, paste this prompt into your agent's system prompt or session:

```text
Please install and enable the Tameru compaction system for high-performance context management:
1. Clone or vendor tameru into your environment.
2. In your context configuration, select 'tameru' as the active context engine.
3. Use tameru.compress_context(context, query) before passing large tool outputs to your context window.
```

---

## 💻 Python API & Agent Integration

```python
from tameru.compress_context import compress_context

context_data = (
    "2026-08-25 02:00:00 [INFO] System boot sequence started.\n"
    + ("2026-08-25 02:01:00 [INFO] Routine worker heartbeat.\n" * 500)
    + "2026-08-25 02:14:00 [ERROR] DB connection failed on host db-prod-01: Port 5432 unreachable.\n"
)

query = "Why did the database connection fail?"

result = compress_context(context_data, query)

print(f"Compressed Output:\n{result.compressed_text}\n")
print(f"Token Reduction: {result.tokens_saved_pct:.1f}%")
print(f"Fail-Open Triggered: {result.fail_open}")
print(f"Confidence Diagnostic: {result.verifier}")
```

`strategy="summarise"` remains fail-open and can be configured per call with
`summary_endpoint`, `summary_models`, and `summary_timeout`. Equivalent
environment variables are `TAMERU_SUMMARY_ENDPOINT`,
`TAMERU_SUMMARY_MODELS` (comma-separated), and `TAMERU_SUMMARY_TIMEOUT`
(seconds). The timeout is one total retry budget across all candidate models,
not a fresh timeout per model.

Summary endpoints are restricted to loopback by default. Set
`TAMERU_SUMMARY_ALLOW_REMOTE=1` or pass `summary_allow_remote=True` only when
the integration has explicitly approved sending context to that endpoint.

When using `decision_cache`, first-sight keep/drop outcomes are replayed on
later turns. The cache preserves the oldest prefix and is bounded to 4,096
block decisions. Prefix stability intentionally outranks a later fixed-mode
`budget_ratio`; if frozen keeps exceed that ratio, the engine preserves the
frozen prefix and reports `freeze cache capacity reached` once the cache can no
longer learn new blocks.

---

## 📜 Changelog

All notable changes, version milestones, and migration notes are tracked in **[CHANGELOG.md](CHANGELOG.md)**.

Highlights:
- **v1.2.0**: Bounded industrial preflight, logical-order Unicode across 20 script/language families, ten exact format adapters, deterministic receipt hashes and large-input SLOs.
- **v1.1.1**: Comprehensive factual-retention, fail-open, cache-progression, public-metrics, and current-Hermes integration hardening.
- **v1.1.0**: Production QA hardening, Docker progress recognition, CCR security & expiry sweep, bounded decision caching, loopback summary boundary.
- **v0.10.0**: Compaction audit logs, pinned sink regions, versioned context receipts.
- **v0.9.0**: NTK layer-1 log dedup, error invariants, progress-bar stripping, lost-in-the-middle reordering.
- **v0.8.0**: Opt-in semantic tier with bi-encoders and cross-encoders.
- **v0.1.0 - v0.7.0**: Core extractive engine, graph closure, temporal supersession, and tabular crushers.

---

## 🙏 Credits & Research Lineage

Tameru's design was inspired and sharpened by studying remarkable open-source projects, papers, and ideas:

### Open-Source Projects
- **[NTK / Neural Token Killer](https://github.com/luizinhoh2o1/ntk)** (Rust, MIT) — Template deduplication, error-signal invariant, progress-bar stripping, and stack frame collapse.
- **[caveman-compression](https://github.com/wilpel/caveman-compression)** (MIT) — Executable test specification discipline and factual preservation validation.
- **[leanctx](https://github.com/jia-gao/leanctx)** (MIT) — Loss-tolerance routing and structural verbatim code invariants.
- **[TwoTrim](https://github.com/overseek944/twotrim)** (Apache-2.0) — Lost-in-the-middle mitigation and attention edge anchoring.
- **[clipforge-PAKT](https://github.com/sriinnu/clipforge-PAKT)** (MIT) — Pre-flight compressibility inspection.

### Research Lineage
- **LongLLMLingua** (Microsoft, ACL 2024) — Question-aware coarse-to-fine compression and positional attention reordering.
- **Lost in the Middle** (Liu et al., 2023) — Positional attention decay in decoder transformers.
- **NoLiMa** (2025) — Long-context lexical distractor blind spots.
- **ARC Citations** — Reversible content-addressed reference anchors.

---

## 🤝 Community & Support

- **Author**: Benjamin Ang ([@0xWhiteMage](https://x.com/0xWhiteMage))
- **Support**: [Buy me a coffee on Ko-fi](https://ko-fi.com/0xwhitemage)
- **Issues & Contributions**: Pull requests and issue reports are welcome!

---

## 📄 License

Released under the **[MIT License](LICENSE)**.
