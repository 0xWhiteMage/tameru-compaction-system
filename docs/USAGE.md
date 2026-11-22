# Tameru usage and controls

The [README](../README.md) covers the first run, comparisons and measured results. This guide covers recovery, optional models and controls for integrations.

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

**Credential screening is heuristic.** By default it does not redact returned text, guarantee detection of every secret or encrypt the cache. Opt-in `redact_secrets=True` replaces recognised credential patterns with `[tameru:redacted]` in successful extracts and dropped-span locators; fail-open originals remain unredacted. Code-shaped values such as `password = settings_default_password` are a documented detection gap.

### Optional model-backed paths

`strategy="extract"` is the default and uses no LLM. `strategy="summarise"` can invoke a configured model; `strategy="auto"` tries extraction first and may escalate when extraction fails open. LLM failure falls back to extraction.

Configure `summary_endpoint`, `summary_models` and `summary_timeout` per call, or `TAMERU_SUMMARY_ENDPOINT`, `TAMERU_SUMMARY_MODELS` and `TAMERU_SUMMARY_TIMEOUT`. The timeout is one total retry budget across models. Endpoints are loopback-only by default; remote endpoints require `summary_allow_remote=True` or `TAMERU_SUMMARY_ALLOW_REMOTE=1` and may incur inference charges and transmit context.

An optional semantic extra installs `sentence-transformers`; it is outside the standard-library dependency claim. From a checkout of the [pinned source](../README.md#install):

```bash
python -m pip install -e '.[semantic]'
```

Installing the extra does not enable it. Pass `semantic_tier=SemanticTier(...)` to `compress_context` after importing `SemanticTier` from `tameru.semantic`. Its defaults are `bi_model="sentence-transformers/all-MiniLM-L6-v2"`, `cross_model=None`, `device="cpu"`; a cross-encoder is optional. Model construction may download weights to the Hugging Face cache, so pre-cache/pin models for offline use. Missing dependencies raise `SemanticUnavailable` during construction; keep the default `semantic_tier=None` for the model-free path. There is no semantic CLI flag.

## 1.10.0 results and bounded analysis

Normal results use result schema **3**. Alongside `compressed_text`, `fail_open`, `reasons`, `confidence` and `receipt`, inspect:

| Field | Meaning |
|---|---|
| `confidence_basis` | What the confidence rests on: lexical, cross-lingual, tool-call, structural, derived or anchored evidence, or no basis; not a guarantee of future answer quality |
| `stable_key` | Digest for the engine version, input and query (including `selector_query` when supplied) |
| `dropped` | Bounded summary of omitted spans: category, line count and first locator, not a recovery store |
| `fact_lines_dropped` | Count of detected protected fact lines missing from the extract; a positive count caps confidence |

Rare assignment-shaped facts and error exemplars receive protection from destructive selectors and adapters. Dense fact dumps retain their previous handling and report `fact_dense` in the receipt. `selector_query` lets a host separate user intent from producing-call arguments for destructive pre-filters; scoring and confidence still use the full query (see [integration contracts](INTEGRATION.md#1100-host-contracts)).

Query-independent analyses use a content-digest LRU with a default **64 MiB (67,108,864-byte)** budget per process; set `TAMERU_CACHE_MAX_BYTES` before import to size it. `tameru.cache_stats()` exposes cache counters. This bounds retained cache records, not total process memory or peak working allocation.

Inputs **over 2,000,000 characters** take a head/tail and error-line sample before normal processing, reporting `confidence_basis="partial"`, confidence at most 0.5 and reason `huge_sampled`. This is partial analysis, not full-source evidence verification or full-source recovery. Inputs **over 8,000,000 characters** return the original with `too_large` and confidence 0 before analysis; this early return does not populate all normal schema metadata. Custom `IndustrialLimits` still apply to the normal/sample path and do not override these outer thresholds.

Structural log/trace folding runs even for generic questions, but calls with `pin_patterns` or `pin_recent` retain the older structural behaviour because folding moves pinned block boundaries. Unstructured prose with no specific question may still fail open. See [recorded results and limitations](RESULTS-1.10.0.md); these are replay measurements, not live billing or answer-quality evidence.

## Host controls

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
| `anchor_errors=True` | For empty, generic or saturated queries, anchor selection on error and failure lines; receipts mark `query_source="error-anchored"` and the risk floor is medium |
| `prose_brief=True` | Opt-in (1.6.0) no-query brief for prose in any script: keeps the first and last block, one paragraph per repeat group and repeats that carry data; receipts mark `query_source="prose-brief"`; over 90% kept still fails open |
| `decision_cache` | Freeze first-sight block decisions; bounded to 4,096 entries; frozen keeps may exceed a later requested ratio |
| `degraded_view=True` | Opt-in bounded head/tail scoring for certain oversized inputs; preserves safety limits and raises the risk floor |
| `IndustrialLimits` | Configure character, line, record, field, query and bidi limits |

The default pipeline combines bounded preflight, format adapters, lexical/entity/structural scoring, graph and dependency rescue, emission and diagnostic verification. Dependency rescue can restore related definitions or qualifiers; trust and supersession rules address known distractor and stale-state patterns. These are deterministic heuristics, not a semantic judge or a general prompt-injection defence.

The recursion guard avoids compacting recognised Tameru output again. `inspect_compressibility()` estimates duplicate-removal headroom. `fold_lossless`, `error_fingerprints`, `brief_context` and `extract_evidence_lines` are available for host-specific reduction.

For implementation details, see [the source](../src/tameru/), [architecture](ARCHITECTURE.md) and [research digest](RESEARCH.md). Research inspiration is documented separately from implemented mechanisms.
