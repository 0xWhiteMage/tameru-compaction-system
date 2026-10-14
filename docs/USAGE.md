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

**Credential screening is heuristic.** It does not redact returned text, guarantee detection of every secret or encrypt the cache. Code-shaped values such as `password = settings_default_password` are a documented detection gap.

### Optional model-backed paths

`strategy="extract"` is the default and uses no LLM. `strategy="summarise"` can invoke a configured model; `strategy="auto"` tries extraction first and may escalate when extraction fails open. LLM failure falls back to extraction.

Configure `summary_endpoint`, `summary_models` and `summary_timeout` per call, or `TAMERU_SUMMARY_ENDPOINT`, `TAMERU_SUMMARY_MODELS` and `TAMERU_SUMMARY_TIMEOUT`. The timeout is one total retry budget across models. Endpoints are loopback-only by default; remote endpoints require `summary_allow_remote=True` or `TAMERU_SUMMARY_ALLOW_REMOTE=1` and may incur inference charges and transmit context.

An optional semantic extra installs `sentence-transformers`; it is outside the standard-library dependency claim:

```bash
python -m pip install -e '.[semantic]'
```

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
| `decision_cache` | Freeze first-sight block decisions; bounded to 4,096 entries; frozen keeps may exceed a later requested ratio |
| `degraded_view=True` | Opt-in bounded head/tail scoring for certain oversized inputs; preserves safety limits and raises the risk floor |
| `IndustrialLimits` | Configure character, line, record, field, query and bidi limits |

The default pipeline combines bounded preflight, format adapters, lexical/entity/structural scoring, graph and dependency rescue, emission and diagnostic verification. Dependency rescue can restore related definitions or qualifiers; trust and supersession rules address known distractor and stale-state patterns. These are deterministic heuristics, not a semantic judge or a general prompt-injection defence.

The recursion guard avoids compacting recognised Tameru output again. `inspect_compressibility()` estimates duplicate-removal headroom. `fold_lossless`, `error_fingerprints`, `brief_context` and `extract_evidence_lines` are available for host-specific reduction.

For implementation details, see [the source](../src/tameru/), [industrial architecture](industrial-compaction-v1.2.md) and [research digest](RESEARCH.md). Research inspiration is documented separately from implemented mechanisms.

