# Harness Integrations

Tameru is harness-agnostic by construction: `src/tameru/` contains **zero**
imports of any agent framework. There are three ways to wire it into a
harness, cheapest first.

## 1. Python API (pip)

Any harness that can run Python installs the package directly — no
vendoring, updates are `pip install -U`:

```bash
pip install tameru-compaction-system
```

```python
from tameru.compress_context import compress_context

result = compress_context(payload_text, query)
# result.compressed_text — exact spans; result.fail_open — original returned
```

### Transcript-level pruning (OpenAI-style message lists)

`tameru.transcript` prunes bulky tool payloads inside a
`[{"role": ..., "content": ...}]` conversation — the shape shared by
OpenCode, Codex, and most agent loops:

```python
from tameru.transcript import apply_extractive_tool_prune

messages, n_changed = apply_extractive_tool_prune(
    messages,            # list[dict] — returned unchanged if nothing applies
    query=None,          # defaults to the last user message
    min_chars=800,       # payloads below this are left alone
    protect_last_tool=2, # newest N tool messages are never touched
)
```

It calls `compress_context` per tool payload with `ccr=False,
citations=False` (no disk writes, no markers in the transcript) and skips
any payload that fails open or doesn't shrink.

**Building a query for a tool result.** The last user message is often
"continue", which says nothing about an old tool payload. If your harness
compresses results one at a time, derive the query from the task instead:

```python
from tameru.transcript import task_query, text_of

parts = task_query(
    messages,
    idx,                        # index of the tool message being compressed
    focus=None,                 # optional explicit topic, highest priority
    max_chars=2000,             # total cap, parts are cut lowest-priority first
    skip_user=is_synthetic,     # optional predicate for injected user turns
)
query = "\n".join(parts)
```

`task_query` returns an ordered, de-duplicated list of parts: the focus, the
function name and string arguments of the assistant tool call that produced
the result, the first assistant message after it (text and call arguments),
the last real user message, and the first user message. Multimodal content is
reduced to its text parts and base64 blobs / `data:` URIs are stripped.
`text_of(content)` is the underlying helper (str, list of parts or
`{"text": ...}` dict to plain text; images and other parts are skipped).
`last_user_text` now uses it, so multimodal user turns no longer turn into a
`repr` query.

`trajectory_gate` only considers the trailing assistant turn: an orphan
tool call earlier in history no longer suppresses pruning for the rest of the
session.

Deprecated: `query_facts_lost` and `bulky_tools_dropped` (post-hoc checks that
re-scan every tool payload, O(n²) on long sessions). They keep working with no
runtime warning, but new integrations should not call them; bound the loss at
compression time instead (`compress_context` risk rating plus your own
retention checks).

**Hermes Agent users:** use the plugin instead of wiring this yourself —
[`0xWhiteMage/hermes-tameru-plugin`](https://github.com/0xWhiteMage/hermes-tameru-plugin).
It hooks Hermes' per-result demotion seam and has real-Hermes CI. This repo no
longer ships a Hermes bundle; installation lives in the plugin repository.

## 2. CLI shell-out (any language)

`tameru-compress` is the universal contract — stdin or file in, compacted
text on stdout, JSON stats with `--stats`:

```bash
pip install tameru-compaction-system   # provides tameru-compress on PATH
tameru-compress context.txt "query" --stats
cat context.txt | tameru-compress - "query" --pin-recent 4 --strategy auto
```

Hooks in TypeScript/shell harnesses (Claude Code, OpenCode, Cursor)
typically shell out to exactly this.

## 3. Vendored plugin dir (Hermes-style)

The maintained Hermes integration is
[`0xWhiteMage/hermes-tameru-plugin`](https://github.com/0xWhiteMage/hermes-tameru-plugin) —
install into `~/.hermes/plugins/tameru/` or `pip install` (registers via the
`hermes_agent.plugins` entry point). Use it directly, or as the reference for
other harnesses.

When the host requires self-contained plugins with no external deps,
vendor `src/tameru/*.py` into the plugin dir and let the sync script keep
it current:

```bash
python scripts/sync_to_harness.py <plugin_dir> --manifest plugin.yaml
```

`--manifest` paths are resolved **relative to the target dir**, not the
current directory. When the manifest sits next to a vendored subpackage
(`hermes_tameru_plugin/plugin.yaml` for the target
`hermes_tameru_plugin/tameru`), pass `--manifest ../plugin.yaml`.

Check a vendored copy for drift without changing anything (for CI):

```bash
python scripts/sync_to_harness.py <plugin_dir> --manifest plugin.yaml --check
```

`--check` lists modules whose content differs, upstream modules missing from
the target, stale vendored modules a sync would remove, and manifest stamps
that would change (including a `--manifest` path that does not resolve). It
exits 1 if anything differs and 0 if the copy is in sync, and never writes.

Glue-only dirs that vendor no modules of their own (e.g. a compat alias that
just re-exports the engine) should be stamped, not synced:

```bash
python scripts/sync_to_harness.py <alias_dir> --manifest plugin.yaml --stamp-only
```

### Ownership contract

| File | Owner | Updated by sync? |
|---|---|---|
| `src/tameru/*.py` (all modules except `__init__.py`) | upstream | **yes** — copied wholesale |
| `__init__.py` (registration/engine class) | harness | no — upstream's `__init__.py` is package metadata, not shipped |
| `plugin.yaml` / manifest | harness | version + description stamped only |
| tests, docs, benchmarks | upstream | not vendored |

**Update workflow:** merge changes here → run `sync_to_harness.py` →
`git commit && git push` in the harness repo → the integration PR updates
automatically. The sync is a file copy plus a version stamp; nothing else
to maintain. Run `sync_to_harness.py --check` in the harness repo's CI to
catch a vendored copy that has drifted from upstream.

## Design rules for adapters

- Adapters take **generic shapes**: raw text for `compress_context`, a
  `role`/`content` dict list for `tameru.transcript`. Never import the
  host framework.
- Keep CCR off in adapters with no retrieval path (live tool payloads may
  carry secrets; the built-in secrets screen is a second line of defense).
- Respect `fail_open`: when a result fails open the adapter must leave the
  payload untouched, not substitute a degraded rewrite.
